/* Triyana Partner — the provider app: go online, accept nearby requests, navigate turn by turn. */
"use strict";

Object.assign(P, {
  tLeft: '<path d="M14 20v-7a4 4 0 0 0-4-4H4"/><path d="M8 5L4 9l4 4"/>',
  tRight: '<path d="M10 20v-7a4 4 0 0 1 4-4h6"/><path d="M16 5l4 4-4 4"/>',
  tSlightL: '<path d="M14 21v-8L7 6"/><path d="M7 11V6h5"/>',
  tSlightR: '<path d="M10 21v-8l7-7"/><path d="M17 11V6h-5"/>',
  tStraight: '<path d="M12 21V4"/><path d="M6 10l6-6 6 6"/>',
  tUturn: '<path d="M8 21V9a5 5 0 0 1 10 0v4"/><path d="M14 10l4 4 4-4"/>',
  tRound: '<circle cx="12" cy="9" r="4"/><path d="M12 13v8M15 6l3-3"/>',
});

const MANEUVER = (s) => {
  if (!s) return "tStraight";
  if (s.type === "arrive") return "flag";
  if (s.type === "roundabout" || s.type === "rotary") return "tRound";
  const m = s.modifier || "straight";
  return { left: "tLeft", "sharp left": "tLeft", right: "tRight", "sharp right": "tRight", "slight left": "tSlightL", "slight right": "tSlightR", uturn: "tUturn" }[m] || "tStraight";
};

/* Earnings tab for doctors and couriers (Dasher-style pay). */
[TABS.doctor, TABS.courier].forEach((t) => t.splice(1, 0, ["earnings", "Earnings", "wallet"]));
const inr = (n) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: n % 1 ? 2 : 0 }).format(n || 0);

const ROLE_WORD = { doctor: "visits", courier: "deliveries", phlebotomist: "sample collections", physio: "physio sessions" };
let seenOffers = new Set();
const declinedOffers = new Set(); // hidden at once on tap, even before the server answers

/* ------------------------------------------------------------------ dashboard */
SCREENS.dash = async () => {
  const tok = (state.screenTok = {}); // a poll that lands after we've moved to another screen must not redraw
  const status = async () => { const s = await api("/api/provider/status"); s.offers = s.offers.filter((o) => !declinedOffers.has(o.id)); return s; };
  let st = await status();
  const activeJobs = (list) => list.filter((j) => j.kind !== "lab" || ["assigned", "collected"].includes(j.status)); // finished collections live on the Collections tab
  let jobs = st.can_go_online ? activeJobs(await api("/api/provider/jobs")) : [];
  let earn = st.can_go_online ? await api("/api/provider/earnings").catch(() => null) : null;
  let sig = "";
  const signature = () => JSON.stringify([st.online, st.offers.map((o) => o.id), st.active_trip?.id, st.active_trip?.arrived, jobs.map((j) => [j.id, j.status, j.trip_id])]);

  const render = () => {
    sig = signature();
    const word = ROLE_WORD[st.role] || "requests";
    const t = st.active_trip;
    view().innerHTML = `
      <section class="hero partner ${st.online ? "is-online" : ""}">
        <div class="eyebrow">${esc(state.name)}</div>
        <div class="row between" style="align-items:flex-end">
          <div><h1>${st.online ? "You're online" : "You're offline"}</h1>
            <p>${st.online ? `Looking for ${word} near you. New requests appear here, nearest first.` : `Go online to start receiving ${word} from patients near you.`}</p></div>
          <button class="duty ${st.online ? "on" : ""}" id="duty" aria-pressed="${st.online}"><span class="knob">${ic("power")}</span><span class="lbl">${st.online ? "Go offline" : "Go online"}</span></button>
        </div>
        <div class="stats">${earn ? `<button class="stat stat-link" data-earn="1"><b>${inr(earn.today.total)}</b><span>Earned today ›</span></button>` : ""}<div class="stat"><b>${st.offers.length}</b><span>New requests</span></div>
          <div class="stat"><b>${jobs.filter((j) => !["completed", "delivered"].includes(j.status)).length}</b><span>Accepted</span></div>
          <div class="stat"><b>${t ? `${t.eta_min} min` : "—"}</b><span>${t ? "To destination" : "No active trip"}</span></div></div>
      </section>
      ${verifyBanner(st)}
      <div id="faceBanner"></div>
      ${t ? `<button class="live-banner" id="toNav"><span class="live-dot"></span><span class="grow"><b>${t.arrived ? "You've arrived" : `Navigating to ${esc(t.dest_label)}`}</b><span class="tiny">${t.arrived ? "Open to finish this job" : `${t.eta_min} min · ${km(t.remaining_m)} · ${esc(t.next_step?.text || "")}`}</span></span><span class="btn sm">${ic("nav")} Navigate</span></button>` : ""}
      <div class="split"><div>
        <div class="section-title">Requests</div>
        <div id="offers">${st.offers.length ? st.offers.map(offerCard).join("") : `<div class="card empty slim">${st.online ? `<div class="radar-mini"></div><h3>Waiting for requests</h3><p class="small">Stay online. Requests from patients near you will appear here.</p>` : `<div class="ico">${ic("power")}</div><h3>You're offline</h3><p class="small">Go online to receive nearby ${word}.</p>`}</div>`}</div>
        ${jobs.length ? `<div class="section-title">Your jobs</div>${jobs.map(jobCard).join("")}` : ""}
      </div><aside class="sticky">
        ${earn ? `<button class="card earn-mini" data-earn="1"><div class="row between"><span class="eyebrow-sm">${ic("wallet")} This week</span><span class="tiny muted">${earn.week.jobs} job${earn.week.jobs === 1 ? "" : "s"}</span></div>
          <div class="earn-big">${inr(earn.week.total)}</div>
          <div class="mini-bars">${earn.week.days.map((d) => `<i class="${d.today ? "today" : ""}" style="height:${Math.max(4, Math.round((d.total / Math.max(1, ...earn.week.days.map((x) => x.total))) * 100))}%"></i>`).join("")}</div>
          <div class="row between small"><span class="muted">Balance ${inr(earn.balance)}</span><span class="strong" style="color:var(--brand)">View earnings ›</span></div></button>` : ""}
        <div class="card map-card"><div class="mini-map" id="areaMap"></div>
          <div class="row between small" style="margin-top:10px"><span class="muted">${ic("pin")} Your location</span><span class="badge ${st.online ? "good" : ""}">${st.online ? "Visible to dispatch" : "Hidden"}</span></div></div>
        <div class="notice info small">${ic("info")}<span>Demo: your GPS is simulated. In the field the app uses your phone's location.</span></div>
      </aside></div>`;
    wire();
    faceBanner();
    drawArea();
    tickCountdowns();
  };

  const drawArea = () => {
    const map = makeMap($("#areaMap"), { center: st.location, zoom: 14, interactive: false });
    if (!map) return;
    L.marker(st.location, { icon: markerIcon("me", ic("nav"), st.online ? "pulse" : "") }).addTo(map);
    const pts = [st.location];
    st.offers.forEach((o) => {
      if (o.pickup) { L.marker([o.pickup.lat, o.pickup.lng], { icon: markerIcon("pharmacy", ic("store")) }).addTo(map); pts.push([o.pickup.lat, o.pickup.lng]); }
      L.marker([o.dropoff.lat, o.dropoff.lng], { icon: markerIcon("home", ic("home2")) }).addTo(map); pts.push([o.dropoff.lat, o.dropoff.lng]);
      L.polyline([st.location, ...(o.pickup ? [[o.pickup.lat, o.pickup.lng]] : []), [o.dropoff.lat, o.dropoff.lng]], { color: "#0b7a6c", weight: 3, dashArray: "4 8" }).addTo(map);
    });
    if (pts.length > 1) map.fitBounds(pts, { padding: [30, 30], maxZoom: 15 });
  };

  const wire = () => {
    $("#duty").onclick = () => guard(async () => {
      st = await post("/api/provider/duty", { online: !st.online });
      toast(st.online ? "You're online. Requests near you will appear here." : "You're offline", st.online ? "bolt" : "info");
      stopLive(); SCREENS.dash();
    });
    const tn = $("#toNav"); if (tn) tn.onclick = () => navScreen();
    $$("[data-earn]").forEach((b) => (b.onclick = () => go("earnings")));
    $$("[data-accept]").forEach((b) => (b.onclick = () => guard(async () => {
      b.disabled = true;
      const offer = st.offers.find((o) => o.id === +b.dataset.accept);
      const r = await post(`/api/provider/offers/${b.dataset.accept}/accept`);
      if (r.trip) { toast("Accepted. Let's go!", "check"); navScreen(); }
      else if (offer?.kind === "visit" && offer.on_demand) { toast("Accepted. Verify it's you to start the journey.", "check"); stopLive(); SCREENS.dash(); faceStartJourney(offer.visit_id); }
      else { toast("Accepted.", "check"); stopLive(); SCREENS.dash(); }
    })));
    $$("[data-decline]").forEach((b) => (b.onclick = async () => {
      /* Take the card away straight away (like Dasher) so a slow network never looks like a dead button. */
      const id = +b.dataset.decline, card = b.closest(".offer");
      card.querySelectorAll("button").forEach((x) => (x.disabled = true));
      b.textContent = "Declining…";
      declinedOffers.add(id);
      card.classList.add("leaving");
      try {
        await post(`/api/provider/offers/${id}/decline`);
        toast("Declined. We'll offer it to the next nearest provider.", "info");
      } catch (e) {
        if (e.status !== 409 && e.status !== 404) { declinedOffers.delete(id); toast(e.message, "alert"); }
      }
      stopLive(); SCREENS.dash();
    }));
    $$("[data-depart]").forEach((b) => (b.onclick = () => faceStartJourney(+b.dataset.depart)));
    $$("[data-nav]").forEach((b) => (b.onclick = () => navScreen()));
    $$("[data-visits]").forEach((b) => (b.onclick = () => go("visits")));
    $$("[data-collect]").forEach((b) => (b.onclick = () => guard(async () => { await post(`/api/pharmacy/orders/${b.dataset.collect}/dispatch`); navScreen(); })));
    wireLabJobs();
    $$("[data-pdepart]").forEach((b) => (b.onclick = () => guard(async () => { await post(`/api/physio/sessions/${b.dataset.pdepart}/depart`); navScreen(); })));
    $$("[data-pstart]").forEach((b) => (b.onclick = () => guard(async () => { await post(`/api/physio/sessions/${b.dataset.pstart}/start`); physioNotesScreen(+b.dataset.pstart); })));
    $$("[data-notes]").forEach((b) => (b.onclick = () => physioNotesScreen(+b.dataset.notes)));
  };

  if (state.screenTok !== tok) return;
  render();
  st.offers.forEach((o) => seenOffers.add(o.id));
  every(1000, async () => tickCountdowns());
  every(3000, async () => {
    const [s2, j2, e2] = await Promise.all([status(), st.can_go_online ? api("/api/provider/jobs") : [], st.can_go_online ? api("/api/provider/earnings").catch(() => earn) : null]);
    if (e2 && earn && e2.today.total !== earn.today.total) sig = "";
    earn = e2;
    const fresh = s2.offers.filter((o) => !seenOffers.has(o.id));
    st = s2; jobs = activeJobs(j2);
    if (fresh.length) {
      fresh.forEach((o) => seenOffers.add(o.id));
      try { navigator.vibrate?.([120, 60, 120]); } catch {}
      toast(`New request · ${fresh[0].distance_km} km away`, "bolt");
    }
    if (state.screenTok !== tok) return;
    if (signature() !== sig) { stopLiveMapsOnly(); render(); }
  });
};

function stopLiveMapsOnly() { /* remove maps but keep the polling timers */
  state.cleanups.forEach((f) => { try { f(); } catch {} }); state.cleanups = [];
}

function tickCountdowns() {
  $$("[data-expires]").forEach((el) => {
    const left = Math.max(0, Math.round((new Date(el.dataset.expires + "Z") - Date.now()) / 1000));
    const total = +el.dataset.total || 45;
    el.querySelector("b").textContent = left;
    el.querySelector("circle.fg").style.strokeDashoffset = `${113 * (1 - left / total)}`;
    el.closest(".offer")?.classList.toggle("urgent", left <= 10);
  });
}

function offerCard(o) {
  const ring = o.expires_at ? `<div class="ring" data-expires="${esc(o.expires_at)}" data-total="${o.offer_seconds}"><svg viewBox="0 0 40 40"><circle class="bg" cx="20" cy="20" r="18"/><circle class="fg" cx="20" cy="20" r="18"/></svg><b>${o.seconds_left}</b></div>` : `<span class="badge info">${ic("calendar")} Booked time</span>`;
  return `<article class="offer card">
    <div class="row between" style="flex-wrap:nowrap;align-items:flex-start">
      <div><div class="eyebrow-sm">${o.on_demand ? `<span class="live-dot"></span> ${esc(o.title)}` : esc(o.title)}</div>
        <div class="earning">${money(o.earning)}</div>
        <div class="meta"><span>${ic("pin")} ${o.distance_km} km away</span><span>${ic("clock")} ~${o.drive_min} min drive</span>${o.on_demand ? "" : `<span>${ic("calendar")} ${when(o.scheduled_for)}</span>`}</div></div>
      ${ring}</div>
    <div class="route-list">
      ${o.pickup ? `<div><span class="dot a"></span><div><b>Pick up</b><span class="tiny muted">${esc(shortName(o.pickup.label))}</span></div></div>` : ""}
      <div><span class="dot b"></span><div><b>${o.kind === "delivery" ? "Drop off" : o.kind === "lab" ? "Collect from" : "Patient"}</b><span class="tiny muted">${esc(o.patient)}${o.address ? ` · ${esc(o.address)}` : o.dropoff_km ? ` · ${o.dropoff_km} km from pickup` : ""}</span></div></div>
      ${o.lab ? `<div><span class="dot a"></span><div><b>Drop at lab</b><span class="tiny muted">${esc(shortName(o.lab.label))} · ${o.lab_km} km from patient</span></div></div>` : ""}
    </div>
    ${o.reason ? `<div class="instructions">${esc(o.reason)}</div>` : ""}
    ${o.kind === "physio" ? `<div class="row small" style="margin-top:8px"><span class="badge premium">${ic("heart")} ${esc(o.plan)}</span>${o.sessions_total > 1 ? `<span class="badge good">${money(o.package_earning)} for all ${o.sessions_total} sessions</span>` : ""}</div>` : ""}
    ${o.cold_chain ? `<div class="row small" style="margin-top:8px"><span class="badge info">${ic("snow")} Keep cold</span></div>` : ""}
    <div class="offer-actions"><button class="btn ghost" data-decline="${o.id}">Decline</button><button class="btn primary" data-accept="${o.id}">${ic("check")} Accept</button></div>
  </article>`;
}

function jobCard(j) {
  if (j.kind === "physio") return physioJobCard(j);
  if (j.kind === "lab") return labJobCard(j);
  const visit = j.kind === "visit";
  const label = { accepted: ["Accepted", "brand"], in_progress: ["With patient", "warn"], ready_for_pickup: ["Collect from pharmacy", "info"], out_for_delivery: ["Out for delivery", "brand"], delivered: ["Delivered", "good"] }[j.status] || [j.status, ""];
  let action = "";
  if (j.trip_id) action = `<button class="btn primary sm" data-nav="1">${ic("nav")} Navigate</button>`;
  else if (visit && j.status === "accepted") action = `<button class="btn primary sm" data-depart="${j.id}">${ic("scan")} Verify face &amp; start journey</button>`;
  else if (visit && j.status === "in_progress") action = `<button class="btn sm" data-visits="1">${ic("rx")} Consultation & prescription</button>`;
  else if (!visit && j.status === "ready_for_pickup") action = `<button class="btn primary sm" data-collect="${j.id}">${ic("truck")} Collected, start delivery</button>`;
  return `<article class="card job"><div class="card-head"><div class="row" style="flex-wrap:nowrap"><div class="avatar">${visit ? ic("stethoscope") : ic("truck")}</div>
      <div><h3>${esc(j.patient)}</h3><div class="meta">${visit ? `<span>${ic("clock")} ${j.on_demand ? "Now" : when(j.scheduled_for)}</span>` : `<span>${ic("bag")} ${esc(j.order_no)}</span>`}<span>${ic("pin")} ${esc(j.address)}</span></div></div></div>
      <span class="badge ${label[1]}">${label[0]}</span></div>
    ${j.reason ? `<div class="instructions">${esc(j.reason)}</div>` : ""}
    ${action ? `<div class="actions-bar">${action}</div>` : ""}</article>`;
}

function physioJobCard(j) {
  const label = { scheduled: ["Upcoming", "brand"], in_progress: ["In session", "warn"] }[j.status] || [j.status, ""];
  let action = "";
  if (j.trip_id) action = `<button class="btn primary sm" data-nav="1">${ic("nav")} Navigate</button>`;
  else if (j.status === "scheduled") action = `<button class="btn primary sm" data-pdepart="${j.id}">${ic("nav")} Start trip</button><button class="btn sm" data-pstart="${j.id}">${ic("heart")} I'm here, start session</button>`;
  else if (j.status === "in_progress") action = `<button class="btn primary sm" data-notes="${j.id}">${ic("file")} Write notes and finish</button>`;
  return `<article class="card job"><div class="card-head"><div class="row" style="flex-wrap:nowrap"><div class="avatar">${ic("heart")}</div>
      <div><h3>${esc(j.patient)}</h3><div class="meta"><span>${ic("clock")} ${j.on_demand ? "Now" : when(j.scheduled_for)}</span><span>Session ${j.number} of ${j.sessions_total}</span><span>${ic("pin")} ${esc(j.address)}</span></div></div></div>
      <span class="badge ${label[1]}">${label[0]}</span></div>
    ${j.reason ? `<div class="instructions">${esc(j.reason)}</div>` : ""}
    <div class="actions-bar">${action}</div></article>`;
}

/* ------------------------------------------------------------------ road routing (free OSRM demo server) */
function osrmText(step, destLabel) {
  const m = step.maneuver, name = step.name || "", mod = m.modifier || "straight";
  const onto = name ? ` onto ${name}` : "";
  switch (m.type) {
    case "depart": return `Head ${["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"][Math.round((m.bearing_after || 0) / 45) % 8]}${name ? ` on ${name}` : ""}`;
    case "arrive": return `Arrive at ${destLabel}`;
    case "roundabout": case "rotary": return `At the roundabout, take exit ${m.exit || 1}${onto}`;
    case "fork": return `Keep ${mod.replace("slight ", "")} at the fork${onto}`;
    case "merge": return `Merge ${mod.replace("slight ", "")}${onto}`;
    case "end of road": return `At the end of the road, turn ${mod.replace("slight ", "")}${onto}`;
    case "new name": case "continue": return mod === "straight" ? `Continue${onto || " straight"}` : `Keep ${mod}${onto}`;
    default: return mod === "straight" ? `Continue straight${onto}` : mod === "uturn" ? "Make a U-turn" : `Turn ${mod}${onto}`;
  }
}

async function roadRoute(trip) {
  const [a, b] = [trip.origin, trip.destination];
  const ctrl = new AbortController(); setTimeout(() => ctrl.abort(), 7000);
  const r = await fetch(`https://router.project-osrm.org/route/v1/driving/${a[1]},${a[0]};${b[1]},${b[0]}?overview=full&geometries=geojson&steps=true`, { signal: ctrl.signal });
  const j = await r.json();
  if (j.code !== "Ok" || !j.routes?.length) throw new Error("no route");
  const rt = j.routes[0];
  let along = 0;
  const steps = rt.legs[0].steps.map((s) => { const out = { text: osrmText(s, trip.dest_label).slice(0, 200), along_m: Math.round(along), type: s.maneuver.type, modifier: s.maneuver.modifier || "straight" }; along += s.distance; return out; });
  let route = rt.geometry.coordinates.map(([lng, lat]) => [lat, lng]);
  if (route.length > 4000) route = route.filter((_, i) => i % Math.ceil(route.length / 4000) === 0).concat([route[route.length - 1]]);
  return { route, steps: steps.slice(0, 200), distance_m: Math.max(rt.distance, 1), duration_s: Math.max(rt.duration, 1), source: "osrm" };
}
const triedRoad = new Set();

/* ------------------------------------------------------------------ turn-by-turn navigation */
async function navScreen() {
  stopLive();
  state.screenTok = "nav";
  state.tab = "dash"; renderNav();
  let t = await api("/api/provider/trip");
  if (!t) { toast("No active trip", "info"); return go("dash"); }
  const labJob = t.lab_booking_id ? (await api("/api/provider/jobs")).find((j) => j.kind === "lab" && j.id === t.lab_booking_id) : null;
  const destIco = t.leg === "to_lab" ? "flask" : t.leg === "to_pharmacy" ? "store" : "home2";
  document.body.classList.add("nav-mode");
  state.cleanups.push(() => document.body.classList.remove("nav-mode"));
  view().innerHTML = `<div class="nav">
      <div class="nav-banner" id="navBanner"></div>
      <div class="nav-map" id="navMap"></div>
      <button class="map-back" id="navBack" aria-label="Back to dashboard">${ic("arrow")}</button>
      <button class="recenter" id="recenter" aria-label="Recenter">${ic("nav")}</button>
      <div class="nav-sheet" id="navSheet"></div></div>`;
  $("#navBack").onclick = () => go("dash");
  const map = makeMap($("#navMap"), { center: t.position, zoom: 16 });
  const M = {};
  let follow = true, routeKey = "";
  if (map) {
    map.on("dragstart", () => { follow = false; $("#recenter").classList.add("show"); });
    M.dest = L.marker(t.destination, { icon: markerIcon(t.leg === "to_patient" ? "home" : "pharmacy", ic(destIco)), zIndexOffset: 100 }).addTo(map);
    M.me = L.marker(t.position, { icon: markerIcon("me", `<i class="hd">${ic("nav")}</i>`), zIndexOffset: 600 }).addTo(map);
  }
  $("#recenter").onclick = () => { follow = true; $("#recenter").classList.remove("show"); map && map.setView(t.position, 16); };

  const drawRoute = () => {
    if (!map) return;
    const key = `${t.id}:${t.source}`;
    if (key === routeKey) return;
    routeKey = key;
    [M.bg, M.line].forEach((x) => x && x.remove());
    M.bg = L.polyline(t.route, { color: "#06302a", weight: 11, opacity: .25, lineCap: "round" }).addTo(map);
    M.line = L.polyline(routeAhead(t), { color: "#2c7bf2", weight: 7, opacity: .95, lineCap: "round", lineJoin: "round" }).addTo(map);
    map.fitBounds(t.route, { padding: [60, 60], maxZoom: 16 });
    setTimeout(() => { if (follow) map.setView(t.position, 16, { animate: true }); }, 1200);
  };

  const draw = () => {
    const s = t.next_step;
    const idx = t.steps.indexOf(t.steps.find((x) => x.along_m === s?.along_m && x.text === s?.text));
    const then = idx >= 0 ? t.steps[idx + 1] : null;
    $("#navBanner").className = `nav-banner ${t.arrived ? "arrived" : ""}`;
    $("#navBanner").innerHTML = t.arrived
      ? `<div class="mv">${ic("flag")}</div><div class="grow"><div class="dist">You've arrived</div><div class="instr">${esc(t.dest_label)}</div></div>`
      : `<div class="mv">${ic(MANEUVER(s))}</div><div class="grow"><div class="dist">${km(t.next_step_in_m)}</div><div class="instr">${esc(s?.text || "Continue")}</div>
         ${then ? `<div class="then">Then ${ic(MANEUVER(then))} ${esc(then.text)}</div>` : ""}</div>`;
    if (M.line) M.line.setLatLngs(routeAhead(t));
    if (M.me) {
      glide(M.me, t.position, 1300);
      const hd = M.me.getElement()?.querySelector(".hd"); if (hd) hd.style.transform = `rotate(${t.heading - 45}deg)`;
      if (follow && map) map.panTo(t.position, { animate: true, duration: 1.2 });
    }
    const isVisit = !!t.visit_id;
    let actions;
    if (t.lab_booking_id) actions = labNavActions(t, labJob);
    else if (t.physio_session_id) actions = `<button class="btn primary block" id="navPhysio" ${t.arrived ? "" : "disabled"}>${ic("heart")} ${t.arrived ? "Start session" : "Start session on arrival"}</button>`;
    else if (isVisit) actions = `<div class="row small" style="margin-bottom:8px"><span class="id-verified">${ic("shield")} Identity verified for this visit</span></div>
      <label class="field">Patient's arrival code<input id="arrCode" inputmode="numeric" maxlength="4" autocomplete="off" placeholder="4 digits from the patient's app"></label>
      <button class="btn primary block" id="navStart" ${t.arrived ? "" : "disabled"} style="margin-top:8px">${ic("stethoscope")} ${t.arrived ? "Confirm code and start visit" : "Start visit on arrival"}</button>`;
    else if (t.leg === "to_pharmacy") actions = `<button class="btn primary block" id="navCollect">${ic("bag")} ${t.arrived ? "Collected, start delivery" : "Collected the order"}</button>`;
    else actions = `<div class="form-grid"><label>Handover code<input id="hoCode" inputmode="numeric" maxlength="4" placeholder="4 digits"></label><label>Received by<input id="hoWho" placeholder="Name"></label></div>
      <label class="check" style="margin:10px 0"><input type="checkbox" id="hoId"><span>Photo ID checked (if required)</span></label>
      <button class="btn primary block" id="navDeliver">${ic("check")} Confirm delivery</button>`;
    $("#navSheet").innerHTML = `<div class="grab"></div>
      <div class="row between" style="flex-wrap:nowrap">
        <div><div class="eta-big">${t.arrived ? "Arrived" : `${t.eta_min} min`}</div><div class="small muted">${t.arrived ? esc(t.dest_label) : `${km(t.remaining_m)} · arrive ${clock(t.eta_min)}`}</div></div>
        <a class="btn sm" target="_blank" rel="noopener" href="https://www.google.com/maps/dir/?api=1&destination=${t.destination[0]},${t.destination[1]}&travelmode=driving">${ic("nav")} Google Maps</a></div>
      <div class="trip-bar"><i style="width:${Math.round(t.fraction * 100)}%"></i></div>
      <div class="row small" style="margin:8px 0 12px"><span class="badge">${ic(destIco)} ${esc(t.dest_label)}</span><span class="badge ${t.source === "osrm" ? "good" : ""}">${t.source === "osrm" ? "Road route" : "Approximate route"}</span><span class="badge">Demo GPS ×${t.speedup}</span></div>
      <div id="navActions">${actions}</div>`;
    wireActions();
  };

  const wireActions = () => {
    const ps = $("#navPhysio"); if (ps) ps.onclick = () => guard(async () => { await post(`/api/physio/sessions/${t.physio_session_id}/start`); toast("Session started", "heart"); physioNotesScreen(t.physio_session_id); });
    const st = $("#navStart"); if (st) st.onclick = () => guard(async () => { await post(`/api/doctor/visits/${t.visit_id}/start`, { arrival_code: $("#arrCode").value.trim() }); toast("Visit started. Write your notes and vitals here.", "stethoscope"); state.tab = "visits"; renderNav(); notesScreen(t.visit_id); });
    const co = $("#navCollect"); if (co) co.onclick = () => guard(async () => { await post(`/api/pharmacy/orders/${t.order_id}/dispatch`); toast("Collected. Navigating to the patient.", "truck"); navScreen(); });
    const dl = $("#navDeliver"); if (dl) dl.onclick = () => guard(async () => {
      await post(`/api/orders/${t.order_id}/handover`, { code: $("#hoCode").value, recipient_name: $("#hoWho").value || "Patient", id_verified: $("#hoId").checked });
      toast("Delivered. Your pay was added to Earnings."); go("dash");
    });
    wireLabNav(t);
  };

  drawRoute(); draw();
  if (t.source === "synthetic" && !triedRoad.has(t.id)) {
    triedRoad.add(t.id);
    roadRoute(t).then((r) => api(`/api/provider/trips/${t.id}/route`, { method: "PUT", body: r })).then((nt) => { if (nt) { t = nt; drawRoute(); draw(); } }).catch(() => {});
  }
  let keepForms = false;
  every(1500, async () => {
    const nt = await api("/api/provider/trip");
    if (!nt) return go("dash");
    if (nt.id !== t.id) return navScreen(); // e.g. sample collected: now heading to the lab
    const typing = document.activeElement && ["hoCode", "hoWho", "labCode", "arrCode"].includes(document.activeElement.id);
    keepForms = typing || ($("#hoCode")?.value || "") !== "" || ($("#labCode")?.value || "") !== "" || ($("#arrCode")?.value || "") !== "";
    const arrivedNow = nt.arrived && !t.arrived;
    t = nt; drawRoute();
    if (keepForms && !arrivedNow) { // update only the moving parts while the courier is typing
      if (M.me) glide(M.me, t.position, 1300);
      return;
    }
    draw();
    if (arrivedNow) { try { navigator.vibrate?.(300); } catch {} toast("You've arrived", "flag"); }
  });
}

/* ------------------------------------------------------------------ earnings */
SCREENS.earnings = async () => {
  const e = await api("/api/provider/earnings");
  const max = Math.max(1, ...e.week.days.map((d) => d.total));
  const range = `${day(e.week.days[0].date + "T06:00:00")} – ${day(e.week.days[6].date + "T06:00:00")}`;
  const keyOfIso = (iso) => parseIso(iso).toLocaleDateString("en-CA", { timeZone: TZ });
  const byDay = {};
  e.jobs.forEach((j) => { const k = keyOfIso(j.earned_at); (byDay[k] = byDay[k] || []).push(j); });
  const todayK = new Date().toLocaleDateString("en-CA", { timeZone: TZ });
  const yestK = new Date(Date.now() - 864e5).toLocaleDateString("en-CA", { timeZone: TZ });
  const dayTitle = (k) => (k === todayK ? "Today" : k === yestK ? "Yesterday" : new Date(k + "T06:00:00Z").toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" }));
  view().innerHTML = `
    <section class="hero partner earn-hero"><div class="eyebrow">This week · ${esc(range)}</div>
      <h1 class="earn-total">${inr(e.week.total)}</h1>
      <p>${e.week.jobs} job${e.week.jobs === 1 ? "" : "s"}${e.week.bonus ? ` · includes ${inr(e.week.bonus)} in bonuses` : ""}</p>
      <div class="bars" role="img" aria-label="Earnings by day this week">${e.week.days.map((d) => `<button class="bar ${d.today ? "today" : ""} ${d.future ? "future" : ""}" data-day="${d.date}" title="${inr(d.total)}">
          <span class="amt">${d.total ? inr(d.total) : ""}</span><span class="col"><i style="height:${d.total ? Math.max(6, Math.round((d.total / max) * 100)) : 3}%"></i></span><span class="lbl">${d.label}</span></button>`).join("")}</div>
    </section>
    <div class="earn-tiles">
      <div class="card"><span class="eyebrow-sm">Today</span><b>${inr(e.today.total)}</b><span class="tiny muted">${e.today.jobs} job${e.today.jobs === 1 ? "" : "s"}</span></div>
      <div class="card"><span class="eyebrow-sm">Balance</span><b>${inr(e.balance)}</b><span class="tiny muted">Paid out Monday</span></div>
      <div class="card"><span class="eyebrow-sm">All time</span><b>${inr(e.lifetime.total)}</b><span class="tiny muted">${e.lifetime.jobs} jobs</span></div>
    </div>
    <div class="split earn-split"><div>
      <div class="section-title">Jobs</div>
      ${Object.keys(byDay).length ? Object.entries(byDay).map(([k, list]) => `<div class="card earn-day" data-k="${k}"><div class="row between"><h3>${esc(dayTitle(k))}</h3><b>${inr(list.reduce((a, j) => a + j.total, 0))}</b></div>
        ${list.map((j) => `<details class="earn-job"><summary><span class="avatar">${ic(j.kind === "visit" ? "stethoscope" : j.kind === "lab" ? "flask" : j.kind === "physio" ? "heart" : "truck")}</span>
            <span class="grow"><b>${esc(j.title)}</b><span class="tiny muted">${time(j.earned_at)} · ${j.distance_km} km${j.paid_out ? " · paid out" : ""}</span></span>
            <span class="amt">${inr(j.total)}</span></summary>
          <table class="price"><tr><td>${j.kind === "visit" ? "Visit fee" : j.kind === "physio" ? "Session pay" : "Delivery pay"}</td><td>${inr(j.base)}</td></tr>
            ${j.bonus ? `<tr><td>Doctor now bonus</td><td>${inr(j.bonus)}</td></tr>` : ""}${j.tip ? `<tr><td>Tip</td><td>${inr(j.tip)}</td></tr>` : ""}
            <tr class="total"><td>You earned</td><td>${inr(j.total)}</td></tr></table></details>`).join("")}</div>`).join("")
        : empty("wallet", "No earnings yet", "Go online and complete a job. Your pay shows up here right away.")}
    </div><aside class="sticky">
      <div class="card featured payout-card"><span class="eyebrow-sm">${ic("wallet")} Available to cash out</span>
        <div class="earn-big">${inr(e.balance)}</div>
        <div class="small muted">Next automatic payout <b>${day(e.next_payout.date + "T06:00:00")}</b> (Monday)</div>
        <div class="row small" style="margin:10px 0"><span class="badge">${ic("bolt")} ${esc(e.payout_method)}</span></div>
        <button class="btn primary block" id="cashOut" ${e.balance >= 1 ? "" : "disabled"}>${ic("bolt")} Cash out ${inr(e.balance)} now</button>
        <p class="tiny muted" style="margin:8px 0 0;text-align:center">Instant payout to UPI · no fee in the demo</p></div>
      <div class="card"><h3>Payouts</h3>${e.payouts.map((p) => `<div class="list-item"><div class="avatar">${ic("check")}</div><div class="grow"><b>${inr(p.amount)}</b><div class="tiny muted">${p.kind === "instant" ? "Instant cash out" : "Weekly payout"} · ${day(p.at)} · ${esc(p.reference)}</div></div><span class="badge good">Paid</span></div>`).join("") || `<p class="small muted">No payouts yet.</p>`}</div>
      <div class="notice info small">${ic("info")}<span>${esc(e.rules)}</span></div>
    </aside></div>`;
  $$(".bar").forEach((b) => (b.onclick = () => { const el = $(`.earn-day[data-k="${b.dataset.day}"]`); if (el) el.scrollIntoView({ behavior: "smooth", block: "center" }); else toast("No jobs that day", "info"); }));
  const co = $("#cashOut"); if (co) co.onclick = () => guard(async () => {
    if (!confirm(`Cash out ${inr(e.balance)} to ${e.payout_method}?`)) return;
    co.disabled = true;
    await post("/api/provider/earnings/cash-out"); toast(`${inr(e.balance)} is on its way to your UPI`, "check"); SCREENS.earnings();
  });
};

/* ------------------------------------------------------------------ courier: deliveries list */
SCREENS.deliveries = async () => {
  const [jobs, shop] = await Promise.all([api("/api/provider/jobs"), state.role === "courier" ? api("/api/pharmacy/orders").catch(() => []) : []]);
  const waiting = shop.filter((o) => o.fulfillment === "delivery" && o.status === "ready_for_pickup" && !o.delivery?.courier);
  view().innerHTML = `<section class="hero partner"><div class="eyebrow">${esc(state.name)}</div><h1>Your deliveries</h1><p>Requests you accept appear here. Navigate to the pharmacy, collect, then deliver with the patient's handover code.</p>
    <div class="stats"><div class="stat"><b>${jobs.filter((o) => o.status === "ready_for_pickup").length}</b><span>To collect</span></div><div class="stat"><b>${jobs.filter((o) => o.status === "out_for_delivery").length}</b><span>On the road</span></div><div class="stat"><b>${jobs.filter((o) => o.status === "delivered").length}</b><span>Delivered</span></div></div></section>
    ${waiting.length ? `<div class="section-title">Waiting at your pharmacy</div>${waiting.map((o) => `<article class="card job"><div class="card-head"><div class="row"><div class="avatar">${ic("bag")}</div><div><h3>${esc(o.patient.name)}</h3><div class="tiny muted">${esc(o.order_no)}</div></div></div><span class="badge info">Unassigned</span></div>
      <div class="actions-bar"><button class="btn primary sm" data-collect="${o.id}">${ic("truck")} Collected, start delivery</button></div></article>`).join("")}` : ""}
    <div class="section-title">Accepted</div>
    ${jobs.map(jobCard).join("") || empty("truck", "No deliveries yet", "Go online on your dashboard to receive nearby deliveries.")}`;
  $$("[data-nav]").forEach((b) => (b.onclick = () => navScreen()));
  $$("[data-collect]").forEach((b) => (b.onclick = () => guard(async () => { await post(`/api/pharmacy/orders/${b.dataset.collect}/dispatch`); navScreen(); })));
};

boot();
