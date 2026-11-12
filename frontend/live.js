/* Triyana — live maps, "Doctor now" and patient tracking. Shared by the Patient and Provider apps.
   Maps: Leaflet + OpenStreetMap data (CARTO tiles). GPS is simulated on the server for the demo. */
"use strict";

Object.assign(P, {
  flask: '<path d="M9 3h6M10 3v6L4.5 18.5A2 2 0 0 0 6.2 21.5h11.6a2 2 0 0 0 1.7-3L14 9V3"/><path d="M7 15h10"/>',
  heart: '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 1 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8z"/>',
  power: '<path d="M12 2v10"/><path d="M18.4 6.6a9 9 0 1 1-12.8 0"/>',
  nav: '<path d="M3 11l19-9-9 19-2-8z"/>',
  phoneCall: '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8 9.8a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.5c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2z"/>',
  flag: '<path d="M4 22V4"/><path d="M4 4h13l-2 4 2 4H4"/>',
  home2: '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/>',
});

/* ------------------------------------------------------------------ map helpers */
const DARK = () => window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches;
const hasMap = () => typeof window.L !== "undefined";

function makeMap(el, { center = [17.44, 78.35], zoom = 14, interactive = true } = {}) {
  if (!hasMap()) { el.innerHTML = `<div class="map-off">${ic("pin")}<span>Map unavailable offline</span></div>`; return null; }
  const map = L.map(el, { zoomControl: false, attributionControl: true, dragging: interactive, scrollWheelZoom: interactive, doubleClickZoom: interactive, touchZoom: interactive, keyboard: interactive })
    .setView(center, zoom);
  L.tileLayer(`https://{s}.basemaps.cartocdn.com/${DARK() ? "dark_all" : "rastertiles/voyager"}/{z}/{x}/{y}{r}.png`, {
    maxZoom: 19, subdomains: "abcd",
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
  }).addTo(map);
  if (interactive) L.control.zoom({ position: "bottomright" }).addTo(map);
  state.cleanups.push(() => map.remove());
  setTimeout(() => map.invalidateSize(), 60);
  return map;
}

function markerIcon(kind, inner = "", extra = "") {
  const size = { provider: 46, me: 44, home: 38, pharmacy: 38, dest: 38 }[kind] || 36;
  return L.divIcon({ className: "", iconSize: [size, size], iconAnchor: [size / 2, size / 2],
    html: `<div class="mk mk-${kind} ${extra}">${inner}</div>` });
}

/* Smoothly move a marker between server updates. */
function glide(marker, to, ms = 1400) {
  if (!marker) return;
  const from = marker.getLatLng();
  if (marker._glide) cancelAnimationFrame(marker._glide);
  const t0 = performance.now();
  const step = (t) => {
    const k = Math.min(1, (t - t0) / ms);
    const e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
    marker.setLatLng([from.lat + (to[0] - from.lat) * e, from.lng + (to[1] - from.lng) * e]);
    if (k < 1) marker._glide = requestAnimationFrame(step);
  };
  marker._glide = requestAnimationFrame(step);
}

/* The part of the route still ahead of the provider. */
function routeAhead(t) {
  const R = 6371000, rad = Math.PI / 180;
  const dist = (a, b) => { const dl = (b[0] - a[0]) * rad, dn = (b[1] - a[1]) * rad; const h = Math.sin(dl / 2) ** 2 + Math.cos(a[0] * rad) * Math.cos(b[0] * rad) * Math.sin(dn / 2) ** 2; return 2 * R * Math.asin(Math.sqrt(h)); };
  let done = 0;
  for (let i = 1; i < t.route.length; i++) {
    done += dist(t.route[i - 1], t.route[i]);
    if (done > t.traveled_m) return [t.position, ...t.route.slice(i)];
  }
  return [t.position, t.route[t.route.length - 1]];
}

function every(ms, fn) { const t = setInterval(() => fn().catch?.(() => {}), ms); state.timers.push(t); return t; }
const clock = (minsAhead) => new Date(Date.now() + minsAhead * 60000).toLocaleTimeString(undefined, { timeStyle: "short", timeZone: TZ });
const km = (m) => (m < 1000 ? `${Math.round(m / 10) * 10} m` : `${(m / 1000).toFixed(1)} km`);

/* ------------------------------------------------------------------ patient: services */
const SERVICES = [
  { key: "shop", title: "Medicine shop", sub: "Rider delivery in under an hour", icon: "bag", go: "shop", tone: "blue" },
  { key: "book", title: "Book a home visit", sub: "Pick a doctor and a time", icon: "calendar", go: "book" },
  { key: "physio", title: "Physio at home", sub: "Sessions & packages, live map", icon: "heart", go: "physio", tone: "gold" },
  { key: "lab", title: "Lab tests at home", sub: "Collector at your door, reports here", icon: "flask", go: "labs", tone: "blue" },
  { key: "rx", title: "Prescriptions", sub: "E-signed by your doctor", icon: "rx", go: "rx" },
  { key: "cart", title: "Medicine cart", sub: "Choose what to buy, and how much", icon: "cart", go: "cart", tone: "blue" },
  { key: "orders", title: "Track orders", sub: "Live courier map", icon: "truck", go: "orders", tone: "blue" },
  { key: "meds", title: "My Medicines", sub: "Prescribed, ordered, dispensed", icon: "pills", go: "meds" },
  { key: "yana", title: "Ask Yana", sub: "Your medicine assistant", icon: "chat", tone: "gold" },
];

function servicesHTML() {
  return `<div class="section-title">Services</div>
    <div class="services">
      <button class="svc-hero" data-svc="now">
        <span class="svc-glow"></span>
        <span class="row" style="gap:8px"><span class="live-dot"></span><span class="tiny strong" style="letter-spacing:.1em">ON DEMAND</span></span>
        <b>Doctor now</b>
        <span>The nearest available doctor accepts in seconds and comes to your door. Watch them arrive on the map.</span>
        <span class="row svc-meta"><span class="chip-glass">${ic("stethoscope")} <span id="onlineDocs">Doctors online nearby</span></span><span class="chip-glass">${ic("clock")} Arrives in ~15–30 min</span></span>
        <span class="svc-cta">Get a doctor now ${ic("arrow")}</span>
      </button>
      <button class="card now-banner physio-banner" data-svc="physio" data-svc-go="physio"><div class="row" style="flex-wrap:nowrap"><div class="ico">${ic("heart", "lg")}</div>
        <div><h3 style="margin:0">Physiotherapy at home</h3><span class="small muted">Back, knee, post-surgery and stroke rehab. Book a session or a package; a verified physio comes to you.</span></div></div>
        <span class="btn primary sm">${ic("heart")} Book physio</span></button>
      ${SERVICES.map((s) => `<button class="svc ${s.soon ? "soon" : ""}" data-svc="${s.key}" ${s.go ? `data-svc-go="${s.go}"` : ""}>
        <span class="ico ${s.tone || ""}">${ic(s.icon, "lg")}</span><b>${s.title}</b><span class="tiny muted">${s.sub}</span>
        ${s.soon ? `<span class="badge">Coming soon</span>` : ""}</button>`).join("")}
    </div>`;
}

function doctorNowBanner() {
  return `<div class="card now-banner"><div class="row" style="flex-wrap:nowrap"><div class="ico">${ic("bolt", "lg")}</div>
      <div><h3 style="margin:0">Need a doctor right now?</h3><span class="small muted">We send the nearest available doctor. Track them live as they come to you.</span></div></div>
      <button class="btn primary" data-svc="now">${ic("bolt")} Doctor now</button></div>`;
}

function wireServices() {
  $$("[data-svc]").forEach((b) => (b.onclick = () => {
    const k = b.dataset.svc;
    if (k === "now") return doctorNowSheet();
    if (k === "yana") return openYana();
    if (b.dataset.svcGo) return go(b.dataset.svcGo);
    toast("Coming soon to Triyana", "info");
  }));
  const el = $("#onlineDocs");
  if (el) api("/api/patient/online-nearby").then((r) => { el.textContent = r.doctors ? `${r.doctors} doctor${r.doctors > 1 ? "s" : ""} online nearby` : "No doctors online right now"; }).catch(() => {});
}

function sheet(html) {
  const wrap = document.createElement("div");
  wrap.className = "sheet-wrap";
  wrap.innerHTML = `<div class="sheet" role="dialog" aria-modal="true">${html}</div>`;
  document.body.appendChild(wrap);
  requestAnimationFrame(() => wrap.classList.add("open"));
  const close = () => { wrap.classList.remove("open"); setTimeout(() => wrap.remove(), 250); };
  wrap.onclick = (e) => { if (e.target === wrap) close(); };
  state.cleanups.push(() => wrap.remove());
  return { el: wrap, close };
}

async function doctorNowSheet() {
  const [near, online] = await Promise.all([api("/api/doctors"), api("/api/patient/online-nearby")]);
  const b = { reason: "", details: "", address: near.address };
  const s = sheet(`<div class="sheet-head"><div><div class="eyebrow-sm"><span class="live-dot"></span> ${online.doctors} doctor${online.doctors === 1 ? "" : "s"} online near you</div>
      <h2>Doctor now</h2><p class="small muted">The nearest available verified doctor gets your request first. If they can't come, it goes to the next nearest.</p></div>
      <button class="x" aria-label="Close">${ic("x")}</button></div>
    <div class="choice-grid">${REASONS.map(([r, i]) => `<button class="choice" data-r="${esc(r)}"><span class="ico">${ic(i)}</span><div><b>${r}</b></div></button>`).join("")}</div>
    <label class="field" style="margin-top:12px">Tell the doctor more (optional)<textarea id="nowDetails" rows="2" placeholder="For example: fever since last night, 102°F"></textarea></label>
    <label class="field" style="margin-top:10px">Visit address<input id="nowAddr" value="${esc(b.address)}"></label>
    <div class="notice info small">${ic("shield")}<span><b>Nothing to pay now.</b> Licence-verified doctors only. Visit fee from ${money(Math.min(...near.doctors.map((d) => d.visit_fee)))}, paid after the visit.</span></div>
    <div class="notice warn small">${ic("alert")}<span>For chest pain, breathing trouble or other emergencies, call <b>112</b> now.</span></div>
    <button class="btn primary block" id="nowGo" disabled>${ic("bolt")} Find a doctor now</button>`);
  $(".x", s.el).onclick = s.close;
  $$("[data-r]", s.el).forEach((x) => (x.onclick = () => { b.reason = x.dataset.r; $$("[data-r]", s.el).forEach((y) => y.classList.toggle("on", y === x)); $("#nowGo").disabled = false; }));
  $("#nowGo").onclick = () => guard(async () => {
    const reason = [b.reason, $("#nowDetails").value.trim()].filter(Boolean).join(" · ");
    $("#nowGo").disabled = true;
    try {
      const v = await post("/api/patient/visits/now", { reason, address: $("#nowAddr").value });
      s.close(); liveScreen("visit", v.id);
    } catch (e) { $("#nowGo").disabled = false; throw e; }
  });
}

async function patientLiveBanner(visits, orders) {
  const slot = $("#liveSlot"); if (!slot) return;
  const v = visits.find((x) => (x.status === "requested" && x.on_demand) || x.status === "accepted");
  const o = orders.find((x) => x.delivery && ["ready_for_pickup", "out_for_delivery"].includes(x.status));
  const items = [];
  if (v) { const d = await api(`/api/patient/visits/${v.id}/live`).catch(() => null); if (d && ["searching", "on_the_way", "arrived"].includes(d.phase)) items.push(d); }
  if (o) { const d = await api(`/api/orders/${o.id}/live`).catch(() => null); if (d && ["searching", "to_pharmacy", "on_the_way", "arrived"].includes(d.phase)) items.push(d); }
  const pb = (await api("/api/patient/physio/bookings").catch(() => [])).find((b) => b.next_session && ["searching", "active"].includes(b.status));
  if (pb) { const d = await api(`/api/patient/physio/sessions/${pb.next_session.id}/live`).catch(() => null); if (d && ["searching", "on_the_way", "arrived", "with_you"].includes(d.phase)) items.push(d); }
  if (!slot.isConnected) return;
  slot.innerHTML = items.map((d) => `<button class="live-banner" data-live="${d.kind}:${d.id}"><span class="live-dot"></span>
      <span class="grow"><b>${esc(liveHeadline(d))}</b><span class="tiny">${d.trip && !d.trip.arrived ? `${d.trip.eta_min} min away · arriving around ${clock(d.trip.eta_min)}` : esc(liveSub(d))}</span></span>
      <span class="btn sm">${ic("pin")} Live map</span></button>`).join("");
  $$("[data-live]", slot).forEach((b) => (b.onclick = () => { const [k, id] = b.dataset.live.split(":"); liveScreen(k, +id); }));
}

/* ------------------------------------------------------------------ patient: live map */
function liveHeadline(d) {
  const who = d.provider?.name || (d.kind === "visit" ? "Your doctor" : d.kind === "physio" ? "Your physiotherapist" : "Your courier");
  const care = d.kind !== "delivery";
  return ({
    searching: d.kind === "visit" ? "Finding your doctor" : d.kind === "physio" ? "Finding your physiotherapist" : "Finding a courier near the pharmacy",
    waiting: `Waiting for ${who} to confirm`,
    confirmed: d.kind === "physio" ? `Session ${d.number} with ${who} is confirmed` : `${who} confirmed your visit`,
    to_pharmacy: `${who} is collecting your medicines`,
    on_the_way: `${who} is on the way`,
    arrived: care ? `${who} has arrived` : `${who} is at your door`,
    with_you: `${who} is with you`,
    assigned: `${who} will collect your order`,
    preparing: "Your pharmacy is preparing your order",
    done: d.kind === "visit" ? "Visit complete" : d.kind === "physio" ? `Session ${d.number} complete` : "Delivered",
    cancelled: care ? "This request was cancelled" : "This order was cancelled",
  })[d.phase] || "Live tracking";
}
function liveSub(d) {
  return ({
    searching: d.kind === "visit" ? `Asking the nearest available doctor · ${d.online_nearby} online near you` : d.kind === "physio" ? `Asking the nearest available physiotherapist · ${d.online_nearby} online near you` : "We're asking the nearest courier to pick it up.",
    waiting: `Booked for ${when(d.scheduled_for)}. You'll see them on the map when they set off.`,
    confirmed: `Booked for ${when(d.scheduled_for)}. You'll see them on the map when they set off.`,
    to_pharmacy: `Picking up at ${shortName(d.pharmacy?.label)}.`,
    arrived: d.kind === "visit" ? "Please open the door. Your doctor will show their ID." : d.kind === "physio" ? "Please open the door. Your physiotherapist will show their ID." : "Share your handover code to receive your medicines.",
    with_you: d.kind === "physio" ? `Session ${d.number} of ${d.sessions_total}. Your notes and home exercises appear after the session.` : "Your prescription will appear here after the visit.",
    done: d.kind === "physio" ? "Your session notes and home exercises are ready." : "Thank you for using Triyana.",
    cancelled: "No one is coming. You can book again any time.",
  })[d.phase] || "";
}

async function liveScreen(kind, id) {
  stopLive();
  state.tab = kind === "visit" ? "book" : kind === "physio" ? "physio" : "orders"; renderNav();
  document.body.classList.add("live-mode");
  state.cleanups.push(() => document.body.classList.remove("live-mode"));
  window.scrollTo({ top: 0 });
  const url = kind === "visit" ? `/api/patient/visits/${id}/live` : kind === "physio" ? `/api/patient/physio/sessions/${id}/live` : `/api/orders/${id}/live`;
  let d = await api(url);
  const order = kind === "delivery" ? await api(`/api/orders/${id}`) : null;
  view().innerHTML = `<div class="live">
      <div class="live-map-wrap"><div class="live-map" id="liveMap"></div>
        <button class="map-back" id="liveBack" aria-label="Back">${ic("arrow")}</button>
        <div class="live-chip" id="liveChip"></div></div>
      <div class="live-sheet" id="liveSheet"></div></div>`;
  $("#liveBack").onclick = () => (kind === "physio" ? physioBookingScreen(d.booking_id) : go(kind === "visit" ? "home" : "orders"));
  const map = makeMap($("#liveMap"), { center: [d.home.lat, d.home.lng], zoom: 15 });
  const L_ = {};
  if (map) {
    L_.home = L.marker([d.home.lat, d.home.lng], { icon: markerIcon("home", ic("home2")), zIndexOffset: 100 }).addTo(map);
    if (d.pharmacy) L_.pharmacy = L.marker([d.pharmacy.lat, d.pharmacy.lng], { icon: markerIcon("pharmacy", ic("store")) }).addTo(map);
  }
  let routeKey = "", fitted = false;
  const draw = () => {
    const t = d.trip;
    $("#liveChip").innerHTML = `<span class="live-dot ${["done", "cancelled"].includes(d.phase) ? "off" : ""}"></span>${t && !t.arrived ? `${t.eta_min} min` : d.phase === "searching" ? "Searching" : "Live"}`;
    if (map) {
      $("#liveMap").classList.toggle("searching", d.phase === "searching");
      if (d.provider_location) {
        const ini = d.provider ? esc(initials(d.provider.name)) : "";
        if (!L_.prov) L_.prov = L.marker(d.provider_location, { icon: markerIcon("provider", `<span>${ini}</span><i class="hd"></i>`), zIndexOffset: 500 }).addTo(map);
        else glide(L_.prov, d.provider_location);
        const hd = L_.prov.getElement()?.querySelector(".hd"); if (hd && t) hd.style.transform = `rotate(${t.heading}deg)`;
      } else if (L_.prov) { L_.prov.remove(); delete L_.prov; }
      const key = t ? `${t.id}:${t.source}` : "";
      if (key !== routeKey) {
        routeKey = key; fitted = false;
        [L_.routeBg, L_.route].forEach((x) => x && x.remove());
        if (t) {
          L_.routeBg = L.polyline(t.route, { color: "#0b2f2a", weight: 9, opacity: .18, lineCap: "round" }).addTo(map);
          L_.route = L.polyline(routeAhead(t), { color: DARK() ? "#2fd1b5" : "#0b7a6c", weight: 5, opacity: .95, lineCap: "round", dashArray: t.source === "synthetic" ? "1 9" : null }).addTo(map);
        }
      } else if (t && L_.route) L_.route.setLatLngs(routeAhead(t));
      if (!fitted) {
        const pts = [[d.home.lat, d.home.lng]];
        if (d.provider_location) pts.push(d.provider_location);
        if (t) pts.push(...t.route);
        if (d.pharmacy && ["searching", "to_pharmacy", "preparing", "assigned"].includes(d.phase)) pts.push([d.pharmacy.lat, d.pharmacy.lng]);
        if (pts.length > 1) map.fitBounds(pts, { padding: [50, 50], maxZoom: 16 }); else map.setView(pts[0], 15);
        fitted = true;
      }
    }
    const p = d.provider, t2 = d.trip;
    const pct = t2 ? Math.round(t2.fraction * 100) : 0;
    $("#liveSheet").innerHTML = `
      <div class="grab"></div>
      <div class="row between" style="align-items:flex-start;flex-wrap:nowrap">
        <div><div class="eyebrow-sm">${kind === "visit" ? `${d.on_demand ? "Doctor now" : "Home visit"} · ${esc(d.booking_ref || "")}` : kind === "physio" ? `Physio · session ${d.number} of ${d.sessions_total} · ${esc(d.booking_ref)}` : `Order ${esc(d.order_no)}`}</div>
          <h2>${esc(liveHeadline(d))}</h2><p class="small muted" style="margin:2px 0 0">${t2 && !t2.arrived ? `${km(t2.remaining_m)} away · arriving around <b>${clock(t2.eta_min)}</b>` : esc(liveSub(d))}</p></div>
        ${t2 && !t2.arrived ? `<div class="eta"><b>${t2.eta_min}</b><span>min</span></div>` : d.phase === "arrived" ? `<div class="eta good">${ic("check", "lg")}</div>` : ""}
      </div>
      ${d.phase === "searching" ? `<div class="search-bar"><i></i></div>` : t2 ? `<div class="trip-bar"><i style="width:${pct}%"></i></div>` : ""}
      ${p ? `<div class="prov-card"><div class="avatar lg">${esc(initials(p.name))}</div><div class="grow"><b>${esc(p.name)}</b> ${p.license_no ? `<span class="verified" title="Verified licence">${ic("badge")}</span>` : ""}
          <div class="tiny muted">${p.specialty ? `${esc(p.specialty)} · ` : ""}${p.rating ? `<span class="stars">★ ${p.rating.toFixed(1)}</span> · ` : ""}${esc(p.vehicle || (p.role === "courier" ? "Courier" : ""))}${p.license_no ? ` · Reg. ${esc(p.license_no)}` : ""}</div></div>
          <button class="btn sm" id="callProv" title="Calls are masked to protect both numbers">${ic("phoneCall")} Call</button></div>` : ""}
      ${order && order.delivery?.handover_code && !["done", "cancelled"].includes(d.phase) ? `<div class="code-inline"><span class="tiny">Handover code</span><b>${esc(order.delivery.handover_code)}</b><span class="tiny muted">Share it only at your door</span></div>` : ""}
      <div class="live-steps">${(kind !== "delivery"
        ? [["Requested", true], [kind === "physio" ? "Physio accepted" : "Doctor accepted", !["searching", "waiting", "cancelled"].includes(d.phase)], ["On the way", ["on_the_way", "arrived", "with_you", "done"].includes(d.phase)], ["Arrived", ["arrived", "with_you", "done"].includes(d.phase)], [kind === "physio" ? "Session" : "Visit", ["with_you", "done"].includes(d.phase)]]
        : [["Packed", d.phase !== "preparing"], ["Courier assigned", !!p], ["Picked up", ["on_the_way", "arrived", "done"].includes(d.phase)], ["Arriving", ["arrived", "done"].includes(d.phase)], ["Delivered", d.phase === "done"]])
        .map(([l, on]) => `<span class="${on ? "on" : ""}"><i></i>${l}</span>`).join("")}</div>
      <div class="row between" style="margin-top:10px">
        <span class="tiny muted">${ic("info")} Demo: GPS is simulated${t2 ? ` and runs ${t2.speedup}× faster` : ""}.</span>
        ${kind !== "delivery" && ["searching", "waiting", "confirmed"].includes(d.phase) ? `<button class="btn ghost sm danger" id="liveCancel">${ic("x")} Cancel</button>` : ""}
        ${["done", "with_you"].includes(d.phase) ? `<button class="btn sm" id="liveHome">${ic(kind === "physio" ? "file" : "home")} ${kind === "physio" ? "Session notes" : "Home"}</button>` : ""}</div>`;
    const c = $("#liveCancel"); if (c) c.onclick = () => guard(async () => { if (!confirm("Cancel this request?")) return; await post(kind === "physio" ? `/api/patient/physio/bookings/${d.booking_id}/cancel` : `/api/patient/visits/${id}/cancel`); toast("Request cancelled"); d = await api(url); draw(); });
    const h = $("#liveHome"); if (h) h.onclick = () => (kind === "physio" ? physioBookingScreen(d.booking_id) : go("home"));
    const cp = $("#callProv"); if (cp) cp.onclick = () => toast("Masked calling connects you in the live app (demo)", "phone");
  };
  draw();
  every(2000, async () => { d = await api(url); draw(); });
}

/* Start the app once every screen is registered. */
if (!document.body.dataset.deferBoot) boot();
