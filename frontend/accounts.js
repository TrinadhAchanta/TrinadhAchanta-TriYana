/* Triyana accounts: email sign-up and sign-in (DoorDash style) for both apps, plus the Account tab.
   Patients register in Triyana; doctors, riders and sample collectors register in Triyana Partner.
   Everything they do is saved to their account, so it is there whenever they sign in again. */
"use strict";

const ACCOUNT_TAB = ["account", "Account", "user", "desktop"];
const PROVIDER_KINDS = [
  ["doctor", "Doctor", "stethoscope", "Home visits and prescriptions"],
  ["physio", "Physiotherapist", "heart", "Home therapy sessions"],
  ["courier", "Delivery rider", "truck", "Medicine deliveries"],
  ["phlebotomist", "Sample collector", "flask", "Lab sample pickups"],
];
const auth = { mode: "signin", kind: "doctor", draft: {}, countries: [] };

/* ------------------------------------------------------------ country picker */
const flagOf = (iso) => /^[A-Z]{2}$/.test(iso) ? String.fromCodePoint(...[...iso].map((c) => 127397 + c.charCodeAt(0))) : "🌐";
const guessCountry = () => {
  try { const r = new Intl.Locale(navigator.language).maximize().region; if (r) return r; } catch {}
  return "IN";
};
let regionNames = null; try { regionNames = new Intl.DisplayNames([navigator.language || "en", "en"], { type: "region" }); } catch {}
let keepDraft = () => {};
fetch("/api/countries").then((r) => r.json()).then((list) => {
  auth.countries = list.map((c) => { let n = c.name; try { n = (regionNames && regionNames.of(c.iso)) || n; } catch {} return { ...c, name: n }; })
    .sort((a, b) => a.name.localeCompare(b.name));
  // Re-draw an open sign-up form (keeping what was typed) so the picker lists every country.
  if (document.body.classList.contains("signed-out") && $("#phoneCountry")) { keepDraft(); renderAuth(); }
  const acct = $("#newPhoneCountryWrap");
  if (acct) { acct.outerHTML = countrySelect("newPhoneCountry", $("#newPhoneCountry").value); wireCountry("newPhoneCountry"); }
}).catch(() => {});
const countryOf = (iso) => auth.countries.find((c) => c.iso === iso) || { iso, dial: iso === "IN" ? "+91" : "", example: iso === "IN" ? "98480 12345" : "" };
const ccFace = (iso) => `${flagOf(iso)} ${esc(countryOf(iso).dial)}<svg viewBox="0 0 24 24" class="i"><path d="M6 9l6 6 6-6"/></svg>`;

/* A compact "🇮🇳 +91" button over a native, searchable list of every country. */
function countrySelect(id, iso) {
  const list = auth.countries.length ? auth.countries : [countryOf(iso)];
  const opts = list.map((x) => `<option value="${x.iso}" ${x.iso === iso ? "selected" : ""}>${flagOf(x.iso)} ${esc(x.name || x.iso)} (${x.dial})</option>`).join("");
  return `<span class="cc-pick" id="${id}Wrap"><span class="cc-face" aria-hidden="true">${ccFace(iso)}</span><select id="${id}" aria-label="Country">${opts}</select></span>`;
}
function wireCountry(id, onChange) {
  const sel = $(`#${id}`); if (!sel) return;
  sel.onchange = () => { $(`#${id}Wrap .cc-face`).innerHTML = ccFace(sel.value); if (onChange) onChange(countryOf(sel.value)); };
}

function renderAuth(mode) {
  if (mode) auth.mode = mode;
  const partner = APP === "provider";
  const signup = auth.mode === "signup";
  const d = auth.draft;
  const input = (id, label, type = "text", attrs = "") => `<label class="field">${label}<input id="${id}" type="${type}" value="${esc(d[id] || "")}" ${attrs}></label>`;
  const icon = { doctor: "stethoscope", courier: "truck", pharmacist: "store", phlebotomist: "flask", hospital: "store", patient: "user", physiotherapist: "heart" };

  const signinForm = `
    <form class="auth-form" id="authForm" novalidate>
      ${input("email", "Email", "email", 'autocomplete="email" inputmode="email" required')}
      ${input("password", "Password", "password", 'autocomplete="current-password" required')}
      <button class="btn primary block" id="authGo">Sign in</button>
      <p class="tiny muted center">New to ${partner ? "Triyana Partner" : "Triyana"}? <a href="#" data-mode="signup">Create an account</a></p>
    </form>`;

  const providerFields = !partner ? "" : `
      <div class="section-title" style="margin-top:2px">I want to sign up as</div>
      <div class="kind-pick">${PROVIDER_KINDS.map(([k, l, i, sub]) => `<button type="button" class="kind ${auth.kind === k ? "on" : ""}" data-kind="${k}">${ic(i)}<b>${l}</b><span class="tiny muted">${sub}</span></button>`).join("")}</div>`;
  const physio = auth.kind === "physio";
  const councils = physio ? ["Indian Association of Physiotherapists (IAP)", "Telangana State Allied & Healthcare Council", "Karnataka Allied & Healthcare Council", "Maharashtra OT & PT Council", "Delhi Council for Physiotherapy & OT", "Other state council"]
    : ["National Medical Commission", "Telangana State Medical Council", "Andhra Pradesh Medical Council", "Karnataka Medical Council", "Tamil Nadu Medical Council", "Maharashtra Medical Council", "Delhi Medical Council", "Other state medical council"];
  const doctorFields = partner && (auth.kind === "doctor" || physio) ? `
      <div class="auth-note">${ic("shield")}<span>We check your registration with the ${physio ? "council" : "medical council"} before you can take ${physio ? "sessions" : "visits"}.</span></div>
      <div class="form-grid">
        <label class="wide">${physio ? "Council" : "Medical council"}<select id="council">${councils.map((c) => `<option ${d.council === c ? "selected" : ""}>${c}</option>`).join("")}</select></label>
        <label>Registration number<input id="licence" value="${esc(d.licence || "")}" placeholder="e.g. 12345" required></label>
        <label>Year registered<input id="regYear" inputmode="numeric" maxlength="4" value="${esc(d.regYear || "")}" placeholder="2015"></label>
        <label${physio ? ' class="wide"' : ""}>Qualification<input id="qual" value="${esc(d.qual || (physio ? "BPT" : "MBBS"))}"></label>
        ${physio ? "" : `<label>Specialty<input id="spec" value="${esc(d.spec || "General Medicine")}"></label>`}
      </div>` : partner ? `
      <label class="field">Vehicle<select id="vehicle">${["Bike", "Scooter", "Bicycle", "Car"].map((v) => `<option ${d.vehicle === v ? "selected" : ""}>${v}</option>`).join("")}</select></label>
      <div class="auth-note">${ic("shield")}<span>We check your ID${auth.kind === "courier" ? " and driving licence" : " and training"} before you can go online.</span></div>` : "";

  const signupForm = `
    <form class="auth-form" id="authForm" novalidate>
      ${providerFields}
      ${input("name", "Full name", "text", 'autocomplete="name" required')}
      ${input("email", "Email", "email", 'autocomplete="email" inputmode="email" required')}
      <div class="field"><span>Mobile number</span><div class="otp-row"><div class="phone-in">${countrySelect("phoneCountry", d.phoneCountry || (d.phoneCountry = guessCountry()))}<input id="phone" type="tel" value="${esc(d.phone || "")}" autocomplete="tel-national" inputmode="tel" placeholder="${esc(countryOf(d.phoneCountry).example || "Mobile number")}" aria-label="Mobile number"></div><button type="button" class="btn" id="sendOtp">${auth.otp ? "Resend" : "Send code"}</button></div></div>
      ${auth.otp ? `<label class="field">6-digit code from the SMS<input id="otp" value="${esc(d.otp || "")}" inputmode="numeric" maxlength="6" autocomplete="one-time-code" placeholder="••••••"></label>
        <p class="tiny muted" style="margin:-4px 0 0">Sent to ${esc(auth.otp.masked)}.${auth.otp.demo_code ? ` <span class="otp-demo">Demo: no real SMS is sent. Your code is <b>${esc(auth.otp.demo_code)}</b></span>` : ""}</p>` : `<p class="tiny muted" style="margin:-4px 0 0">We'll text you a code to confirm your number.</p>`}
      ${input("password", "Create a password", "password", 'autocomplete="new-password" minlength="8" required')}
      <p class="tiny muted" style="margin:-4px 0 0">At least 8 characters, with letters and numbers.</p>
      ${partner ? input("address", "Area you work in (optional)", "text", 'placeholder="e.g. Lake View"') : `
        ${input("address", "Home address", "text", 'autocomplete="street-address" required placeholder="House, street, area"')}
        <div class="form-grid">${input("dob", "Date of birth", "date", 'max="' + new Date().toISOString().slice(0, 10) + '"')}
          <label class="field">Gender<select id="gender">${[["", "Select"], ["female", "Female"], ["male", "Male"], ["other", "Other"], ["prefer_not", "Prefer not to say"]].map(([v, l]) => `<option value="${v}" ${d.gender === v ? "selected" : ""}>${l}</option>`).join("")}</select></label></div>
        <p class="tiny muted" style="margin:-4px 0 0">This demo serves Demo City, so new accounts are placed there for doctors and riders.</p>`}
      ${doctorFields}
      <button class="btn primary block" id="authGo">Create account</button>
      <p class="tiny muted center">Already have an account? <a href="#" data-mode="signin">Sign in</a></p>
    </form>`;

  const demoGroups = {};
  state.accounts.forEach((a) => {
    const k = partner ? (a.label.split("·")[1] || "").trim().split(" ")[0] || "account" : "patient";
    (demoGroups[k] = demoGroups[k] || []).push(a);
  });
  const demo = state.accounts.length ? `
    <details class="demo-accounts" ${d.demoOpen ? "open" : ""}><summary>${ic("info")} Try a demo account instead</summary>
      ${Object.entries(demoGroups).map(([g, list]) => `<div class="section-title">${partner ? `${esc(g)}s` : "Demo patients and hospitals"}</div>
        <div class="login-list">${list.map((a) => `<button class="login-acc" data-token="${esc(a.token)}"><span class="avatar">${ic(icon[g] || "user")}</span><span class="grow"><b>${esc(a.label.split("·")[0].replace(/\s*\(.*\)/, ""))}</b><span class="tiny muted">${esc((a.label.split("·")[1] || "Patient").trim())}</span></span>${ic("arrow")}</button>`).join("")}</div>`).join("")}
    </details>` : "";

  $("#login").innerHTML = `<div class="login-card">
      <div class="brand"><div class="mark">${ic("logo")}</div><div><b>${partner ? "Triyana Partner" : "Triyana"}</b><small>${partner ? "For doctors, physios, riders, pharmacists & sample collectors" : "Home healthcare"}</small></div></div>
      <h1>${signup ? (partner ? "Join Triyana Partner" : "Create your account") : (partner ? "Welcome back, partner" : "Welcome back")}</h1>
      <p class="muted">${signup ? (partner ? "Sign up with your email. Once we verify you, go online and get nearby requests." : "Sign up with your email. Your visits, prescriptions, orders and lab reports stay in your account.") : (partner ? "Sign in to go online, see your jobs and your earnings." : "Sign in to book doctors, order medicines and see your history.")}</p>
      <div class="seg auth-seg"><button type="button" data-mode="signin" class="${signup ? "" : "on"}">Sign in</button><button type="button" data-mode="signup" class="${signup ? "on" : ""}">Create account</button></div>
      <div class="auth-error" id="authErr" role="alert" hidden></div>
      ${signup ? signupForm : signinForm}
      ${demo}
      <div class="demo-flag">${ic("info")}<span>${partner ? `Patients use <a href="/">the Triyana app</a>.` : `Doctors and riders use <a href="/provider">Triyana Partner</a>.`}</span></div>
    </div>`;

  const keep = () => $$("#authForm input, #authForm select").forEach((el) => (d[el.id] = el.value));
  keepDraft = keep;
  wireCountry("phoneCountry", (c) => { d.phoneCountry = c.iso; const p = $("#phone"); if (p) { p.placeholder = c.example || "Mobile number"; p.focus(); } });
  $$("[data-mode]").forEach((b) => (b.onclick = (e) => { e.preventDefault(); keep(); renderAuth(b.dataset.mode); }));
  $$("[data-kind]").forEach((b) => (b.onclick = () => { keep(); auth.kind = b.dataset.kind; renderAuth(); }));
  $$("[data-token]").forEach((b) => (b.onclick = () => signIn(b.dataset.token)));
  const det = $(".demo-accounts"); if (det) det.ontoggle = () => (d.demoOpen = det.open);
  $("#authForm").onsubmit = (e) => { e.preventDefault(); keep(); submitAuth(); };
  if ($("#sendOtp")) $("#sendOtp").onclick = async () => {
    keep(); $("#authErr").hidden = true;
    const btn = $("#sendOtp"); btn.disabled = true; btn.textContent = "Sending…";
    try {
      const res = await fetch("/api/auth/otp", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ phone: d.phone || "", country: d.phoneCountry, app: APP }) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error((data.detail && data.detail.message) || "Could not send the code.");
      auth.otp = { ...data, typed: d.phone, country: d.phoneCountry }; d.otp = "";
      renderAuth(); toast(`Code sent to ${data.masked}`); const o = $("#otp"); if (o) o.focus();
    } catch (e) { showAuthErr(e.message); btn.disabled = false; btn.textContent = auth.otp ? "Resend" : "Send code"; }
  };
}

async function submitAuth() {
  const d = auth.draft, partner = APP === "provider", btn = $("#authGo"), err = $("#authErr");
  err.hidden = true;
  let body;
  if (auth.mode === "signin") {
    body = { app: APP, email: (d.email || "").trim(), password: d.password || "" };
    if (!body.email || !body.password) return showAuthErr("Enter your email and password.");
  } else {
    body = { app: APP, name: (d.name || "").trim(), email: (d.email || "").trim(), password: d.password || "",
             phone: (d.phone || "").trim(), otp: (d.otp || "").trim(), address: (d.address || "").trim() || null };
    if (!body.name || !body.email || !body.password) return showAuthErr("Fill in your name, email and a password.");
    if (!auth.otp) return showAuthErr("Tap Send code to verify your mobile number.");
    if (auth.otp.typed !== d.phone || auth.otp.country !== d.phoneCountry) return showAuthErr("Your number changed. Tap Send code to verify the new number.");
    body.phone = auth.otp.phone;
    if (!/^\d{6}$/.test(body.otp)) return showAuthErr("Enter the 6-digit code we sent to your phone.");
    if (partner) {
      body.role = auth.kind;
      if (auth.kind === "doctor" || auth.kind === "physio") {
        const ph = auth.kind === "physio";
        if (!(d.licence || "").trim()) return showAuthErr("Enter your council registration number.");
        body.doctor = { license_no: d.licence.trim(), medical_council: d.council || (ph ? "Indian Association of Physiotherapists (IAP)" : "National Medical Commission"),
                        qualification: (d.qual || (ph ? "BPT" : "MBBS")).trim(), specialty: (d.spec || "General Medicine").trim(),
                        registration_year: /^\d{4}$/.test(d.regYear || "") ? +d.regYear : null };
      } else body.vehicle = d.vehicle || "Bike";
    } else {
      if (!body.address) return showAuthErr("Enter your home address so doctors and riders can reach you.");
      body.date_of_birth = d.dob || null;
      body.gender = d.gender || null;
    }
  }
  btn.disabled = true; btn.textContent = auth.mode === "signin" ? "Signing in…" : "Creating your account…";
  try {
    const res = await fetch(auth.mode === "signin" ? "/api/auth/login" : "/api/auth/register",
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const det = data.detail || {};
      if (det.code === "email_taken") { auth.mode = "signin"; renderAuth(); }
      throw new Error(typeof det === "string" ? det : det.message || (Array.isArray(det) ? "Please check the form and try again." : "Something went wrong."));
    }
    const fresh = auth.mode === "signup";
    auth.draft = {}; auth.otp = null;
    await signIn(data.token);
    toast(fresh ? `Welcome to ${partner ? "Triyana Partner" : "Triyana"}, ${data.account.name.replace(/^Dr\.?\s+/i, "").split(" ")[0]}` : "Signed in");
  } catch (e) {
    showAuthErr(e.message);
  } finally {
    const b = $("#authGo"); if (b) { b.disabled = false; b.textContent = auth.mode === "signin" ? "Sign in" : "Create account"; }
  }
}

function showAuthErr(msg) { const err = $("#authErr"); err.innerHTML = `${ic("alert")}<span>${esc(msg)}</span>`; err.hidden = false; }

/* Sidebar / top bar: a demo persona switcher for demo accounts, your name for real accounts. */
function accountChrome() {
  const real = !state.demo;
  ["#account", "#accountMobile"].forEach((s) => { const el = $(s); el.hidden = real; if (!real) el.value = state.token; });
  $("#reset").hidden = real;
  $("#demoFlag").hidden = real;
  const who = $("#acctWho");
  who.hidden = !real;
  who.innerHTML = real ? `<span class="avatar sm">${esc(acctInitials(state.name))}</span><span class="grow"><b>${esc(state.name)}</b><span class="tiny muted">${esc(state.email || "")}</span></span>` : "";
  who.onclick = () => go("account");
  const me = $("#acctMe");
  me.hidden = !real;
  me.innerHTML = real ? `<span class="avatar sm">${esc(acctInitials(state.name))}</span>` : "";
  me.onclick = () => go("account");
}
const acctInitials = (n) => (n || "?").replace(/^Dr\.?\s+/i, "").split(/\s+/).slice(0, 2).map((w) => w[0] || "").join("").toUpperCase();

/* Provider dashboard: shown until Triyana approves a newly registered provider.
   Lists each partner check (council registry, ID, court records) and asks for an ID when needed. */
function verifyBanner(st) {
  const v = st.verification_status || state.verification;
  if (!v || v === "verified") return "";
  const rejected = v === "rejected";
  setTimeout(loadVerifyChecks, 0);
  return `<div class="card verify-card ${rejected ? "bad" : ""}">
      <div class="row" style="gap:12px;align-items:flex-start">${ic(rejected ? "alert" : "shield", "lg")}
      <div class="grow"><h3 style="margin:0 0 4px">${rejected ? "We couldn't verify your account" : "We're verifying your account"}</h3>
        <p class="small muted" style="margin:0" id="vIntro">${rejected ? "Please contact Triyana support to fix your details." : "You can go online and take requests as soon as Triyana approves you, usually within one working day."}</p>
        <div id="vChecks"></div>
        ${!rejected && state.accounts.length ? `<button class="btn sm" id="demoVerify" style="margin-top:10px">${ic("check")} Approve me (demo only)</button>` : ""}</div></div></div>`;
}
const V_ICON = { passed: ["check", "good", "Passed"], needs_review: ["alert", "warn", "Needs review"], failed: ["alert", "bad", "Failed"], error: ["alert", "warn", "Retrying"], in_progress: ["clock", "", "Checking"], not_started: ["clock", "", "Waiting for you"] };
const vRow = (c) => { const [i, cls, word] = V_ICON[c.status] || V_ICON.not_started;
  return `<li class="v-row"><span class="badge ${cls}">${ic(i)} ${word}</span><span class="grow"><b>${esc(c.label)}</b>${c.partner ? `<span class="tiny muted"> · ${esc(c.partner)}</span>` : ""}<span class="tiny muted v-sum">${esc(c.summary)}</span></span></li>`; };
const V_STAGE = { needs_documents: "Add your ID to continue.", checking: "Our verification partners are checking your details.", ready_for_review: "All checks passed. Triyana is doing a final review.", flagged: "Some checks need a closer look. Triyana will review them and may contact you." };
async function loadVerifyChecks() {
  const box = $("#vChecks"); if (!box) return;
  let v; try { v = await api("/api/account/verification"); } catch { return; }
  if (!$("#vChecks")) return;
  if (V_STAGE[v.stage]) $("#vIntro").textContent = V_STAGE[v.stage] + " You can go online as soon as you're approved.";
  const idForm = v.id_needed && v.stage !== "rejected" ? `<form class="form-grid v-form" id="vIdForm">
      <label>ID type<select id="vType">${v.id_types.map((t) => `<option value="${t}">${t === "pan" ? "PAN card" : "Driving licence"}</option>`).join("")}</select></label>
      <label>ID number<input id="vNum" required autocomplete="off" placeholder="ABCPE1234F" style="text-transform:uppercase"></label>
      <label>Date of birth<input id="vDob" type="date" required></label>
      <label class="wide">Address (for the court-record search)<input id="vAddr" placeholder="House, street, city"></label>
      <label class="wide check"><input type="checkbox" id="vConsent"> I agree that Triyana and its verification partner (IDfy) may check this ID with the issuing authority and search court records in my name. Triyana keeps only a masked copy of the number.</label>
      <div class="wide"><button class="btn primary sm">${ic("shield")} Start ID check</button></div></form>` : "";
  const faceForm = v.face_needed && v.stage !== "rejected" && typeof faceEnroll === "function" ? `<div class="v-form"><p class="small" style="margin:0 0 8px"><b>Live face enrolment.</b> Take a live selfie with consent. Before every home visit you'll repeat a 5-second face check against it.</p>
      <button class="btn primary sm" id="vFace">${ic("scan")} Enrol my face</button></div>` : "";
  box.innerHTML = `<ul class="v-list">${v.checks.map(vRow).join("")}<li class="v-row"><span class="badge ${v.stage === "ready_for_review" ? "warn" : ""}">${ic("clock")} ${v.stage === "ready_for_review" ? "In review" : "Next"}</span><span class="grow"><b>Final review</b><span class="tiny muted"> · Triyana</span><span class="tiny muted v-sum">A person at Triyana approves your account.</span></span></li></ul>${idForm}${faceForm}`;
  const vf = $("#vFace"); if (vf) vf.onclick = () => faceEnroll(loadVerifyChecks);
  const f = $("#vIdForm");
  if (f) f.onsubmit = (e) => { e.preventDefault(); guard(async () => {
    await post("/api/account/verification/identity", { id_type: $("#vType").value, id_number: $("#vNum").value, date_of_birth: $("#vDob").value, address: $("#vAddr").value, consent: $("#vConsent").checked });
    toast("ID submitted. We'll let you know when you're approved."); loadVerifyChecks();
  }); };
}
document.addEventListener("click", (e) => {
  if (!e.target.closest || !e.target.closest("#demoVerify")) return;
  guard(async () => { await post("/api/account/demo-verify"); state.verification = "verified"; toast("Approved. You can go online now."); go("dash"); });
});

/* ---------------------------------------------------------------- Account tab */
SCREENS.account = async () => {
  const a = await api("/api/account");
  const roleName = { patient: "Patient", doctor: "Doctor", physio: "Physiotherapist", courier: "Delivery rider", phlebotomist: "Sample collector", pharmacist: "Pharmacist", hospital: "Hospital staff" }[a.role] || a.role;
  const vBadge = a.role === "patient" || a.role === "hospital" ? "" : a.verification_status === "verified" ? `<span class="badge">${ic("check")} Verified</span>` : a.verification_status === "rejected" ? `<span class="badge bad">Not verified</span>` : `<span class="badge warn">Verification pending</span>`;
  const history = APP === "patient" && a.role === "patient";
  view().innerHTML = `${pageHead("Account", a.demo ? "This is a shared demo account. Create your own account to keep your history private." : `Member since ${esc(a.member_since || "today")}`)}
    <div class="split"><div>
      <div class="card">
        <div class="row" style="gap:14px"><span class="avatar lg">${esc(acctInitials(a.name))}</span>
          <div class="grow"><h3 style="margin:0">${esc(a.name)}</h3><div class="small muted">${esc(a.email || "Demo account")} · ${esc(roleName)}</div></div>${vBadge}</div>
        ${a.demo ? "" : `<form class="form-grid" id="profile" style="margin-top:16px">
          <label>Full name<input id="pName" value="${esc(a.name)}"></label>
          ${a.patient ? `<label>Date of birth<input id="pDob" type="date" value="${esc(/^\d{4}-\d\d-\d\d$/.test(a.patient.date_of_birth) ? a.patient.date_of_birth : "")}"></label>
          <label>Gender<select id="pGender">${[["", "Select"], ["female", "Female"], ["male", "Male"], ["other", "Other"], ["prefer_not", "Prefer not to say"]].map(([v, l]) => `<option value="${v}" ${a.patient.gender === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>` : ""}
          ${a.patient ? `<label class="wide">Home address<input id="pAddr" value="${esc(a.patient.address)}"></label>` : ""}
          <div class="wide"><button class="btn primary">Save changes</button></div></form>`}
      </div>
      ${a.physio ? `<div class="card"><h3>Registration</h3><p class="small muted" style="margin:6px 0 0">${esc([a.physio.qualification, `Reg. No. ${a.physio.license_no}`, a.physio.medical_council].join(" · "))}</p></div>` : ""}
      ${a.doctor ? `<div class="card"><h3>Registration</h3><p class="small muted" style="margin:6px 0 0">${regLine(a.doctor)}${a.doctor.specialty ? ` · ${esc(a.doctor.specialty)}` : ""}</p></div>` : ""}
      ${a.doctor && typeof faceEnroll === "function" ? `<div class="card" id="faceCard"></div>` : ""}
      ${history ? `<div class="card"><h3>Your history</h3><p class="small muted" style="margin:6px 0 12px">Visits, notes, prescriptions, medicine orders and lab reports are saved to this account.</p>
        <div class="row" style="gap:8px;flex-wrap:wrap"><button class="btn sm" data-go="home">Visit history</button><button class="btn sm" data-go="orders">Orders</button><button class="btn sm" data-go="meds">My medicines</button>${TABS.patient.some((t) => t[0] === "labs") ? `<button class="btn sm" data-go="labs">Lab reports</button>` : ""}</div></div>` : ""}
    </div><aside>
      ${a.demo ? `<div class="card"><h3>Your own account</h3><p class="small muted" style="margin:6px 0 12px">Sign up with your email to keep your own history.</p><button class="btn primary" id="toSignup">Create an account</button></div>` : `
      <div class="card"><h3>Mobile number</h3>
        <p class="small muted" style="margin:6px 0 10px">${a.phone ? `${esc(a.phone)} ${a.phone_verified ? `<span class="badge">${ic("check")} Verified</span>` : ""}` : "No number yet"}</p>
        <form id="phoneForm" class="auth-form"><div class="otp-row"><div class="phone-in">${countrySelect("newPhoneCountry", guessCountry())}<input id="newPhone" type="tel" inputmode="tel" placeholder="New mobile number" aria-label="New mobile number"></div><button type="button" class="btn" id="phoneOtp">Send code</button></div>
          <div id="phoneCode" hidden><label class="field">Code from the SMS<input id="phoneOtpIn" inputmode="numeric" maxlength="6" autocomplete="one-time-code"></label><p class="tiny muted" id="phoneHint"></p><button class="btn">Verify and save</button></div></form></div>
      <div class="card"><h3>Change password</h3>
        <form id="pw" class="auth-form" style="margin-top:10px">
          <label class="field">Current password<input id="pwOld" type="password" autocomplete="current-password"></label>
          <label class="field">New password<input id="pwNew" type="password" autocomplete="new-password" minlength="8"></label>
          <button class="btn">Update password</button></form></div>`}
      <div class="card"><button class="btn ghost block" id="acctOut">Sign out</button></div>
    </aside></div>`;
  $$("[data-go]").forEach((b) => (b.onclick = () => go(b.dataset.go)));
  if ($("#faceCard")) faceAccountCard();
  $("#acctOut").onclick = signOut;
  if ($("#toSignup")) $("#toSignup").onclick = () => { signOut(); renderAuth("signup"); };
  if ($("#profile")) $("#profile").onsubmit = (e) => { e.preventDefault(); guard(async () => {
    const body = { name: $("#pName").value };
    if ($("#pAddr")) Object.assign(body, { address: $("#pAddr").value, date_of_birth: $("#pDob").value || null, gender: $("#pGender").value || null });
    const r = await api("/api/account", { method: "PATCH", body });
    state.name = r.name; accountChrome(); toast("Saved");
  }); };
  wireCountry("newPhoneCountry");
  if ($("#phoneOtp")) $("#phoneOtp").onclick = () => guard(async () => {
    const r = await post("/api/account/phone/otp", { phone: $("#newPhone").value, country: $("#newPhoneCountry").value });
    $("#newPhone").value = r.phone; $("#phoneCode").hidden = false; $("#phoneOtp").textContent = "Resend code";
    $("#phoneHint").innerHTML = `Sent to ${esc(r.masked)}.${r.demo_code ? ` <span class="otp-demo">Demo: no real SMS is sent. Your code is <b>${esc(r.demo_code)}</b></span>` : ""}`;
    $("#phoneOtpIn").focus();
  });
  if ($("#phoneForm")) $("#phoneForm").onsubmit = (e) => { e.preventDefault(); guard(async () => {
    await post("/api/account/phone", { phone: $("#newPhone").value, otp: $("#phoneOtpIn").value });
    toast("Mobile number updated"); SCREENS.account();
  }); };
  if ($("#pw")) $("#pw").onsubmit = (e) => { e.preventDefault(); guard(async () => {
    await post("/api/account/password", { current_password: $("#pwOld").value, new_password: $("#pwNew").value });
    $("#pwOld").value = $("#pwNew").value = ""; toast("Password updated");
  }); };
};

/* Account tab (doctors): verified face, re-enrol, withdraw biometric consent. */
async function faceAccountCard() {
  const box = $("#faceCard"); if (!box) return;
  const f = await api("/api/provider/face").catch(() => null); if (!f || !$("#faceCard")) return;
  const e = f.enrollment;
  const word = f.locked ? ["bad", "Locked for review"] : f.active ? ["good", "Active"] : e?.status === "pending_review" ? ["warn", "Waiting for approval"] : ["", "Not enrolled"];
  box.innerHTML = `<div class="row between"><h3 style="margin:0">Face verification</h3><span class="badge ${word[0]}">${word[1]}</span></div>
    <div class="row" style="gap:12px;margin:10px 0">${e?.photo ? `<img class="prov-photo" src="${esc(e.photo)}" alt="Your verified profile photo">` : `<span class="avatar lg">${ic("scan")}</span>`}
      <p class="small muted" style="margin:0">Patients see this photo, your name and your registration once you pass the live check for their visit. They never see your face data or documents.${e ? ` Enrolled ${esc(day(e.created_at))}.` : ""}</p></div>
    <div class="row" style="gap:8px;flex-wrap:wrap"><button class="btn sm" id="faceRe">${ic("scan")} ${e ? "Re-enrol my face" : "Enrol my face"}</button>
      ${e ? `<button class="btn ghost sm danger" id="faceWithdraw">Withdraw consent</button>` : ""}</div>`;
  $("#faceRe").onclick = () => faceEnroll(() => SCREENS.account());
  const w = $("#faceWithdraw"); if (w) w.onclick = () => guard(async () => {
    if (!confirm("Withdraw face verification consent? Your face data is deleted and you can't take home visits until you enrol again or Triyana approves another way to verify you.")) return;
    await api("/api/provider/face/enrollment", { method: "DELETE" }); toast("Consent withdrawn. Your face data was deleted.", "info"); SCREENS.account();
  });
}
