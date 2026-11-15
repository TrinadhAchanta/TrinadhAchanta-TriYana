/* Forgot password, for both apps: we text a code to the account's verified mobile number,
   then the person picks a new password. Every other device is signed out. */
"use strict";

const forgot = { email: "", sent: null };

function forgotScreen(email) {
  if (email !== undefined) { forgot.email = email || ""; forgot.sent = null; }
  const partner = APP === "provider";
  const s = forgot.sent;
  $("#login").innerHTML = `<div class="login-card">
      <div class="brand"><div class="mark">${ic("logo")}</div><div><b>${partner ? PROVIDER_APP : "Triyana"}</b><small>Reset your password</small></div></div>
      <h1>Forgot your password?</h1>
      <p class="muted">${s ? `We texted a 6-digit code to ${esc(s.masked)}, the mobile number on your account.` : "Enter your account email. We'll text a code to the mobile number you verified when you signed up."}</p>
      <div class="auth-error" id="authErr" role="alert" hidden></div>
      <form class="auth-form" id="forgotForm" novalidate>
        <label class="field">Email<input id="fEmail" type="email" value="${esc(forgot.email)}" autocomplete="email" inputmode="email" ${s ? "readonly" : ""} required></label>
        ${s ? `
        <label class="field">6-digit code from the SMS<input id="fOtp" inputmode="numeric" maxlength="6" autocomplete="one-time-code" placeholder="••••••"></label>
        ${s.demo_code ? `<p class="tiny muted" style="margin:-4px 0 0"><span class="otp-demo">Demo: no real SMS is sent. Your code is <b>${esc(s.demo_code)}</b></span></p>` : ""}
        <label class="field">New password<input id="fPass" type="password" autocomplete="new-password" minlength="8" required></label>
        <p class="tiny muted" style="margin:-4px 0 0">At least 8 characters, with letters and numbers. You'll be signed out on your other devices.</p>
        <button class="btn primary block" id="fGo">Set new password</button>
        <p class="tiny muted center">No SMS? <a href="#" id="fResend">Send a new code</a></p>` : `
        <button class="btn primary block" id="fGo">Text me a code</button>`}
        <p class="tiny muted center"><a href="#" id="fBack">Back to sign in</a></p>
      </form>
    </div>`;
  $("#fBack").onclick = (e) => { e.preventDefault(); auth.draft.email = forgot.email; renderAuth("signin"); };
  if ($("#fResend")) $("#fResend").onclick = (e) => { e.preventDefault(); sendResetCode(); };
  $("#forgotForm").onsubmit = (e) => { e.preventDefault(); s ? finishReset() : sendResetCode(); };
  const first = s ? $("#fOtp") : $("#fEmail"); if (first) first.focus();
}

async function resetCall(path, body) {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ app: APP, ...body }) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const det = data.detail || {};
    throw new Error(typeof det === "string" ? det : det.message || (Array.isArray(det) ? "Please check the form and try again." : "Something went wrong."));
  }
  return data;
}

async function sendResetCode() {
  forgot.email = ($("#fEmail").value || "").trim();
  if (!forgot.email) return showAuthErr("Enter the email you signed up with.");
  const btn = $("#fGo"); btn.disabled = true; btn.textContent = "Sending…";
  try {
    forgot.sent = await resetCall("/api/auth/password/forgot", { email: forgot.email });
    forgotScreen(); toast(`Code sent to ${forgot.sent.masked}`);
  } catch (e) { showAuthErr(e.message); btn.disabled = false; btn.textContent = forgot.sent ? "Set new password" : "Text me a code"; }
}

async function finishReset() {
  const otp = ($("#fOtp").value || "").replace(/\D/g, ""), pass = $("#fPass").value || "";
  if (!/^\d{6}$/.test(otp)) return showAuthErr("Enter the 6-digit code we sent to your phone.");
  if (pass.length < 8) return showAuthErr("Use at least 8 characters for your password.");
  const btn = $("#fGo"); btn.disabled = true; btn.textContent = "Saving…";
  try {
    const data = await resetCall("/api/auth/password/reset", { email: forgot.email, otp, new_password: pass });
    forgot.sent = null; auth.draft = {};
    await signIn(data.token);
    toast("Password changed. You're signed in.");
  } catch (e) { showAuthErr(e.message); btn.disabled = false; btn.textContent = "Set new password"; }
}
