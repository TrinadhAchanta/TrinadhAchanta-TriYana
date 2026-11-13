/* Family care, SOS, shared live tracking and the verified doctor card (patient app). */
"use strict";

Object.assign(P, {
  sos: '<path d="M12 3l9 16H3z"/><path d="M12 9v4M12 16h.01"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><circle cx="17.5" cy="9" r="2.5"/><path d="M16.5 14.2A5 5 0 0 1 22 19"/>',
  share: '<circle cx="18" cy="5" r="2.5"/><circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="19" r="2.5"/><path d="M8.2 10.8l7.6-4.4M8.2 13.2l7.6 4.4"/>',
  siren: '<path d="M6 18v-6a6 6 0 0 1 12 0v6"/><path d="M4 18h16v3H4zM12 2v2M4.2 5.2l1.4 1.4M19.8 5.2l-1.4 1.4"/>',
  copy: '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>',
});

if (APP === "patient") {
  const at = TABS.patient.findIndex((t) => t[0] === "privacy");
  TABS.patient.splice(at < 0 ? TABS.patient.length : at, 0, ["family", "Family & SOS", "users", "desktop"]);
  SERVICES.unshift({ key: "family", title: "Family care", sub: "Book for parents and kids, SOS contacts", icon: "users", go: "family", tone: "gold" });
}

/* ------------------------------------------------------------------ who is this visit for */
const FAM = { data: null, member: null };
async function famLoad(force = false) {
  if (!FAM.data || force) FAM.data = await api("/api/patient/family").catch(() => null);
  if (FAM.member && !FAM.data?.members.some((m) => m.id === FAM.member)) FAM.member = null;
  return FAM.data;
}
const famQ = () => (FAM.member ? `?member=${FAM.member}` : "");
const famMember = () => FAM.data?.members.find((m) => m.id === FAM.member) || null;
const first = (n) => String(n || "").split(" ")[0];

function whoPickerHTML(label = "Who is this for?") {
  const ms = FAM.data?.members || [];
  return `<div class="who"><span class="tiny strong muted">${label}</span><div class="who-row">
    <button class="who-chip ${FAM.member ? "" : "on"}" data-who="">${ic("user")} Me</button>
    ${ms.map((m) => `<button class="who-chip ${FAM.member === m.id ? "on" : ""}" data-who="${m.id}">${esc(first(m.name))} <span class="tiny">${esc(m.relation)}</span></button>`).join("")}
    <button class="who-chip add" data-who-add>${ic("users")} ${ms.length ? "Add" : "Add family"}</button></div></div>`;
}
function wireWho(root, onChange) {
  $$("[data-who]", root).forEach((b) => (b.onclick = () => { FAM.member = b.dataset.who ? +b.dataset.who : null; onChange(); }));
  $$("[data-who-add]", root).forEach((b) => (b.onclick = () => { root.classList?.contains("sheet-wrap") && root.remove(); go("family"); }));
}

/* ------------------------------------------------------------------ SOS */
function syncSosFab() {
  let fab = $("#sosFab");
  const show = APP === "patient" && state.role === "patient";
  if (!show) { fab?.remove(); return; }
  if (!fab) {
    fab = document.createElement("button");
    fab.id = "sosFab"; fab.className = "sos-fab"; fab.setAttribute("aria-label", "SOS: get emergency help");
    fab.innerHTML = `<b>SOS</b>`;
    fab.onclick = () => guard(sosSheet);
    document.body.appendChild(fab);
  }
}
const _renderNavBase = renderNav;
renderNav = function () { _renderNavBase(); syncSosFab(); }; // eslint-disable-line no-func-assign

async function sosSheet() {
  const o = await api("/api/patient/sos/options");
  await famLoad();
  const pick = { member: FAM.member, symptoms: new Set() };
  const s = sheet(`<div class="sheet-head"><div><div class="eyebrow-sm sos-eyebrow"><span class="live-dot sos"></span> Emergency</div><h2>SOS</h2>
      <p class="small muted" style="margin:2px 0 0">One tap sends the nearest doctor first and texts your family a live map.</p></div>
      <button class="x" aria-label="Close">${ic("x")}</button></div>
    <div id="sosWho"></div>
    <button class="sos-go" id="sosGo">${ic("siren", "lg")}<span><b>Send SOS now</b><small id="sosWhere"></small></span></button>
    <a class="btn block sos-call" href="tel:${esc(o.emergency_number)}">${ic("phone")} Call ${esc(o.emergency_number)} ambulance</a>
    <div class="section-title" style="margin:16px 0 8px">What's happening? <span class="tiny muted">(optional, helps the doctor)</span></div>
    <div class="sym-grid">${o.red_flags.map((r) => `<button class="sym red" data-sym="${r.key}">${esc(r.label)}</button>`).join("")}
      ${o.urgent.map((r) => `<button class="sym" data-sym="${r.key}">${esc(r.label)}</button>`).join("")}</div>
    <div class="notice bad small" id="sosRed" hidden>${ic("alert")}<span><b>These signs need an ambulance.</b> Call ${esc(o.emergency_number)} now. We'll still send the nearest doctor and tell your family.</span></div>
    <div class="notice info small">${ic("users")}<span>${o.contacts.length
      ? `We'll text <b>${o.contacts.map((c) => esc(c.name)).join(", ")}</b> with a live tracking link.`
      : `No emergency contacts yet. <button class="link-btn" id="sosAddC">Add who we should text</button>`}</span></div>`);
  const drawWho = () => {
    const ms = o.members;
    $("#sosWho", s.el).innerHTML = ms.length ? `<div class="who-row" style="margin:6px 0 12px">
      <button class="who-chip ${pick.member ? "" : "on"}" data-sw="">${ic("user")} Me</button>
      ${ms.map((m) => `<button class="who-chip ${pick.member === m.id ? "on" : ""}" data-sw="${m.id}">${esc(first(m.name))} <span class="tiny">${esc(m.relation)}</span></button>`).join("")}</div>` : "";
    const m = ms.find((x) => x.id === pick.member);
    $("#sosWhere", s.el).textContent = `Doctor goes to ${m ? `${first(m.name)}'s home, ${m.address}` : o.me.address}`;
    $$("[data-sw]", s.el).forEach((b) => (b.onclick = () => { pick.member = b.dataset.sw ? +b.dataset.sw : null; drawWho(); }));
  };
  drawWho();
  $(".x", s.el).onclick = s.close;
  const ac = $("#sosAddC", s.el); if (ac) ac.onclick = () => { s.close(); go("family"); };
  $$("[data-sym]", s.el).forEach((b) => (b.onclick = () => {
    const k = b.dataset.sym; pick.symptoms.has(k) ? pick.symptoms.delete(k) : pick.symptoms.add(k);
    b.classList.toggle("on", pick.symptoms.has(k));
    $("#sosRed", s.el).hidden = !o.red_flags.some((r) => pick.symptoms.has(r.key));
  }));
  $("#sosGo", s.el).onclick = () => guard(async () => {
    const btn = $("#sosGo", s.el); btn.disabled = true;
    try {
      const r = await post("/api/patient/sos", { member_id: pick.member, symptoms: [...pick.symptoms] });
      s.close();
      toast(r.contacts_alerted.length ? `SOS sent. ${r.contacts_alerted.length} family contact${r.contacts_alerted.length > 1 ? "s" : ""} alerted.` : "SOS sent", "siren");
      if (r.visit_id) liveScreen("visit", r.visit_id); else sosNoDoctor(r);
    } catch (e) { btn.disabled = false; throw e; }
  });
}

function sosNoDoctor(r) {
  const s = sheet(`<div class="sheet-head"><div><div class="eyebrow-sm sos-eyebrow">SOS sent</div><h2>No doctor is online nearby</h2></div><button class="x" aria-label="Close">${ic("x")}</button></div>
    <div class="notice bad">${ic("alert")}<span><b>Call ${esc(r.emergency_number)} for an ambulance now.</b> We couldn't find a Triyana doctor near ${esc(r.patient.address)}.</span></div>
    <a class="btn block sos-call" href="tel:${esc(r.emergency_number)}">${ic("phone")} Call ${esc(r.emergency_number)}</a>
    ${alertedHTML(r)}`);
  $(".x", s.el).onclick = s.close;
}

const alertedHTML = (r) => (r.contacts_alerted.length
  ? `<div class="tiny muted" style="margin-top:10px">${ic("check")} Alerted: ${r.contacts_alerted.map((c) => `${esc(c.name.replace(/\s*\(.*\)/, ""))} (${c.channel === "sms" ? "SMS" : "app"})`).join(", ")}</div>`
  : `<div class="tiny muted" style="margin-top:10px">No emergency contacts to alert. Add them under Family &amp; SOS.</div>`);

/* Shown at the top of the live map for an SOS visit. */
function sosPanelHTML(d) {
  const x = d.sos; if (!x) return "";
  const amb = x.ambulance;
  const ambLine = amb.status === "requested" ? `<div class="arrival-ok">${ic("check")} Ambulance requested · ref ${esc(amb.ref)}${amb.partner ? "" : " (demo: no real ambulance is sent, call " + esc(x.emergency_number) + ")"}</div>`
    : amb.status === "called" ? `<div class="arrival-ok">${ic("check")} You called ${esc(x.emergency_number)}</div>` : "";
  return `<div class="sos-panel ${x.serious ? "serious" : ""}"><div class="row between" style="flex-wrap:nowrap;align-items:flex-start">
      <div><b>${ic("siren")} SOS${d.for ? ` for ${esc(first(d.for.name))}` : ""}</b>
      <div class="tiny">${x.symptoms.length ? x.symptoms.map((s) => esc(s.label)).join(" · ") : "Urgent help requested"}</div></div>
      <a class="btn sm sos-call" href="tel:${esc(x.emergency_number)}">${ic("phone")} ${esc(x.emergency_number)}</a></div>
    ${x.serious && amb.status === "advised" ? `<div class="small" style="margin-top:8px"><b>These signs need an ambulance.</b> Call ${esc(x.emergency_number)} now. Your doctor is still coming.</div>
      <div class="row" style="gap:8px;margin-top:8px"><button class="btn sm" data-amb="called">${ic("check")} I called ${esc(x.emergency_number)}</button><button class="btn sm" data-amb="request">${ic("siren")} Request ambulance</button></div>` : ""}
    ${ambLine}${alertedHTML(x)}</div>`;
}

/* ------------------------------------------------------------------ verified doctor card */
function doctorCardHTML(c, idProf) {
  const photo = c.photo || idProf?.photo;
  return `<div class="doc-card"><div class="row" style="flex-wrap:nowrap;align-items:flex-start;gap:12px">
      ${photo ? `<img class="prov-photo" src="${esc(photo)}" alt="Verified photo of ${esc(c.name)}">` : `<div class="avatar lg">${esc(initials(c.name))}</div>`}
      <div class="grow"><div class="row" style="gap:6px"><b>${esc(c.name)}</b>${c.verified ? `<span class="badge good">${ic("badge")} Verified doctor</span>` : `<span class="badge warn">Checks pending</span>`}</div>
        <div class="tiny muted">${esc([c.specialty, c.qualification, c.experience_years ? `${c.experience_years} yrs` : ""].filter(Boolean).join(" · "))}</div>
        <div class="tiny" style="margin-top:2px">${c.rating ? `<span class="stars">★ ${c.rating.toFixed(1)}</span> <span class="muted">from ${c.rating_count} patients</span>` : ""}${c.languages.length ? ` <span class="muted">· ${esc(c.languages.join(", "))}</span>` : ""}</div></div>
      <button class="btn sm" id="callProv" title="Calls are masked to protect both numbers">${ic("phone")} Call</button></div>
    <ul class="doc-checks">${c.checks.map((k) => `<li class="${k.ok ? "ok" : "wait"}">${ic(k.ok ? "check" : "clock")}<div><b>${esc(k.label)}${k.at ? ` · ${esc(time(k.at))}` : ""}</b><span class="tiny muted">${esc(k.detail)}</span></div></li>`).join("")}</ul>
    ${c.face_verified ? `<div class="tiny muted">${ic("shield")} ${photo ? "Compare the person at your door with this photo." : "Check their name and registration at the door."} Never let anyone in who can't enter your arrival code.</div>` : ""}</div>`;
}

/* ------------------------------------------------------------------ share live tracking */
async function shareSheet(visitId, forName) {
  const r = await post(`/api/patient/visits/${visitId}/share`, { label: "Shared from app" });
  const url = location.origin + r.path;
  const text = `Follow ${forName ? `${forName}'s` : "my"} Triyana doctor visit live: ${url}`;
  const s = sheet(`<div class="sheet-head"><div><div class="eyebrow-sm">Live tracking link</div><h2>Share with family</h2>
      <p class="small muted" style="margin:2px 0 0">Anyone with this link sees the doctor on the map and who they are, until ${esc(time(r.expires_at))}. No health details are shown.</p></div>
      <button class="x" aria-label="Close">${ic("x")}</button></div>
    <div class="share-url"><input readonly value="${esc(url)}" aria-label="Tracking link"><button class="btn sm" id="shCopy">${ic("copy")} Copy</button></div>
    <div class="row" style="gap:8px;margin-top:10px">
      <a class="btn primary" target="_blank" rel="noopener" href="https://wa.me/?text=${encodeURIComponent(text)}">${ic("chat")} WhatsApp</a>
      <a class="btn" href="sms:?&body=${encodeURIComponent(text)}">${ic("phone")} SMS</a>
      ${navigator.share ? `<button class="btn" id="shNative">${ic("share")} More</button>` : ""}
      <button class="btn ghost danger" id="shStop">${ic("x")} Turn off link</button></div>`);
  $(".x", s.el).onclick = s.close;
  $("#shCopy", s.el).onclick = () => { navigator.clipboard?.writeText(url).then(() => toast("Link copied"), () => toast("Copy the link above", "info")); };
  const n = $("#shNative", s.el); if (n) n.onclick = () => navigator.share({ title: "Triyana live visit", text, url }).catch(() => {});
  $("#shStop", s.el).onclick = () => guard(async () => { await api(`/api/patient/visits/${visitId}/shares/${r.id}`, { method: "DELETE" }); toast("Link turned off", "info"); s.close(); });
}

/* Hooks the live map calls after each redraw. */
function wireFamilyLive(d, id, refresh) {
  $$("[data-amb]").forEach((b) => (b.onclick = () => guard(async () => {
    await post(`/api/patient/sos/${d.sos.id}/ambulance/${b.dataset.amb}`);
    toast(b.dataset.amb === "request" ? "Ambulance requested" : "Noted", "siren"); await refresh();
  })));
  const sh = $("#liveShare"); if (sh) sh.onclick = () => guard(() => shareSheet(id, d.for ? first(d.for.name) : ""));
}

/* ------------------------------------------------------------------ Family & SOS screen */
SCREENS.family = async () => {
  const f = await famLoad(true);
  const me = f.me;
  view().innerHTML = pageHead("Family & SOS", "Book doctors for your parents and children, at their own home, and choose who we alert in an emergency.") + `
    <div class="split"><div>
      <button class="card sos-banner" id="famSos"><span class="sos-dot">SOS</span><div><h3 style="margin:0">Emergency? Press SOS</h3>
        <span class="small">The nearest doctor is sent first, your family gets a live map, and serious cases are handed to an ambulance (108).</span></div></button>
      <div class="section-title">Family members</div>
      ${f.members.length ? f.members.map((m) => `<article class="card fam-card"><div class="row" style="flex-wrap:nowrap;gap:12px;align-items:flex-start">
          <div class="avatar lg">${esc(initials(m.name))}</div><div class="grow"><b>${esc(m.name)}</b> <span class="badge">${esc(m.relation)}</span>
          <div class="small muted">${[m.age != null ? `${m.age} yrs` : "", m.gender || "", m.phone || ""].filter(Boolean).map(esc).join(" · ")}</div>
          <div class="tiny muted">${ic("pin")} ${m.same_home ? "Lives with you" : esc(m.address)}</div></div>
          <button class="btn ghost sm danger" data-rm="${m.id}" aria-label="Remove ${esc(m.name)}">${ic("x")}</button></div>
        <div class="actions-bar"><button class="btn primary sm" data-now="${m.id}">${ic("bolt")} Doctor in 10 min for ${esc(first(m.name))}</button><button class="btn sm" data-book="${m.id}">${ic("calendar")} Book a visit</button></div></article>`).join("")
        : empty("users", "No family members yet", "Add a parent or child to book doctors for them and follow their visits live.")}
      <div class="card"><h3>Add a family member</h3>
        <form class="form-grid" id="famForm" style="margin-top:12px">
          <label>Full name<input id="fmName" required minlength="2" placeholder="e.g. Kamala Rao"></label>
          <label>Relation<select id="fmRel">${f.relations.map((r) => `<option>${esc(r)}</option>`).join("")}</select></label>
          <label>Date of birth<input id="fmDob" type="date"></label>
          <label>Gender<select id="fmGender"><option value="">Select</option><option>Female</option><option>Male</option><option>Other</option></select></label>
          <label class="wide">Their mobile (optional)<input id="fmPhone" type="tel" inputmode="tel" placeholder="98480 12345"></label>
          <div class="wide seg" role="radiogroup"><button type="button" class="on" data-home="same">Lives with me</button><button type="button" data-home="other">Lives elsewhere</button></div>
          <div class="wide" id="fmOther" hidden><label class="field">Their home address<input id="fmAddr" placeholder="House, street, area, city"></label>
            <p class="tiny muted" style="margin:8px 0 6px">Tap their home on the map so the nearest doctor goes there.</p><div class="fam-map" id="fmMap"></div></div>
          <div class="wide"><button class="btn primary">${ic("check")} Add family member</button></div></form></div>
    </div><aside>
      <div class="card"><h3>Emergency contacts</h3><p class="small muted" style="margin:6px 0 10px">When you press SOS, we text them a live tracking link.</p>
        ${f.contacts.length ? f.contacts.map((c) => `<div class="list-item"><div class="avatar">${esc(initials(c.name.replace(/\s*\(.*\)/, "")))}</div><div class="grow"><b>${esc(c.name)}</b><div class="tiny muted">${esc([c.relation, c.phone].filter(Boolean).join(" · "))}</div></div>
          <button class="btn ghost sm danger" data-rmc="${c.id}" aria-label="Remove ${esc(c.name)}">${ic("x")}</button></div>`).join("") : `<p class="small muted">None yet.</p>`}
        <form class="auth-form" id="ecForm" style="margin-top:10px">
          <label class="field">Name<input id="ecName" required minlength="2"></label>
          <label class="field">Relation<input id="ecRel" placeholder="e.g. Brother"></label>
          <label class="field">Mobile<input id="ecPhone" type="tel" inputmode="tel" required placeholder="98480 12345"></label>
          <button class="btn">${ic("users")} Add contact</button></form>
        <p class="tiny muted" style="margin:10px 0 0">${ic("info")} Demo: SOS texts are logged, not sent.</p></div>
      <div class="card"><h3>How family booking works</h3><ul class="small muted" style="padding-left:18px;margin:8px 0 0">
        <li>Choose who the visit is for when you book. The nearest doctor to <b>their</b> home is sent.</li>
        <li>You see their visit live in your app and get every update.</li>
        <li>Share a live link with anyone else in the family.</li></ul></div>
    </aside></div>`;
  $("#famSos").onclick = () => guard(sosSheet);
  $$("[data-now]").forEach((b) => (b.onclick = () => { FAM.member = +b.dataset.now; guard(doctorNowSheet); }));
  $$("[data-book]").forEach((b) => (b.onclick = () => { FAM.member = +b.dataset.book; go("book"); }));
  $$("[data-rm]").forEach((b) => (b.onclick = () => guard(async () => {
    if (!confirm("Remove this family member? Their past visits stay in their record.")) return;
    await api(`/api/patient/family/members/${b.dataset.rm}`, { method: "DELETE" }); toast("Removed", "info"); SCREENS.family();
  })));
  $$("[data-rmc]").forEach((b) => (b.onclick = () => guard(async () => {
    await api(`/api/patient/family/contacts/${b.dataset.rmc}`, { method: "DELETE" }); toast("Contact removed", "info"); SCREENS.family();
  })));
  let home = "same", pin = null, map = null, marker = null;
  $$("[data-home]").forEach((b) => (b.onclick = () => {
    home = b.dataset.home; $$("[data-home]").forEach((x) => x.classList.toggle("on", x === b));
    $("#fmOther").hidden = home !== "other";
    if (home === "other" && !map) {
      map = makeMap($("#fmMap"), { center: [me.lat, me.lng], zoom: 13 });
      if (map) map.on("click", (e) => { pin = [e.latlng.lat, e.latlng.lng]; marker ? marker.setLatLng(pin) : (marker = L.marker(pin, { icon: markerIcon("home", ic("home")) }).addTo(map)); });
      else pin = [me.lat, me.lng]; // no map available: use the account's area
    }
  }));
  $("#famForm").onsubmit = (e) => { e.preventDefault(); guard(async () => {
    const m = await post("/api/patient/family/members", { name: $("#fmName").value, relation: $("#fmRel").value, date_of_birth: $("#fmDob").value,
      gender: $("#fmGender").value || null, phone: $("#fmPhone").value, same_home: home === "same", address: $("#fmAddr").value,
      lat: pin?.[0] ?? null, lng: pin?.[1] ?? null });
    toast(`${first(m.name)} added`); SCREENS.family();
  }); };
  $("#ecForm").onsubmit = (e) => { e.preventDefault(); guard(async () => {
    await post("/api/patient/family/contacts", { name: $("#ecName").value, relation: $("#ecRel").value, phone: $("#ecPhone").value });
    toast("Emergency contact added"); SCREENS.family();
  }); };
};
