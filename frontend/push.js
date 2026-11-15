/* Push alerts: lets doctors and partners hear new requests with the phone locked (and patients hear
   "Doctor on the way"). Uses the browser's own Web Push, so no app store build is needed.
   iPhone only allows it for apps added to the Home Screen (iOS 16.4+), so iPhone users get that hint. */
"use strict";

window.TriyanaPush = (() => {
  const SNOOZE_KEY = `triyana.${APP}.pushSnooze`;
  const supported = () => "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  const isIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const standalone = () => window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
  const fromB64 = (s) => { const b = atob((s + "===".slice((s.length + 3) % 4)).replace(/-/g, "+").replace(/_/g, "/")); return Uint8Array.from(b, (c) => c.charCodeAt(0)); };
  const sameKey = (a, b) => a && b && a.byteLength === b.byteLength && new Uint8Array(a).every((v, i) => v === b[i]);
  const authed = (token, path, body) => fetch(path, { method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` }, body: JSON.stringify(body || {}) });

  async function subscribe(token) {
    const reg = await navigator.serviceWorker.ready;
    const { public_key } = await (await fetch("/api/push/key")).json();
    const key = fromB64(public_key);
    let sub = await reg.pushManager.getSubscription();
    if (sub && !sameKey(sub.options && sub.options.applicationServerKey, key)) { await sub.unsubscribe(); sub = null; }
    if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
    const res = await authed(token, "/api/push/subscribe", sub.toJSON());
    if (!res.ok) throw new Error(((await res.json().catch(() => ({}))).detail || {}).message || "Couldn't turn on alerts.");
  }

  const BELL = '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg>';
  const css = document.createElement("style");
  css.textContent = `.push-banner{position:fixed;left:12px;right:12px;bottom:calc(76px + env(safe-area-inset-bottom));z-index:60;max-width:560px;margin:0 auto;
display:flex;gap:12px;align-items:center;background:var(--card,#fff);color:var(--text,inherit);border:1px solid var(--line,#e3e8e6);border-radius:16px;
padding:12px 14px;box-shadow:0 12px 32px rgba(0,0,0,.18)}.push-banner b{display:block;font-size:14px}.push-banner .tiny{display:block;margin-top:2px}
.push-ico{flex:none;width:36px;height:36px;border-radius:12px;display:grid;place-items:center;background:var(--brand-soft,#e6f4f1);color:var(--brand,#0b7a6b)}
.push-ico svg{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.push-actions{display:flex;flex-direction:column;gap:6px}@media(min-width:900px){.push-banner{bottom:20px}}`;
  document.head.appendChild(css);

  function hideBanner() { const b = document.getElementById("pushBanner"); if (b) b.remove(); }

  function banner(me) {
    hideBanner();
    try { if (+localStorage.getItem(SNOOZE_KEY) > Date.now()) return; } catch {}
    const provider = APP === "provider";
    const iosHint = isIOS() && !standalone();
    const el = document.createElement("div");
    el.id = "pushBanner"; el.className = "push-banner"; el.setAttribute("role", "dialog");
    el.innerHTML = `<div class="push-ico">${BELL}</div><div class="grow"><b>${provider ? "Get new requests with your phone locked" : "Know when your doctor is on the way"}</b>
      <span class="tiny muted">${iosHint ? `On iPhone: tap Share, then <b>Add to Home Screen</b>, and open ${provider ? PROVIDER_APP : "Triyana"} from there to turn on alerts.`
        : provider ? "Turn on alerts so a nearby patient's request rings even when the app is closed." : "We'll alert you when your doctor accepts, sets off and arrives."}</span></div>
      <div class="push-actions">${iosHint ? "" : `<button class="btn primary sm" id="pushOn">Turn on</button>`}<button class="btn ghost sm" id="pushLater">${iosHint ? "OK" : "Later"}</button></div>`;
    document.body.appendChild(el);
    $("#pushLater").onclick = () => { try { localStorage.setItem(SNOOZE_KEY, String(Date.now() + 3 * 864e5)); } catch {} hideBanner(); };
    if ($("#pushOn")) $("#pushOn").onclick = () => enable(true);
  }

  async function enable(fromBanner) {
    if (!supported()) { toast(isIOS() ? "Add Triyana to your Home Screen first, then turn on alerts there." : "This browser can't show alerts.", "alert"); return false; }
    const perm = await Notification.requestPermission();
    if (perm !== "granted") {
      hideBanner();
      toast(perm === "denied" ? "Alerts are blocked. Allow notifications for this site in your browser settings." : "Alerts not turned on.", "alert");
      return false;
    }
    try { await subscribe(state.token); hideBanner(); await authed(state.token, "/api/push/test"); toast("Alerts are on"); return true; }
    catch (e) { toast(e.message || "Couldn't turn on alerts.", "alert"); return false; }
  }

  async function afterSignIn(me) {
    hideBanner();
    if (!supported()) { if (isIOS() && !standalone() && APP === "provider") banner(me); return; }
    if (Notification.permission === "granted") { subscribe(state.token).catch(() => {}); return; }  // keeps the server's copy fresh
    if (Notification.permission === "default" && (APP === "provider" || me.role === "patient")) banner(me);
  }

  async function signOut(token) {
    hideBanner();
    if (!supported() || !token) return;
    try {
      const reg = await navigator.serviceWorker.getRegistration();
      const sub = reg && await reg.pushManager.getSubscription();
      if (sub) await authed(token, "/api/push/unsubscribe", { endpoint: sub.endpoint });
    } catch {}
  }

  /* Account tab: "Alerts on this phone" with a button to turn them on or send a test. */
  async function accountCard(box) {
    if (!box) return;
    const on = supported() && Notification.permission === "granted";
    const blocked = supported() && Notification.permission === "denied";
    const provider = APP === "provider";
    box.innerHTML = `<h3>Alerts on this phone</h3>
      <p class="small muted" style="margin:6px 0 10px">${!supported() ? (isIOS() ? `On iPhone, add ${provider ? PROVIDER_APP : "Triyana"} to your Home Screen (Share, then Add to Home Screen) and open it from there to get alerts.` : "This browser can't show alerts.")
        : on ? (provider ? "On. New requests ring here even when your phone is locked." : "On. We'll tell you when your doctor accepts, sets off and arrives.")
        : blocked ? "Blocked. Allow notifications for this site in your browser settings, then come back here."
        : (provider ? "Off. Turn on to hear new requests when the app is closed." : "Off. Turn on to hear when your doctor is on the way.")}</p>
      ${supported() && !blocked ? `<button class="btn sm" id="pushBtn">${on ? "Send a test alert" : "Turn on alerts"}</button>` : ""}`;
    const b = box.querySelector("#pushBtn");
    if (b) b.onclick = async () => {
      if (on) { try { await subscribe(state.token); await authed(state.token, "/api/push/test"); toast("Test alert sent"); } catch (e) { toast(e.message, "alert"); } }
      else if (await enable()) accountCard(box);
    };
  }

  return { afterSignIn, signOut, enable, supported, accountCard };
})();
