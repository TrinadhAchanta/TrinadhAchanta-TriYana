/* Nabzo: live face verification for doctors.
   - faceEnroll(): consent + a live capture that becomes the doctor's verified face.
   - faceStartJourney(visitId): the mandatory check before Start journey on EVERY home visit.
   The server decides every outcome and enforces it; this file only runs the camera and shows results. */
"use strict";

Object.assign(P, {
  scan: '<path d="M4 8V6a2 2 0 0 1 2-2h2M16 4h2a2 2 0 0 1 2 2v2M20 16v2a2 2 0 0 1-2 2h-2M8 20H6a2 2 0 0 1-2-2v-2"/><circle cx="12" cy="10" r="3"/><path d="M7.5 17a5 5 0 0 1 9 0"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  camera: '<path d="M4 8h3l2-3h6l2 3h3a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"/><circle cx="12" cy="13" r="4"/>',
  wifi: '<path d="M2 9a15 15 0 0 1 20 0M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0"/><circle cx="12" cy="19" r="1"/>',
  camOff: '<path d="M3 3l18 18"/><path d="M15 15v1a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h1M9 6h4a2 2 0 0 1 2 2v3l5-3v8"/>',
});

const FACE_FRAME_COUNT = 4;
const FACE_FRAME_GAP_MS = 650;
const FACE_DEMO = [["", "Real camera (default)"], ["other_person", "Someone else's face"], ["printed_photo", "Printed photo"], ["replay_video", "Video replay on a screen"], ["poor_lighting", "Poor lighting"]];

/* One overlay, reused: intro -> camera -> checking -> result. Resolves true only on a server pass. */
function faceCheck({ purpose = "visit", visitId = null, consent = false, title = "Verify it's you" } = {}) {
  return new Promise((resolve) => {
    let stream = null, done = false, scenario = "";
    const root = document.createElement("div");
    root.className = "face-overlay";
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-modal", "true");
    root.setAttribute("aria-labelledby", "faceTitle");
    root.innerHTML = `<div class="face-sheet"><div class="face-head"><b id="faceTitle">${esc(title)}</b>
        <button class="btn ghost sm" id="faceClose" aria-label="Close">${ic("x")}</button></div><div id="faceBody"></div>
        <p class="sr-only" id="faceLive" aria-live="assertive"></p></div>`;
    document.body.appendChild(root);
    document.body.classList.add("face-open");
    const body = () => root.querySelector("#faceBody");
    const say = (t) => { root.querySelector("#faceLive").textContent = t; };
    const stop = () => { if (stream) stream.getTracks().forEach((t) => t.stop()); stream = null; };
    const finish = (ok) => { if (done) return; done = true; stop(); root.remove(); document.body.classList.remove("face-open"); resolve(ok); };
    root.querySelector("#faceClose").onclick = () => finish(false);

    const panel = (icon, cls, head, text, buttons = "") => {
      stop();
      body().innerHTML = `<div class="face-msg ${cls}"><div class="face-ico">${ic(icon, "lg")}</div><h3>${esc(head)}</h3><p>${text}</p><div class="face-actions">${buttons}</div></div>`;
      say(`${head}. ${text.replace(/<[^>]+>/g, "")}`);
      wireButtons();
    };
    const wireButtons = () => {
      const t = body().querySelector("[data-f=retry]"); if (t) t.onclick = () => openCamera();
      const h = body().querySelector("[data-f=help]"); if (h) h.onclick = () => askAlternative(h.dataset.reason || "other");
      const c = body().querySelector("[data-f=close]"); if (c) c.onclick = () => finish(false);
    };
    const helpBtn = (reason) => `<button class="btn sm" data-f="help" data-reason="${reason}">${ic("chat")} Ask for another way to verify</button>`;

    const intro = () => {
      body().innerHTML = `<div class="face-msg"><div class="face-ico">${ic("scan", "lg")}</div>
        <h3>${purpose === "enroll" ? "Take a live selfie" : "Quick identity check"}</h3>
        <p>${purpose === "enroll" ? "This becomes your verified face. Before every home visit you'll do a 5-second check against it, so patients know it's really you."
          : "Before you start this journey, confirm it's you. We check that you're a live person and compare you with your verified face."}</p>
        <ul class="face-tips"><li>${ic("sun")} Face a light, not a window behind you</li><li>${ic("user")} Remove sunglasses or a mask</li><li>${ic("shield")} No photo from this check is kept. Only the result and time are saved.</li></ul>
        <div class="face-actions"><button class="btn primary" data-f="go">${ic("camera")} Open camera</button>${purpose === "visit" ? helpBtn("accessibility") : ""}</div></div>`;
      body().querySelector("[data-f=go]").onclick = () => openCamera();
      wireButtons();
    };

    const askAlternative = (reason) => guard(async () => {
      await post("/api/provider/face/alternative", { visit_id: visitId, reason });
      panel("chat", "", "Request sent", "Triyana's identity team will contact you to verify you another way, for example a video call with your ID. Your journey unlocks for this visit once they approve it.", `<button class="btn primary" data-f="close">OK</button>`);
    });

    const cameraError = (e) => {
      const name = e && e.name;
      if (name === "NotAllowedError" || name === "SecurityError") {
        panel("camOff", "warn", "Camera access is blocked", "Allow the camera for this site in your browser or phone settings (tap the lock or camera icon in the address bar), then try again. If you can't use a camera, ask for another way to verify.", `<button class="btn primary" data-f="retry">Try again</button>${helpBtn("camera_unavailable")}`);
      } else if (name === "NotFoundError" || name === "OverconstrainedError") {
        panel("camOff", "warn", "No camera found", "This device has no front camera we can use. Use your phone, or ask for another way to verify.", `<button class="btn primary" data-f="retry">Try again</button>${helpBtn("camera_unavailable")}`);
      } else {
        panel("camOff", "warn", "The camera didn't start", "Close other apps using the camera and try again.", `<button class="btn primary" data-f="retry">Try again</button>${helpBtn("camera_unavailable")}`);
      }
    };

    const openCamera = async () => {
      stop();
      if (!navigator.mediaDevices?.getUserMedia) return cameraError({ name: "NotFoundError" });
      body().innerHTML = `<div class="face-cam"><video id="faceVideo" playsinline muted autoplay></video><div class="face-oval"></div>
          <div class="face-prompt" id="facePrompt">Starting camera…</div></div>
        <div class="face-under"><div class="face-steps" id="faceSteps"></div><div id="faceDemo"></div>
        <button class="btn primary block" id="faceGo" disabled>${ic("scan")} I'm ready</button></div>`;
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } }, audio: false });
      } catch (e) { return cameraError(e); }
      if (done) return stop();
      const v = root.querySelector("#faceVideo");
      v.srcObject = stream;
      await v.play().catch(() => {});
      root.querySelector("#facePrompt").textContent = "Fit your face inside the oval";
      say("Camera on. Fit your face inside the oval, then tap I'm ready.");
      if (state.accounts.length) { // demo site only: lets testers try the failure cases (can only make a check fail)
        root.querySelector("#faceDemo").innerHTML = `<details class="face-demo"><summary>Demo: test a failure case</summary>${FACE_DEMO.map(([k, l]) => `<label><input type="radio" name="faceScn" value="${k}" ${k === scenario ? "checked" : ""}> ${esc(l)}</label>`).join("")}</details>`;
        root.querySelectorAll("[name=faceScn]").forEach((r) => (r.onchange = () => (scenario = r.value)));
      }
      const go = root.querySelector("#faceGo");
      go.disabled = false;
      go.onclick = () => run(v);
    };

    const grab = (v) => {
      const c = document.createElement("canvas");
      c.width = 320; c.height = 240;
      const vw = v.videoWidth || 640, vh = v.videoHeight || 480;
      const s = Math.max(320 / vw, 240 / vh);
      const ctx = c.getContext("2d");
      ctx.translate(320, 0); ctx.scale(-1, 1); // mirror, like the preview
      ctx.drawImage(v, (320 - vw * s) / 2, (240 - vh * s) / 2, vw * s, vh * s);
      return c.toDataURL("image/jpeg", 0.72);
    };

    const run = async (v) => {
      const go = root.querySelector("#faceGo");
      go.disabled = true;
      let ch;
      try {
        ch = await post("/api/provider/face/challenges", { purpose, visit_id: visitId, consent });
      } catch (e) { return serverError(e); }
      const prompt = root.querySelector("#facePrompt");
      prompt.textContent = ch.prompt; prompt.classList.add("on");
      say(ch.prompt);
      root.querySelector("#faceSteps").innerHTML = Array.from({ length: FACE_FRAME_COUNT }, () => "<i></i>").join("");
      const frames = [];
      await new Promise((r) => setTimeout(r, 700));
      for (let i = 0; i < FACE_FRAME_COUNT; i++) {
        frames.push(grab(v));
        root.querySelectorAll("#faceSteps i")[i]?.classList.add("on");
        await new Promise((r) => setTimeout(r, FACE_FRAME_GAP_MS));
      }
      stop();
      body().innerHTML = `<div class="face-msg"><div class="face-spin"></div><h3>Checking…</h3><p>Confirming you're live and matching your verified face.</p></div>`;
      say("Checking");
      let res;
      try {
        res = await post(`/api/provider/face/challenges/${ch.id}/submit`, { nonce: ch.nonce, frames, demo_scenario: scenario || null });
      } catch (e) { return serverError(e); }
      result(res);
    };

    const result = (r) => {
      if (r.status === "passed") {
        body().innerHTML = `<div class="face-msg good"><div class="face-ico">${ic("check", "lg")}</div><h3>${purpose === "enroll" ? "Face enrolled" : "Identity verified"}</h3>
          <p>${purpose === "enroll" ? (r.enrollment?.status === "active" ? "You're all set." : "Triyana will approve it with the rest of your checks.") : "Your patient has been told. Starting your journey…"}</p></div>`;
        say(purpose === "enroll" ? "Face enrolled" : "Identity verified");
        try { navigator.vibrate?.(120); } catch {}
        setTimeout(() => finish(true), 1100);
      } else if (r.locked || r.status === "spoof") {
        locked();
      } else if (r.status === "poor_quality") {
        panel("sun", "warn", "Let's try that again", esc(r.reason) + " This doesn't count as a failed attempt.", `<button class="btn primary" data-f="retry">Try again</button>`);
      } else {
        const left = r.attempts_left;
        panel("alert", "bad", "We couldn't verify you", `${esc(r.reason)}${left != null ? ` <b>${left} attempt${left === 1 ? "" : "s"} left</b> before your account is locked for review.` : ""}`,
          `<button class="btn primary" data-f="retry">Try again</button>${purpose === "visit" ? helpBtn("keeps_failing") : ""}`);
      }
    };

    const locked = () => panel("lock", "bad", "Journey locked", "We couldn't confirm your identity, so starting journeys is locked. Triyana's security team has been notified and will contact you to verify you. You can't bypass this from the app.", `<button class="btn primary" data-f="close">OK</button>`);

    const serverError = (e) => {
      const code = e.detail?.code;
      if (code === "identity_locked") return locked();
      if (code === "challenge_expired" || code === "challenge_used" || code === "bad_challenge") return panel("clock", "warn", "That took too long", "The check timed out or the connection dropped. Nothing was saved. Try again.", `<button class="btn primary" data-f="retry">Try again</button>`);
      if (code === "face_enrollment_required") return panel("scan", "warn", "Enrol your face first", esc(e.message), `<button class="btn primary" data-f="close">OK</button>`);
      if (code === "face_partner_unavailable") return panel("wifi", "warn", "Identity service unavailable", esc(e.message), `<button class="btn primary" data-f="retry">Try again</button>`);
      if (!e.status) return panel("wifi", "warn", "No connection", "We couldn't reach Triyana. Check your signal and try again. Your journey stays locked until a check passes.", `<button class="btn primary" data-f="retry">Try again</button>`);
      panel("alert", "warn", "Something went wrong", esc(e.message), `<button class="btn primary" data-f="retry">Try again</button>`);
    };

    intro();
  });
}

/* Start journey for a home visit: the face check is always in the way, and the server enforces it. */
async function faceStartJourney(visitId) {
  return guard(async () => {
    const st = await api(`/api/provider/visits/${visitId}/identity`);
    if (!st.verified && !(await faceCheck({ purpose: "visit", visitId, title: "Verify it's you to start" }))) return;
    await post(`/api/provider/visits/${visitId}/depart`);
    toast("Identity verified. Navigating to your patient.", "check");
    navScreen();
  });
}

/* Registration (and re-enrolment): biometric consent, then a live capture. */
async function faceEnroll(after) {
  const f = await api("/api/provider/face");
  const root = document.createElement("div");
  root.className = "face-overlay";
  root.setAttribute("role", "dialog");
  root.setAttribute("aria-modal", "true");
  root.innerHTML = `<div class="face-sheet"><div class="face-head"><b>Face verification consent</b><button class="btn ghost sm" data-x aria-label="Close">${ic("x")}</button></div>
    <div class="face-msg"><div class="face-ico">${ic("shield", "lg")}</div><p class="small" style="text-align:left">${esc(f.consent_text)}</p>
    <label class="check" style="text-align:left"><input type="checkbox" id="faceConsent"> <span>I agree to biometric face verification (version ${esc(f.consent_version)}).</span></label>
    <div class="face-actions"><button class="btn primary" id="faceAgree" disabled>Continue</button><button class="btn sm" data-x>Not now</button></div></div></div>`;
  document.body.appendChild(root);
  const close = () => root.remove();
  root.querySelectorAll("[data-x]").forEach((b) => (b.onclick = close));
  root.querySelector("#faceConsent").onchange = (e) => (root.querySelector("#faceAgree").disabled = !e.target.checked);
  root.querySelector("#faceAgree").onclick = async () => {
    close();
    if (await faceCheck({ purpose: "enroll", consent: true, title: "Enrol your face" })) { toast("Face enrolled", "check"); after && after(); }
  };
}

/* Dashboard banner: doctors without an active face enrolment (or locked out) can't take visits. */
async function faceBanner() {
  const box = $("#faceBanner"); if (!box || state.role !== "doctor") return;
  let f; try { f = await api("/api/provider/face"); } catch { return; }
  if (!$("#faceBanner")) return;
  if (f.locked) {
    box.innerHTML = `<div class="card verify-card bad"><div class="row" style="gap:12px;align-items:flex-start">${ic("lock", "lg")}<div class="grow"><h3 style="margin:0 0 4px">Journeys are locked</h3><p class="small muted" style="margin:0">Your identity needs to be confirmed by Triyana's security team before you can start a journey. They've been notified and will contact you.</p></div></div></div>`;
  } else if (!f.active) {
    const pending = f.enrollment && f.enrollment.status === "pending_review";
    box.innerHTML = `<div class="card verify-card"><div class="row" style="gap:12px;align-items:flex-start">${ic("scan", "lg")}<div class="grow"><h3 style="margin:0 0 4px">${pending ? "Face enrolment in review" : "Enrol your face to take visits"}</h3>
      <p class="small muted" style="margin:0">${pending ? "Triyana is reviewing your new verified face. You can take home visits once it's approved." : "Every home visit starts with a quick live face check, so patients know it's you. Enrol once to get started."}</p>
      ${pending ? "" : `<button class="btn primary sm" id="faceEnrolBtn" style="margin-top:10px">${ic("scan")} Enrol my face</button>`}</div></div></div>`;
    const b = $("#faceEnrolBtn"); if (b) b.onclick = () => faceEnroll(() => SCREENS.dash());
  } else box.innerHTML = "";
}
