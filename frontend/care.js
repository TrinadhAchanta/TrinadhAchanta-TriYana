/* Triyana — care that keeps patients coming back:
   monthly care plans, the free follow-up call within 48 hours, health records in one place, and voice booking.
   Loaded by both apps: patients get plans, calls, records and voice; doctors get their follow-up call list. */
"use strict";

Object.assign(P, {
  mic: '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v4"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
  folder: '<path d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  repeat: '<path d="M17 2l4 4-4 4"/><path d="M3 11V9a3 3 0 0 1 3-3h15"/><path d="M7 22l-4-4 4-4"/><path d="M21 13v2a3 3 0 0 1-3 3H3"/>',
});
const hourLabel = (h) => `${((h + 11) % 12) + 1}:00 ${h < 12 ? "AM" : "PM"}`;
const callWhen = (iso) => `${dayLabel(iso)}, ${time(iso)}`;

/* ------------------------------------------------------------------ navigation */
if (APP === "patient") {
  const at = TABS.patient.findIndex((t) => t[0] === "meds") + 1;
  TABS.patient.splice(at, 0, ["records", "Health records", "folder", "desktop"], ["care", "Care plans", "repeat", "desktop"]);
  const afterBook = SERVICES.findIndex((s) => s.key === "book") + 1;
  SERVICES.splice(afterBook, 0,
    { key: "voice", title: "Book by voice", sub: "Just say what's wrong, in your language", icon: "mic", tone: "gold" },
    { key: "care", title: "Care plans", sub: "Monthly home check-ups: diabetes, BP, elders", icon: "repeat", go: "care" },
    { key: "records", title: "Health records", sub: "Visits, vitals, labs and prescriptions", icon: "folder", go: "records", tone: "blue" });
} else {
  // Desktop sidebar tab; on phones the bottom bar is full, so the doctor's Home shows a card that opens it.
  TABS.doctor.push(["calls", "Follow-up calls", "phoneCall", "desktop"]);
  const dashBefore = SCREENS.dash;
  SCREENS.dash = async () => {
    await dashBefore();
    if (state.role !== "doctor" || state.tab !== "dash") return;
    const open = (await api("/api/doctor/follow-up-calls").catch(() => [])).filter((c) => c.status === "scheduled");
    if (!open.length || state.tab !== "dash" || $("#callsBanner")) return;
    const worse = open.filter((c) => c.feeling === "worse").length;
    view().insertAdjacentHTML("afterbegin", `<button class="card now-banner" id="callsBanner"><div class="row" style="flex-wrap:nowrap"><div class="ico">${ic("phoneCall", "lg")}</div>
      <div><h3 style="margin:0">${open.length} follow-up call${open.length > 1 ? "s" : ""} to make</h3><span class="small muted">${worse ? `${worse} patient${worse > 1 ? "s" : ""} feel worse. ` : ""}Next: ${esc(open[0].patient.name)}, ${callWhen(open[0].scheduled_for)}</span></div></div>
      <span class="btn primary sm">${ic("phoneCall")} Open calls</span></button>`);
    $("#callsBanner").onclick = () => go("calls");
  };
}
Object.assign(SHORT, { "Health records": "Records", "Care plans": "Plans", "Follow-up calls": "Calls" });

/* ------------------------------------------------------------------ patient: follow-up call card */
const FEEL = [["better", "Better", "check"], ["same", "About the same", "minus"], ["worse", "Worse", "alert"]];
function callCard(c) {
  const head = `<div class="row" style="flex-wrap:nowrap;align-items:flex-start"><div class="avatar">${ic("phoneCall")}</div><div class="grow">
      <div class="eyebrow-sm">Free follow-up call</div>
      <b>${c.status === "done" ? `${esc(c.doctor.name)} called you` : c.status === "missed" ? "We missed your follow-up call" : `${esc(c.doctor.name)} will call you`}</b>
      <div class="small muted">${c.status === "done" ? when(c.done_at) : callWhen(c.scheduled_for)} · after your visit on ${day(c.visit.date)}${c.visit.diagnosis ? ` for ${esc(c.visit.diagnosis)}` : ""}</div></div>
      <span class="badge ${c.status === "done" ? "brand" : c.status === "missed" ? "warn" : "good"}">${c.status === "done" ? "Done" : c.status === "missed" ? "Missed" : "Free"}</span></div>`;
  if (c.status === "done") return `<article class="card">${head}<div class="instructions" style="margin-top:10px"><b>Doctor's note:</b> ${esc(c.doctor_note)}</div></article>`;
  if (c.status === "missed") return `<article class="card">${head}<div class="actions-bar"><button class="btn sm" data-svc="now">${ic("bolt")} Get a doctor now</button></div></article>`;
  return `<article class="card call-card" data-call="${c.id}">${head}
    <div class="small" style="margin-top:12px"><b>How are you feeling since the visit?</b></div>
    <div class="seg" style="margin-top:6px">${FEEL.map(([k, l]) => `<button class="${c.feeling === k ? "on" : ""}" data-feel="${k}">${l}</button>`).join("")}</div>
    ${c.feeling === "worse" ? `<div class="notice warn small" style="margin-top:10px">${ic("alert")}<span>We've told ${esc(c.doctor.name)}. If it can't wait, get a doctor now, or call <b>112</b> in an emergency.</span></div>
      <div class="actions-bar"><button class="btn primary sm" data-svc="now">${ic("bolt")} Doctor in 10 min</button></div>` : ""}
    <div class="actions-bar"><button class="btn ghost sm" data-move="${c.id}">${ic("clock")} Change call time</button></div></article>`;
}
function wireCalls(calls, after) {
  $$("[data-call]").forEach((card) => {
    const c = calls.find((x) => x.id === +card.dataset.call);
    $$("[data-feel]", card).forEach((b) => (b.onclick = () => guard(async () => {
      await post(`/api/patient/follow-up-calls/${c.id}/feeling`, { feeling: b.dataset.feel });
      toast(b.dataset.feel === "worse" ? "Your doctor has been told" : "Thanks, your doctor will see this"); after();
    })));
    const mv = $("[data-move]", card);
    if (mv) mv.onclick = () => moveCallSheet(c, after);
  });
  $$("[data-svc='now']").forEach((b) => (b.onclick = () => doctorNowSheet()));
}
function moveCallSheet(c, after) {
  const days = [...new Set(c.slots.map(dayKey))];
  const s = sheet(`<div class="sheet-head"><div><div class="eyebrow-sm">Free follow-up call</div><h2>When should ${esc(c.doctor.name)} call?</h2>
      <p class="small muted">Any time before ${callWhen(c.due_by)} (48 hours after your visit).</p></div><button class="x" aria-label="Close">${ic("x")}</button></div>
    ${days.map((d) => `<div class="section-title">${dayLabel(c.slots.find((x) => dayKey(x) === d))}</div>
      <div class="slot-grid">${c.slots.filter((x) => dayKey(x) === d).map((x) => `<button class="slot ${x === c.scheduled_for ? "on" : ""}" data-t="${x}">${time(x)}</button>`).join("")}</div>`).join("")
      || `<p class="muted small">No other times are left before the 48-hour mark.</p>`}`);
  $(".x", s.el).onclick = s.close;
  $$("[data-t]", s.el).forEach((b) => (b.onclick = () => guard(async () => {
    await post(`/api/patient/follow-up-calls/${c.id}/time`, { scheduled_for: b.dataset.t });
    s.close(); toast("Call time changed"); after();
  })));
}

/* ------------------------------------------------------------------ patient: home additions */
if (APP === "patient") {
  const homeBefore = SCREENS.home;
  SCREENS.home = async () => {
    await homeBefore();
    if (state.role !== "patient" || state.tab !== "home") return;
    const hero = $(".home-hero .actions");
    if (hero && !$("#voiceHero")) hero.insertAdjacentHTML("beforeend", `<button class="btn" id="voiceHero">${ic("mic")} Book by voice</button>`);
    $$("#voiceHero, [data-svc='voice']").forEach((b) => (b.onclick = () => voiceSheet()));
    const calls = (await api("/api/patient/follow-up-calls").catch(() => [])).filter((c) => c.status === "scheduled");
    const slot = $("#liveSlot");
    if (calls.length && slot && state.tab === "home") {
      slot.insertAdjacentHTML("afterend", `<div id="callSlot">${calls.map(callCard).join("")}</div>`);
      wireCalls(calls, () => SCREENS.home());
    }
  };
}

/* ------------------------------------------------------------------ patient: care plans */
SCREENS.care = async () => {
  const [cat, plans] = await Promise.all([api("/api/care-plans/catalog"), api("/api/care-plans")]);
  const active = plans.filter((p) => p.status === "active");
  const have = new Set(active.map((p) => p.kind));
  const ck = (c) => {
    const lbl = c.status === "completed" ? ["Done", "brand"] : c.status === "accepted" ? ["Confirmed", "good"] : c.status === "requested" ? ["Booked", "info"]
      : c.status === "in_progress" ? ["Doctor with you", "warn"] : c.status === "cancelled" ? ["Cancelled", ""] : ["We'll book it", ""];
    return `<li class="${c.status === "completed" ? "done" : ""}"><span class="node">${ic(c.status === "completed" ? "check" : "calendar")}</span>
      <div class="row between"><b>${c.scheduled_for ? callWhen(c.scheduled_for) : day(c.due + "T06:30:00")}</b><span class="badge ${lbl[1]}">${lbl[0]}</span></div>
      <div class="tiny muted">${c.doctor ? esc(c.doctor) : c.note ? esc(c.note) : "Booked for you a few days before"}</div></li>`;
  };
  view().innerHTML = `${pageHead("Care plans", "Regular doctor check-ups at home for long-term conditions. We book every visit for you.")}
    ${active.map((p) => `<article class="card"><div class="card-head"><div class="row" style="flex-wrap:nowrap"><div class="avatar">${ic(p.icon)}</div><div>
        <h3 style="margin:0">${esc(p.title)}</h3><div class="small muted">${p.visits_per_month} check-up${p.visits_per_month > 1 ? "s" : ""} a month · ${money(p.monthly_fee)}/month · around ${hourLabel(p.preferred_hour)}</div></div></div>
        <span class="badge good">${ic("check")} Active</span></div>
      ${p.doctor ? `<div class="small" style="margin-top:8px">${ic("stethoscope")} Your regular doctor: <b>${esc(p.doctor.name)}</b></div>` : ""}
      <div class="section-title" style="margin-top:12px">This month · ${p.completed} of ${p.checkups.length} done</div>
      <ul class="timeline">${p.checkups.map(ck).join("")}</ul>
      <div class="row between small"><span class="muted">Renews ${day(p.renews_on)} · cancel any time</span><button class="btn ghost sm danger" data-stop="${p.id}">${ic("x")} Cancel plan</button></div></article>`).join("")}
    <div class="section-title">${active.length ? "Add another plan" : "Choose a plan"}</div>
    <div class="choice-grid plans">${cat.map((p) => `<article class="card plan-card">
      <div class="row" style="flex-wrap:nowrap"><div class="avatar">${ic(p.icon)}</div><div><h3 style="margin:0">${esc(p.title)}</h3><div class="tiny muted">${esc(p.for)}</div></div></div>
      <div class="plan-price"><b>${money(p.monthly_fee)}</b><span class="small muted">/month · ${p.visits_per_month} home visit${p.visits_per_month > 1 ? "s" : ""}</span></div>
      <ul class="checks plain">${p.checks.map((c) => `<li class="ok"><span class="ck">${ic("check")}</span><div class="small">${esc(c)}</div></li>`).join("")}</ul>
      <div class="tiny muted" style="margin:4px 0 10px">+ a free doctor call within 48 hours of every visit</div>
      ${have.has(p.kind) ? `<span class="badge good">${ic("check")} You have this plan</span>` : `<button class="btn primary block" data-plan="${p.kind}">${ic("repeat")} Start plan</button>`}</article>`).join("")}</div>
    <p class="tiny muted">Demo prices. Billing is a sandbox: nothing is charged. For emergencies call 112.</p>`;
  $$("[data-plan]").forEach((b) => (b.onclick = () => startPlanSheet(cat.find((p) => p.kind === b.dataset.plan))));
  $$("[data-stop]").forEach((b) => (b.onclick = () => guard(async () => {
    if (!confirm("Cancel this care plan? Booked check-ups will be cancelled too.")) return;
    await post(`/api/care-plans/${b.dataset.stop}/cancel`); toast("Plan cancelled"); SCREENS.care();
  })));
};
function startPlanSheet(p) {
  let hour = 10;
  const s = sheet(`<div class="sheet-head"><div><div class="eyebrow-sm">${ic(p.icon)} ${esc(p.title)}</div><h2>What time suits you for check-ups?</h2>
      <p class="small muted">${p.visits_per_month} home visit${p.visits_per_month > 1 ? "s" : ""} a month. We'll book each one with the same doctor when we can, and remind you the day before.</p></div>
      <button class="x" aria-label="Close">${ic("x")}</button></div>
    <div class="slot-grid hours">${[9, 10, 11, 12, 14, 15, 16, 17, 18].map((h) => `<button class="slot ${h === hour ? "on" : ""}" data-h="${h}">${hourLabel(h)}</button>`).join("")}</div>
    <div class="notice info small" style="margin-top:12px">${ic("shield")}<span><b>${money(p.monthly_fee)} a month</b>, about ${money(p.per_visit)} a visit. Cancel any time. Demo billing: nothing is charged.</span></div>
    <button class="btn primary block" id="planGo">${ic("check")} Start ${esc(p.title)}</button>`);
  $(".x", s.el).onclick = s.close;
  $$("[data-h]", s.el).forEach((b) => (b.onclick = () => { hour = +b.dataset.h; $$("[data-h]", s.el).forEach((x) => x.classList.toggle("on", x === b)); }));
  $("#planGo").onclick = () => guard(async () => {
    $("#planGo").disabled = true;
    try { await post("/api/care-plans", { kind: p.kind, preferred_hour: hour }); } finally { $("#planGo").disabled = false; }
    s.close(); toast("Plan started. Your first check-up is booked"); SCREENS.care();
  });
}

/* ------------------------------------------------------------------ patient: health records */
const REC = { visit: ["Doctor visits", "stethoscope"], prescription: ["Prescriptions", "rx"], lab: ["Lab reports", "flask"], physio: ["Physio", "heart"], call: ["Follow-up calls", "phoneCall"] };
function bpChart(rows) {
  const pts = rows.filter((r) => r.bp_systolic != null);
  if (!pts.length) return "";
  const W = 320, H = 120, pad = 18, lo = 60, hi = 180;
  const x = (i) => (pts.length === 1 ? W / 2 : pad + (i * (W - pad * 2)) / (pts.length - 1));
  const y = (v) => H - pad - ((Math.min(hi, Math.max(lo, v)) - lo) / (hi - lo)) * (H - pad * 2);
  const line = (k) => pts.map((r, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(r[k]).toFixed(1)}`).join(" ");
  const dots = (k, cls) => pts.map((r, i) => `<circle class="${cls}" cx="${x(i).toFixed(1)}" cy="${y(r[k]).toFixed(1)}" r="3.5"><title>${day(r.at)}: ${r.bp_systolic}/${r.bp_diastolic}</title></circle>`).join("");
  const last = pts[pts.length - 1];
  return `<div class="card"><div class="row between"><h3 style="margin:0">${ic("heart")} Blood pressure</h3><span class="small"><b>${last.bp_systolic}/${last.bp_diastolic}</b> <span class="muted">on ${day(last.at)}</span></span></div>
    <svg class="bp-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Blood pressure over time">
      <rect class="band" x="0" y="${y(120)}" width="${W}" height="${y(80) - y(120)}"></rect>
      <path class="sys" d="${line("bp_systolic")}"/><path class="dia" d="${line("bp_diastolic")}"/>${dots("bp_systolic", "sys")}${dots("bp_diastolic", "dia")}</svg>
    <div class="row tiny muted" style="gap:14px"><span><i class="key sys"></i> Top number</span><span><i class="key dia"></i> Bottom number</span><span><i class="key band"></i> Usual range</span></div></div>`;
}
SCREENS.records = async () => {
  const [rec, calls] = await Promise.all([api("/api/patient/records"), api("/api/patient/follow-up-calls").catch(() => [])]);
  const filter = state.ctx.recFilter || "all";
  const lastV = [...rec.vitals].reverse();
  const latest = (k) => lastV.find((r) => r[k] != null);
  const tile = (label, r, val) => (r ? `<div class="stat"><b>${val(r)}</b><span>${label}</span></div>` : "");
  const items = rec.items.filter((i) => filter === "all" || i.kind === filter);
  const upcoming = calls.filter((c) => c.status === "scheduled");
  view().innerHTML = `${pageHead("Health records", "Visit notes, vitals, prescriptions and lab reports in one place.", `<button class="btn" id="recPrint">${ic("print")} Print</button>`)}
    ${upcoming.map(callCard).join("")}
    ${rec.vitals.length ? `<div class="card"><h3 style="margin-top:0">Latest vitals</h3><div class="stats vitals-row">
      ${tile("Blood pressure", latest("bp_systolic"), (r) => `${r.bp_systolic}/${r.bp_diastolic}`)}
      ${tile("Pulse", latest("pulse_bpm"), (r) => `${r.pulse_bpm}`)}
      ${tile("SpO2", latest("spo2_pct"), (r) => `${r.spo2_pct}%`)}
      ${tile("Temperature", latest("temperature_c"), (r) => `${(r.temperature_c * 9 / 5 + 32).toFixed(1)}°F`)}
      ${tile("Weight", latest("weight_kg"), (r) => `${r.weight_kg} kg`)}</div></div>${bpChart(rec.vitals)}` : ""}
    <div class="seg" style="margin:6px 0 12px"><button class="${filter === "all" ? "on" : ""}" data-f="all">All · ${rec.items.length}</button>
      ${Object.entries(REC).filter(([k]) => rec.counts[k]).map(([k, [l]]) => `<button class="${filter === k ? "on" : ""}" data-f="${k}">${l} · ${rec.counts[k]}</button>`).join("")}</div>
    ${items.length ? `<div class="card"><ul class="timeline records">${items.map((i) => `<li class="done"><span class="node">${ic(REC[i.kind][1])}</span>
        <button class="rec-item" data-k="${i.kind}" data-id="${i.id}"><div class="row between"><b>${esc(i.title)}</b><span class="tiny muted">${day(i.at)}</span></div>
        <div class="small muted">${esc(i.subtitle || "")}</div>
        ${i.kind === "visit" && i.detail.notes ? `<div class="row" style="gap:6px;margin-top:6px">${i.detail.notes.bp ? `<span class="badge">BP ${esc(i.detail.notes.bp)}</span>` : ""}${i.detail.notes.spo2_pct != null ? `<span class="badge">SpO2 ${i.detail.notes.spo2_pct}%</span>` : ""}${flagBadges(i.detail.notes.flags)}</div>` : ""}
        ${i.kind === "lab" && i.detail.flagged.length ? `<div style="margin-top:6px"><span class="badge warn">${ic("alert")} ${i.detail.flagged.length} to discuss</span></div>` : ""}
        ${i.kind === "physio" && i.detail.pain_before != null ? `<div style="margin-top:6px"><span class="badge">Pain ${i.detail.pain_before} → ${i.detail.pain_after ?? "?"}</span></div>` : ""}
        </button></li>`).join("")}</ul></div>`
      : empty("folder", "No records yet", "After your first home visit, lab test or physio session, everything shows up here.")}`;
  wireCalls(upcoming, () => SCREENS.records());
  $("#recPrint").onclick = () => window.print();
  $$("[data-f]").forEach((b) => (b.onclick = () => { state.ctx.recFilter = b.dataset.f; SCREENS.records(); }));
  $$(".rec-item").forEach((b) => (b.onclick = () => {
    const id = +b.dataset.id;
    if (b.dataset.k === "visit") return guard(() => patientNotesScreen(id, () => go("records")));
    if (b.dataset.k === "prescription") return go("rx");
    if (b.dataset.k === "lab") return go("labreport", { labId: id });
    if (b.dataset.k === "physio" && typeof physioNotesScreen === "function") return guard(() => physioNotesScreen(id));
  }));
};

/* ------------------------------------------------------------------ doctor: follow-up calls */
SCREENS.calls = async () => {
  const calls = await api("/api/doctor/follow-up-calls");
  const open = calls.filter((c) => c.status !== "done"), done = calls.filter((c) => c.status === "done");
  const card = (c) => `<article class="card" data-dcall="${c.id}"><div class="card-head"><div class="row" style="flex-wrap:nowrap"><div class="avatar">${esc(initials(c.patient.name))}</div><div>
      <h3 style="margin:0">${esc(c.patient.name)}</h3><div class="small muted">Visit ${esc(c.visit.booking_ref)} on ${day(c.visit.date)}${c.visit.diagnosis ? ` · ${esc(c.visit.diagnosis)}` : ""}</div></div></div>
      ${c.status === "done" ? `<span class="badge brand">${ic("check")} Done</span>` : c.status === "missed" ? `<span class="badge warn">Past 48 h</span>` : `<span class="badge info">${ic("clock")} ${callWhen(c.scheduled_for)}</span>`}</div>
    ${c.feeling ? `<div class="notice ${c.feeling === "worse" ? "warn" : c.feeling === "better" ? "good" : "info"} small">${ic(c.feeling === "worse" ? "alert" : "info")}<span>Patient says they feel <b>${c.feeling === "same" ? "about the same" : c.feeling}</b>.${c.patient_note ? ` "${esc(c.patient_note)}"` : ""}</span></div>` : ""}
    ${c.status === "done" ? `<div class="instructions"><b>Your note:</b> ${esc(c.doctor_note)}</div>` : `
      <label class="field" style="margin-top:10px">How is the patient doing?<textarea rows="2" data-note placeholder="For example: fever settled, eating well. Continue medicines."></textarea></label>
      <div class="actions-bar">${c.patient.phone ? `<a class="btn primary sm" href="tel:${esc(c.patient.phone)}">${ic("phoneCall")} Call ${esc(c.patient.phone)}</a>` : `<span class="small muted">${ic("phoneCall")} Call through the app line (demo)</span>`}
        <button class="btn sm" data-done="${c.id}">${ic("check")} Mark call done</button></div>`}</article>`;
  view().innerHTML = `${pageHead("Follow-up calls", "Every patient gets a free call from you within 48 hours of the visit. Patients who feel worse are shown first.")}
    ${open.length ? open.map(card).join("") : empty("phoneCall", "No calls to make", "When you complete a home visit, its follow-up call shows up here.")}
    ${done.length ? `<div class="section-title">Done</div>${done.slice(0, 10).map(card).join("")}` : ""}`;
  $$("[data-done]").forEach((b) => (b.onclick = () => guard(async () => {
    const note = $("[data-note]", b.closest("[data-dcall]")).value;
    await post(`/api/doctor/follow-up-calls/${b.dataset.done}/done`, { note }); toast("Call marked done"); SCREENS.calls();
  })));
};

/* ------------------------------------------------------------------ patient: voice booking */
const SPEECH_LANG = { en: "en-IN", hi: "hi-IN", te: "te-IN", ta: "ta-IN" };
const VOICE_EXAMPLE = {
  en: "“I have fever, send a doctor now”",
  hi: "“मुझे बुखार है, अभी डॉक्टर भेजो”",
  te: "“నాకు జ్వరం ఉంది, వెంటనే డాక్టర్‌ను పంపండి”",
  ta: "“எனக்குக் காய்ச்சல், உடனே டாக்டரை அனுப்புங்கள்”",
};
const tr = (s) => (typeof T === "function" ? T(s) : s);
const curLang = () => (typeof LANG === "string" ? LANG : "en");
function say(text) {
  try {
    if (!window.speechSynthesis) return;
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = SPEECH_LANG[curLang()]; u.rate = 0.92;
    speechSynthesis.speak(u);
  } catch {}
}
const PART_HOURS = { morning: [9, 12], afternoon: [12, 16], evening: [16, 21] };
async function pickSlot(dayWord, part) {
  const slots = await api("/api/visit-slots");
  const target = keyOf(new Date(Date.now() + (dayWord === "tomorrow" ? 864e5 : 0)));
  const hour = (s) => +parseIso(s).toLocaleString("en-GB", { hour: "2-digit", hour12: false, timeZone: TZ });
  const onDay = slots.filter((s) => dayKey(s) === target);
  const [a, b] = PART_HOURS[part] || [0, 24];
  return onDay.find((s) => hour(s) >= a && hour(s) < b) || onDay[0] || slots[0] || null;
}
function voiceSheet() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const lang = curLang();
  let rec = null, intent = null;
  const s = sheet(`<div class="sheet-head"><div><div class="eyebrow-sm">${ic("mic")} Book by voice</div><h2>Tap the mic and say what's wrong</h2>
      <p class="small muted" data-no-i18n>${esc(VOICE_EXAMPLE[lang])}</p></div><button class="x" aria-label="Close">${ic("x")}</button></div>
    <div class="voice-box"><button class="mic-btn" id="micBtn" aria-label="Tap to speak">${ic("mic")}</button>
      <div class="small muted" id="micState">${SR ? "Tap to speak" : "Voice input isn't available in this browser. Type below instead."}</div>
      <div class="voice-heard" id="heard" data-no-i18n></div></div>
    <form class="row" id="typed" style="gap:8px;flex-wrap:nowrap;margin-top:10px"><input id="typedText" class="grow" placeholder="Or type it here" autocomplete="off"><button class="btn">Go</button></form>
    <div id="voiceResult"></div>
    <div class="notice warn small" style="margin-top:12px">${ic("alert")}<span>For chest pain, breathing trouble or other emergencies, call <b>112</b> now.</span></div>`);
  const close = () => { try { rec && rec.abort(); } catch {} s.close(); };
  $(".x", s.el).onclick = close;
  const result = (html) => { $("#voiceResult").innerHTML = html; };

  const understand = (text) => guard(async () => {
    $("#heard").textContent = text;
    intent = await post("/api/voice/understand", { text, lang });
    if (!intent.understood) {
      result(`<div class="notice info small">${ic("info")}<span>${tr("Sorry, we didn't catch that. Please try again, or pick a reason below.")}</span></div>
        <div class="choice-grid" style="margin-top:10px">${REASONS.slice(0, 5).map(([r, i]) => `<button class="choice" data-vr="${esc(r)}"><span class="ico">${ic(i)}</span><div><b>${esc(r)}</b></div></button>`).join("")}</div>`);
      say(tr("Sorry, we didn't catch that. Please try again, or pick a reason below."));
      $$("[data-vr]", s.el).forEach((b) => (b.onclick = () => { intent = { ...intent, reason: b.dataset.vr, action: "now", understood: true }; showIntent(); }));
      return;
    }
    showIntent();
  });
  const showIntent = () => {
    const whenTxt = intent.action === "now" ? tr("A doctor now") : [tr(intent.day || "today"), intent.part ? tr(intent.part) : ""].filter(Boolean).join(", ");
    const reasonTxt = intent.reason.startsWith("Urgent:") ? intent.reason : tr(intent.reason);
    result(`${intent.emergency ? `<div class="notice bad" style="margin-top:12px">${ic("alert")}<span><b>${tr("This sounds like an emergency. Call 112 now.")}</b></span></div>
        <a class="btn danger block" href="tel:112" style="margin-top:8px">${ic("phoneCall")} ${tr("Call 112")}</a>` : ""}
      <div class="card voice-intent" data-no-i18n><div class="eyebrow-sm">${tr("We heard:")}</div>
        <div class="row" style="gap:8px;margin-top:6px"><span class="badge brand">${ic(intent.action === "now" ? "bolt" : "calendar")} ${esc(whenTxt)}</span><span class="badge">${ic("stethoscope")} ${esc(reasonTxt)}</span></div></div>
      <button class="btn primary block big" id="voiceGo" data-no-i18n>${ic("check")} ${intent.emergency ? tr("Send a doctor now") : tr("Confirm and book")}</button>
      <button class="btn ghost block" id="voiceAgain" style="margin-top:6px">${ic("mic")} Try again</button>`);
    say(`${whenTxt}. ${reasonTxt}. ${intent.emergency ? tr("This sounds like an emergency. Call 112 now.") : tr("Shall we book it?")}`);
    $("#voiceAgain").onclick = () => { result(""); $("#heard").textContent = ""; listen(); };
    $("#voiceGo").onclick = () => guard(async () => {
      const go1 = $("#voiceGo"); go1.disabled = true;
      try {
        const reason = `${intent.reason} (booked by voice: "${intent.text.slice(0, 140)}")`;
        let v;
        if (intent.action === "now") {
          try { v = await post("/api/patient/visits/now", { reason, address: "", accept_longer: true }); }
          catch (e) { if (e.detail?.code !== "no_doctor_online") throw e; v = await post("/api/patient/visits", { asap: true, reason }); }
        } else {
          const slot = await pickSlot(intent.day, intent.part);
          if (!slot) throw new Error("No doctor has a free time then. Please pick a time on the booking screen.");
          v = await post("/api/patient/visits", { doctor_id: null, scheduled_for: slot, reason });
        }
        close();
        toast(v.on_demand ? "Finding your doctor" : `Booked: ${when(v.scheduled_for)}`);
        if (v.on_demand) liveScreen("visit", v.id); else go("home");
      } finally { go1.disabled = false; }
    });
  };
  const listen = () => {
    if (!SR) { $("#typedText").focus(); return; }
    try { rec && rec.abort(); } catch {}
    rec = new SR();
    rec.lang = SPEECH_LANG[lang]; rec.interimResults = true; rec.maxAlternatives = 1;
    const btn = $("#micBtn"), st = $("#micState");
    let finalText = "";
    rec.onstart = () => { btn.classList.add("on"); st.textContent = tr("Listening…"); };
    rec.onresult = (e) => {
      const txt = [...e.results].map((r) => r[0].transcript).join(" ");
      $("#heard").textContent = txt;
      if (e.results[e.results.length - 1].isFinal) finalText = txt;
    };
    rec.onerror = (e) => { st.textContent = e.error === "not-allowed" ? "Allow the microphone, or type below." : tr("Sorry, we didn't catch that. Please try again, or pick a reason below."); };
    rec.onend = () => { btn.classList.remove("on"); st.textContent = tr("Tap to speak"); const t = finalText || $("#heard").textContent; if (t.trim()) understand(t.trim()); };
    rec.start();
  };
  $("#micBtn").onclick = listen;
  $("#typed").onsubmit = (e) => { e.preventDefault(); const t = $("#typedText").value.trim(); if (t) understand(t); };
}
