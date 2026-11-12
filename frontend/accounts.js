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
const auth = { mode: "signin", kind: "doctor", draft: {} };

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
      <div class="field"><span>Mobile number</span><div class="otp-row"><input id="phone" type="tel" value="${esc(d.phone || "")}" autocomplete="tel" inputmode="tel" placeholder="98480 12345" aria-label="Mobile number"><button type="button" class="btn" id="sendOtp">${auth.otp ? "Resend code" : "Send code"}</button></div></div>
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
  $$("[data-mode]").forEach((b) => (b.onclick = (e) => { e.preventDefault(); keep(); renderAuth(b.dataset.mode); }));
  $$("[data-kind]").forEach((b) => (b.onclick = () => { keep(); auth.kind = b.dataset.kind; renderAuth(); }));
  $$("[data-token]").forEach((b) => (b.onclick = () => signIn(b.dataset.token)));
  const det = $(".demo-accounts"); if (det) det.ontoggle = () => (d.demoOpen = det.open);
  $("#authForm").onsubmit = (e) => { e.preventDefault(); keep(); submitAuth(); };
  if ($("#sendOtp")) $("#sendOtp").onclick = async () => {
    keep(); $("#authErr").hidden = true;
    const btn = $("#sendOtp"); btn.disabled = true; btn.textContent = "Sending…";
    try {
      const res = await fetch("/api/auth/otp", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ phone: d.phone || "" }) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error((data.detail && data.detail.message) || "Could not send the code.");
      auth.otp = data; d.phone = data.phone; d.otp = "";
      renderAuth(); toast(`Code sent to ${data.masked}`); const o = $("#otp"); if (o) o.focus();
    } catch (e) { showAuthErr(e.message); btn.disabled = false; btn.textContent = auth.otp ? "Resend code" : "Send code"; }
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
    if (auth.otp.phone !== body.phone) return showAuthErr("Your number changed. Tap Send code to verify the new number.");
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

/* Provider dashboard: shown until Triyana approves a newly registered provider. */
function verifyBanner(st) {
  const v = st.verification_status || state.verification;
  if (!v || v === "verified") return "";
  const rejected = v === "rejected";
  return `<div class="card verify-card ${rejected ? "bad" : ""}">
      <div class="row" style="gap:12px;align-items:flex-start">${ic(rejected ? "alert" : "shield", "lg")}
      <div class="grow"><h3 style="margin:0 0 4px">${rejected ? "We couldn't verify your account" : "We're verifying your account"}</h3>
        <p class="small muted" style="margin:0">${rejected ? "Please contact Triyana support to fix your details." : st.role === "doctor" || st.role === "physio" ? "We're checking your council registration. You can go online and take visits as soon as you're approved, usually within one working day." : "We're checking your ID. You can go online as soon as you're approved, usually within one working day."}</p>
        ${!rejected && state.accounts.length ? `<button class="btn sm" id="demoVerify" style="margin-top:10px">${ic("check")} Approve me (demo only)</button>` : ""}</div></div></div>`;
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
      ${history ? `<div class="card"><h3>Your history</h3><p class="small muted" style="margin:6px 0 12px">Visits, notes, prescriptions, medicine orders and lab reports are saved to this account.</p>
        <div class="row" style="gap:8px;flex-wrap:wrap"><button class="btn sm" data-go="home">Visit history</button><button class="btn sm" data-go="orders">Orders</button><button class="btn sm" data-go="meds">My medicines</button>${TABS.patient.some((t) => t[0] === "labs") ? `<button class="btn sm" data-go="labs">Lab reports</button>` : ""}</div></div>` : ""}
    </div><aside>
      ${a.demo ? `<div class="card"><h3>Your own account</h3><p class="small muted" style="margin:6px 0 12px">Sign up with your email to keep your own history.</p><button class="btn primary" id="toSignup">Create an account</button></div>` : `
      <div class="card"><h3>Mobile number</h3>
        <p class="small muted" style="margin:6px 0 10px">${a.phone ? `${esc(a.phone)} ${a.phone_verified ? `<span class="badge">${ic("check")} Verified</span>` : ""}` : "No number yet"}</p>
        <form id="phoneForm" class="auth-form"><div class="otp-row"><input id="newPhone" type="tel" inputmode="tel" placeholder="New mobile number" aria-label="New mobile number"><button type="button" class="btn" id="phoneOtp">Send code</button></div>
          <div id="phoneCode" hidden><label class="field">Code from the SMS<input id="phoneOtpIn" inputmode="numeric" maxlength="6" autocomplete="one-time-code"></label><p class="tiny muted" id="phoneHint"></p><button class="btn">Verify and save</button></div></form></div>
      <div class="card"><h3>Change password</h3>
        <form id="pw" class="auth-form" style="margin-top:10px">
          <label class="field">Current password<input id="pwOld" type="password" autocomplete="current-password"></label>
          <label class="field">New password<input id="pwNew" type="password" autocomplete="new-password" minlength="8"></label>
          <button class="btn">Update password</button></form></div>`}
      <div class="card"><button class="btn ghost block" id="acctOut">Sign out</button></div>
    </aside></div>`;
  $$("[data-go]").forEach((b) => (b.onclick = () => go(b.dataset.go)));
  $("#acctOut").onclick = signOut;
  if ($("#toSignup")) $("#toSignup").onclick = () => { signOut(); renderAuth("signup"); };
  if ($("#profile")) $("#profile").onsubmit = (e) => { e.preventDefault(); guard(async () => {
    const body = { name: $("#pName").value };
    if ($("#pAddr")) Object.assign(body, { address: $("#pAddr").value, date_of_birth: $("#pDob").value || null, gender: $("#pGender").value || null });
    const r = await api("/api/account", { method: "PATCH", body });
    state.name = r.name; accountChrome(); toast("Saved");
  }); };
  if ($("#phoneOtp")) $("#phoneOtp").onclick = () => guard(async () => {
    const r = await post("/api/account/phone/otp", { phone: $("#newPhone").value });
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
