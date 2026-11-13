/* Triyana — physiotherapy at home. Patient: book a session or package, track the physio live, read session notes.
   Nabzo: physiotherapists get nearby requests, navigate, run the session and write notes. */
"use strict";

TABS.physio = [["dash", "Dashboard", "bolt"], ["earnings", "Earnings", "wallet"], ["sessions", "My patients", "heart"]];
if (APP === "patient") TABS.patient.splice(2, 0, ["physio", "Physio at home", "heart", "desktop"]);
Object.assign(SHORT, { "My patients": "Patients", "Physio at home": "Physio" });

const PHYSIO_STATUS = { searching: ["Finding your physiotherapist", "info"], active: ["Active", "good"], completed: ["Completed", "brand"], cancelled: ["Cancelled", ""] };
const SESSION_STATUS = { requested: ["Waiting", "info"], scheduled: ["Upcoming", "brand"], in_progress: ["In session", "warn"], completed: ["Done", "good"], cancelled: ["Cancelled", ""] };

function painBar(before, after) {
  if (before == null) return "";
  const w = (n) => `${n * 10}%`;
  return `<div class="pain"><div class="pain-row"><span class="tiny muted">Pain before</span><div class="pain-track"><i class="b" style="width:${w(before)}"></i></div><b>${before}/10</b></div>
    <div class="pain-row"><span class="tiny muted">Pain after</span><div class="pain-track"><i class="a" style="width:${w(after)}"></i></div><b>${after}/10</b></div></div>`;
}

function sessionNotesHTML(s) {
  const n = s.notes;
  if (!n) return "";
  return `<div class="session-notes">
    ${painBar(n.pain_before, n.pain_after)}
    ${n.exercises.length ? `<div class="px-chips">${n.exercises.map((e) => `<span class="px-chip">${ic("check")} ${esc(e)}</span>`).join("")}</div>` : ""}
    ${n.notes ? `<p class="small" style="margin:8px 0 0">${esc(n.notes)}</p>` : ""}
    ${n.home_plan ? `<div class="notice good small" style="margin-top:8px">${ic("home")}<span><b>Your home exercises:</b> ${esc(n.home_plan)}</span></div>` : ""}
    ${n.next_focus ? `<p class="tiny muted" style="margin:6px 0 0">${ic("arrow")} Next time: ${esc(n.next_focus)}</p>` : ""}</div>`;
}

function physioCardHTML(ph, extra = "") {
  return `<div class="row" style="flex-wrap:nowrap;align-items:flex-start"><div class="avatar">${esc(initials(ph.name))}</div><div class="grow">
      <b>${esc(ph.name)}</b> ${ph.verified ? `<span class="verified" title="Verified registration">${ic("badge")}</span>` : ""} ${extra}
      <div class="small muted">${esc(ph.qualification)} · ${ph.experience_years} yrs${ph.distance_km != null ? ` · ${ph.distance_km} km away` : ""}</div>
      <div class="tiny muted">Reg. ${esc(ph.registration_no)} · ${esc(ph.council)}</div>
      <div class="meta small"><span><span class="stars">★ ${ph.rating.toFixed(1)}</span> <span class="muted">(${ph.rating_count})</span></span><span>${ic("chat")} ${esc(ph.languages.join(", "))}</span></div></div></div>`;
}

function physioBookingCard(b) {
  const [label, cls] = PHYSIO_STATUS[b.status] || [b.status, ""];
  const s = b.next_session;
  const pct = Math.round((b.sessions_done / b.sessions_total) * 100);
  return `<article class="card physio-card"><div class="card-head"><div class="row" style="flex-wrap:nowrap"><div class="avatar">${ic("heart")}</div><div>
      <h3>${esc(b.condition_label)}</h3><div class="meta"><span>${esc(b.plan_label)}</span><span>${esc(b.ref)}</span>${b.physio ? `<span>${ic("user")} ${esc(b.physio.name)}</span>` : ""}</div></div></div>
      <span class="badge ${cls}">${label}</span></div>
    <div class="row between small" style="margin-top:6px"><span>${b.sessions_done} of ${b.sessions_total} sessions done</span>${s ? `<span class="muted">${ic("clock")} Next: ${b.on_demand && s.number === 1 && b.status === "searching" ? "now" : `${dayLabel(s.scheduled_for)}, ${time(s.scheduled_for)}`}</span>` : ""}</div>
    <div class="trip-bar"><i style="width:${pct}%"></i></div>
    <div class="actions-bar"><button class="btn primary sm" data-pb="${b.id}">${ic("file")} Sessions & notes</button>
      ${s && (b.status === "searching" && b.on_demand || b.status === "active") ? `<button class="btn sm" data-plive="${s.id}">${ic("pin")} Live map</button>` : ""}</div></article>`;
}

function wirePhysioCards() {
  $$("[data-pb]").forEach((x) => (x.onclick = () => physioBookingScreen(+x.dataset.pb)));
  $$("[data-plive]").forEach((x) => (x.onclick = () => liveScreen("physio", +x.dataset.plive)));
}

/* ------------------------------------------------------------------ patient: book */
SCREENS.physio = async () => {
  const [cat, mine] = await Promise.all([api("/api/physio/catalogue"), api("/api/patient/physio/bookings")]);
  const b = { condition: null, plan: "pack5", when: cat.online_nearby ? "now" : "later", day: null, slot: null, details: "", address: cat.address };
  const days = [...new Set(cat.slots.map(dayKey))];
  b.day = days[0];
  const ready = () => b.condition && (b.when === "now" ? cat.online_nearby : b.slot) && b.address.trim();
  const ongoing = mine.filter((x) => ["searching", "active"].includes(x.status));
  const past = mine.filter((x) => !["searching", "active"].includes(x.status));

  const render = () => {
    const plan = cat.plans.find((p) => p.key === b.plan);
    const daySlots = cat.slots.filter((s) => dayKey(s) === b.day);
    view().innerHTML = `<section class="hero physio-hero"><div class="eyebrow"><span class="live-dot"></span> ${cat.online_nearby} physiotherapist${cat.online_nearby === 1 ? "" : "s"} online near you</div>
        <h1>Physiotherapy at home</h1>
        <p>A registered physiotherapist comes to your home for a ${cat.session_minutes}-minute session. Book one session or a package, follow them on the map, and read your notes and home exercises after every session.</p>
        <div class="stats"><div class="stat"><b>${money(plan.per_session)}</b><span>Per session</span></div><div class="stat"><b>${cat.session_minutes} min</b><span>At your home</span></div><div class="stat"><b>${cat.physios.length}</b><span>Physios nearby</span></div></div></section>
      ${ongoing.length ? `<div class="section-title">Your physiotherapy</div>${ongoing.map(physioBookingCard).join("")}` : ""}
      <div class="split"><div>
        <div class="card"><div class="step-label"><span class="n">1</span><h3>What do you need help with?</h3></div>
          <div class="choice-grid">${cat.conditions.map((c) => `<button class="choice ${b.condition === c.key ? "on" : ""}" data-cond="${c.key}"><span class="ico">${ic(c.icon)}</span><div><b>${esc(c.label)}</b></div></button>`).join("")}</div>
          <label class="field" style="margin-top:14px">Tell the physiotherapist more (optional)<textarea id="pDetails" rows="2" placeholder="For example: knee replacement 3 weeks ago, using a walker">${esc(b.details)}</textarea></label></div>

        <div class="card"><div class="step-label"><span class="n">2</span><h3>Session or package</h3></div>
          <div class="plan-grid">${cat.plans.map((p) => `<button class="plan ${b.plan === p.key ? "on" : ""}" data-plan="${p.key}">
              ${p.saving ? `<span class="badge good">Save ${money(p.saving)}</span>` : `<span class="badge">Try it</span>`}
              <b>${esc(p.label)}</b><span class="price-big">${money(p.price)}</span>
              <span class="tiny muted">${p.sessions > 1 ? `${money(p.per_session)} a session · every other day` : `${cat.session_minutes} minutes`}</span>
              <span class="tiny">${esc(p.blurb)}</span></button>`).join("")}</div>
          <p class="tiny muted" style="margin:10px 0 0">${ic("user")} The same physiotherapist comes for every session in your package. You can move any session later.</p></div>

        <div class="card"><div class="step-label"><span class="n">3</span><h3>When should they come?</h3></div>
          <div class="doc-list">
            <button class="doc any ${b.when === "now" ? "on" : ""}" data-when="now" ${cat.online_nearby ? "" : "disabled"}><div class="avatar">${ic("bolt")}</div><div class="info"><b>As soon as possible</b>
              <div class="small muted">${cat.online_nearby ? "The nearest online physiotherapist gets your request first. Watch them arrive on the map." : "No physiotherapist is online right now. Pick a time instead."}</div></div><div class="fee"><span class="badge brand">Fastest</span></div></button>
            <button class="doc any ${b.when === "later" ? "on" : ""}" data-when="later"><div class="avatar">${ic("calendar")}</div><div class="info"><b>Pick a time</b>
              <div class="small muted">We send the nearest physiotherapist who is free then.</div></div></button></div>
          ${b.when === "later" ? `<div class="seg" style="margin-top:12px">${days.map((k) => `<button class="${k === b.day ? "on" : ""}" data-pday="${esc(k)}">${dayLabel(cat.slots.find((s) => dayKey(s) === k))}</button>`).join("")}</div>
            <div class="slot-grid">${daySlots.map((s) => `<button class="slot ${s === b.slot ? "on" : ""}" data-pslot="${s}">${time(s)}</button>`).join("")}</div>` : ""}</div>

        <div class="card"><div class="step-label"><span class="n">4</span><h3>Where should they come?</h3></div>
          <label class="field">Address<input id="pAddr" value="${esc(b.address)}"></label></div>

        <div class="section-title">Physiotherapists near you</div>
        ${cat.physios.map((ph) => `<div class="card slim">${physioCardHTML(ph, ph.online ? `<span class="badge good"><span class="live-dot"></span> Online</span>` : `<span class="badge">Offline</span>`)}
          <div class="tiny muted" style="margin-top:6px">${esc(ph.focus.join(" · "))}</div></div>`).join("") || empty("heart", "No physiotherapists near you yet")}
      </div>
      <aside class="sticky"><div class="card featured">
        <h3>Your booking</h3>
        <table class="price" style="margin-top:8px">
          <tr><td>For</td><td>${esc(cat.conditions.find((c) => c.key === b.condition)?.label || "—")}</td></tr>
          <tr><td>Plan</td><td>${esc(plan.label)}</td></tr>
          <tr><td>First session</td><td>${b.when === "now" ? "As soon as possible" : b.slot ? `${dayLabel(b.slot)}, ${time(b.slot)}` : "—"}</td></tr>
          ${plan.saving ? `<tr><td>Package saving</td><td>−${money(plan.saving)}</td></tr>` : ""}
          <tr class="total"><td>Total</td><td>${money(plan.price)}</td></tr></table>
        <div class="notice info small">${ic("shield")}<span><b>Nothing to pay now.</b> Pay after your first session. Every physiotherapist's registration is verified.</span></div>
        <div class="notice warn small">${ic("alert")}<span>For a fall with a suspected fracture, chest pain or sudden weakness, call <b>112</b> now.</span></div>
        <button class="btn primary block" id="pBook" ${ready() ? "" : "disabled"}>${ic(b.when === "now" ? "bolt" : "check")} ${b.when === "now" ? "Find a physiotherapist now" : "Confirm booking"}</button>
        <p class="tiny muted" style="text-align:center;margin:10px 0 0">${!b.condition ? "Choose what you need help with" : b.when === "later" && !b.slot ? "Pick a time to continue" : "The physiotherapist confirms in the Nabzo app."}</p>
      </div></aside></div>
      ${past.length ? `<div class="section-title">Past physiotherapy</div>${past.map(physioBookingCard).join("")}` : ""}`;
    $$("[data-cond]").forEach((x) => (x.onclick = () => { b.condition = x.dataset.cond; render(); }));
    $$("[data-plan]").forEach((x) => (x.onclick = () => { b.plan = x.dataset.plan; render(); }));
    $$("[data-when]").forEach((x) => (x.onclick = () => { b.when = x.dataset.when; render(); }));
    $$("[data-pday]").forEach((x) => (x.onclick = () => { b.day = x.dataset.pday; render(); }));
    $$("[data-pslot]").forEach((x) => (x.onclick = () => { b.slot = x.dataset.pslot; render(); }));
    $("#pDetails").oninput = (e) => { b.details = e.target.value; };
    $("#pAddr").oninput = (e) => { b.address = e.target.value; $("#pBook").disabled = !ready(); };
    wirePhysioCards();
    $("#pBook").onclick = () => guard(async () => {
      $("#pBook").disabled = true;
      try {
        const r = await post("/api/patient/physio/bookings", { condition: b.condition, plan: b.plan, when: b.when === "now" ? "now" : b.slot, details: b.details, address: b.address });
        if (r.on_demand) liveScreen("physio", r.sessions[0].id);
        else { toast("Booking sent to the nearest physiotherapist", "check"); physioBookingScreen(r.id); }
      } catch (e) { $("#pBook").disabled = false; throw e; }
    });
  };
  render();
};

/* ------------------------------------------------------------------ patient: one booking, sessions and notes */
async function physioBookingScreen(id) {
  stopLive();
  state.tab = "physio"; renderNav();
  window.scrollTo({ top: 0 });
  const b = await api(`/api/patient/physio/bookings/${id}`);
  const [label, cls] = PHYSIO_STATUS[b.status] || [b.status, ""];
  const done = b.sessions.filter((s) => s.notes);
  const first = done[0]?.notes, last = done[done.length - 1]?.notes;
  view().innerHTML = `<section class="hero physio-hero"><div class="eyebrow">${esc(b.plan_label)} · ${esc(b.ref)}</div>
      <h1>${esc(b.condition_label)}</h1>
      <p>${b.physio ? `With ${esc(b.physio.name)}. ` : "We're finding the nearest physiotherapist. "}${b.sessions_done} of ${b.sessions_total} sessions done.${first && last && done.length > 1 ? ` Pain has gone from ${first.pain_before}/10 to ${last.pain_after}/10.` : ""}</p>
      <div class="actions"><button class="btn" data-go="physio">${ic("arrow")} All physiotherapy</button></div></section>
    ${b.physio ? `<div class="card">${physioCardHTML(b.physio, `<span class="badge ${cls}">${label}</span>`)}</div>` : `<div class="notice info">${ic("clock")}<span>${label}</span></div>`}
    <div class="section-title">Sessions</div>
    ${b.sessions.map((s) => { const [sl, sc] = SESSION_STATUS[s.status] || [s.status, ""]; return `<article class="card session">
      <div class="card-head"><div class="row" style="flex-wrap:nowrap"><div class="session-n">${s.number}</div><div><h3>Session ${s.number}</h3>
        <div class="meta"><span>${ic("clock")} ${s.completed_at ? when(s.completed_at) : b.on_demand && s.number === 1 && b.status === "searching" ? "As soon as possible" : when(s.scheduled_for)}</span></div></div></div>
        <span class="badge ${sc}">${sl}</span></div>
      ${sessionNotesHTML(s)}
      ${["requested", "scheduled", "in_progress"].includes(s.status) && b.status !== "cancelled" ? `<div class="actions-bar">
        ${s.id === b.next_session?.id && s.status !== "in_progress" && (b.status === "active" || b.on_demand) ? `<button class="btn sm primary" data-plive="${s.id}">${ic("pin")} Live map</button>` : ""}
        ${s.status === "scheduled" && b.status === "active" ? `<button class="btn sm" data-move="${s.id}">${ic("calendar")} Move</button>` : ""}</div>` : ""}</article>`; }).join("")}
    <div class="notice info small">${ic("lock")}<span>Session notes are private to you and your physiotherapist and stored encrypted.</span></div>
    ${b.can_cancel ? `<div class="actions-bar"><button class="btn ghost sm danger" id="pCancel">${ic("x")} ${b.sessions_done ? "Cancel remaining sessions" : "Cancel booking"}</button></div>` : ""}`;
  $$("[data-go]").forEach((x) => (x.onclick = () => go(x.dataset.go)));
  wirePhysioCards();
  const c = $("#pCancel"); if (c) c.onclick = () => guard(async () => { if (!confirm("Cancel the remaining sessions?")) return; await post(`/api/patient/physio/bookings/${id}/cancel`); toast("Cancelled"); physioBookingScreen(id); });
  $$("[data-move]").forEach((x) => (x.onclick = () => guard(() => moveSessionSheet(id, +x.dataset.move))));
}

async function moveSessionSheet(bookingId, sessionId) {
  const cat = await api("/api/physio/catalogue");
  const days = [...new Set(cat.slots.map(dayKey))];
  let dayK = days[0], slot = null;
  const s = sheet(`<div class="sheet-head"><div><h2>Move this session</h2><p class="small muted">Pick a new time. Your physiotherapist is told straight away.</p></div><button class="x" aria-label="Close">${ic("x")}</button></div><div id="moveBody"></div>`);
  const draw = () => {
    $("#moveBody").innerHTML = `<div class="seg">${days.map((k) => `<button class="${k === dayK ? "on" : ""}" data-md="${esc(k)}">${dayLabel(cat.slots.find((x) => dayKey(x) === k))}</button>`).join("")}</div>
      <div class="slot-grid">${cat.slots.filter((x) => dayKey(x) === dayK).map((x) => `<button class="slot ${x === slot ? "on" : ""}" data-ms="${x}">${time(x)}</button>`).join("")}</div>
      <button class="btn primary block" id="moveGo" ${slot ? "" : "disabled"}>${ic("check")} Move session</button>`;
    $$("[data-md]", s.el).forEach((x) => (x.onclick = () => { dayK = x.dataset.md; draw(); }));
    $$("[data-ms]", s.el).forEach((x) => (x.onclick = () => { slot = x.dataset.ms; draw(); }));
    $("#moveGo").onclick = () => guard(async () => { await put(`/api/patient/physio/sessions/${sessionId}/time`, { when: slot }); s.close(); toast("Session moved"); physioBookingScreen(bookingId); });
  };
  $(".x", s.el).onclick = s.close;
  draw();
}

/* ------------------------------------------------------------------ partner app: physiotherapist */
SCREENS.sessions = async () => {
  const rows = await api("/api/physio/bookings");
  const active = rows.filter((b) => b.status === "active");
  const inSession = active.flatMap((b) => b.sessions.filter((s) => s.status === "in_progress").map((s) => ({ b, s })));
  view().innerHTML = `<section class="hero partner"><div class="eyebrow">${esc(state.name)}</div><h1>Your patients</h1>
      <p>Every package you've accepted, with past notes so you can pick up where you left off.</p>
      <div class="stats"><div class="stat"><b>${active.length}</b><span>Active</span></div><div class="stat"><b>${active.reduce((n, b) => n + b.sessions.filter((s) => s.status === "scheduled").length, 0)}</b><span>Upcoming sessions</span></div><div class="stat"><b>${rows.reduce((n, b) => n + b.sessions_done, 0)}</b><span>Sessions done</span></div></div></section>
    ${inSession.map(({ b, s }) => `<button class="live-banner" data-notes="${s.id}"><span class="live-dot"></span><span class="grow"><b>In session with ${esc(b.patient.name)}</b><span class="tiny">Session ${s.number} of ${b.sessions_total} · tap to write notes and finish</span></span><span class="btn sm">${ic("file")} Notes</span></button>`).join("")}
    ${rows.map((b) => `<article class="card"><div class="card-head"><div class="row" style="flex-wrap:nowrap"><div class="avatar">${esc(initials(b.patient.name))}</div><div>
        <h3>${esc(b.patient.name)}</h3><div class="meta"><span>${esc(b.condition_label)}</span><span>${esc(b.plan_label)}</span><span>${esc(b.ref)}</span></div></div></div>
        <span class="badge ${(PHYSIO_STATUS[b.status] || [])[1] || ""}">${b.sessions_done}/${b.sessions_total}</span></div>
      ${b.details ? `<div class="instructions">${esc(b.details)}</div>` : ""}
      <details class="history"><summary class="small">Sessions and notes</summary>
        ${b.sessions.map((s) => `<div class="list-item"><div class="session-n sm">${s.number}</div><div class="grow"><div class="row between"><b>${(SESSION_STATUS[s.status] || [s.status])[0]}</b><span class="tiny muted">${when(s.completed_at || s.scheduled_for)}</span></div>${sessionNotesHTML(s)}</div></div>`).join("")}</details>
      <div class="actions-bar">${b.sessions.filter((s) => s.status === "in_progress").map((s) => `<button class="btn primary sm" data-notes="${s.id}">${ic("file")} Write notes · session ${s.number}</button>`).join("")}</div></article>`).join("") || empty("heart", "No patients yet", "Go online on your dashboard to receive nearby physio requests.")}`;
  $$("[data-notes]").forEach((x) => (x.onclick = () => physioNotesScreen(+x.dataset.notes)));
};

async function physioNotesScreen(sessionId) {
  stopLive();
  state.tab = "sessions"; renderNav();
  window.scrollTo({ top: 0 });
  const rows = await api("/api/physio/bookings");
  const b = rows.find((x) => x.sessions.some((s) => s.id === sessionId));
  if (!b) { toast("Session not found", "alert"); return go("sessions"); }
  const s = b.sessions.find((x) => x.id === sessionId);
  const prev = [...b.sessions].reverse().find((x) => x.notes);
  const f = { pain_before: prev?.notes.pain_after ?? 5, pain_after: prev?.notes.pain_after ?? 5, exercises: new Set(), custom: [] };
  view().innerHTML = `${pageHead(`Session ${s.number} notes`, `${esc(b.patient.name)} · ${esc(b.condition_label)} · ${esc(b.plan_label)}`)}
    <div class="split"><div>
      <div class="card"><div class="step-label"><span class="n">1</span><h3>Pain (0 = none, 10 = worst)</h3></div>
        <label class="field">Before the session <b id="pbV">${f.pain_before}</b><input type="range" min="0" max="10" id="pb" value="${f.pain_before}"></label>
        <label class="field" style="margin-top:10px">After the session <b id="paV">${f.pain_after}</b><input type="range" min="0" max="10" id="pa" value="${f.pain_after}"></label></div>
      <div class="card"><div class="step-label"><span class="n">2</span><h3>Exercises and treatment done</h3></div>
        <div class="px-chips" id="exChips"></div>
        <div class="row" style="margin-top:10px;flex-wrap:nowrap"><input id="exNew" placeholder="Add another (e.g. ultrasound therapy)" style="flex:1"><button class="btn sm" id="exAdd">${ic("check")} Add</button></div></div>
      <div class="card"><div class="step-label"><span class="n">3</span><h3>Notes</h3></div>
        <label class="field">What you found and did<textarea id="nNotes" rows="3" placeholder="Range of motion, strength, swelling, how they responded"></textarea></label>
        <label class="field" style="margin-top:10px">Home exercise plan for the patient<textarea id="nHome" rows="2" placeholder="Sets, reps and how often"></textarea></label>
        <label class="field" style="margin-top:10px">Focus for next session<input id="nNext" placeholder="Optional"></label></div>
    </div><aside class="sticky">
      ${prev ? `<div class="card"><h3>Last session</h3>${sessionNotesHTML(prev)}</div>` : ""}
      <div class="card featured"><div class="notice info small">${ic("lock")}<span>The patient sees these notes in their Triyana app. Keep them clear and kind.</span></div>
        <button class="btn primary block" id="nSave">${ic("check")} Finish session and send notes</button></div></aside></div>`;
  const drawChips = () => {
    $("#exChips").innerHTML = [...b.suggested_exercises, ...f.custom].map((e) => `<button class="px-chip pick ${f.exercises.has(e) ? "on" : ""}" data-ex="${esc(e)}">${f.exercises.has(e) ? ic("check") : ""} ${esc(e)}</button>`).join("");
    $$("[data-ex]").forEach((x) => (x.onclick = () => { const e = x.dataset.ex; f.exercises.has(e) ? f.exercises.delete(e) : f.exercises.add(e); drawChips(); }));
  };
  drawChips();
  $("#pb").oninput = (e) => { f.pain_before = +e.target.value; $("#pbV").textContent = f.pain_before; };
  $("#pa").oninput = (e) => { f.pain_after = +e.target.value; $("#paV").textContent = f.pain_after; };
  $("#exAdd").onclick = () => { const v = $("#exNew").value.trim(); if (v) { f.custom.push(v); f.exercises.add(v); $("#exNew").value = ""; drawChips(); } };
  $("#nSave").onclick = () => guard(async () => {
    await post(`/api/physio/sessions/${sessionId}/complete`, { pain_before: f.pain_before, pain_after: f.pain_after, exercises: [...f.exercises], notes: $("#nNotes").value, home_plan: $("#nHome").value, next_focus: $("#nNext").value });
    toast("Session finished. Notes sent to the patient."); go("sessions");
  });
}
