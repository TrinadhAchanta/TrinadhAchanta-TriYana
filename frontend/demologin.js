/* Demo site only: the shared Triyana demo login (server env TRIYANA_DEMO_LOGIN).
   After it is used once in any Triyana app, it is kept in this browser so every app on this site
   (Triyana, Heros, Pharmacy, Rider and /admin) signs in by itself. The server only accepts it in demo mode,
   so in live mode it simply fails and is forgotten. Sign out forgets it on this device. */
"use strict";
window.TriyanaDemoLogin = (() => {
  const KEY = "triyana.demoLogin";
  const get = () => { try { const v = JSON.parse(localStorage.getItem(KEY) || "null"); return v && v.email && v.password ? v : null; } catch { return null; } };
  const save = (email, password) => { try { localStorage.setItem(KEY, JSON.stringify({ email: String(email).trim(), password })); } catch {} };
  const forget = () => { try { localStorage.removeItem(KEY); } catch {} };
  /* Sign in with the saved demo login. Resolves to the server's reply, or null when there is nothing saved
     or it no longer works (then it is forgotten). */
  async function signIn(url, extra = {}) {
    const c = get(); if (!c) return null;
    try {
      const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...extra, email: c.email, password: c.password }) });
      const d = await r.json().catch(() => ({}));
      if (r.ok && d.demo_login && d.token) return d;
      if (r.status >= 400 && r.status < 500 && r.status !== 429) forget();
    } catch {}
    return null;
  }
  return { get, save, forget, signIn };
})();
