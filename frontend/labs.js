/* Triyana — Lab tests at home. Patient: choose tests, book a slot or "collect now", track the
   sample collector live, read reports. Nabzo: phlebotomists collect at the door and drop at the lab. */
"use strict";

Object.assign(P, {
  flask: '<path d="M9 3h6M10 3v6L4.5 18.5A2 2 0 0 0 6.2 21.5h11.6a2 2 0 0 0 1.7-3L14 9V3"/><path d="M7 15h10"/>',
  drop: '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/>',
  report: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M8 17v-3M11 17v-5M14 17v-2"/>',
  print: '<path d="M6 9V3h12v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M6 14h12v7H6z"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
  tube: '<path d="M9 3h6M10 3v15a2 2 0 0 0 4 0V3"/><path d="M10 12h4"/>',
});

TABS.patient.splice(2, 0, ["labs", "Lab tests", "flask", "desktop"]);
TABS.phlebotomist = [["dash", "Dashboard", "bolt"], ["earnings", "Earnings", "wallet"], ["collections", "Collections", "flask"]];
Object.assign(SHORT, { "Lab tests": "Labs", Collections: "Samples" });

const LAB_OPEN = ["booked", "assigned", "collected", "at_lab"];
const LAB_BADGE = { booked: ["Finding collector", "info"], assigned: ["Collector confirmed", "good"], collected: ["Sample on the way to lab", "brand"], at_lab: ["Testing at lab", "warn"], report_ready: ["Report ready", "good"], cancelled: ["Cancelled", ""] };
const labCart = { ids: new Set() };

/* ------------------------------------------------------------------ patient: catalog */
SCREENS.labs = async () => {
  const [cat, bookings, near] = await Promise.all([api("/api/labs/catalog"), api("/api/labs/bookings"), api("/api/patient/collectors-nearby")]);
  const all = [...cat.packages, ...cat.tests];
  const f = { q: "", cat: "All" };
  const active = bookings.filter((b) => LAB_OPEN.includes(b.status));
  const reports = bookings.filter((b) => b.status === "report_ready");

  const card = (t) => {
    const on = labCart.ids.has(t.id);
    return `<article class="card lab-item ${t.kind} ${on ? "on" : ""}">
      <div class="row between" style="flex-wrap:nowrap;align-items:flex-start;gap:10px">
        <div class="grow"><div class="row" style="gap:6px">${t.popular ? `<span class="badge premium">Popular</span>` : ""}${t.kind === "package" ? `<span class="badge info">${t.parameter_count} parameters</span>` : `<span class="badge">${esc(t.category)}</span>`}</div>
          <h3>${esc(t.name)}</h3><p class="small muted" style="margin:2px 0 6px">${esc(t.about)}</p>
          ${t.includes ? `<div class="tiny muted lab-includes">Includes: ${t.includes.map(esc).join(" · ")}</div>` : ""}
          <div class="meta">${t.fasting_hours ? `<span>${ic("clock")} Fasting ${t.fasting_hours} h</span>` : `<span>${ic("check")} No fasting</span>`}<span>${ic("drop")} ${esc(t.sample)}</span><span>${ic("report")} Report in ${t.turnaround_hours} h</span></div></div>
        <div class="lab-price"><b>${money(t.price)}</b><s class="tiny muted">${money(t.mrp)}</s><span class="tiny good-text">${t.discount_pct}% off</span>
          <button class="btn ${on ? "" : "primary"} sm" data-add="${t.id}">${on ? `${ic("check")} Added` : "Add"}</button></div>
      </div></article>`;
  };

  const render = () => {
    const q = f.q.trim().toLowerCase();
    const match = (t) => (!q || `${t.name} ${t.about} ${t.category} ${(t.includes || []).join(" ")}`.toLowerCase().includes(q)) && (f.cat === "All" || (f.cat === "Packages" ? t.kind === "package" : t.category === f.cat));
    const pk = cat.packages.filter(match), ts = cat.tests.filter(match);
    const chosen = all.filter((t) => labCart.ids.has(t.id));
    const sum = chosen.reduce((s, t) => s + t.price, 0);
    view().innerHTML = `
      <section class="hero lab-hero"><div class="eyebrow">${ic("flask")} Lab tests at home</div>
        <h1>Blood tests at home, reports on your phone</h1>
        <p>A certified phlebotomist comes to your door, collects your sample, and ${esc(cat.lab?.name || "our partner lab")} (${esc(cat.lab?.accreditation || "")}) sends your report here.</p>
        <div class="row svc-meta" style="margin-top:12px"><span class="chip-glass"><span class="live-dot"></span> ${near.collectors ? `${near.collectors} sample collector${near.collectors > 1 ? "s" : ""} online nearby` : "Collectors offline right now. Book a time slot."}</span>
          <span class="chip-glass">${ic("shield")} Sealed, barcoded tubes</span><span class="chip-glass">${ic("truck")} Free collection above ${money(cat.fees.free_above)}</span></div>
      </section>
      ${active.length ? `<div class="section-title">Your collections</div>${active.map(bookingCard).join("")}` : ""}
      <div class="lab-search"><span>${ic("search")}</span><input id="labQ" placeholder="Search tests: thyroid, sugar, vitamin D…" value="${esc(f.q)}" autocomplete="off"></div>
      <div class="lab-cats">${["All", "Packages", ...cat.categories].map((c) => `<button class="${c === f.cat ? "on" : ""}" data-cat="${esc(c)}">${esc(c)}</button>`).join("")}</div>
      ${pk.length ? `<div class="section-title">Health packages</div><div class="lab-grid">${pk.map(card).join("")}</div>` : ""}
      ${ts.length ? `<div class="section-title">Individual tests</div><div class="lab-grid">${ts.map(card).join("")}</div>` : ""}
      ${!pk.length && !ts.length ? empty("search", "No tests match", "Try another word, like sugar or thyroid.") : ""}
      ${reports.length ? `<div class="section-title">Your reports</div>${reports.map(bookingCard).join("")}` : ""}
      <div class="lab-bar ${chosen.length ? "show" : ""}"><div class="grow"><b>${chosen.length} selected · ${money(sum)}</b><span class="tiny">${chosen.map((t) => esc(t.name)).join(", ")}</span></div>
        <button class="btn primary" id="labNext">Book collection ${ic("arrow")}</button></div>`;
    wire();
  };
  const wire = () => {
    const qi = $("#labQ");
    qi.oninput = (e) => { f.q = e.target.value; const pos = e.target.selectionStart; render(); const n = $("#labQ"); n.focus(); n.setSelectionRange(pos, pos); };
    $$("[data-cat]").forEach((b) => (b.onclick = () => { f.cat = b.dataset.cat; render(); }));
    $$("[data-add]").forEach((b) => (b.onclick = () => { const id = +b.dataset.add; labCart.ids.has(id) ? labCart.ids.delete(id) : labCart.ids.add(id); render(); }));
    const n = $("#labNext"); if (n) n.onclick = () => go("labbook");
    wireBookingCards(() => SCREENS.labs());
  };
  render();
};

function bookingCard(b) {
  const [label, cls] = LAB_BADGE[b.status] || [b.status, ""];
  const when_ = b.on_demand ? `Collect now · booked ${time(b.created_at)}` : `${dayLabel(b.slot_start)}, ${time(b.slot_start)}–${time(b.slot_end)}`;
  let act = "";
  if (b.status === "report_ready") act = `<button class="btn primary sm" data-report="${b.id}">${ic("report")} View report</button>`;
  else if (LAB_OPEN.includes(b.status)) act = `<button class="btn primary sm" data-lab-live="${b.id}">${ic("pin")} ${["booked", "assigned"].includes(b.status) ? "Track collector" : "Track sample"}</button>`;
  if (b.can_cancel) act += `<button class="btn ghost sm danger" data-lab-cancel="${b.id}">${ic("x")} Cancel</button>`;
  return `<article class="card lab-booking"><div class="card-head"><div class="row" style="flex-wrap:nowrap"><div class="avatar">${ic("flask")}</div>
      <div><h3>${b.items.map((i) => esc(i.name)).join(", ")}</h3><div class="meta"><span>${ic("calendar")} ${when_}</span><span>${esc(b.booking_ref)}</span></div></div></div>
      <span class="badge ${cls}">${label}</span></div>
    ${b.collection_code ? `<div class="code-inline"><span class="tiny">Collection code</span><b>${esc(b.collection_code)}</b><span class="tiny muted">Share it with your collector at the door</span></div>` : ""}
    ${b.status === "at_lab" && b.report_eta ? `<p class="small muted" style="margin:8px 0 0">${ic("clock")} Report expected around ${time(b.report_eta)} (demo labs run fast).</p>` : ""}
    <div class="actions-bar">${act}</div></article>`;
}

function wireBookingCards(after) {
  $$("[data-report]").forEach((b) => (b.onclick = () => go("labreport", { labId: +b.dataset.report })));
  $$("[data-lab-live]").forEach((b) => (b.onclick = () => labLiveScreen(+b.dataset.labLive)));
  $$("[data-lab-cancel]").forEach((b) => (b.onclick = () => guard(async () => {
    if (!confirm("Cancel this lab test booking? Any payment hold is released.")) return;
    await post(`/api/labs/bookings/${b.dataset.labCancel}/cancel`); toast("Booking cancelled"); after();
  })));
}

/* ------------------------------------------------------------------ patient: book a collection */
SCREENS.labbook = async () => {
  if (!labCart.ids.size) return go("labs");
  const b = { when: null, day: null, slot: null, pay: "cash", address: "" };
  let q, slots, cat;
  const load = async () => {
    [q, cat] = await Promise.all([post("/api/labs/quote", { test_ids: [...labCart.ids], on_demand: b.when === "now" }), cat || api("/api/labs/catalog")]);
    if (!slots) slots = await api(`/api/labs/slots?fasting_hours=${q.fasting_hours}`);
    if (!b.address) b.address = q.address;
    if (b.when === null) b.when = q.collectors_online && !q.fasting_hours ? "now" : "slot";
    const days = [...new Set(slots.filter((s) => s.available).map((s) => dayKey(s.start)))];
    if (!days.includes(b.day)) b.day = days.find((d) => slots.some((s) => dayKey(s.start) === d && s.recommended && s.available)) || days[0];
  };
  await load();
  if (b.when === "now") await load(); // price "collect now" correctly

  const render = () => {
    const days = [...new Set(slots.filter((s) => s.available).map((s) => dayKey(s.start)))];
    const daySlots = slots.filter((s) => dayKey(s.start) === b.day);
    const ok = (b.when === "now" ? q.collectors_online : b.slot) && b.address.trim();
    view().innerHTML = `${pageHead("Book home collection", "A certified phlebotomist comes to you. Sealed, barcoded tubes go straight to the lab.", `<button class="btn ghost" id="back">${ic("arrow")} Change tests</button>`)}
      <div class="split"><div>
        <div class="card"><div class="step-label"><span class="n">1</span><h3>Your tests</h3></div>
          ${q.items.map((i) => `<div class="list-item"><div class="avatar">${ic(i.kind === "package" ? "badge" : "flask")}</div><div class="grow"><b>${esc(i.name)}</b><div class="tiny muted">${i.kind === "package" ? "Health package" : "Test"}</div></div><div style="text-align:right"><b>${money(i.price)}</b><div class="tiny muted"><s>${money(i.mrp)}</s></div></div><button class="x-mini" data-rm="${i.id}" aria-label="Remove">${ic("x")}</button></div>`).join("")}
          ${q.removed_duplicates.length ? `<div class="notice info small">${ic("info")}<span>${q.removed_duplicates.map(esc).join(", ")} ${q.removed_duplicates.length > 1 ? "are" : "is"} already in your package, so we removed ${q.removed_duplicates.length > 1 ? "them" : "it"}.</span></div>` : ""}
          <div class="row small" style="margin-top:10px;gap:8px"><span class="badge">${ic("drop")} ${q.samples.map(esc).join(" + ")} sample</span><span class="badge">${ic("report")} Report in ~${q.report_hours} h</span></div>
          ${q.fasting_hours ? `<div class="notice warn small">${ic("clock")}<span><b>Fast for ${q.fasting_hours} hours before collection.</b> Water is fine. We've suggested early-morning slots for you.</span></div>` : ""}
        </div>
        <div class="card"><div class="step-label"><span class="n">2</span><h3>When should we come?</h3></div>
          <div class="choice-grid two">
            <button class="choice ${b.when === "now" ? "on" : ""}" data-when="now" ${q.collectors_online ? "" : "disabled"}><span class="ico">${ic("bolt")}</span><div><b>Collect now</b><span>${q.collectors_online ? `Nearest collector, ~20–40 min · +${money(cat.fees.collect_now_fee)}` : "No collector online right now"}</span></div></button>
            <button class="choice ${b.when === "slot" ? "on" : ""}" data-when="slot"><span class="ico">${ic("calendar")}</span><div><b>Pick a time</b><span>${q.collection_fee && b.when === "slot" ? `${money(q.collection_fee)} collection` : "Free collection above " + money(cat.fees.free_above)}</span></div></button>
          </div>
          ${b.when === "slot" ? `<div style="margin-top:14px"><div class="seg">${days.map((k) => `<button class="${k === b.day ? "on" : ""}" data-day="${esc(k)}">${dayLabel(slots.find((s) => dayKey(s.start) === k).start)}</button>`).join("")}</div>
            <div class="slot-grid">${daySlots.map((s) => `<button class="slot ${s.start === b.slot ? "on" : ""} ${s.recommended ? "rec" : ""}" data-slot="${s.start}" ${s.available ? "" : "disabled"}>${time(s.start)}${s.recommended ? `<span>Fasting</span>` : ""}</button>`).join("")}</div>
            <p class="tiny muted" style="margin:8px 0 0">Each slot is a one-hour window. Your collector's live location shows when they set off.</p></div>` : ""}
        </div>
        <div class="card"><div class="step-label"><span class="n">3</span><h3>Collection address</h3></div>
          <label class="field">Address<input id="labAddr" value="${esc(b.address)}"></label></div>
        <div class="card"><div class="step-label"><span class="n">4</span><h3>Payment</h3></div>
          <div class="choice-grid">${Object.entries(cat.payment_methods).map(([k, v]) => `<button class="choice ${b.pay === k ? "on" : ""}" data-pay="${k}"><span class="ico">${ic(k === "cash" ? "wallet" : k === "card" ? "card" : k === "upi" ? "phone" : "wallet")}</span><div><b>${k === "cash" ? "Pay at collection" : esc({ upi: "UPI", card: "Card", netbanking: "Netbanking", wallet: "Wallet" }[k] || v)}</b><span>${k === "cash" ? "Cash or UPI to the collector" : "Charged only after collection"}</span></div></button>`).join("")}</div></div>
      </div>
      <aside class="sticky"><div class="card featured">
        <h3>Summary</h3>
        <table class="price" style="margin-top:8px">
          <tr><td>Tests (${q.items.length})</td><td>${money(q.subtotal)}</td></tr>
          <tr><td>You save</td><td class="good-text">−${money(q.savings)}</td></tr>
          <tr><td>${b.when === "now" ? "Collect-now fee" : "Home collection"}</td><td>${q.collection_fee ? money(q.collection_fee) : "Free"}</td></tr>
          <tr><td>When</td><td>${b.when === "now" ? "Now" : b.slot ? `${dayLabel(b.slot)}, ${time(b.slot)}` : "—"}</td></tr>
          <tr class="total"><td>Total</td><td>${money(q.total)}</td></tr></table>
        <div class="notice info small">${ic("shield")}<span>${b.pay === "cash" ? "Nothing to pay now." : "We only hold the amount now and charge it after your sample is collected."} Cancel free until collection.</span></div>
        <button class="btn primary block" id="labBook" ${ok ? "" : "disabled"}>${ic("check")} ${b.when === "now" ? "Book and send a collector" : "Confirm booking"}</button>
        <p class="tiny muted" style="text-align:center;margin:10px 0 0">${ok ? "Reports by a NABL-accredited lab (demo)." : "Pick a time to continue"}</p>
      </div></aside></div>`;
    $("#back").onclick = () => go("labs");
    const redo = (fn) => guard(async () => { await fn(); render(); });
    $$("[data-rm]").forEach((x) => (x.onclick = () => redo(async () => { labCart.ids.delete(+x.dataset.rm); if (!labCart.ids.size) return go("labs"); slots = null; await load(); })));
    $$("[data-when]").forEach((x) => (x.onclick = () => redo(async () => { b.when = x.dataset.when; await load(); })));
    $$("[data-day]").forEach((x) => (x.onclick = () => { b.day = x.dataset.day; render(); }));
    $$("[data-slot]").forEach((x) => (x.onclick = () => { b.slot = x.dataset.slot; render(); }));
    $$("[data-pay]").forEach((x) => (x.onclick = () => { b.pay = x.dataset.pay; render(); }));
    $("#labAddr").oninput = (e) => { b.address = e.target.value; $("#labBook").disabled = !((b.when === "now" ? q.collectors_online : b.slot) && b.address.trim()); };
    $("#labBook").onclick = () => guard(async () => {
      $("#labBook").disabled = true;
      try {
        const r = await post("/api/labs/bookings", { test_ids: [...labCart.ids], slot: b.when === "now" ? "now" : b.slot, address: b.address, payment_method: b.pay });
        labCart.ids.clear();
        toast(b.when === "now" ? "Booked. Finding the nearest collector…" : "Collection booked", "check");
        labLiveScreen(r.id);
      } catch (e) { $("#labBook").disabled = false; throw e; }
    });
  };
  render();
};

/* ------------------------------------------------------------------ patient: live tracking */
function labHeadline(d) {
  const who = d.provider?.name || "Your collector";
  return ({ searching: "Finding a sample collector", waiting: "Assigning your collector", confirmed: `${who} will collect your sample`,
    on_the_way: `${who} is on the way`, arrived: `${who} is at your door`, to_lab: "Your sample is on the way to the lab",
    testing: "Testing at the lab", done: "Your report is ready", cancelled: "This booking was cancelled" })[d.phase] || "Live tracking";
}
function labSub(d) {
  return ({ searching: `Asking the nearest collector · ${d.online_nearby} online near you`,
    waiting: `Booked for ${dayLabel(d.scheduled_for)}, ${time(d.scheduled_for)}. We'll confirm your collector shortly.`,
    confirmed: `Booked for ${dayLabel(d.scheduled_for)}, ${time(d.scheduled_for)}. You'll see them on the map when they set off.`,
    arrived: "Open the door and share your collection code.",
    to_lab: `Sealed and barcoded, heading to ${shortName(d.pharmacy.label)}.`,
    testing: d.report_eta ? `Report expected around ${time(d.report_eta)}.` : "Your report will appear here.",
    done: "Tap View report to see your results.", cancelled: "Nothing was charged. You can book again any time." })[d.phase] || "";
}

async function labLiveScreen(id) {
  stopLive();
  state.tab = "labs"; renderNav();
  document.body.classList.add("live-mode");
  state.cleanups.push(() => document.body.classList.remove("live-mode"));
  window.scrollTo({ top: 0 });
  const url = `/api/labs/bookings/${id}/live`;
  let d = await api(url);
  view().innerHTML = `<div class="live"><div class="live-map-wrap"><div class="live-map" id="liveMap"></div>
      <button class="map-back" id="liveBack" aria-label="Back">${ic("arrow")}</button><div class="live-chip" id="liveChip"></div></div>
      <div class="live-sheet" id="liveSheet"></div></div>`;
  $("#liveBack").onclick = () => go("labs");
  const map = makeMap($("#liveMap"), { center: [d.home.lat, d.home.lng], zoom: 15 });
  const M = {};
  if (map) {
    M.home = L.marker([d.home.lat, d.home.lng], { icon: markerIcon("home", ic("home2")), zIndexOffset: 100 }).addTo(map);
    M.lab = L.marker([d.pharmacy.lat, d.pharmacy.lng], { icon: markerIcon("pharmacy", ic("flask")) }).addTo(map);
  }
  let routeKey = "", lastPhase = d.phase;
  const draw = () => {
    const t = d.trip;
    $("#liveChip").innerHTML = `<span class="live-dot ${["done", "cancelled"].includes(d.phase) ? "off" : ""}"></span>${t && !t.arrived ? `${t.eta_min} min` : d.phase === "searching" ? "Searching" : "Live"}`;
    if (map) {
      $("#liveMap").classList.toggle("searching", d.phase === "searching");
      if (d.provider_location && !["done", "testing", "cancelled"].includes(d.phase)) {
        const ini = d.provider ? esc(initials(d.provider.name)) : "";
        if (!M.prov) M.prov = L.marker(d.provider_location, { icon: markerIcon("provider", `<span>${ini}</span><i class="hd"></i>`), zIndexOffset: 500 }).addTo(map);
        else glide(M.prov, d.provider_location);
        const hd = M.prov.getElement()?.querySelector(".hd"); if (hd && t) hd.style.transform = `rotate(${t.heading}deg)`;
      } else if (M.prov) { M.prov.remove(); delete M.prov; }
      const key = t ? `${t.id}:${t.source}` : "";
      if (key !== routeKey) {
        routeKey = key;
        [M.bg, M.route].forEach((x) => x && x.remove());
        const pts = [[d.home.lat, d.home.lng]];
        if (t) {
          M.bg = L.polyline(t.route, { color: "#0b2f2a", weight: 9, opacity: .18, lineCap: "round" }).addTo(map);
          M.route = L.polyline(routeAhead(t), { color: DARK() ? "#2fd1b5" : "#0b7a6c", weight: 5, opacity: .95, lineCap: "round", dashArray: t.source === "synthetic" ? "1 9" : null }).addTo(map);
          pts.push(...t.route);
        }
        if (d.provider_location) pts.push(d.provider_location);
        if (["to_lab", "testing", "done"].includes(d.phase)) pts.push([d.pharmacy.lat, d.pharmacy.lng]);
        if (pts.length > 1) map.fitBounds(pts, { padding: [50, 50], maxZoom: 16 }); else map.setView(pts[0], 15);
      } else if (t && M.route) M.route.setLatLngs(routeAhead(t));
    }
    const p = d.provider, steps = [["Booked", true], ["Collector assigned", !!p || ["to_lab", "testing", "done"].includes(d.phase)],
      ["Collected", ["to_lab", "testing", "done"].includes(d.phase)], ["At lab", ["testing", "done"].includes(d.phase)], ["Report", d.phase === "done"]];
    $("#liveSheet").innerHTML = `<div class="grab"></div>
      <div class="row between" style="align-items:flex-start;flex-wrap:nowrap">
        <div><div class="eyebrow-sm">${d.on_demand ? "Lab test · collect now" : "Lab test at home"} · ${esc(d.booking_ref)}</div>
          <h2>${esc(labHeadline(d))}</h2><p class="small muted" style="margin:2px 0 0">${t && !t.arrived ? `${km(t.remaining_m)} away · arriving around <b>${clock(t.eta_min)}</b>` : esc(labSub(d))}</p></div>
        ${t && !t.arrived ? `<div class="eta"><b>${t.eta_min}</b><span>min</span></div>` : d.phase === "arrived" || d.phase === "done" ? `<div class="eta good">${ic("check", "lg")}</div>` : ""}</div>
      ${d.phase === "searching" ? `<div class="search-bar"><i></i></div>` : t ? `<div class="trip-bar"><i style="width:${Math.round(t.fraction * 100)}%"></i></div>` : ""}
      ${p && !["done", "cancelled"].includes(d.phase) ? `<div class="prov-card"><div class="avatar lg">${esc(initials(p.name))}</div><div class="grow"><b>${esc(p.name)}</b>
          <div class="tiny muted">${esc(p.specialty)} · <span class="stars">★ ${p.rating.toFixed(1)}</span> · ${esc(p.vehicle)}</div></div>
          <button class="btn sm" id="callProv">${ic("phoneCall")} Call</button></div>` : ""}
      ${d.collection_code ? `<div class="code-inline"><span class="tiny">Collection code</span><b>${esc(d.collection_code)}</b><span class="tiny muted">Share it only at your door</span></div>` : ""}
      ${d.fasting_hours && ["searching", "waiting", "confirmed", "on_the_way", "arrived"].includes(d.phase) ? `<div class="notice warn small">${ic("clock")}<span>Please stay fasting (${d.fasting_hours} h) until your sample is taken. Water is fine.</span></div>` : ""}
      <div class="live-steps">${steps.map(([l, on]) => `<span class="${on ? "on" : ""}"><i></i>${l}</span>`).join("")}</div>
      <div class="row between" style="margin-top:10px">
        <span class="tiny muted">${ic("info")} Demo: GPS is simulated${t ? ` and runs ${t.speedup}× faster` : ""}.</span>
        <span class="row" style="gap:6px">${["searching", "waiting", "confirmed", "on_the_way"].includes(d.phase) ? `<button class="btn ghost sm danger" id="liveCancel">${ic("x")} Cancel</button>` : ""}
        ${d.phase === "done" ? `<button class="btn primary sm" id="liveReport">${ic("report")} View report</button>` : ""}</span></div>`;
    const c = $("#liveCancel"); if (c) c.onclick = () => guard(async () => { if (!confirm("Cancel this booking?")) return; await post(`/api/labs/bookings/${id}/cancel`); toast("Booking cancelled"); d = await api(url); draw(); });
    const r = $("#liveReport"); if (r) r.onclick = () => go("labreport", { labId: id });
    const cp = $("#callProv"); if (cp) cp.onclick = () => toast("Masked calling connects you in the live app (demo)", "phone");
  };
  draw();
  every(2000, async () => {
    d = await api(url); draw();
    if (d.phase !== lastPhase && d.phase === "done") toast("Your lab report is ready", "report");
    lastPhase = d.phase;
  });
}

/* ------------------------------------------------------------------ patient: report */
SCREENS.labreport = async () => {
  const b = await api(`/api/labs/bookings/${state.ctx.labId}`);
  const r = b.report;
  if (!r) { labLiveScreen(b.id); return; }
  const bar = (x) => {
    if (x.low == null && x.high == null) return "";
    const lo = x.low ?? 0, hi = x.high ?? lo * 2, span = (hi - lo) || 1;
    const min = lo - span * .5, max = hi + span * .5;
    const pos = Math.max(2, Math.min(98, ((x.value - min) / (max - min)) * 100));
    const a = ((lo - min) / (max - min)) * 100, w = ((hi - lo) / (max - min)) * 100;
    return `<div class="rng"><i class="ok" style="left:${x.low == null ? 0 : a}%;width:${x.low == null ? a + w : x.high == null ? 100 - a : w}%"></i><b class="${x.flag}" style="left:${pos}%"></b></div>`;
  };
  view().innerHTML = `${pageHead("Lab report", `${esc(b.items.map((i) => i.name).join(", "))}`, `<div class="row" style="gap:6px"><button class="btn ghost" id="back">${ic("arrow")} Lab tests</button><button class="btn" id="print">${ic("print")} Download PDF</button></div>`)}
    <div class="card report">
      <div class="report-head"><div><div class="eyebrow-sm">${ic("flask")} ${esc(r.lab.name)}</div><b>${esc(r.lab.accreditation)}</b><div class="tiny muted">${esc(r.lab.address)}</div></div>
        <div class="report-meta"><div><span>Patient</span><b>${esc(r.patient.name)}</b></div><div><span>Patient ID</span><b>${esc(r.patient.ref)}</b></div>
          <div><span>Booking</span><b>${esc(r.booking_ref)}</b></div><div><span>Collected</span><b>${when(r.collected_at)}</b></div><div><span>Reported</span><b>${when(r.reported_at)}</b></div>
          <div><span>Sample IDs</span><b>${r.sample_ids.map(esc).join(", ")}</b></div></div></div>
      <div class="notice ${r.flagged.length ? "warn" : "good"} small">${ic(r.flagged.length ? "alert" : "check")}<span>${esc(r.summary)}</span></div>
      ${r.sections.map((s) => `<div class="report-sec"><h3>${esc(s.name)} <span class="tiny muted">· ${esc(s.sample)}</span></h3>
        <table class="report-table"><thead><tr><th>Test</th><th>Result</th><th class="hide-sm">Reference range</th><th></th></tr></thead><tbody>
        ${s.results.map((x) => `<tr class="${x.flag}"><td>${esc(x.name)}<div class="tiny muted show-sm">Range ${esc(x.range)} ${esc(x.unit)}</div></td>
          <td><b>${esc(x.value)}</b> <span class="tiny muted">${esc(x.unit)}</span>${x.flag !== "normal" ? ` <span class="badge ${x.flag === "high" ? "bad" : "warn"}">${x.flag === "high" ? "High" : "Low"}</span>` : ""}</td>
          <td class="hide-sm">${esc(x.range)} ${esc(x.unit)}</td><td class="bar-cell">${bar(x)}</td></tr>`).join("")}</tbody></table></div>`).join("")}
      <div class="report-foot"><div class="tiny muted">Electronically verified by ${esc(r.pathologist)}. Demo report with fictional values. Not for medical use.</div></div>
    </div>
    <div class="card now-banner no-print"><div class="row" style="flex-wrap:nowrap"><div class="ico">${ic("stethoscope", "lg")}</div>
      <div><h3 style="margin:0">${r.flagged.length ? "Talk to a doctor about your results" : "Want a doctor to go through it?"}</h3><span class="small muted">A verified doctor can visit you at home and review this report.</span></div></div>
      <button class="btn primary" id="toDoc">${ic("stethoscope")} Book a doctor</button></div>`;
  $("#back").onclick = () => go("labs");
  $("#print").onclick = () => window.print();
  $("#toDoc").onclick = () => go("book");
};

/* ------------------------------------------------------------------ patient: home banner */
if (APP === "patient") {
  const baseHome = SCREENS.home;
  SCREENS.home = async () => {
    await baseHome();
    if (state.role !== "patient") return;
    const list = await api("/api/labs/bookings").catch(() => []);
    const live = list.filter((b) => LAB_OPEN.includes(b.status));
    const fresh = list.find((b) => b.status === "report_ready" && Date.now() - parseIso(b.events.at(-1)?.at || b.created_at) < 864e5);
    const slot = $("#liveSlot"); if (!slot?.isConnected) return;
    const el = document.createElement("div");
    el.innerHTML = [...live.map((b) => `<button class="live-banner" data-lab-live="${b.id}"><span class="live-dot"></span><span class="grow"><b>${esc(LAB_BADGE[b.status][0])} · lab test</b><span class="tiny">${esc(b.items.map((i) => i.name).join(", "))}</span></span><span class="btn sm">${ic("pin")} Track</span></button>`),
      fresh ? `<button class="live-banner" data-report="${fresh.id}"><span class="live-dot off"></span><span class="grow"><b>Your lab report is ready</b><span class="tiny">${esc(fresh.items.map((i) => i.name).join(", "))}</span></span><span class="btn sm">${ic("report")} View</span></button>` : ""].join("");
    slot.after(el);
    wireBookingCards(() => SCREENS.home());
  };
}

/* ------------------------------------------------------------------ Nabzo: phlebotomist */
const LAB_JOB_LABEL = { assigned: ["To collect", "brand"], collected: ["Drop at lab", "info"], at_lab: ["At lab", "good"], report_ready: ["Report ready", "good"], cancelled: ["Cancelled", ""] };

function labJobCard(j) {
  const label = LAB_JOB_LABEL[j.status] || [j.status, ""];
  let action = "";
  if (j.trip_id) action = `<button class="btn primary sm" data-nav="1">${ic("nav")} ${j.trip_leg === "to_lab" ? "Navigate to lab" : "Navigate"}</button>`;
  else if (j.status === "assigned") action = `<button class="btn primary sm" data-lab-depart="${j.id}">${ic("nav")} Start trip</button>`;
  return `<article class="card job"><div class="card-head"><div class="row" style="flex-wrap:nowrap"><div class="avatar">${ic("flask")}</div>
      <div><h3>${esc(j.patient)}</h3><div class="meta"><span>${ic("clock")} ${j.on_demand ? "Now" : `${dayLabel(j.scheduled_for)}, ${time(j.scheduled_for)}`}</span><span>${ic("pin")} ${esc(j.address)}</span></div></div></div>
      <span class="badge ${label[1]}">${label[0]}</span></div>
    <div class="instructions">${esc(j.reason)}${j.fasting_hours ? ` · <b>Fasting ${j.fasting_hours} h</b>` : ""}${j.payment_due ? ` · Collect ${money(j.payment_due)}` : ""}</div>
    ${j.sample_ids?.length ? `<div class="tiny muted" style="margin-top:6px">${ic("tube")} ${j.sample_ids.map(esc).join(", ")}</div>` : ""}
    ${action ? `<div class="actions-bar">${action}</div>` : ""}</article>`;
}

function wireLabJobs(after) {
  $$("[data-lab-depart]").forEach((b) => (b.onclick = () => guard(async () => { await post(`/api/provider/labs/${b.dataset.labDepart}/depart`); navScreen(); })));
  $$("[data-nav]").forEach((b) => (b.onclick = () => navScreen()));
}

/* Actions in the navigation sheet for a lab trip. */
function labNavActions(t, job) {
  if (t.leg === "to_lab") return `<button class="btn primary block" id="labHand" ${t.arrived ? "" : "disabled"}>${ic("flask")} ${t.arrived ? "Handed samples to the lab" : "Hand over on arrival"}</button>`;
  return `<div class="tiny muted" style="margin-bottom:8px">${ic("tube")} ${esc(job?.reason || "")}</div>
    <div class="form-grid"><label>Patient's collection code<input id="labCode" inputmode="numeric" maxlength="4" placeholder="4 digits"></label></div>
    ${job?.fasting_hours ? `<label class="check" style="margin:10px 0"><input type="checkbox" id="labFast"><span>Patient confirms ${job.fasting_hours} h fasting</span></label>` : ""}
    ${job?.payment_due ? `<div class="notice info small">${ic("wallet")}<span>Collect <b>${money(job.payment_due)}</b> by cash or UPI.</span></div>` : ""}
    <button class="btn primary block" id="labCollect" ${t.arrived ? "" : "disabled"}>${ic("drop")} ${t.arrived ? "Sample collected" : "Collect on arrival"}</button>`;
}

function wireLabNav(t) {
  const c = $("#labCollect");
  if (c) c.onclick = () => guard(async () => {
    await post(`/api/provider/labs/${t.lab_booking_id}/collect`, { code: $("#labCode").value, fasting_confirmed: !!$("#labFast")?.checked });
    toast("Sample collected. Navigating to the lab.", "flask"); navScreen();
  });
  const h = $("#labHand");
  if (h) h.onclick = () => guard(async () => { await post(`/api/provider/labs/${t.lab_booking_id}/handover`); toast("Handed over. The lab has your samples."); go("dash"); });
}

SCREENS.collections = async () => {
  const jobs = await api("/api/provider/jobs");
  const n = (s) => jobs.filter((j) => j.status === s).length;
  view().innerHTML = `<section class="hero partner"><div class="eyebrow">${esc(state.name)}</div><h1>Sample collections</h1>
      <p>Accept nearby requests on your dashboard. Collect at the door with the patient's code, then drop the sealed tubes at the lab.</p>
      <div class="stats"><div class="stat"><b>${n("assigned")}</b><span>To collect</span></div><div class="stat"><b>${n("collected")}</b><span>To drop at lab</span></div><div class="stat"><b>${n("at_lab") + n("report_ready")}</b><span>Done</span></div></div></section>
    <div class="section-title">Your collections</div>
    ${jobs.map(labJobCard).join("") || empty("flask", "No collections yet", "Go online on your dashboard to receive nearby sample collections.")}`;
  wireLabJobs();
};
