/* Triyana Home — premium client for the Prescription → Delivery journey (no build step). */
"use strict";

const APP = document.body.dataset.app || "patient"; // "patient" = Triyana, "provider" = Triyana Partner
const state = { token: null, role: null, name: "", unread: 0, tab: null, ctx: {}, accounts: [], currency: "INR", timers: [], cleanups: [] };
const TOKEN_KEY = `triyana.${APP}.token`;
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const view = () => $("#view");
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (n) => (n == null ? "—" : new Intl.NumberFormat(undefined, { style: "currency", currency: state.currency }).format(n));
const parseIso = (iso) => new Date(iso + (/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? "" : "Z"));
const TZ = "Asia/Kolkata"; // the demo city runs on India time, wherever the viewer is
const when = (iso) => (iso ? parseIso(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short", timeZone: TZ }) : "—");
const day = (iso) => (iso ? parseIso(iso).toLocaleDateString(undefined, { dateStyle: "medium", timeZone: TZ }) : "—");
const time = (iso) => (iso ? parseIso(iso).toLocaleTimeString(undefined, { timeStyle: "short", timeZone: TZ }) : "—");
const mins = (m) => (m == null ? "—" : m < 90 ? `${m} min` : `${Math.round(m / 60)} h`);
const initials = (s) => String(s || "?").replace(/^Dr\.?\s*/i, "").split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
const shortName = (s) => String(s || "").replace(" (Demo)", "");

/* --------------------------------------------------------------- icons */
const P = {
  logo: '<path d="M12 21s-7-4.5-7-11a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 6.5-7 11-7 11z"/><path d="M12 9v5M9.5 11.5h5"/>',
  home: '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>',
  rx: '<path d="M7 3h7a5 5 0 0 1 0 10H7z"/><path d="M7 13v8M12 13l7 8M19 13l-7 8"/>',
  cart: '<circle cx="9" cy="20" r="1.5"/><circle cx="18" cy="20" r="1.5"/><path d="M2 3h3l2.7 12.2a2 2 0 0 0 2 1.6h7.7a2 2 0 0 0 2-1.5L21 8H6"/>',
  store: '<path d="M3 9l1.5-5h15L21 9"/><path d="M4 9v11h16V9"/><path d="M3 9a3 3 0 0 0 6 0 3 3 0 0 0 6 0 3 3 0 0 0 6 0"/><path d="M10 20v-5h4v5"/>',
  truck: '<path d="M1 5h13v11H1z"/><path d="M14 9h4l4 4v3h-8"/><circle cx="5.5" cy="18.5" r="1.8"/><circle cx="17.5" cy="18.5" r="1.8"/>',
  pills: '<rect x="3" y="9" width="12" height="6" rx="3" transform="rotate(-45 9 12)"/><path d="M7.8 7.8l4.4 4.4"/><circle cx="17.5" cy="16.5" r="4"/><path d="M14.7 19.3l5.6-5.6"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 3v4M16 3v4"/>',
  file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
  chat: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>',
  inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5h13L22 12v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6z"/>',
  check: '<path d="M20 6L9 17l-5-5"/>',
  shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
  badge: '<path d="M12 2l2.4 2.1 3.2-.3.8 3.1 2.8 1.6-1.2 3 1.2 3-2.8 1.6-.8 3.1-3.2-.3L12 22l-2.4-2.1-3.2.3-.8-3.1L2.8 15.5l1.2-3-1.2-3 2.8-1.6.8-3.1 3.2.3z"/><path d="M8.5 12l2.3 2.3 4.7-4.6"/>',
  pin: '<path d="M12 22s7-6.2 7-12a7 7 0 1 0-14 0c0 5.8 7 12 7 12z"/><circle cx="12" cy="10" r="2.5"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  bag: '<path d="M5 8h14l-1 13H6z"/><path d="M9 8V6a3 3 0 0 1 6 0v2"/>',
  card: '<rect x="2" y="5" width="20" height="14" rx="3"/><path d="M2 10h20M6 15h4"/>',
  phone: '<rect x="6" y="2" width="12" height="20" rx="3"/><path d="M11 18h2"/>',
  wallet: '<path d="M3 7a2 2 0 0 1 2-2h13v4"/><path d="M3 7v11a2 2 0 0 0 2 2h15V9H5a2 2 0 0 1-2-2z"/><circle cx="16" cy="14.5" r="1.2"/>',
  bolt: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
  snow: '<path d="M12 2v20M4.9 6l14.2 12M19.1 6L4.9 18M9 4l3 2 3-2M9 20l3-2 3 2"/>',
  id: '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="11" r="2"/><path d="M6 16c.6-1.5 1.7-2.2 3-2.2s2.4.7 3 2.2M14 10h4M14 13h3"/>',
  x: '<path d="M18 6L6 18M6 6l12 12"/>',
  minus: '<path d="M5 12h14"/>',
  later: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5h4"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  thermo: '<path d="M14 14.8V4a2 2 0 0 0-4 0v10.8a4 4 0 1 0 4 0z"/><path d="M12 10v7"/>',
  heart: '<path d="M20.8 5.6a5.5 5.5 0 0 0-7.8 0L12 6.6l-1-1a5.5 5.5 0 0 0-7.8 7.8L12 22l8.8-8.6a5.5 5.5 0 0 0 0-7.8z"/>',
  notes: '<path d="M6 3h9l4 4v14H6z"/><path d="M14 3v5h5M9 12h7M9 16h7M9 8h2"/>',
  stethoscope: '<path d="M5 3v6a5 5 0 0 0 10 0V3"/><path d="M10 14v2a5 5 0 0 0 10 0v-3"/><circle cx="20" cy="11" r="2"/>',
  alert: '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  drone: '<circle cx="5" cy="5" r="2.5"/><circle cx="19" cy="5" r="2.5"/><circle cx="5" cy="19" r="2.5"/><circle cx="19" cy="19" r="2.5"/><path d="M7 7l3 3M17 7l-3 3M7 17l3-3M17 17l-3-3"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/>',
  sign: '<path d="M3 17c3-3 5-8 7-8s-1 8 2 8 3-4 5-4 2 3 4 3"/><path d="M3 21h18"/>',
  audit: '<path d="M9 3h6l1 2h3v16H5V5h3z"/><path d="M9 12l2 2 4-4"/>',
  lock: '<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
};
const ic = (n, cls = "") => `<svg class="i ${cls}" viewBox="0 0 24 24" aria-hidden="true">${P[n] || ""}</svg>`;

let toastTimer;
function toast(msg, icon = "check") {
  const t = $("#toast"); t.innerHTML = `${ic(icon)}<span>${esc(msg)}</span>`; t.classList.add("show");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), 4200);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    method: opts.method || "GET",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${state.token}`, "X-Triyana-App": APP },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data.detail || {};
    const msg = typeof d === "string" ? d : d.message || (Array.isArray(d) ? "Please check the form and try again." : "Something went wrong.");
    const err = new Error(msg); err.detail = d; err.status = res.status; throw err;
  }
  return data;
}
const post = (p, body) => api(p, { method: "POST", body });
const put = (p, body) => api(p, { method: "PUT", body });
async function guard(fn) { try { await fn(); } catch (e) { toast(e.message, "alert"); } }

const empty = (icon, title, body = "") => `<div class="card empty"><div class="ico">${ic(icon)}</div><h3>${esc(title)}</h3><p class="small">${esc(body)}</p></div>`;
const pageHead = (title, sub = "", right = "") => `<div class="page-head"><div><h1>${esc(title)}</h1>${sub ? `<p>${sub}</p>` : ""}</div>${right}</div>`;
const pillClass = (i) => ["", "c2", "c3", "c4"][i % 4];
const schedBadge = (s) => (!s ? "" : `<span class="badge ${s.code === "X" ? "bad" : s.code === "H1" ? "warn" : s.code === "OTC" ? "" : "info"}" title="${esc(s.note)}">${s.code === "OTC" ? "OTC" : esc(s.label)}</span>`);
const regLine = (d) => [d.qualification, d.license_no ? `Reg. No. ${d.license_no}` : "", d.medical_council].filter(Boolean).map(esc).join(" · ");
const miniPill = (i, off = false) => `<div class="pill sm ${off ? "off" : pillClass(i)}">${ic("pills")}</div>`;

/* ---------------------------------------------------------------- shell */
const TABS = {
  patient: [["home", "Home", "home"], ["book", "Book a doctor", "stethoscope"], ["rx", "Prescription", "rx"], ["cart", "Cart", "cart"], ["pharmacies", "Pharmacies", "store", "desktop"], ["orders", "Tracking", "truck"], ["meds", "My Medicines", "pills"], ["privacy", "Privacy & consent", "shield", "desktop"]],
  doctor: [["visits", "Home visits", "calendar"], ["availability", "My hours", "clock"], ["prescriptions", "Prescriptions", "file"], ["clarifications", "Clarifications", "chat"]],
  pharmacist: [["queue", "Order queue", "inbox"], ["shipments", "Hospital drones", "drone"]],
  courier: [["dash", "Dashboard", "bolt"], ["deliveries", "Deliveries", "truck"]],
  hospital: [["shipments", "Deliveries", "drone"], ["send", "Send or request", "bolt"], ["coverage", "Coverage", "pin"]],
};
if (APP === "provider") TABS.doctor.unshift(["dash", "Dashboard", "bolt"]);
const SHORT = { Dashboard: "Home", "Book a doctor": "Doctor", Tracking: "Track", "My Medicines": "Medicines", "Home visits": "Visits", "My hours": "Hours", "Order queue": "Orders", Prescription: "Rx", Prescriptions: "Rx", Clarifications: "Questions", "Hospital drones": "Drones", "Send or request": "Send" };
const GREETING = () => { const h = new Date().getHours(); return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening"; };

async function boot() {
  ["#markA", "#markB"].forEach((s) => ($(s).innerHTML = ic("logo")));
  $("#flagIco").innerHTML = ic("info");
  const r = await fetch(`/api/demo/accounts?app=${APP}`);
  state.accounts = await r.json();
  const opts = state.accounts.map((a) => `<option value="${esc(a.token)}">${esc(a.label)}</option>`).join("");
  $("#account").innerHTML = opts; $("#accountMobile").innerHTML = opts;
  ["#account", "#accountMobile"].forEach((s) => ($(s).onchange = (e) => signIn(e.target.value)));
  $("#reset").onclick = () => guard(async () => { await fetch("/api/demo/reset", { method: "POST" }); toast("Demo data restored"); signIn(state.token); });
  $$(".sign-out").forEach((b) => (b.onclick = signOut));
  if (APP === "patient") setupYana();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  let saved = null; try { saved = localStorage.getItem(TOKEN_KEY); } catch {}
  if (saved && state.accounts.some((a) => a.token === saved)) signIn(saved); else loginScreen();
}

function stopLive() {
  state.timers.forEach(clearInterval); state.timers = [];
  state.cleanups.forEach((f) => { try { f(); } catch {} }); state.cleanups = [];
}

/* Each app has its own sign-in: patients use Triyana, providers use Triyana Partner. */
function loginScreen() {
  stopLive();
  document.body.classList.add("signed-out");
  const partner = APP === "provider";
  const groups = {};
  state.accounts.forEach((a) => {
    const k = partner ? (a.label.split("·")[1] || "").trim().split(" ")[0] || "account" : "patient";
    (groups[k] = groups[k] || []).push(a);
  });
  const icon = { doctor: "stethoscope", courier: "truck", pharmacist: "store", phlebotomist: "flask", patient: "user" };
  $("#login").innerHTML = `<div class="login-card">
      <div class="brand"><div class="mark">${ic("logo")}</div><div><b>${partner ? "Triyana Partner" : "Triyana"}</b><small>${partner ? "For doctors, couriers, pharmacists & sample collectors" : "Home healthcare"}</small></div></div>
      <h1>${partner ? "Go online. Get nearby visits and deliveries." : "Doctors, medicines and care, at your door."}</h1>
      <p class="muted">${partner ? "Accept requests from patients near you and navigate there turn by turn." : "Book a verified doctor now or for later, get your prescription, and track your medicines live."}</p>
      ${Object.entries(groups).map(([g, list]) => `<div class="section-title">${partner ? `${esc(g)}s` : "Choose a demo account"}</div>
        <div class="login-list">${list.map((a) => `<button class="login-acc" data-token="${esc(a.token)}"><span class="avatar">${ic(icon[g] || "user")}</span><span class="grow"><b>${esc(a.label.split("·")[0].replace(/\s*\(.*\)/, ""))}</b><span class="tiny muted">${esc((a.label.split("·")[1] || "Patient").trim())}</span></span>${ic("arrow")}</button>`).join("")}</div>`).join("")}
      <div class="demo-flag">${ic("info")}<span>Demo · fictional people and data. ${partner ? `Patients use <a href="/">the Triyana app</a>.` : `Doctors and couriers use <a href="/provider">Triyana Partner</a>.`}</span></div>
    </div>`;
  $$("[data-token]").forEach((b) => (b.onclick = () => signIn(b.dataset.token)));
}

function signOut() {
  try { localStorage.removeItem(TOKEN_KEY); } catch {}
  state.token = null;
  $("#yanaPanel").classList.remove("open"); $("#yanaBtn").hidden = true;
  loginScreen();
}

async function signIn(token) {
  stopLive();
  document.body.classList.remove("signed-out");
  state.token = token;
  $("#account").value = token; $("#accountMobile").value = token;
  try { localStorage.setItem(TOKEN_KEY, token); } catch {}
  let me;
  try { me = await api("/api/me"); } catch (e) { toast(e.message, "alert"); return signOut(); }
  Object.assign(state, { role: me.role, name: me.name, unread: me.unread_notifications, ctx: {}, hospitalId: me.hospital_id });
  $("#yanaBtn").hidden = me.role !== "patient";
  $("#yanaPanel").classList.remove("open");
  if (me.role === "patient") {
    const c = await api("/api/consents");
    if (!c.consents.care) { state.tab = null; renderNav(); return consentScreen(); }
  }
  go(TABS[me.role][0][0]);
}

function renderNav() {
  const tabs = TABS[state.role];
  $("#sideNav").innerHTML = tabs.map(([k, l, i]) => `<button class="nav-item ${k === state.tab ? "active" : ""}" data-tab="${k}">${ic(i)}<span>${l}</span>${k === "home" && state.unread ? `<span class="dot">${state.unread}</span>` : ""}</button>`).join("");
  $("#bottomNav").innerHTML = tabs.filter((t) => t[3] !== "desktop").map(([k, l, i]) => `<button class="${k === state.tab ? "active" : ""}" data-tab="${k}">${ic(i, "lg")}<span>${SHORT[l] || l}</span></button>`).join("");
  $$("[data-tab]").forEach((b) => (b.onclick = () => go(b.dataset.tab)));
}

function go(tab, ctx = {}) {
  clearInterval(state.poll);
  stopLive();
  state.tab = tab; Object.assign(state.ctx, ctx);
  renderNav();
  view().innerHTML = `<div class="skeleton" style="height:180px"></div><div class="skeleton"></div><div class="skeleton"></div>`;
  window.scrollTo({ top: 0 });
  guard(() => SCREENS[tab]());
}

/* --------------------------------------------------------------- patient */
async function latestCartId() {
  if (state.ctx.cartId) return state.ctx.cartId;
  const carts = await api("/api/patient/carts");
  state.ctx.cartId = carts[0]?.id || null;
  return state.ctx.cartId;
}
const SCREENS = {};

const OPEN_VISIT = ["requested", "accepted", "in_progress"];
const VISIT_LABEL = { requested: ["Waiting for doctor to confirm", "info", "clock"], accepted: ["Confirmed", "good", "check"], in_progress: ["Doctor is with you", "warn", "stethoscope"], completed: ["Completed", "brand", "check"], cancelled: ["Cancelled", "", "x"] };
const dateChip = (iso) => { const d = parseIso(iso); return `<div class="date-chip"><b>${d.toLocaleDateString("en-IN", { day: "numeric", timeZone: TZ })}</b><span>${d.toLocaleDateString(undefined, { month: "short", timeZone: TZ })}</span></div>`; };
const stars = (d) => `<span class="stars">★ ${d.rating.toFixed(1)}</span> <span class="muted">(${d.rating_count})</span>`;

function visitCard(v) {
  const [label, cls, icon] = VISIT_LABEL[v.status] || [v.status, "", "info"];
  return `<article class="card visit-card"><div class="card-head"><div class="when">${dateChip(v.scheduled_for)}<div>
      <h3>${v.doctor ? `${esc(v.doctor.name)} ${v.doctor.license_verified ? `<span class="verified" title="Verified licence">${ic("badge")}</span>` : ""}` : "Finding the nearest doctor…"}</h3>
      <div class="meta">${v.doctor ? `<span>${ic("stethoscope")} ${esc(v.doctor.specialty)}</span>` : `<span>${ic("bolt")} Doctor now</span>`}<span>${ic("clock")} ${when(v.scheduled_for)}</span>${v.follow_up_of ? `<span class="badge premium">${ic("later")} Follow-up</span>` : ""}</div></div></div>
      <span class="badge ${cls}">${ic(icon)} ${label}</span></div>
    <div class="instructions"><b>Reason:</b> ${esc(v.reason)}</div>
    <div class="row between small" style="margin-top:10px"><span class="muted">${ic("pin")} ${esc(v.address)}</span><span><b>${money(v.fee)}</b> <span class="muted">pay after the visit</span></span></div>
    <div class="actions-bar">${v.status === "requested" && v.on_demand || v.status === "accepted" ? `<button class="btn primary sm" data-live-visit="${v.id}">${ic("pin")} ${v.on_demand ? "Track live" : "Live map"}</button>` : ""}
    ${v.can_cancel ? `<button class="btn ghost sm danger" data-cancel="${v.id}">${ic("x")} Cancel booking</button>` : ""}</div></article>`;
}
function wireCancel(after) {
  $$("[data-live-visit]").forEach((b) => (b.onclick = () => liveScreen("visit", +b.dataset.liveVisit)));
  $$("[data-cancel]").forEach((b) => (b.onclick = () => guard(async () => {
    if (!confirm("Cancel this home visit?")) return;
    await post(`/api/patient/visits/${b.dataset.cancel}/cancel`); toast("Booking cancelled"); after();
  })));
}

SCREENS.home = async () => {
  const [notes, dash, visits] = await Promise.all([api("/api/notifications"), api("/api/patient/medicines"), api("/api/patient/visits")]);
  const ready = notes.find((n) => n.link.startsWith("cart:") && !n.read);
  const active = dash.active_orders[0];
  const upcoming = visits.filter((v) => OPEN_VISIT.includes(v.status)).sort((a, b) => a.scheduled_for.localeCompare(b.scheduled_for));
  const past = visits.filter((v) => v.status === "completed");
  const first = state.name.split(" ")[0];
  const activeRx = dash.prescriptions.filter((p) => p.status === "signed");
  const bookBtn = (cls = "primary") => `<button class="btn ${cls}" data-go="book">${ic("stethoscope")} Book a home visit</button>`;
  let hero;
  if (ready) hero = `<h1>Your prescription is ready</h1><p>Your doctor has signed it. Review your medicines, choose what you'd like to order, and we'll match you with the best licensed pharmacy nearby.</p>
        <div class="actions"><button class="btn primary" id="openCart">${ic("cart")} Review my medicines</button><button class="btn" id="openRx">${ic("rx")} View prescription</button></div>`;
  else if (active) hero = `<h1>${esc(active.status_label)}</h1><p>Order ${esc(active.order_no)} from ${esc(shortName(active.pharmacy.name))}.</p>
        <div class="actions"><button class="btn primary" data-go="orders">${ic("truck")} Track my order</button>${bookBtn("")}</div>`;
  else if (upcoming.length) hero = `<h1>${upcoming[0].status === "requested" ? "Your visit request is with the doctor" : upcoming[0].status === "accepted" ? "Your doctor is confirmed" : "Your doctor is with you"}</h1>
        <p>${esc(upcoming[0].doctor.name)} · ${when(upcoming[0].scheduled_for)}. After the visit, your prescription and medicine cart appear here automatically.</p>
        <div class="actions">${bookBtn("")}</div>`;
  else hero = `<h1>Need a doctor at home?</h1><p>Book a verified doctor near you in under a minute. They visit you at home, prescribe, and your medicines are delivered to your door.</p>
        <div class="actions">${bookBtn()}<button class="btn" data-go="meds">${ic("pills")} My Medicines</button></div>`;
  const showCta = ready || active;
  view().innerHTML = `
    <section class="hero home-hero"><div class="eyebrow">${GREETING()}, ${esc(first)}</div>${hero}
      <div class="stats"><div class="stat"><b>${upcoming.length}</b><span>Upcoming visits</span></div>
        <div class="stat"><b>${activeRx.length}</b><span>Active prescriptions</span></div>
        <div class="stat"><b>${dash.active_orders.length}</b><span>Orders in progress</span></div></div>
    </section>
    <div id="liveSlot"></div>
    ${servicesHTML()}
    ${upcoming.length ? `<div class="section-title">Your upcoming visit${upcoming.length > 1 ? "s" : ""}</div>${upcoming.map(visitCard).join("")}` : ""}
    ${past.length ? `<div class="section-title">Visit history</div>${past.slice(0, 5).map(pastVisitCard).join("")}` : ""}
    <div class="section-title">Notifications</div>
    <div class="card">${notes.length ? notes.slice(0, 8).map((n) => `
      <div class="list-item"><div class="avatar">${ic(n.link.startsWith("order") ? "truck" : n.link.startsWith("cart") ? "rx" : n.link.startsWith("visit") ? "stethoscope" : "info")}</div>
        <div class="grow"><div class="row between"><b>${esc(n.title)}</b><span class="tiny muted">${when(n.at)}</span></div>
        <div class="small muted">${esc(n.body)}</div></div></div>`).join("") : `<p class="muted small" style="margin:0">You're all caught up.</p>`}</div>`;
  $$("[data-go]").forEach((b) => (b.onclick = () => go(b.dataset.go)));
  wireServices();
  wireCancel(() => SCREENS.home());
  $$("[data-vnotes]").forEach((b) => (b.onclick = () => guard(() => patientNotesScreen(+b.dataset.vnotes))));
  patientLiveBanner(visits, dash.active_orders);
  if (ready) {
    const markRead = () => post(`/api/notifications/${ready.id}/read`).catch(() => {});
    $("#openCart").onclick = () => { markRead(); state.unread = Math.max(0, state.unread - 1); go("cart", { cartId: +ready.link.split(":")[1] }); };
    $("#openRx").onclick = () => { markRead(); go("rx"); };
  }
};

const REASONS = [["Fever or cold", "bolt"], ["General check-up", "stethoscope"], ["Child is unwell", "user"], ["Elderly parent care", "shield"], ["Joint or back pain", "pin"], ["Follow-up visit", "calendar"]];
const keyOf = (d) => d.toLocaleDateString("en-CA", { timeZone: TZ });
const dayKey = (iso) => keyOf(parseIso(iso));
function dayLabel(iso) {
  const k = dayKey(iso);
  if (k === keyOf(new Date())) return "Today";
  if (k === keyOf(new Date(Date.now() + 864e5))) return "Tomorrow";
  return parseIso(iso).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", timeZone: TZ });
}

const FOLLOW_UP = "Follow-up visit";
const hourIso = (date, h) => `${date}T${String(h).padStart(2, "0")}:00:00+05:30`;
function dateLabel(date) { return dayLabel(parseIso(hourIso(date, 12)).toISOString().replace("Z", "")); }

SCREENS.book = async () => {
  const preset = state.ctx.followUp; state.ctx.followUp = false;
  const [near, visits, fu] = await Promise.all([api("/api/doctors"), api("/api/patient/visits"), api("/api/patient/follow-up")]);
  const docs = near.doctors;
  // mode: "asap" = whoever is free soonest, "any" = nearest doctor free at my time, "doctor" = a specific doctor's slot
  const b = { reason: preset ? FOLLOW_UP : "", details: "", mode: "any", doctor: null, day: null, slot: null, address: near.address };
  let slots = [];
  const loadSlots = async () => {
    slots = await api(`/api/visit-slots${b.mode === "doctor" ? `?doctor_id=${b.doctor}` : ""}`);
    if (!slots.includes(b.slot)) b.slot = null;
    const days = [...new Set(slots.map(dayKey))];
    if (b.slot) b.day = dayKey(b.slot);
    if (!days.includes(b.day)) b.day = days[0] || null;
  };
  const pickDoctor = async (id, slot = null) => { b.mode = "doctor"; b.doctor = id; b.slot = slot; await loadSlots(); };
  const prevDoc = fu.doctor;
  const isFollowUp = () => b.reason === FOLLOW_UP && fu.previous_visit;
  // Suggest the doctor from last time straight away when they can come soon.
  const suggestPrevious = async () => { if (isFollowUp() && fu.available_soon && b.mode === "any" && !b.slot) await pickDoctor(prevDoc.id, fu.next_slot); };
  await loadSlots();
  await suggestPrevious();
  const minFee = Math.min(...docs.map((d) => d.visit_fee));
  const chosen = () => (b.mode === "doctor" ? docs.find((d) => d.id === b.doctor) : b.mode === "asap" ? near.soonest?.doctor : null);
  const ready = () => b.reason && (b.mode === "asap" ? near.soonest : b.slot) && b.address.trim();

  const followUpCard = () => {
    if (!isFollowUp()) return "";
    const pv = fu.previous_visit, d = prevDoc, alt = fu.alternative;
    const onPrev = b.mode === "doctor" && b.doctor === d.id;
    const head = `<div class="row" style="flex-wrap:nowrap;align-items:flex-start"><div class="avatar">${esc(initials(d.name))}</div><div class="grow">
        <div class="eyebrow-sm">Your doctor from last time</div><b>${esc(d.name)}</b> <span class="verified" title="Verified licence">${ic("badge")}</span>
        <div class="small muted">${esc(d.specialty)} · saw you on ${day(pv.date)} for ${esc(pv.reason)}</div></div></div>`;
    const altBtn = alt ? `<button class="btn sm" data-alt="1">${ic("bolt")} ${esc(alt.doctor.name)} · ${dayLabel(alt.slot)}, ${time(alt.slot)}</button>` : "";
    let body;
    if (fu.available_soon) {
      body = `<div class="notice good small">${ic("check")}<span><b>${esc(d.name)} is available.</b> Next free time: ${dayLabel(fu.next_slot)}, ${time(fu.next_slot)}. We've picked it for you, or choose another time below.</span></div>
        ${onPrev ? "" : `<div class="actions-bar"><button class="btn primary sm" data-prev="1">${ic("calendar")} Book ${esc(d.name)} again</button></div>`}`;
    } else if (fu.next_slot) {
      body = `<div class="notice warn small">${ic("clock")}<span><b>${esc(d.name)} isn't free in the next 24 hours.</b> You can book an appointment for their next opening, ${dayLabel(fu.next_slot)} at ${time(fu.next_slot)}${alt ? ", or see another verified doctor sooner" : ""}.</span></div>
        <div class="actions-bar"><button class="btn ${onPrev ? "" : "primary"} sm" data-prev="1">${ic("calendar")} Book appointment with ${esc(d.name)}</button>${altBtn}</div>`;
    } else {
      body = `<div class="notice warn small">${ic("clock")}<span><b>${esc(d.name)} has no openings in the next 7 days${fu.bookable ? "" : " in your area"}.</b>${alt ? " Another verified doctor can come sooner." : ""}</span></div>
        ${alt ? `<div class="actions-bar">${altBtn}</div>` : ""}`;
    }
    return `<div class="card follow-up">${head}${body}</div>`;
  };

  const render = () => {
    const days = [...new Set(slots.map(dayKey))];
    const daySlots = slots.filter((s) => dayKey(s) === b.day);
    const doc = chosen();
    const reasonText = [b.reason, b.details.trim()].filter(Boolean).join(" · ");
    const ok = ready();
    const upcoming = visits.filter((v) => OPEN_VISIT.includes(v.status));
    const soon = near.soonest;
    const timeCard = b.mode === "asap"
      ? (soon ? `<div class="notice info">${ic("bolt")}<span><b>Earliest time: ${dayLabel(soon.slot)}, ${time(soon.slot)}</b> with ${esc(soon.doctor.name)} (${soon.doctor.distance_km} km away). No need to pick a time.</span></div>`
        : `<p class="muted small">No doctor has a free time right now. Pick a doctor and a time instead.</p>`)
      : days.length ? `${b.mode === "doctor" && doc ? `<p class="small muted" style="margin:0 0 10px">${ic("clock")} Times ${esc(doc.name)} has opened for home visits.</p>` : ""}
          <div class="seg">${days.map((k) => `<button class="${k === b.day ? "on" : ""}" data-day="${esc(k)}">${dayLabel(slots.find((s) => dayKey(s) === k))}</button>`).join("")}</div>
          <div class="slot-grid">${daySlots.map((s) => `<button class="slot ${s === b.slot ? "on" : ""}" data-slot="${s}">${time(s)}</button>`).join("")}</div>`
      : `<p class="muted small">No free times in the next 7 days. Try another doctor.</p>`;
    view().innerHTML = pageHead(isFollowUp() ? "Book a follow-up visit" : "Book a doctor home visit", `${ic("pin")} Verified doctors near <b>${esc(near.address)}</b>`) + doctorNowBanner() + `
      <div class="split"><div>
        <div class="card"><div class="step-label"><span class="n">1</span><h3>What do you need help with?</h3></div>
          <div class="choice-grid">${REASONS.map(([r, i]) => `<button class="choice ${b.reason === r ? "on" : ""}" data-reason="${esc(r)}"><span class="ico">${ic(i)}</span><div><b>${r}</b></div></button>`).join("")}</div>
          <label class="field" style="margin-top:14px">Tell the doctor more (optional)<textarea id="details" rows="2" placeholder="For example: fever since yesterday, 101°F">${esc(b.details)}</textarea></label></div>

        <div class="card"><div class="step-label"><span class="n">2</span><h3>Choose a doctor</h3></div>
          ${followUpCard()}
          <div class="doc-list">
            <button class="doc any ${b.mode === "asap" ? "on" : ""}" data-mode="asap" ${soon ? "" : "disabled"}><div class="avatar">${ic("bolt")}</div><div class="info"><b>Whoever is available soonest</b>
              <div class="small muted">${soon ? `The first verified doctor who can come: ${esc(soon.doctor.name)}, ${dayLabel(soon.slot)} at ${time(soon.slot)}.` : "No doctor has a free time right now."}</div></div>
              <div class="fee"><span class="badge brand">Fastest</span></div></button>
            <button class="doc any ${b.mode === "any" ? "on" : ""}" data-mode="any"><div class="avatar">${ic("clock")}</div><div class="info"><b>Nearest doctor at a time I choose</b>
              <div class="small muted">Pick your time and we send the closest verified doctor who is free then${docs[0] ? `, usually ${esc(docs[0].name)} (${docs[0].distance_km} km away)` : ""}.</div></div></button>
            ${docs.map((d, n) => `<button class="doc ${b.mode === "doctor" && b.doctor === d.id ? "on" : ""}" data-doc="${d.id}"><div class="avatar">${esc(initials(d.name))}</div>
              <div class="info"><b>${esc(d.name)}</b> <span class="verified" title="Verified licence">${ic("badge")}</span>${prevDoc && prevDoc.id === d.id ? ` <span class="badge premium">Your doctor</span>` : ""}${n === 0 ? ` <span class="badge good">Nearest</span>` : ""}
                <div class="small muted">${esc(d.specialty)} · ${d.experience_years} yrs experience</div>
                <div class="tiny muted">${regLine(d)}</div>
                <div class="meta small"><span>${stars(d)}</span><span>${ic("pin")} ${d.distance_km} km · can arrive in ~${d.arrives_in_min} min</span><span>${ic("chat")} ${esc(d.languages.join(", "))}</span></div>
                <div class="tiny muted" style="margin-top:4px">${d.next_slot ? `Next free: ${dayLabel(d.next_slot)}, ${time(d.next_slot)}` : "No openings in the next 7 days"}</div></div>
              <div class="fee"><b>${money(d.visit_fee)}</b><span class="tiny muted">per visit</span></div></button>`).join("")}
          </div></div>

        <div class="card"><div class="step-label"><span class="n">3</span><h3>${b.mode === "asap" ? "When they can come" : "Pick a time"}</h3></div>${timeCard}</div>

        <div class="card"><div class="step-label"><span class="n">4</span><h3>Where should the doctor come?</h3></div>
          <label class="field">Visit address<input id="addr" value="${esc(b.address)}"></label></div>
      </div>
      <aside class="sticky"><div class="card featured">
        <h3>Your booking</h3>
        <table class="price" style="margin-top:8px">
          <tr><td>Reason</td><td>${esc(b.reason || "—")}</td></tr>
          <tr><td>Doctor</td><td>${b.mode === "asap" ? `Soonest available${doc ? `<div class="tiny muted">${esc(doc.name)}</div>` : ""}` : doc ? esc(doc.name) : "Nearest available"}</td></tr>
          <tr><td>Time</td><td>${b.mode === "asap" ? (soon ? `${dayLabel(soon.slot)}, ${time(soon.slot)}` : "—") : b.slot ? `${dayLabel(b.slot)}, ${time(b.slot)}` : "—"}</td></tr>
          ${isFollowUp() ? `<tr><td>Follow-up of</td><td>${esc(fu.previous_visit.booking_ref || "last visit")}</td></tr>` : ""}
          <tr class="total"><td>Visit fee</td><td>${doc ? money(doc.visit_fee) : `from ${money(minFee)}`}</td></tr></table>
        <div class="notice info small">${ic("shield")}<span><b>Nothing to pay now.</b> You pay the doctor after the visit. Every doctor's licence is verified.</span></div>
        <button class="btn primary block" id="bookBtn" ${ok ? "" : "disabled"}>${ic("check")} Confirm booking</button>
        <p class="tiny muted" style="text-align:center;margin:10px 0 0">${ok ? "The doctor will confirm your request." : !b.reason ? "Choose a reason to continue" : "Pick a time to continue"}</p>
      </div></aside></div>
      ${upcoming.length ? `<div class="section-title">Your bookings</div>${upcoming.map(visitCard).join("")}` : ""}`;
    const redo = (fn) => guard(async () => { await fn(); render(); });
    $$("[data-reason]").forEach((x) => (x.onclick = () => redo(async () => { b.reason = x.dataset.reason; await suggestPrevious(); })));
    $("#details").oninput = (e) => { b.details = e.target.value; };
    $("#addr").oninput = (e) => { b.address = e.target.value; $("#bookBtn").disabled = !ready(); };
    $$("[data-mode]").forEach((x) => (x.onclick = () => redo(async () => { b.mode = x.dataset.mode; b.doctor = null; await loadSlots(); })));
    $$("[data-doc]").forEach((x) => (x.onclick = () => redo(() => pickDoctor(+x.dataset.doc))));
    $$("[data-prev]").forEach((x) => (x.onclick = () => redo(() => pickDoctor(prevDoc.id, fu.next_slot))));
    $$("[data-alt]").forEach((x) => (x.onclick = () => redo(() => pickDoctor(fu.alternative.doctor.id, fu.alternative.slot))));
    $$("[data-day]").forEach((x) => (x.onclick = () => { b.day = x.dataset.day; render(); }));
    $$("[data-slot]").forEach((x) => (x.onclick = () => { b.slot = x.dataset.slot; render(); }));
    wireCancel(() => SCREENS.book());
    wireServices();
    $("#bookBtn").onclick = () => guard(async () => {
      const v = await post("/api/patient/visits", {
        doctor_id: b.mode === "doctor" ? b.doctor : null, scheduled_for: b.mode === "asap" ? "" : b.slot, asap: b.mode === "asap",
        reason: reasonText, address: b.address, follow_up_of: isFollowUp() ? fu.previous_visit.id : null,
      });
      bookedScreen(v);
    });
  };
  render();
};

function bookedScreen(v) {
  window.scrollTo({ top: 0 });
  const isDemoDoctor = true;
  view().innerHTML = `<section class="hero"><div class="eyebrow">Booking ${esc(v.booking_ref)}</div>
      <h1>Request sent to ${esc(v.doctor.name)}</h1>
      <p>${esc(v.doctor.specialty)} · ${v.doctor.distance_km} km away · ${dayLabel(v.scheduled_for)}, ${time(v.scheduled_for)}. We'll let you know as soon as the doctor confirms.</p>
      <div class="actions"><button class="btn primary" data-go="home">${ic("home")} Back to home</button></div></section>
    ${visitCard(v)}
    <div class="section-title">What happens next</div>
    <div class="how">${[["Doctor confirms", "You get a notification when your request is accepted."], ["Doctor visits you", "They examine you at home and e-sign your prescription."], ["Your cart is ready", "Medicines appear in your cart. Choose a pharmacy and pay."], ["Delivered home", "Track the courier and share your code at the door."]]
      .map(([t, s], i) => `<div class="step"><div class="n">${i + 1}</div><b>${t}</b><span>${s}</span></div>`).join("")}</div>
    <div class="notice info" style="margin-top:16px">${ic("info")}<span>${isDemoDoctor ? `Demo tip: open <a href="/provider" target="_blank">Triyana Partner</a> and sign in as <b>${esc(v.doctor.name)}</b> to see this request arrive and accept it.` : ""}</span></div>`;
  $$("[data-go]").forEach((x) => (x.onclick = () => go(x.dataset.go)));
  wireCancel(() => go("home"));
}

SCREENS.rx = async () => {
  const list = await api("/api/patient/prescriptions");
  if (!list.length) { view().innerHTML = pageHead("Prescriptions") + empty("rx", "No prescriptions yet", "After a home visit, your doctor's signed prescription will appear here."); return; }
  view().innerHTML = pageHead("Official prescriptions", "Read-only. Only your prescribing doctor can change these.") + list.map((rx, idx) => `
    <article class="card ${rx.status === "signed" && idx === 0 ? "featured" : rx.status !== "signed" ? "muted-card" : ""}">
      <div class="card-head"><div><div class="tiny muted strong">PRESCRIPTION ${esc(rx.reference_no)}</div>
        <h2 style="margin-top:4px">${esc(rx.doctor.name)} ${rx.doctor.license_verified ? `<span class="verified" title="Verified licence">${ic("badge")}</span>` : ""}</h2>
        <div class="meta"><span>${ic("stethoscope")} ${esc(rx.doctor.specialty)}</span><span>${ic("id")} ${regLine(rx.doctor)}</span><span>${ic("calendar")} ${day(rx.consultation_date)}</span></div></div>
        ${rx.status === "signed" ? `<span class="badge ${rx.integrity_verified ? "good" : "bad"}">${ic(rx.integrity_verified ? "shield" : "alert")} ${rx.integrity_verified ? "E-signed & verified" : "Signature check failed"}</span>` : `<span class="badge">${esc(rx.status)}</span>`}</div>
      <div class="row small muted" style="margin-bottom:6px"><span>${ic("user")} ${esc(rx.patient.name)} · ${esc(rx.patient.patient_ref)}</span><span>· Valid until ${day(rx.valid_until)}</span></div>
      ${rx.items.map((i, n) => `<div class="list-item">${miniPill(n)}
        <div class="grow"><div class="row between"><b>${esc(i.medicine)} ${esc(i.strength)}</b><span class="row" style="gap:6px">${schedBadge(i.india_schedule)}<span class="badge brand">${i.quantity} ${esc(i.unit)}</span></span></div>
        <div class="small muted">${esc(i.generic_name)} · ${esc(i.form)} · ${esc(i.route)}</div>
        <div class="small" style="margin-top:4px">${esc(i.dosage)} · ${esc(i.frequency)} · ${i.duration_days} days${i.refills_allowed ? ` · ${i.refills_allowed} refill(s)` : ""}</div>
        ${i.instructions ? `<div class="instructions" style="margin-top:8px">${esc(i.instructions)}</div>` : ""}</div></div>`).join("")}
      ${rx.signature ? `<hr class="soft"><div class="row small muted">${ic("sign")} Signed ${when(rx.signature.signed_at)} · ${esc(rx.signature.method)} · ${esc(rx.signature.content_hash)}</div>` : ""}
    </article>`).join("");
};

const QTY = {
  full: ["Full prescribed quantity", "good", "check"], pending_pharmacist: ["Pharmacist will confirm", "warn", "clock"],
  pending_prescriber: ["Awaiting your doctor", "warn", "clock"], approved: ["Smaller quantity approved", "good", "check"],
  rejected: ["Not permitted", "bad", "x"], not_permitted: ["Not permitted", "bad", "x"],
};

SCREENS.cart = async () => {
  const id = await latestCartId();
  if (!id) { view().innerHTML = pageHead("Medicine cart") + empty("cart", "Your cart is empty", "Your suggested cart appears automatically after your doctor signs a prescription."); return; }
  const cart = await api(`/api/carts/${id}`);
  state.currency = cart.currency;
  const inCart = cart.items.filter((i) => i.status === "in_cart");
  view().innerHTML = pageHead("Suggested medicine cart", `From ${esc(cart.prescription.doctor)} · ${esc(cart.prescription.reference_no)}`, `<span class="badge info">${ic("lock")} Nothing charged until you authorise</span>`) + `
    <div class="split"><div>
    ${cart.items.map((i, n) => {
      const [ql, qc, qi] = QTY[i.quantity_status] || [i.quantity_status, "", "info"];
      const st = { removed: i.online_sale_blocked ? `<span class="badge bad">${ic("store")} Buy in person</span>` : `<span class="badge">${ic("minus")} Removed from cart</span>`, buy_later: `<span class="badge">${ic("later")} Saved for later</span>`, ordered: `<span class="badge brand">${ic("bag")} Ordered</span>` }[i.status] || "";
      return `<article class="card ${i.status === "removed" || i.status === "buy_later" ? "muted-card" : ""}" data-item="${i.id}">
        <div class="med"><div class="pill ${i.status === "in_cart" ? pillClass(n) : "off"}">${ic("pills", "lg")}</div><div style="min-width:0">
          <div class="row between"><h3>${esc(i.medicine)} ${esc(i.strength)}</h3>${st}</div>
          <div class="meta">${schedBadge(i.india_schedule)}<span>${esc(i.generic_name)} · ${esc(i.form)}</span>${i.cold_chain ? `<span>${ic("snow")} Cold chain</span>` : ""}${i.id_check_required ? `<span>${ic("id")} ID at delivery</span>` : ""}${i.status === "in_cart" ? `<span>${ic("store")} ${i.pharmacies_with_stock} pharmacies</span>` : ""}</div>
        </div></div>
        <div class="qty-compare"><div class="qty-box"><span>Prescribed</span><b>${i.prescribed.quantity} ${esc(i.unit)}</b></div><div class="qty-arrow">${ic("arrow")}</div>
          ${i.online_sale_blocked ? `<div class="qty-box"><span>Online</span><b>Not sold online</b></div>` : `<div class="qty-box req"><span>You're buying</span><b>${i.requested_quantity} ${esc(i.unit)}</b></div>`}</div>
        <div class="instructions"><b>Doctor's instructions:</b> ${esc(i.prescribed.dosage)}, ${esc(i.prescribed.frequency)}, ${i.prescribed.duration_days} days. ${esc(i.prescribed.instructions)}</div>
        <div class="row between" style="margin-top:12px"><span class="badge ${qc}">${ic(qi)} ${ql}</span>${i.online_sale_blocked ? "" : `<span class="strong">${money(i.estimated_line_total)} <span class="tiny muted">est.</span></span>`}</div>
        ${i.quantity_note && i.quantity_status !== "full" ? `<div class="notice ${qc}">${ic("info")}<span>${esc(i.quantity_note)}</span></div>` : ""}
        ${i.status === "ordered" ? "" : i.online_sale_blocked ? `<div class="actions-bar">
          <button class="btn ghost sm" data-act="pharmacist">${ic("chat")} Ask pharmacist</button>
          <button class="btn ghost sm" data-act="doctor">${ic("stethoscope")} Contact doctor</button></div><div class="qty-form"></div>` : `<div class="actions-bar">
          ${i.status !== "in_cart" ? `<button class="btn primary sm" data-act="add">${ic("cart")} Add to cart</button>` : ""}
          <button class="btn sm" data-act="qty">${ic("pills")} Different quantity</button>
          ${i.status === "in_cart" ? `<button class="btn sm" data-act="remove">${ic("x")} Remove</button><button class="btn sm" data-act="buy_later">${ic("later")} Buy later</button>` : ""}
          <button class="btn ghost sm" data-act="pharmacist">${ic("chat")} Ask pharmacist</button>
          <button class="btn ghost sm" data-act="doctor">${ic("stethoscope")} Contact doctor</button></div><div class="qty-form"></div>`}
      </article>`;
    }).join("")}
    </div><aside class="sticky"><div class="card">
      <h3>Order summary</h3>
      <table class="price" style="margin-top:8px"><tr><td>Medicines (${inCart.length})</td><td>${money(cart.estimate.subtotal)}</td></tr>
        <tr><td>Delivery from</td><td>${money(cart.estimate.delivery_fee)}</td></tr><tr><td>Taxes</td><td>${money(cart.estimate.tax)}</td></tr>
        <tr class="total"><td>Estimated</td><td>${money(cart.estimate.total)}</td></tr></table>
      <div class="notice small">${ic("bolt")}<span>Fastest delivery around ${mins(cart.estimate.fastest_eta_minutes)}. ${esc(cart.estimate.note)}</span></div>
      <button class="btn primary block" id="toPharm" ${inCart.length ? "" : "disabled"}>Choose pharmacy ${ic("arrow")}</button>
      <p class="tiny muted" style="margin:10px 0 0">You're free to buy all, some or none of your medicines here. Removing an item never changes your prescription.</p>
    </div></aside></div>`;
  $("#toPharm").onclick = () => go("pharmacies");
  $$("[data-item]").forEach((card) => {
    const itemId = +card.dataset.item;
    const item = cart.items.find((x) => x.id === itemId);
    $$("[data-act]", card).forEach((b) => (b.onclick = () => guard(async () => {
      const act = b.dataset.act;
      if (["add", "remove", "buy_later"].includes(act)) {
        const r = await post(`/api/cart-items/${itemId}/${act}`);
        toast(r.message, act === "add" ? "check" : "info"); return SCREENS.cart();
      }
      if (act === "pharmacist" || act === "doctor") return messageForm(card, itemId, act, item.medicine);
      quantityForm(card, item);
    })));
  });
};

function messageForm(card, itemId, who, med) {
  const f = $(".qty-form", card);
  f.innerHTML = `<div class="card" style="margin:14px 0 0;background:var(--surface-2);box-shadow:none"><b class="row">${ic("lock")} Secure message to your ${who}</b>
    <textarea id="m${itemId}" rows="3" style="width:100%;margin-top:10px" placeholder="Your question about ${esc(med)}…"></textarea>
    <div class="row" style="margin-top:10px"><button class="btn primary sm" id="ms${itemId}">Send</button><button class="btn ghost sm" id="mc${itemId}">Cancel</button></div></div>`;
  $(`#mc${itemId}`).onclick = () => (f.innerHTML = "");
  $(`#ms${itemId}`).onclick = () => guard(async () => {
    const body = $(`#m${itemId}`).value.trim(); if (!body) return toast("Please write a message", "alert");
    await post(`/api/cart-items/${itemId}/messages`, { recipient: who, body });
    f.innerHTML = ""; toast(`Message sent securely to your ${who}`);
  });
}

function quantityForm(card, item) {
  const f = $(".qty-form", card);
  const opts = item.allowed_quantities.length ? item.allowed_quantities : [item.prescribed.quantity];
  let idx = Math.max(0, opts.indexOf(item.requested_quantity));
  f.innerHTML = `<div class="card" style="margin:14px 0 0;background:var(--surface-2);box-shadow:none">
    <div class="row between"><div><b>How many would you like to buy?</b><div class="tiny muted">Up to ${item.prescribed.quantity} ${esc(item.unit)} · packs of ${item.pack_sizes.join(", ")}</div></div>
    <div class="stepper"><button type="button" data-d="-1" aria-label="Fewer">−</button><output id="qv${item.id}">${opts[idx]}</output><button type="button" data-d="1" aria-label="More">+</button></div></div>
    <div class="notice warn">${ic("alert")}<span>Buying fewer than prescribed may leave you without the full course. Your doctor's prescription stays unchanged and the dispensing pharmacist makes the final decision.</span></div>
    <div class="row"><button class="btn primary" id="qs${item.id}">Request ${ic("arrow")}</button><button class="btn ghost" id="qc${item.id}">Cancel</button></div><div id="qr${item.id}"></div></div>`;
  $$("[data-d]", f).forEach((b) => (b.onclick = () => { idx = Math.min(opts.length - 1, Math.max(0, idx + +b.dataset.d)); $(`#qv${item.id}`).textContent = opts[idx]; }));
  $(`#qc${item.id}`).onclick = () => (f.innerHTML = "");
  $(`#qs${item.id}`).onclick = () => guard(async () => {
    const r = await put(`/api/cart-items/${item.id}/quantity`, { requested_quantity: opts[idx] });
    const ok = !["rejected", "not_permitted"].includes(r.status);
    $(`#qr${item.id}`).innerHTML = `<div class="notice ${ok ? "good" : "bad"}">${ic(ok ? "check" : "x")}<span>${esc(r.explanation)}</span></div>` +
      (ok ? "" : `<div class="row"><button class="btn sm" data-c="pharmacist">${ic("chat")} Contact pharmacy</button><button class="btn sm" data-c="doctor">${ic("stethoscope")} Contact doctor</button></div>`);
    $$("[data-c]", $(`#qr${item.id}`)).forEach((c) => (c.onclick = () => messageForm(card, item.id, c.dataset.c, item.medicine)));
    if (ok) setTimeout(SCREENS.cart, 1500);
  });
}

const SORTS = [["nearest", "Nearest"], ["price", "Lowest price"], ["fastest", "Fastest"], ["rating", "Top rated"], ["pickup", "Pickup"]];

SCREENS.pharmacies = async () => {
  const id = await latestCartId();
  if (!id) { view().innerHTML = pageHead("Pharmacies") + empty("store", "No cart yet", "Pharmacy matching starts once your doctor signs a prescription."); return; }
  const sort = state.ctx.sort || "nearest";
  const data = await api(`/api/carts/${id}/pharmacies?sort=${sort}`);
  state.currency = data.currency;
  const eligible = data.pharmacies.filter((p) => p.eligible).length;
  view().innerHTML = pageHead("Licensed pharmacies near you", `${eligible} of ${data.pharmacies.length} can fulfil your cart · only verified, licensed pharmacies are shown`) + `
    <div class="seg" style="margin-bottom:18px">${SORTS.map(([k, l]) => `<button class="${k === sort ? "on" : ""}" data-sort="${k}">${l}</button>`).join("")}</div>
    <div class="grid">${data.pharmacies.map((p) => `
      <article class="card lift rel ${p.recommended ? "has-ribbon featured" : ""} ${p.eligible ? "" : "muted-card"}">
        ${p.recommended ? `<div class="ribbon">BEST MATCH</div>` : ""}
        <div class="pharm-head"><div class="pharm-logo">${esc(initials(p.name))}</div><div style="min-width:0">
          <h3>${esc(shortName(p.name))} <span class="verified" title="Licence verified">${ic("badge")}</span></h3>
          <div class="meta"><span>${ic("pin")} ${p.distance_km} km</span><span class="stars">★ ${p.rating}</span><span>(${p.rating_count.toLocaleString()})</span><span>${ic("clock")} ${esc(p.hours)}</span></div></div></div>
        <div class="tiny muted row" style="margin-top:8px;gap:6px">${ic("shield")} Licence ${esc(p.verified.license_no)} · Reg. ${esc(p.verified.business_reg_no)}</div>
        <ul class="stock-list">${p.items.map((i) => `<li><span>${esc(i.medication)} × ${i.quantity}</span>
          <span class="badge ${i.stock_status === "confirmed" ? "good" : i.stock_status === "unconfirmed" ? "warn" : "bad"}">${{ confirmed: "In stock · live", unconfirmed: "Unconfirmed", out_of_stock: "Out of stock", not_carried: "Not stocked" }[i.stock_status]}</span></li>`).join("")}</ul>
        <table class="price"><tr><td>Medicines</td><td>${money(p.subtotal)}</td></tr><tr><td>Delivery</td><td>${p.delivery_available ? money(p.delivery_fee) : "—"}</td></tr>
          <tr><td>Taxes</td><td>${money(p.tax)}</td></tr><tr class="total"><td>Total</td><td>${money(p.total)}</td></tr></table>
        <div class="row small" style="margin:10px 0 14px">${p.delivery_available ? `<span class="badge brand">${ic("truck")} ~${mins(p.eta_minutes)}</span>` : `<span class="badge">No delivery here</span>`}
          ${p.pickup_available ? `<span class="badge">${ic("bag")} Pickup</span>` : ""}${p.open_now ? `<span class="badge good">Open now</span>` : ""}
          ${p.delivery_options.some((o) => o.code === "drone") ? `<span class="badge info">${ic("drone")} Drone</span>` : ""}</div>
        ${p.drone_note && !p.delivery_options.some((o) => o.code === "drone") ? `<div class="tiny muted row" style="gap:6px;margin:-6px 0 12px">${ic("drone")} No drone here: ${esc(p.drone_note)}</div>` : ""}
        ${p.eligible ? `<button class="btn primary block" data-pick="${p.pharmacy_id}">Choose ${ic("arrow")}</button>` :
          `<div class="notice bad small">${ic("info")}<span>${p.reasons.map(esc).join("<br>")}</span></div>`}
      </article>`).join("")}</div>`;
  $$("[data-sort]").forEach((b) => (b.onclick = () => { state.ctx.sort = b.dataset.sort; SCREENS.pharmacies(); }));
  $$("[data-pick]").forEach((b) => (b.onclick = () => guard(() => checkoutScreen(data.pharmacies.find((p) => p.pharmacy_id === +b.dataset.pick)))));
};

const PAY_ICON = { upi: "bolt", card: "card", netbanking: "store", wallet: "wallet", apple_pay: "phone", google_pay: "phone", paypal: "wallet", regional_wallet: "wallet" };
let rzpLoading;
function loadRazorpay() {
  if (window.Razorpay) return Promise.resolve();
  rzpLoading = rzpLoading || new Promise((resolve, reject) => {
    const sc = document.createElement("script"); sc.src = "https://checkout.razorpay.com/v1/checkout.js";
    sc.onload = resolve; sc.onerror = () => { rzpLoading = null; reject(new Error("Couldn't load Razorpay. Check your connection and try again.")); };
    document.head.appendChild(sc);
  });
  return rzpLoading;
}
async function payWithRazorpay(p, opt, total) {
  const intent = await post(`/api/carts/${state.ctx.cartId}/payment-intent`, { pharmacy_id: p.pharmacy_id, fulfillment: opt.fulfillment, delivery_option: opt.fulfillment === "delivery" ? opt.delivery_option : null });
  if (Math.abs(intent.amount - total) > 0.009) throw new Error("The total changed. Please review the updated price.");
  await loadRazorpay();
  const r = await new Promise((resolve, reject) => {
    const rz = new window.Razorpay({
      key: intent.key_id, order_id: intent.order_id, amount: intent.amount_paise, currency: "INR", name: "Triyana",
      description: "Medicines · held until a pharmacist approves", prefill: { ...intent.prefill, method: opt.method },
      theme: { color: "#0b7a6c" }, handler: resolve,
      modal: { ondismiss: () => reject(new Error("Payment cancelled. You have not been charged.")) },
    });
    rz.on("payment.failed", (e) => reject(new Error(e?.error?.description || "Payment failed. You have not been charged.")));
    rz.open();
  });
  return `rzp:${r.razorpay_order_id}:${r.razorpay_payment_id}:${r.razorpay_signature}`;
}
const DELIV = { standard: ["truck", "Standard"], same_day: ["clock", "Same day"], scheduled: ["calendar", "Scheduled"], priority: ["bolt", "Priority"], drone: ["drone", "Drone"] };
const MULT = { standard: 1, same_day: 1.4, scheduled: 1, priority: 2, drone: 2.5 };
const r2 = (n) => Math.round(n * 100) / 100;

async function checkoutScreen(p) {
  const [methods, cfg] = await Promise.all([api("/api/payment-methods"), api("/api/payment-config")]);
  const rzp = cfg.gateway === "razorpay";
  const opt = { fulfillment: p.delivery_available ? "delivery" : "pickup", delivery_option: p.delivery_options[0]?.code || null, method: methods[0].code, decline: false };
  const key = `chk-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const render = () => {
    const fee = opt.fulfillment === "delivery" ? r2(p.delivery_fee * (MULT[opt.delivery_option] || 1)) : 0;
    const total = r2(p.subtotal + p.tax + fee);
    view().innerHTML = pageHead("Checkout", `${esc(shortName(p.name))} · ${p.distance_km} km away`, `<button class="btn ghost" id="back">← Pharmacies</button>`) + `
      <div class="split"><div>
        <div class="card"><h3>Your medicines</h3>${p.items.map((i, n) => `<div class="list-item">${miniPill(n)}
          <div class="grow">${esc(i.medication)}<div class="tiny muted">Quantity ${i.quantity}</div></div><b>${money(i.line_total)}</b></div>`).join("")}</div>
        <div class="card"><h3>Delivery or pickup</h3><div class="choice-grid" style="margin-top:12px">
          ${p.delivery_available ? `<button class="choice ${opt.fulfillment === "delivery" ? "on" : ""}" data-f="delivery"><span class="ico">${ic("truck")}</span><div><b>Home delivery</b><span>~${mins(p.eta_minutes)}</span></div></button>` : ""}
          ${p.pickup_available ? `<button class="choice ${opt.fulfillment === "pickup" ? "on" : ""}" data-f="pickup"><span class="ico">${ic("bag")}</span><div><b>Pickup</b><span>Bring photo ID</span></div></button>` : ""}</div>
          ${opt.fulfillment === "delivery" ? `<div class="section-title" style="margin-top:18px">Delivery speed</div><div class="choice-grid">${p.delivery_options.map((o) => `<button class="choice ${o.code === opt.delivery_option ? "on" : ""}" data-d="${o.code}"><span class="ico">${ic(DELIV[o.code]?.[0] || "truck")}</span><div><b>${esc(DELIV[o.code]?.[1] || o.label)}</b><span>${money(r2(p.delivery_fee * (MULT[o.code] || 1)))}</span></div></button>`).join("")}</div>
            ${opt.delivery_option === "scheduled" ? `<label class="field" style="margin-top:12px">Deliver at<input type="datetime-local" id="sched"></label>` : ""}` : ""}</div>
        <div class="card"><h3>Payment method</h3><div class="choice-grid" style="margin-top:12px">${methods.map((m) => `<button class="choice ${m.code === opt.method ? "on" : ""}" data-m="${m.code}"><span class="ico">${ic(PAY_ICON[m.code] || "card")}</span><div><b>${esc(m.label)}</b></div></button>`).join("")}</div>
          ${rzp ? "" : `<label class="check" style="margin-top:14px"><input type="checkbox" id="decline" ${opt.decline ? "checked" : ""}> <span class="small muted">Sandbox: simulate a declined payment</span></label>`}</div>
      </div><aside class="sticky"><div class="card featured">
        <h3>Payment summary</h3>
        <table class="price" style="margin-top:8px"><tr><td>Medicine subtotal</td><td>${money(p.subtotal)}</td></tr><tr><td>Delivery fee</td><td>${money(fee)}</td></tr>
          <tr><td>Taxes</td><td>${money(p.tax)}</td></tr><tr><td>Discounts</td><td>${money(0)}</td></tr><tr class="total"><td>Total</td><td>${money(total)}</td></tr></table>
        <div class="notice info small">${ic("shield")}<span><b>Authorised, not charged.</b> You're only charged after a licensed pharmacist approves your order, and only for what they approve.</span></div>
        <button class="btn primary block" id="pay">${ic("lock")} Pay ${money(total)}</button>
        <p class="tiny muted" style="text-align:center;margin:10px 0 0">${rzp ? (cfg.test_mode ? "Secured by Razorpay · test mode, no real money moves" : "Secured by Razorpay") : "Sandbox payments · no real money moves"}</p>
      </div></aside></div>`;
    $("#back").onclick = () => SCREENS.pharmacies();
    $$("[data-f]").forEach((b) => (b.onclick = () => { opt.fulfillment = b.dataset.f; render(); }));
    $$("[data-d]").forEach((b) => (b.onclick = () => { opt.delivery_option = b.dataset.d; render(); }));
    $$("[data-m]").forEach((b) => (b.onclick = () => { opt.method = b.dataset.m; render(); }));
    if ($("#decline")) $("#decline").onchange = (e) => (opt.decline = e.target.checked);
    $("#pay").onclick = () => guard(async () => {
      const btn = $("#pay"); btn.disabled = true; btn.textContent = "Authorising…";
      try {
        const sched = $("#sched")?.value;
        const token = rzp ? await payWithRazorpay(p, opt, total) : opt.decline ? "sandbox-decline" : "sandbox-ok";
        btn.textContent = "Placing order…";
        const order = await post(`/api/carts/${state.ctx.cartId}/checkout`, {
          pharmacy_id: p.pharmacy_id, fulfillment: opt.fulfillment, delivery_option: opt.fulfillment === "delivery" ? opt.delivery_option : null,
          scheduled_for: sched ? new Date(sched).toISOString().slice(0, 19) : null, payment_method: opt.method,
          payment_token: token, idempotency_key: key, expected_total: total,
        });
        toast("Order placed. A pharmacist is reviewing it.");
        go("orders", { orderId: order.id });
      } catch (e) { render(); throw e; }
    });
  };
  render();
}

const STEPS = [["prescription_received", "Prescription received"], ["pharmacist_reviewing", "Pharmacist reviewing"], ["order_accepted", "Order accepted"], ["preparing", "Preparing medicines"], ["ready_for_pickup", "Ready for pickup"], ["out_for_delivery", "Out for delivery"], ["delivered", "Delivered"]];

SCREENS.orders = async () => {
  const dash = await api("/api/patient/medicines");
  const all = [...dash.active_orders, ...dash.purchase_history];
  if (!all.length) { view().innerHTML = pageHead("Tracking") + empty("truck", "No orders yet", "Once you place an order, you can follow it here step by step."); return; }
  const o = all.find((x) => x.id === state.ctx.orderId) || all[0];
  const steps = o.fulfillment === "pickup" ? STEPS.slice(0, 5).concat([["picked_up", "Collected"]]) : STEPS;
  const seen = new Set(o.timeline.map((e) => e.status));
  const doneCount = steps.filter(([s]) => seen.has(s)).length;
  const bad = ["rejected", "cancelled"].includes(o.status);
  const last = o.timeline[o.timeline.length - 1];
  view().innerHTML = pageHead("Order tracking", `${esc(o.order_no)} · ${esc(shortName(o.pharmacy.name))}`,
    all.length > 1 ? `<select id="pickOrder">${all.map((x) => `<option value="${x.id}" ${x.id === o.id ? "selected" : ""}>${esc(x.order_no)} · ${esc(x.status_label)}</option>`).join("")}</select>` : "") + `
    <section class="hero"><div class="eyebrow">${o.fulfillment === "pickup" ? "Pickup order" : esc(DELIV[o.delivery_option]?.[1] || "") + " delivery"}</div>
      <h1>${esc(o.status_label)}</h1><p>${esc(last.note)}</p>
      ${o.delivery && !["delivered", "cancelled", "rejected"].includes(o.status) ? `<div class="actions"><button class="btn primary" id="liveOrder">${ic("pin")} ${o.delivery.courier ? `Track ${esc(o.delivery.courier)} live` : "Live map"}</button></div>` : ""}
      ${bad ? "" : `<div class="progress"><i style="width:${Math.round((doneCount / steps.length) * 100)}%"></i></div>
      <div class="stats">${o.delivery?.eta && o.status !== "delivered" ? `<div class="stat"><b>${time(o.delivery.eta)}</b><span>Estimated arrival</span></div>` : ""}
        <div class="stat"><b>${doneCount}/${steps.length}</b><span>Steps complete</span></div><div class="stat"><b>${money(o.price.total)}</b><span>Payment ${esc(o.payment.status)}</span></div></div>`}
    </section>
    <div class="split"><div>
      ${o.status === "awaiting_clarification" ? `<div class="notice warn">${ic("chat")}<span>The pharmacist asked your doctor a quick question. We'll notify you as soon as it's answered.</span></div>` : ""}
      <div class="card"><h3>Journey</h3>${bad ? `<div class="notice bad">${ic("x")}<span>${esc(last.note)}</span></div>` : `<ul class="timeline">${steps.map(([s, l], i) => {
        const ev = o.timeline.filter((e) => e.status === s).pop();
        const cur = !seen.has(s) && i === doneCount;
        return `<li class="${seen.has(s) ? "done" : ""} ${cur ? "current" : ""}"><span class="node">${seen.has(s) ? ic("check") : ""}</span><b>${l}</b>
          <div class="small muted">${ev ? `${time(ev.at)} · ${esc(ev.note)}` : cur ? "Up next" : ""}</div></li>`; }).join("")}</ul>`}</div>
      ${o.mission ? missionPanels(o.mission) : ""}
      <div class="card"><h3>Items</h3><div class="table-wrap"><table><tr><th>Medicine</th><th>Prescribed</th><th>Requested</th><th>Approved</th></tr>
        ${o.items.map((i) => `<tr><td><b>${esc(i.medicine)}</b> ${schedBadge(i.india_schedule)}</td><td>${i.prescribed_quantity}</td><td>${i.requested_quantity}</td><td>${i.approved_quantity ?? `<span class="badge warn">Pending</span>`}</td></tr>`).join("")}</table></div></div>
    </div><aside class="sticky">
      ${o.delivery && o.status !== "delivered" ? `<div class="code-box"><div class="tiny" style="opacity:.8">${o.mission?.mode === "drone" ? "SHARE THIS CODE WHEN THE DRONE ARRIVES" : "SHARE THIS CODE WITH YOUR COURIER"}</div><div class="code">${esc(o.delivery.handover_code)}</div><div class="tiny" style="opacity:.8">Proof of delivery</div></div>` : ""}
      ${o.delivery ? `<div class="card"><div class="row"><div class="avatar">${o.delivery.courier ? esc(initials(o.delivery.courier)) : ic("truck")}</div><div><b>${esc(o.delivery.courier || "Finding the nearest courier…")}</b><div class="tiny muted">${esc(o.delivery.provider)} · ${esc(o.delivery.tracking_ref)}</div></div></div>
        <div class="row small" style="margin-top:12px">${o.delivery.cold_chain ? `<span class="badge info">${ic("snow")} Temperature controlled</span>` : ""}${o.delivery.id_check_required ? `<span class="badge warn">${ic("id")} Photo ID required</span>` : ""}<span class="badge">${ic("sign")} Signature</span></div>
        ${o.delivery.proof_of_delivery ? `<div class="notice good">${ic("check")}<span>Delivered to ${esc(o.delivery.proof_of_delivery.recipient)}</span></div>` : ""}</div>` : ""}
      <div class="card"><h3>Payment</h3><table class="price" style="margin-top:6px"><tr><td>Subtotal</td><td>${money(o.price.subtotal)}</td></tr><tr><td>Delivery</td><td>${money(o.price.delivery_fee)}</td></tr><tr><td>Taxes</td><td>${money(o.price.tax)}</td></tr>
        <tr class="total"><td>Total</td><td>${money(o.price.total)}</td></tr></table>
        <div class="row small" style="margin-top:8px"><span class="badge">${esc(o.payment.method.replace("_", " "))}</span><span class="badge ${o.payment.status === "captured" ? "good" : o.payment.status === "authorized" ? "info" : ""}">${esc(o.payment.status)}</span>${o.payment.refunded ? `<span class="badge good">Refunded ${money(o.payment.refunded)}</span>` : ""}</div>
        ${["prescription_received", "pharmacist_reviewing", "awaiting_clarification", "order_accepted"].includes(o.status) ? `<button class="btn danger block" id="cancel" style="margin-top:14px">Cancel order</button>` : ""}</div>
    </aside></div>`;
  if (o.mission && ["in_flight", "in_transit"].includes(o.mission.status)) state.poll = setInterval(() => state.tab === "orders" && SCREENS.orders(), 15000);
  const lo = $("#liveOrder"); if (lo) lo.onclick = () => liveScreen("delivery", o.id);
  const pick = $("#pickOrder"); if (pick) pick.onchange = () => { state.ctx.orderId = +pick.value; SCREENS.orders(); };
  const c = $("#cancel");
  if (c) c.onclick = () => guard(async () => { if (!confirm("Cancel this order? Any payment hold will be released or refunded.")) return; await post(`/api/orders/${o.id}/cancel`, { reason: "Cancelled by patient" }); toast("Order cancelled"); SCREENS.orders(); });
};

SCREENS.meds = async () => {
  const d = await api("/api/patient/medicines");
  view().innerHTML = pageHead("My Medicines", "Everything your doctors prescribed, what you've ordered and what's been dispensed.") + `
    <div class="notice info">${ic("info")}<span>${esc(d.note)}</span></div>
    ${d.prescriptions.length ? d.prescriptions.map((rx) => `<div class="card"><div class="card-head"><div><h3>${esc(rx.reference_no)}</h3><div class="meta"><span>${ic("stethoscope")} ${esc(rx.doctor)}</span><span>${ic("calendar")} Expires ${day(rx.valid_until)}</span></div></div>
      <span class="badge ${rx.status === "signed" ? "good" : rx.status === "expired" ? "bad" : ""}">${esc(rx.status === "signed" ? "Active" : rx.status)}</span></div>
      ${rx.items.map((i, n) => `<div class="list-item">${miniPill(n)}<div class="grow">
        <b>${esc(i.medicine)}</b><div class="tiny muted">${esc(i.dosage)} · ${esc(i.frequency)}</div>
        <div class="row tiny" style="margin-top:6px;gap:6px"><span class="badge">Prescribed ${i.prescribed_quantity}</span><span class="badge info">Ordered ${i.ordered_quantity}</span><span class="badge good">Dispensed ${i.dispensed_quantity}</span>
        ${i.refill_eligible ? `<span class="badge premium">Refill eligible</span>` : i.refills_allowed ? `<span class="badge">${i.refills_allowed} refill(s)</span>` : ""}</div></div></div>`).join("")}</div>`).join("") : empty("pills", "No prescriptions yet")}
    <div class="grid">
      <div class="card"><h3>Pending orders</h3>${d.active_orders.map((o) => `<div class="list-item"><div class="avatar">${ic("truck")}</div><div class="grow"><b>${esc(o.order_no)}</b><div class="tiny muted">${esc(shortName(o.pharmacy.name))}</div></div><button class="btn sm" data-o="${o.id}">${esc(o.status_label)}</button></div>`).join("") || `<p class="small muted">None right now.</p>`}</div>
      <div class="card"><h3>Purchase history</h3>${d.purchase_history.map((o) => `<div class="list-item"><div class="avatar">${ic("bag")}</div><div class="grow"><b>${esc(o.order_no)}</b><div class="tiny muted">${day(o.created_at)} · ${money(o.price.total)}</div></div><span class="badge ${o.status === "delivered" || o.status === "picked_up" ? "good" : ""}">${esc(o.status_label)}</span></div>`).join("") || `<p class="small muted">No purchases yet.</p>`}</div>
      <div class="card"><h3>Messages</h3>${d.messages.map((m) => `<div class="list-item"><div class="avatar">${ic("chat")}</div><div class="grow"><b>To your ${esc(m.recipient)}</b><div class="small muted">${esc(m.body)}</div><div class="tiny muted">${when(m.at)}</div></div></div>`).join("") || `<p class="small muted">No messages.</p>`}</div>
    </div>
    <section class="hero" style="margin-top:6px"><div class="eyebrow">Doctor follow-up</div><h1>Need to see your doctor again?</h1><p>Book a verified doctor to visit you at home.</p>
      <div class="actions"><button class="btn primary" id="follow">${ic("calendar")} ${esc(d.doctor_follow_up.label)}</button></div></section>`;
  $$("[data-o]").forEach((b) => (b.onclick = () => go("orders", { orderId: +b.dataset.o })));
  $("#follow").onclick = () => go("book", { followUp: true });
};

/* ---------------------------------------------------------------- doctor */
SCREENS.visits = async () => {
  const visits = await api("/api/doctor/visits");
  const next = { requested: ["accept", "Accept booking", "check"], accepted: ["start", "Start visit", "stethoscope"], in_progress: ["complete", "Complete consultation", "check"] };
  const label = { requested: ["New request", "info"], accepted: ["Accepted", "brand"], in_progress: ["In progress", "warn"], completed: ["Completed", "good"], cancelled: ["Cancelled", ""] };
  view().innerHTML = `<section class="hero"><div class="eyebrow">${GREETING()}, ${esc(state.name)}</div><h1>Today's home visits</h1>
      <p>Accept bookings, complete consultations and send e-signed prescriptions straight to your patient's cart.</p>
      <div class="stats"><div class="stat"><b>${visits.length}</b><span>Visits</span></div><div class="stat"><b>${visits.filter((v) => v.status === "requested").length}</b><span>New requests</span></div><div class="stat"><b>${visits.filter((v) => v.status === "completed").length}</b><span>Completed</span></div></div></section>` +
    (visits.map((v) => `<article class="card lift"><div class="card-head"><div class="row"><div class="avatar">${esc(initials(v.patient.name))}</div><div><h3>${esc(v.patient.name)}</h3>
      <div class="meta"><span>${ic("id")} ${esc(v.patient.patient_ref)}</span><span>${ic("clock")} ${when(v.scheduled_for)}</span>${v.booking_ref ? `<span>${ic("calendar")} ${esc(v.booking_ref)}</span>` : ""}</div>
      <div class="meta"><span>${ic("pin")} ${esc(v.address)}</span>${v.follow_up_of ? `<span class="badge premium">${ic("later")} Follow-up${v.follow_up_of.same_doctor ? " · your patient" : ""} of ${esc(v.follow_up_of.booking_ref || "earlier visit")}</span>` : ""}</div></div></div><span class="badge ${label[v.status][1]}">${label[v.status][0]}</span></div>
      <div class="instructions">${esc(v.reason)}</div>
      <div class="actions-bar">${v.status === "in_progress" ? `<button class="btn primary sm" data-notes="${v.id}">${ic("notes")} ${v.has_notes ? "Visit notes · complete visit" : "Write visit notes & vitals"}</button>`
        : next[v.status] ? `<button class="btn primary sm" data-v="${v.id}" data-a="${next[v.status][0]}">${ic(next[v.status][2])} ${next[v.status][1]}</button>` : ""}
      ${v.status === "completed" ? `<button class="btn sm" data-notes="${v.id}">${ic("notes")} ${v.has_notes ? "Visit notes" : "Add visit notes"}</button>` : ""}
      ${["in_progress", "completed"].includes(v.status) ? `<button class="btn sm" data-rx="${v.id}">${ic("rx")} Write prescription</button>` : ""}</div></article>`).join("") || empty("calendar", "No visits scheduled"));
  $$("[data-notes]").forEach((b) => (b.onclick = () => guard(() => notesScreen(+b.dataset.notes))));
  $$("[data-a]").forEach((b) => (b.onclick = () => guard(async () => {
    await post(`/api/doctor/visits/${b.dataset.v}/${b.dataset.a}`);
    if (b.dataset.a === "complete") { const v = visits.find((x) => x.id === +b.dataset.v); toast(`Visit complete. You earned ${money((v?.fee || 0) + (v?.on_demand ? 100 : 0))}. See Earnings.`, "wallet"); }
    SCREENS.visits();
  })));
  $$("[data-rx]").forEach((b) => (b.onclick = () => guard(() => prescribeScreen(+b.dataset.rx, visits.find((v) => v.id === +b.dataset.rx)))));
};

const PRESETS = [["All day", (h) => h >= 9 && h <= 19], ["Mornings", (h) => h >= 9 && h <= 12], ["Evenings", (h) => h >= 16 && h <= 20], ["Day off", () => false]];
SCREENS.availability = async () => {
  const av = await api("/api/doctor/availability");
  const fmtH = (date, h) => time(hourIso(date, h));
  const dayCard = (d) => {
    const n = d.hours.filter((h) => !d.past.includes(h)).length;
    const status = !d.hours.length ? `<span class="badge">Day off</span>` : `<span class="badge ${n ? "good" : ""}">${n} hour${n === 1 ? "" : "s"} open</span>`;
    return `<article class="card hours-day" data-date="${d.date}"><div class="card-head"><div><h3>${esc(dateLabel(d.date))}</h3>
        <div class="tiny muted">${d.custom ? "Your hours" : "Standard hours (9 AM to 7 PM). Tap to change."}${d.booked.length ? ` · ${d.booked.length} booked` : ""}</div></div>${status}</div>
      <div class="seg">${PRESETS.map(([l], i) => `<button data-preset="${i}">${l}</button>`).join("")}</div>
      <div class="slot-grid hours">${av.openable_hours.map((h) => {
        const booked = d.booked.includes(h), past = d.past.includes(h), on = d.hours.includes(h);
        return `<button class="slot ${on ? "on" : ""} ${booked ? "booked" : ""}" data-h="${h}" ${booked || past ? "disabled" : ""} title="${booked ? "A patient has booked this time" : past ? "Too late to open today" : on ? "Open: tap to close" : "Closed: tap to open"}">${fmtH(d.date, h)}${booked ? `<span>Booked</span>` : ""}</button>`;
      }).join("")}</div></article>`;
  };
  view().innerHTML = pageHead("Your visit hours", "Open the hours you can do home visits. Patients can only book times you open here.") + `
    <div class="notice info">${ic("info")}<span>Tap a time to open or close it. Changes save straight away. Booked times stay open until the patient cancels.</span></div>
    <div class="legend small muted"><span><i class="sw on"></i> Open for booking</span><span><i class="sw"></i> Closed</span><span><i class="sw booked"></i> Booked by a patient</span></div>
    <div class="hours-list">${av.days.map(dayCard).join("")}</div>`;
  const save = async (date, hours) => {
    const day = await put("/api/doctor/availability", { date, hours });
    const i = av.days.findIndex((d) => d.date === date); av.days[i] = day;
    $(`[data-date="${date}"]`).outerHTML = dayCard(day); wire(); toast(`Saved ${dateLabel(date)}`);
  };
  const wire = () => {
    $$(".hours-day").forEach((card) => {
      const d = av.days.find((x) => x.date === card.dataset.date);
      $$("[data-h]", card).forEach((b) => (b.onclick = () => guard(() => {
        const h = +b.dataset.h; return save(d.date, d.hours.includes(h) ? d.hours.filter((x) => x !== h) : [...d.hours, h]);
      })));
      $$("[data-preset]", card).forEach((b) => (b.onclick = () => guard(() => {
        const keep = PRESETS[+b.dataset.preset][1];
        return save(d.date, [...new Set([...av.openable_hours.filter(keep), ...d.booked])]);
      })));
    });
  };
  wire();
};

/* ---------------------------------------------------------------- visit notes & vitals */
const VITALS = [
  ["temp", "Temperature", "thermo"], ["bp", "Blood pressure", "heart"], ["pulse_bpm", "Pulse", "heart", "bpm"],
  ["spo2_pct", "SpO2", "bolt", "%"], ["resp_rate", "Respiratory rate", "chat", "/min"], ["weight_kg", "Weight", "user", "kg"],
];
const FLAG_CLS = { high: "bad", watch: "warn" };
const flagBadges = (flags) => flags.map((f) => `<span class="badge ${FLAG_CLS[f.level] || ""}">${ic("alert")} ${esc(f.label)}</span>`).join("");
function vitalTiles(v, flags = []) {
  const flagged = (k) => flags.find((f) => f.vital === k);
  const tile = (key, label, icon, value, unit) => {
    const f = flagged(key);
    return `<div class="vital ${f ? `flag-${f.level}` : ""}"><span class="tiny muted">${ic(icon)} ${label}</span><b>${value == null ? "—" : esc(value)}<small>${value == null ? "" : unit}</small></b>${f ? `<span class="tiny">${esc(f.label)}</span>` : ""}</div>`;
  };
  return `<div class="vitals">
    ${tile("temperature", "Temperature", "thermo", v.temperature_f, " °F")}
    ${tile("bp", "Blood pressure", "heart", v.bp, " mmHg")}
    ${tile("pulse", "Pulse", "heart", v.pulse_bpm, " bpm")}
    ${tile("spo2", "SpO2", "bolt", v.spo2_pct, "%")}
    ${tile("resp_rate", "Breathing", "chat", v.resp_rate, " /min")}
    ${tile("weight", "Weight", "user", v.weight_kg, " kg")}</div>`;
}
const followUpText = (d) => (!d ? "" : d === 1 ? "Follow up tomorrow" : d % 7 === 0 ? `Follow up in ${d / 7} week${d > 7 ? "s" : ""}` : `Follow up in ${d} days`);

async function notesScreen(visitId) {
  stopLive();
  const [visits, note] = await Promise.all([api("/api/doctor/visits"), api(`/api/doctor/visits/${visitId}/notes`)]);
  const v = visits.find((x) => x.id === visitId);
  if (!v) return SCREENS.visits();
  const n = note || {};
  const vt = n.vitals || {};
  let unit = "F";
  const num = (id) => { const x = $(`#${id}`).value.trim(); return x === "" ? null : Number(x); };
  const field = (id, label, value, attrs = "") => `<label>${label}<input id="${id}" inputmode="decimal" value="${value ?? ""}" ${attrs}></label>`;
  view().innerHTML = pageHead("Visit notes", `${esc(v.patient.name)} · ${esc(v.patient.patient_ref)}${v.booking_ref ? ` · ${esc(v.booking_ref)}` : ""}`, `<button class="btn ghost" id="back">← Visits</button>`) + `
    <div class="notice info small">${ic("info")}<span>The patient sees these notes in their visit history after you complete the visit. Fictional demo data only.</span></div>
    <div class="card"><h3>${ic("chat")} What happened</h3>
      <div class="form-grid">
        <label class="wide">Chief complaint<input id="cc" maxlength="500" value="${esc(n.chief_complaint ?? v.reason.replace(/\s*\(fictional\)$/, ""))}" placeholder="Why the patient called, e.g. fever for 2 days"></label>
        <label class="wide">History and examination findings<textarea id="findings" rows="4" maxlength="4000" placeholder="Symptoms, how long, what you found on examination">${esc(n.findings || "")}</textarea></label>
      </div></div>
    <div class="card"><div class="card-head"><h3>${ic("heart")} Vitals</h3><div class="seg" id="tUnit"><button data-u="F" class="on">°F</button><button data-u="C">°C</button></div></div>
      <div class="form-grid vitals-form">
        ${field("temp", `<span>Temperature (<span id="tLbl">°F</span>)</span>`, vt.temperature_f, 'placeholder="98.6"')}
        <label>Blood pressure (mmHg)<span class="bp-pair"><input id="sys" inputmode="numeric" placeholder="120" value="${vt.bp_systolic ?? ""}" aria-label="Systolic"><b>/</b><input id="dia" inputmode="numeric" placeholder="80" value="${vt.bp_diastolic ?? ""}" aria-label="Diastolic"></span></label>
        ${field("pulse", "Pulse (bpm)", vt.pulse_bpm, 'inputmode="numeric" placeholder="72"')}
        ${field("spo2", "SpO2 (%)", vt.spo2_pct, 'inputmode="numeric" placeholder="98"')}
        ${field("rr", "Respiratory rate (/min)", vt.resp_rate, 'inputmode="numeric" placeholder="16"')}
        ${field("wt", "Weight (kg)", vt.weight_kg, 'placeholder="65"')}
      </div>${n.flags?.length ? `<div class="row small" style="margin-top:10px">${flagBadges(n.flags)}</div>` : ""}</div>
    <div class="card"><h3>${ic("stethoscope")} Diagnosis and advice</h3>
      <div class="form-grid">
        <label class="wide">Diagnosis<input id="dx" maxlength="1000" value="${esc(n.diagnosis || "")}" placeholder="e.g. Viral fever"></label>
        <label class="wide">Advice for the patient<textarea id="advice" rows="3" maxlength="2000" placeholder="Rest, fluids, diet, warning signs to watch for">${esc(n.advice || "")}</textarea></label>
        <label>Follow-up<select id="fu">${[["", "Not needed"], [3, "In 3 days"], [7, "In 1 week"], [14, "In 2 weeks"], [30, "In 1 month"]].map(([d, l]) => `<option value="${d}" ${String(n.follow_up_in_days ?? "") === String(d) ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      </div></div>
    ${n.prescriptions?.length ? `<div class="card"><h3>${ic("rx")} Prescriptions from this visit</h3>${n.prescriptions.map((p) => `<div class="list-item"><div class="avatar">${ic("rx")}</div><div class="grow"><b>${esc(p.reference_no)}</b><div class="tiny muted">${p.items.map(esc).join(", ")}</div></div><span class="badge ${p.status === "signed" ? "good" : "warn"}">${esc(p.status)}</span></div>`).join("")}</div>` : ""}
    <div class="row sticky-actions">
      <button class="btn" id="saveNotes">${ic("check")} Save notes</button>
      <button class="btn" id="toRx">${ic("rx")} Save & write prescription</button>
      ${v.status === "in_progress" ? `<button class="btn primary" id="saveDone">${ic("check")} Save & complete visit</button>` : ""}
    </div>`;
  $("#back").onclick = () => SCREENS.visits();
  $$("#tUnit button").forEach((b) => (b.onclick = () => {
    if (b.dataset.u === unit) return;
    const t = num("temp");
    if (t != null) $("#temp").value = unit === "F" ? ((t - 32) * 5 / 9).toFixed(1) : (t * 9 / 5 + 32).toFixed(1);
    unit = b.dataset.u; $("#tLbl").textContent = `°${unit}`; $("#temp").placeholder = unit === "F" ? "98.6" : "37.0";
    $$("#tUnit button").forEach((x) => x.classList.toggle("on", x === b));
  }));
  const body = (complete = false) => {
    const t = num("temp");
    return { chief_complaint: $("#cc").value, findings: $("#findings").value, diagnosis: $("#dx").value, advice: $("#advice").value,
      follow_up_in_days: $("#fu").value ? +$("#fu").value : null,
      temperature_f: unit === "F" ? t : null, temperature_c: unit === "C" ? t : null,
      bp_systolic: num("sys"), bp_diastolic: num("dia"), pulse_bpm: num("pulse"), spo2_pct: num("spo2"), resp_rate: num("rr"), weight_kg: num("wt"), complete };
  };
  const save = async (complete) => {
    const r = await put(`/api/doctor/visits/${visitId}/notes`, body(complete));
    if (r.flags.length) toast(`Saved. Check: ${r.flags.map((f) => f.label).join(", ")}`, "alert"); else toast(complete ? "Visit completed. The patient can see your notes." : "Visit notes saved");
    return r;
  };
  $("#saveNotes").onclick = () => guard(async () => { await save(false); notesScreen(visitId); });
  $("#toRx").onclick = () => guard(async () => { await save(false); prescribeScreen(visitId, v); });
  const d = $("#saveDone"); if (d) d.onclick = () => guard(async () => { await save(true); SCREENS.visits(); });
}

/* patient: read-only visit notes */
async function patientNotesScreen(visitId, back = () => go("home")) {
  stopLive();
  const n = await api(`/api/patient/visits/${visitId}/notes`);
  if (!n) { toast("Your doctor hasn't added notes for this visit yet.", "info"); return; }
  view().innerHTML = pageHead("Visit notes", `${esc(n.doctor.name)} · ${esc(n.doctor.specialty)} · ${day(n.visit_date)}`, `<button class="btn ghost" id="back">← Back</button>`) + `
    <div class="card featured">
      <div class="eyebrow-sm">Diagnosis</div><h2 style="margin:4px 0 6px">${esc(n.diagnosis || "Not recorded")}</h2>
      <div class="meta"><span>${ic("chat")} ${esc(n.chief_complaint)}</span>${n.booking_ref ? `<span>${ic("calendar")} ${esc(n.booking_ref)}</span>` : ""}</div>
    </div>
    <div class="section-title">Vitals</div>
    ${vitalTiles(n.vitals, n.flags)}
    ${n.flags.length ? `<div class="notice warn small">${ic("info")}<span>Highlighted values are outside the usual adult range. Your doctor has seen them; ask them if you have questions.</span></div>` : ""}
    ${n.findings ? `<div class="card"><h3>What the doctor found</h3><p class="small" style="white-space:pre-wrap;margin:0">${esc(n.findings)}</p></div>` : ""}
    ${n.advice || n.follow_up_in_days ? `<div class="card"><h3>Doctor's advice</h3>${n.advice ? `<div class="instructions" style="white-space:pre-wrap">${esc(n.advice)}</div>` : ""}
      ${n.follow_up_in_days ? `<div class="row between" style="margin-top:12px"><span class="badge premium">${ic("later")} ${followUpText(n.follow_up_in_days)}</span><button class="btn sm" id="bookFu">${ic("calendar")} Book follow-up</button></div>` : ""}</div>` : ""}
    ${n.prescriptions.length ? `<div class="card"><h3>Prescription from this visit</h3>${n.prescriptions.map((p) => `<div class="list-item"><div class="avatar">${ic("rx")}</div><div class="grow"><b>${esc(p.reference_no)}</b><div class="tiny muted">${p.items.map(esc).join(", ")}</div></div><button class="btn sm" data-go="rx">View</button></div>`).join("")}</div>` : ""}`;
  $("#back").onclick = back;
  const fu = $("#bookFu"); if (fu) fu.onclick = () => go("book", { followUp: true });
  $$("[data-go]").forEach((b) => (b.onclick = () => go(b.dataset.go)));
}

function pastVisitCard(v) {
  const n = v.notes;
  return `<article class="card visit-card"><div class="card-head"><div class="when">${dateChip(v.scheduled_for)}<div>
      <h3>${v.doctor ? esc(v.doctor.name) : "Home visit"}</h3>
      <div class="meta">${v.doctor ? `<span>${ic("stethoscope")} ${esc(v.doctor.specialty)}</span>` : ""}<span>${ic("clock")} ${when(v.scheduled_for)}</span></div></div></div>
      <span class="badge brand">${ic("check")} Completed</span></div>
    ${n ? `<div class="instructions"><b>Diagnosis:</b> ${esc(n.diagnosis || "Not recorded")}</div>
      <div class="row small" style="margin-top:10px;gap:6px">${n.temperature_c != null ? `<span class="badge">${ic("thermo")} ${(n.temperature_c * 9 / 5 + 32).toFixed(1)} °F</span>` : ""}${n.bp ? `<span class="badge">${ic("heart")} BP ${esc(n.bp)}</span>` : ""}${n.spo2_pct != null ? `<span class="badge">SpO2 ${n.spo2_pct}%</span>` : ""}${flagBadges(n.flags)}</div>
      <div class="actions-bar"><button class="btn sm" data-vnotes="${v.id}">${ic("notes")} View visit notes</button></div>`
      : `<div class="instructions"><b>Reason:</b> ${esc(v.reason)}</div><p class="tiny muted" style="margin:8px 0 0">The doctor hasn't added notes for this visit.</p>`}</article>`;
}

async function prescribeScreen(visitId, visit) {
  const [meds, vnote] = await Promise.all([api("/api/catalog/medications"), api(`/api/doctor/visits/${visitId}/notes`).catch(() => null)]);
  const clinical = vnote ? [vnote.diagnosis, vnote.chief_complaint && `C/o ${vnote.chief_complaint}`].filter(Boolean).join(". ") : "Demo consultation";
  const dolo = meds.find((m) => m.brand_name === "Dolo") || meds[0];
  const rows = [{ medication_id: dolo.id, dosage: "1 tablet", frequency: "Every 8 hours if needed", duration_days: 2, quantity: 5, route: "oral", instructions: "As entered and approved by the licensed doctor (illustrative demo data).", refills_allowed: 0 }];
  const render = () => {
    view().innerHTML = pageHead("New prescription", `${esc(visit.patient.name)} · ${esc(visit.patient.patient_ref)}`, `<button class="btn ghost" id="back">← Visits</button>`) + `
      <div class="notice warn">${ic("info")}<span>Illustrative demo data only. This is not a medical recommendation.</span></div>
      ${vnote ? "" : `<div class="notice info">${ic("notes")}<span>Tip: write the visit notes and vitals first. The diagnosis then fills in here.</span></div>`}
      <div class="card"><label class="field">Clinical note<textarea id="note" rows="2">${esc(clinical)}</textarea></label></div>
      ${rows.map((r, i) => `<div class="card" data-row="${i}"><div class="card-head"><div class="row">${miniPill(i)}<h3>Medicine ${i + 1}</h3></div>${rows.length > 1 ? `<button class="btn ghost sm danger" data-del="${i}">${ic("x")} Remove</button>` : ""}</div>
        <div class="form-grid">
        <label class="wide">Medicine<select data-k="medication_id">${meds.map((m) => `<option value="${m.id}" ${m.id === r.medication_id ? "selected" : ""}>${esc(m.brand_name)} ${esc(m.strength)} (${esc(m.generic_name)})${m.india_schedule && m.india_schedule !== "OTC" ? ` · Schedule ${m.india_schedule}` : ""}${m.india_schedule === "X" ? " (not sold online)" : ""}</option>`).join("")}</select></label>
        <label>Dosage<input data-k="dosage" value="${esc(r.dosage)}"></label><label>Frequency<input data-k="frequency" value="${esc(r.frequency)}"></label>
        <label>Duration (days)<input type="number" min="1" data-k="duration_days" value="${r.duration_days}"></label><label>Quantity<input type="number" min="1" data-k="quantity" value="${r.quantity}"></label>
        <label>Route<input data-k="route" value="${esc(r.route)}"></label><label>Refills<input type="number" min="0" data-k="refills_allowed" value="${r.refills_allowed}"></label>
        <label class="wide">Special instructions<input data-k="instructions" value="${esc(r.instructions)}"></label></div></div>`).join("")}
      <div class="row"><button class="btn" id="addRow">${ic("pills")} Add medicine</button><button class="btn primary" id="save">Review prescription ${ic("arrow")}</button></div>`;
    $("#back").onclick = () => SCREENS.visits();
    $$("[data-row]").forEach((card) => $$("[data-k]", card).forEach((inp) => (inp.onchange = () => {
      const k = inp.dataset.k; rows[+card.dataset.row][k] = ["medication_id", "duration_days", "quantity", "refills_allowed"].includes(k) ? +inp.value : inp.value;
    })));
    $$("[data-del]").forEach((b) => (b.onclick = () => { rows.splice(+b.dataset.del, 1); render(); }));
    $("#addRow").onclick = () => { rows.push({ ...rows[0], medication_id: (meds.find((m) => !rows.some((r) => r.medication_id === m.id)) || meds[0]).id, quantity: 10, frequency: "Once daily", instructions: "" }); render(); };
    $("#save").onclick = () => guard(async () => reviewAndSign(await post("/api/prescriptions", { visit_id: visitId, diagnosis_note: $("#note").value, items: rows })));
  };
  render();
}

function reviewAndSign(rx) {
  view().innerHTML = pageHead("Review & sign", `${esc(rx.reference_no)} · not visible to the patient until signed`) + `
    <div class="card featured"><div class="card-head"><div><h2>${esc(rx.patient.name)}</h2><div class="meta"><span>${ic("stethoscope")} ${esc(rx.doctor.name)}</span><span>${ic("id")} ${esc(rx.doctor.license_no)}</span></div></div><span class="badge warn">Draft</span></div>
      ${rx.items.map((i, n) => `<div class="list-item">${miniPill(n)}<div class="grow"><div class="row between"><b>${esc(i.medicine)} ${esc(i.strength)}</b><span class="badge brand">${i.quantity} ${esc(i.unit)}</span></div>
        <div class="small muted">${esc(i.dosage)} · ${esc(i.frequency)} · ${i.duration_days} days · ${esc(i.route)}</div>${i.instructions ? `<div class="tiny muted">${esc(i.instructions)}</div>` : ""}</div></div>`).join("")}
      <hr class="soft"><label class="check"><input type="checkbox" id="ok"><span>I have reviewed this prescription and authorise it with my electronic signature.</span></label>
      <button class="btn primary block" id="sign" style="margin-top:14px">${ic("sign")} Sign & send to patient</button></div>`;
  $("#sign").onclick = () => guard(async () => {
    const signed = await post(`/api/prescriptions/${rx.id}/sign`, { confirm_reviewed: $("#ok").checked });
    toast(`Signed. ${signed.patient.name} has been notified.`); go("prescriptions");
  });
}

SCREENS.prescriptions = async () => {
  const list = await api("/api/doctor/prescriptions");
  view().innerHTML = pageHead("Prescriptions", "Every prescription you've written, with a tamper-evident audit trail.") + (list.map((rx) => `<article class="card"><div class="card-head"><div class="row"><div class="avatar">${esc(initials(rx.patient.name))}</div><div><h3>${esc(rx.patient.name)}</h3><div class="tiny muted">${esc(rx.reference_no)} · ${day(rx.consultation_date)}</div></div></div>
      <span class="badge ${rx.status === "signed" ? "good" : rx.status === "draft" ? "warn" : ""}">${esc(rx.status)}</span></div>
    <div class="row small">${rx.items.map((i) => `<span class="badge">${esc(i.medicine)} × ${i.quantity}</span>`).join("")}</div>
    <div class="actions-bar">${rx.status === "draft" ? `<button class="btn primary sm" data-sign="${rx.id}">${ic("sign")} Review & sign</button>` : ""}<button class="btn ghost sm" data-audit="${rx.id}">${ic("audit")} Audit trail</button></div><div id="audit${rx.id}"></div></article>`).join("") || empty("file", "No prescriptions yet", "Complete a home visit to write one."));
  $$("[data-sign]").forEach((b) => (b.onclick = () => reviewAndSign(list.find((r) => r.id === +b.dataset.sign))));
  $$("[data-audit]").forEach((b) => (b.onclick = () => guard(async () => {
    const a = await api(`/api/audit/prescriptions/${b.dataset.audit}`);
    $(`#audit${b.dataset.audit}`).innerHTML = `<div class="notice ${a.chain_valid ? "good" : "bad"} small">${ic(a.chain_valid ? "shield" : "alert")}<span>Audit chain ${a.chain_valid ? "intact and verified" : "BROKEN"}</span></div>` +
      `<ul class="timeline">${a.entries.map((e) => `<li class="done"><span class="node">${ic("check")}</span><b class="small">${esc(e.action)}</b><div class="tiny muted">${when(e.at)} · ${esc(e.actor_role)}</div></li>`).join("")}</ul>`;
  })));
};

SCREENS.clarifications = async () => {
  const list = await api("/api/doctor/clarifications");
  view().innerHTML = pageHead("Clarifications", "Questions from pharmacists and quantity requests from patients.") + (list.map((c) => `<article class="card"><div class="card-head"><div class="row"><div class="avatar">${ic("chat")}</div><div><h3 style="text-transform:capitalize">${esc(c.reason.replaceAll("_", " "))}</h3><div class="tiny muted">${when(c.at)}</div></div></div>
    <span class="badge ${c.status === "open" ? "warn" : "good"}">${esc(c.status)}</span></div><div class="instructions">${esc(c.message)}</div>
    ${c.response ? `<div class="notice good small">${ic("check")}<span>Your response: ${esc(c.response)}</span></div>` : `
    <label class="field" style="margin-top:12px">Your response<textarea id="resp${c.id}" rows="2" placeholder="Reply to the pharmacist or patient"></textarea></label>
    <div class="actions-bar">${c.reason === "partial_quantity_authorization" ? `<button class="btn primary sm" data-r="${c.id}" data-auth="1">${ic("check")} Authorise smaller quantity</button><button class="btn sm" data-r="${c.id}" data-auth="0">Decline</button>` : `<button class="btn primary sm" data-r="${c.id}">Send response</button>`}</div>
    <p class="tiny muted">To change the prescription itself, create a signed amendment.</p>`}</article>`).join("") || empty("chat", "No clarification requests", "You're all caught up."));
  $$("[data-r]").forEach((b) => (b.onclick = () => guard(async () => {
    await post(`/api/clarifications/${b.dataset.r}/respond`, { response: $(`#resp${b.dataset.r}`).value || "Reviewed.", authorize: b.dataset.auth === undefined ? null : b.dataset.auth === "1" });
    toast("Response sent"); SCREENS.clarifications();
  })));
};

/* ------------------------------------------------------- privacy (DPDP) */
async function consentScreen() {
  const n = await api("/api/privacy/notice");
  const care = n.purposes.care, rem = n.purposes.reminders;
  view().innerHTML = `<section class="hero"><div class="eyebrow">Welcome to Triyana</div><h1>Your health data, your choice</h1>
      <p>Before you book a doctor or order medicines, please read how we use your information. You can change your mind at any time under Privacy & consent.</p></section>
    <div class="split"><div>
      <div class="card"><h3>What we collect</h3><ul class="small" style="margin:8px 0 0;padding-left:18px">${n.what_we_collect.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>
      <div class="card"><h3>How long we keep it</h3><p class="small muted" style="margin:6px 0 0">${esc(n.retention)}</p></div>
      <div class="card"><h3>Your rights</h3><ul class="small" style="margin:8px 0 0;padding-left:18px">${n.rights.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
        <p class="tiny muted" style="margin:10px 0 0">Grievance officer: ${esc(n.grievance_officer.name)} · ${esc(n.grievance_officer.email)} · replies within ${n.grievance_officer.respond_within_days} days</p></div>
    </div><aside class="sticky"><div class="card featured">
      <h3>Your consent</h3>
      <label class="check" style="margin-top:12px"><input type="checkbox" id="cCare"> <span><b>${esc(care.title)}</b> <span class="badge info">Needed</span><br><span class="small muted">${esc(care.body)}</span></span></label>
      <label class="check" style="margin-top:12px"><input type="checkbox" id="cRem"> <span><b>${esc(rem.title)}</b> <span class="badge">Optional</span><br><span class="small muted">${esc(rem.body)}</span></span></label>
      <button class="btn primary block" id="consentAgree" style="margin-top:16px" disabled>${ic("check")} Agree and continue</button>
      <button class="btn ghost block" id="consentLater" style="margin-top:6px">Not now</button>
      <p class="tiny muted" style="text-align:center;margin:8px 0 0">Under India's Digital Personal Data Protection Act, 2023 · notice ${esc(n.version)}</p>
    </div></aside></div>`;
  $("#cCare").onchange = (e) => ($("#consentAgree").disabled = !e.target.checked);
  $("#consentAgree").onclick = () => guard(async () => {
    await post("/api/consents", { purpose: "care", granted: true });
    if ($("#cRem").checked) await post("/api/consents", { purpose: "reminders", granted: true });
    toast("Thanks. You can change this any time under Privacy & consent."); go("home");
  });
  $("#consentLater").onclick = () => { toast("You can look around, but booking and ordering need your consent.", "info"); go("home"); };
}

SCREENS.privacy = async () => {
  const [c, n] = await Promise.all([api("/api/consents"), api("/api/privacy/notice")]);
  const row = (key) => {
    const pp = n.purposes[key]; const on = c.consents[key];
    return `<div class="list-item"><div class="grow"><div class="row between"><b>${esc(pp.title)}</b><span class="badge ${on ? "good" : ""}">${on ? "On" : "Off"}</span></div>
      <div class="small muted">${esc(pp.body)}</div>${key === "care" && on ? `<div class="tiny muted" style="margin-top:4px">Turning this off stops new bookings and orders. Records the law requires us to keep stay safe.</div>` : ""}</div>
      <button class="btn sm ${on ? "danger" : "primary"}" data-consent="${key}" data-on="${on ? 0 : 1}">${on ? "Withdraw" : "Give consent"}</button></div>`;
  };
  view().innerHTML = pageHead("Privacy & consent", "Your rights under India's Digital Personal Data Protection Act, 2023") + `
    <div class="card"><h3>Your consents</h3>${Object.keys(n.purposes).map(row).join("")}</div>
    <div class="grid">
      <div class="card"><h3>Get a copy of your data</h3><p class="small muted">Visits, prescriptions, orders and consents, as a file.</p><button class="btn" id="export">${ic("file")} Download my data</button></div>
      <div class="card"><h3>Ask us to erase or correct data</h3><div class="seg" style="margin:6px 0 10px"><button class="on" data-kind="erasure">Erase</button><button data-kind="correction">Correct</button></div>
        <textarea id="dpDetails" rows="2" style="width:100%" placeholder="What should we erase or correct?"></textarea><button class="btn" id="dpSend" style="margin-top:10px">Send request</button></div>
    </div>
    <div class="card"><h3>Consent history</h3>${c.history.length ? c.history.map((h) => `<div class="row between small" style="padding:6px 0;border-bottom:1px solid var(--line)"><span>${esc(n.purposes[h.purpose]?.title || h.purpose)}</span><span class="${h.granted ? "" : "muted"}">${h.granted ? "Given" : "Withdrawn"} · ${when(h.at)}</span></div>`).join("") : `<p class="small muted">No consents recorded yet.</p>`}
      <p class="tiny muted" style="margin:10px 0 0">Grievance officer: ${esc(n.grievance_officer.name)} · ${esc(n.grievance_officer.email)}. If you're not satisfied, you can complain to the Data Protection Board of India.</p></div>`;
  $$("[data-consent]").forEach((b) => (b.onclick = () => guard(async () => { await post("/api/consents", { purpose: b.dataset.consent, granted: b.dataset.on === "1" }); toast(b.dataset.on === "1" ? "Consent given" : "Consent withdrawn"); SCREENS.privacy(); })));
  let kind = "erasure";
  $$("[data-kind]").forEach((b) => (b.onclick = () => { kind = b.dataset.kind; $$("[data-kind]").forEach((x) => x.classList.toggle("on", x === b)); }));
  $("#dpSend").onclick = () => guard(async () => { const r = await post("/api/patient/data-requests", { kind, details: $("#dpDetails").value }); toast(`Request ${r.reference} sent. We'll reply within ${r.respond_within_days} days.`); $("#dpDetails").value = ""; });
  $("#export").onclick = () => guard(async () => {
    const data = await api("/api/patient/my-data");
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    a.download = "triyana-my-data.json"; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  });
};

/* ------------------------------------------------------------ pharmacist */
SCREENS.queue = async () => {
  const orders = await api("/api/pharmacy/orders");
  const open = orders.filter((o) => ["prescription_received", "pharmacist_reviewing", "awaiting_clarification"].includes(o.status)).length;
  view().innerHTML = `<section class="hero"><div class="eyebrow">${esc(state.name)}</div><h1>Prescription order queue</h1><p>Validate prescriptions, review requested quantities, then approve, adjust or reject as legally appropriate.</p>
    <div class="stats"><div class="stat"><b>${open}</b><span>Awaiting review</span></div><div class="stat"><b>${orders.filter((o) => ["order_accepted", "preparing"].includes(o.status)).length}</b><span>To prepare</span></div><div class="stat"><b>${orders.filter((o) => o.status === "delivered" || o.status === "picked_up").length}</b><span>Completed</span></div></div></section>` +
    (orders.map((o) => `<article class="card" data-order="${o.id}"><div class="card-head"><div class="row"><div class="avatar">${esc(initials(o.patient.name))}</div><div><h3>${esc(o.order_no)} · ${esc(o.patient.name)}</h3>
      <div class="meta"><span>${ic("rx")} ${esc(o.prescription.reference_no)}</span><span>${ic("stethoscope")} ${esc(o.prescription.doctor)}</span><span>${ic(o.fulfillment === "pickup" ? "bag" : "truck")} ${esc(o.fulfillment)}${o.delivery_option ? " · " + esc(o.delivery_option.replace("_", " ")) : ""}</span></div></div></div>
      <span class="badge brand">${esc(o.status_label)}</span></div>
      <div class="notice ${o.prescription.valid ? "good" : "bad"} small">${ic(o.prescription.valid ? "shield" : "alert")}<span>${o.prescription.valid ? `Signature, licence (${esc(o.prescription.license_no)}) and validity verified` : "Invalid prescription: " + esc(o.prescription.issue)}</span></div>
      <div class="table-wrap"><table><tr><th>Medicine</th><th>Prescribed</th><th>Requested</th><th>Approve</th></tr>${o.items.map((i) => `<tr><td><b>${esc(i.medicine)}</b></td><td>${i.prescribed_quantity}</td>
        <td>${i.requested_quantity}${i.requested_quantity < i.prescribed_quantity ? ` <span class="badge warn">partial</span>` : ""}</td>
        <td>${i.approved_quantity ?? (["prescription_received", "pharmacist_reviewing"].includes(o.status) ? `<input type="number" min="0" max="${i.requested_quantity}" value="${i.requested_quantity}" data-adj="${i.id}" style="width:80px">` : "—")}</td></tr>`).join("")}</table></div>
      ${o.status === "pharmacist_reviewing" && o.items.some((i) => i.india_schedule?.register_required) ? `<label class="check notice warn small" style="margin-top:12px"><input type="checkbox" data-h1> <span>I've entered the Schedule H1 medicines (${o.items.filter((i) => i.india_schedule?.register_required).map((i) => esc(i.medicine)).join(", ")}) in the Schedule H1 register: patient, doctor, medicine and quantity.</span></label>` : ""}
      <div class="row between" style="margin-top:12px"><span class="small muted">Total ${money(o.price.total)} · payment ${esc(o.payment.status)}</span><div class="actions-bar" style="margin:0">${pharmacistActions(o)}</div></div><div class="clar"></div></article>`).join("") || empty("inbox", "No orders yet", "New prescription orders will arrive here."));
  $$("[data-order]").forEach((card) => {
    const id = +card.dataset.order; const o = orders.find((x) => x.id === id);
    $$("[data-x]", card).forEach((b) => (b.onclick = () => guard(async () => {
      const x = b.dataset.x;
      if (["start-review", "prepare", "ready"].includes(x)) await post(`/api/pharmacy/orders/${id}/${x}`);
      else if (x === "approve") {
        const adj = {}; let changed = false;
        $$("[data-adj]", card).forEach((inp) => { const it = o.items.find((i) => i.id === +inp.dataset.adj); adj[inp.dataset.adj] = +inp.value; if (+inp.value !== it.requested_quantity) changed = true; });
        const h1 = !!$("[data-h1]", card)?.checked;
        await post(`/api/pharmacy/orders/${id}/review`, changed ? { decision: "adjust", notes: prompt("Note for the patient about the adjustment:") || "Quantity adjusted by pharmacist", adjustments: adj, h1_register_confirmed: h1 } : { decision: "approve", notes: "Approved by pharmacist", h1_register_confirmed: h1 });
      } else if (x === "reject") {
        const notes = prompt("Reason for rejection (shown to the patient):"); if (!notes) return;
        await post(`/api/pharmacy/orders/${id}/review`, { decision: "reject", notes });
      } else if (x === "clarify") {
        $(".clar", card).innerHTML = `<div class="card" style="margin:14px 0 0;background:var(--surface-2);box-shadow:none"><div class="form-grid"><label>Reason<select id="cr${id}">${["quantity_not_dispensable", "medicine_unavailable", "incomplete_prescription", "substitution_requires_authorization", "refill_authorization"].map((r) => `<option value="${r}">${r.replaceAll("_", " ")}</option>`).join("")}</select></label>
          <label class="wide">Message to prescriber<input id="cm${id}" placeholder="Please clarify…"></label></div><div class="row" style="margin-top:10px"><button class="btn primary sm" id="cs${id}">Send securely</button></div></div>`;
        $(`#cs${id}`).onclick = () => guard(async () => { await post(`/api/pharmacy/orders/${id}/clarify`, { reason: $(`#cr${id}`).value, message: $(`#cm${id}`).value || "Please clarify." }); toast("Sent to prescriber"); SCREENS.queue(); });
        return;
      } else if (x === "pickup") {
        await post(`/api/orders/${id}/handover`, { recipient_name: prompt("Collected by:") || "Patient", id_verified: confirm("Have you verified the patient's photo ID?") });
      } else if (x === "cancel") {
        if (!confirm("Cancel and refund this order?")) return;
        await post(`/api/orders/${id}/cancel`, { reason: "Cancelled by pharmacy" });
      }
      SCREENS.queue();
    })));
  });
};

function pharmacistActions(o) {
  const b = (x, l, cls = "", i = "") => `<button class="btn sm ${cls}" data-x="${x}">${i ? ic(i) : ""} ${l}</button>`;
  switch (o.status) {
    case "prescription_received": return b("start-review", "Start review", "primary", "shield") + b("reject", "Reject", "danger");
    case "pharmacist_reviewing": return b("approve", "Approve", "primary", "check") + b("clarify", "Ask prescriber", "", "chat") + b("reject", "Reject", "danger");
    case "order_accepted": return b("prepare", "Start preparing", "primary", "pills") + b("cancel", "Cancel & refund", "ghost danger");
    case "preparing": return b("ready", "Dispense & mark ready", "primary", "bag") + b("cancel", "Cancel & refund", "ghost danger");
    case "ready_for_pickup": return o.fulfillment === "pickup" ? b("pickup", "Hand over", "primary", "id") : `<span class="badge info">${ic("truck")} Awaiting courier</span>`;
    default: return "";
  }
}

/* ------------------------------------------------------------ drone map */
const KM_LAT = 111.0;
function routeMap({ points, lines = [], zones = [], drone = null }) {
  const lat0 = points.reduce((a, p) => a + p.lat, 0) / points.length, kx = KM_LAT * Math.cos((lat0 * Math.PI) / 180);
  const X0 = (lng) => lng * kx, Y0 = (lat) => -lat * KM_LAT;
  const xs = points.map((p) => X0(p.lng)), ys = points.map((p) => Y0(p.lat));
  let minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const pad = Math.max(1.2, Math.max(maxX - minX, maxY - minY) * 0.14);
  minX -= pad; maxX += pad * 2.4; minY -= pad; maxY += pad * 1.4; // room for labels and legend
  let w = maxX - minX, h = maxY - minY;
  if (w < h * 1.6) { const d = h * 1.6 - w; minX -= d / 2; w = h * 1.6; }
  if (h < w / 2.2) { const d = w / 2.2 - h; minY -= d / 2; h = w / 2.2; }
  const X = (lng) => X0(lng) - minX, Y = (lat) => Y0(lat) - minY, pc = (v, t) => `${((v / t) * 100).toFixed(2)}%`;
  const zoneSvg = zones.map((z) => `<circle class="zone ${z.kind}" cx="${X(z.lng)}" cy="${Y(z.lat)}" r="${z.radius_km}" vector-effect="non-scaling-stroke"><title>${esc(z.name)} · ${z.kind} zone</title></circle>`).join("");
  const lineSvg = lines.map((l) => `<line class="route ${l.cls || ""}" x1="${X(l.a.lng)}" y1="${Y(l.a.lat)}" x2="${X(l.b.lng)}" y2="${Y(l.b.lat)}" vector-effect="non-scaling-stroke"/>`).join("");
  const pins = points.map((p) => `<div class="mpin ${p.cls || ""} ${p.big ? "big" : ""} ${X(p.lng) / w > 0.55 ? "left" : ""}" style="left:${pc(X(p.lng), w)};top:${pc(Y(p.lat), h)}" title="${esc(p.name || p.label || "")}"><i></i>${p.label ? `<span>${esc(p.label)}</span>` : ""}</div>`).join("");
  const dr = drone ? `<div class="mdrone" style="left:${pc(X(drone.lng), w)};top:${pc(Y(drone.lat), h)}">${ic("drone")}</div>` : "";
  return `<div class="map" style="aspect-ratio:${(w / h).toFixed(3)}"><svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">${zoneSvg}${lineSvg}</svg>${pins}${dr}
    <div class="map-legend"><span><i class="lg green"></i>Green</span><span><i class="lg yellow"></i>Yellow · ATC permission</span><span><i class="lg red"></i>Red · no-fly</span></div></div>`;
}

const MODE = { drone: ["drone", "Drone"], road: ["truck", "Road courier"] };
const STATUS_CLS = { scheduled: "info", in_flight: "brand", in_transit: "brand", arrived: "warn", delivered: "good" };
const checkList = (checks) => `<ul class="checks">${checks.map((c) => `<li class="${c.ok ? "ok" : "no"}"><span class="ck">${ic(c.ok ? "check" : "x")}</span><div><b>${esc(c.label)}</b><div class="small muted">${esc(c.detail)}</div></div></li>`).join("")}</ul>`;

function missionMap(m) {
  const pts = [{ ...m.origin, label: shortName(m.origin.name), cls: "origin" }, { ...m.destination, label: shortName(m.destination.name), cls: "dest", big: true }];
  return routeMap({ points: pts, zones: m.zones, lines: [{ a: m.origin, b: m.destination, cls: m.mode }], drone: ["in_flight", "in_transit"].includes(m.status) ? m.position : null });
}

function missionPanels(m) {
  const v = m.vehicle || {}, c = m.compliance || {};
  return `<div class="card"><div class="card-head"><h3>${ic(MODE[m.mode][0])} ${m.mode === "drone" ? "Drone flight" : "Road courier"}</h3><span class="badge ${STATUS_CLS[m.status] || ""}">${esc(m.status_label)}</span></div>
    ${missionMap(m)}
    ${m.fallback_reason ? `<div class="notice warn">${ic("truck")}<span><b>Sent by road.</b> ${esc(m.fallback_reason)}</span></div>` : ""}
    <div class="kv">${m.mode === "drone" ? `<div><span>Drone</span><b>${esc(v.uin)}</b><small>${esc(v.model)} · ${esc(v.category)}</small></div>
      <div><span>Remote pilot</span><b>${esc(String(c.remote_pilot).split(" (")[0])}</b><small>${esc((String(c.remote_pilot).split("(")[1] || "").replace(")", ""))}</small></div>
      <div><span>Airspace</span><b>${esc(c.zone)} zone</b><small>${c.permission_ref ? `ATC permission ${esc(c.permission_ref)}` : `Max ${c.max_altitude_m} m altitude`}</small></div>`
      : `<div><span>Courier</span><b>${esc(v.courier)}</b><small>${esc(v.vehicle)}</small></div>`}
      <div><span>Distance</span><b>${m.distance_km} km</b><small>${mins(m.duration_minutes)} ${m.mode === "drone" ? "flight" : "drive"}</small></div></div>
  </div>`;
}

function missionScreen(title, sub, m, back, actions = "") {
  const pct = Math.round(m.progress * 100);
  const evs = [...(m.events || [])].reverse();
  view().innerHTML = pageHead(title, sub, back ? `<button class="btn ghost" id="back">← All deliveries</button>` : "") + `
    <section class="hero"><div class="eyebrow">${ic(MODE[m.mode][0])} ${MODE[m.mode][1]} · ${esc(m.ref)}</div>
      <h1>${esc(m.status_label)}</h1><p>${esc(shortName(m.origin.name))} → ${esc(shortName(m.destination.name))}</p>
      <div class="progress"><i style="width:${m.status === "delivered" ? 100 : pct}%"></i></div>
      <div class="stats"><div class="stat"><b>${m.status === "delivered" ? time(m.delivered_at) : time(m.eta)}</b><span>${m.status === "delivered" ? "Delivered at" : "Estimated arrival"}</span></div>
        <div class="stat"><b>${m.distance_km} km</b><span>Distance</span></div><div class="stat"><b>${mins(m.duration_minutes)}</b><span>${m.mode === "drone" ? "Flight time" : "Drive time"}</span></div>
        ${m.cold_chain ? `<div class="stat"><b>${m.temperature_log.length ? m.temperature_log[m.temperature_log.length - 1].celsius + " °C" : "2–8 °C"}</b><span>Cold chain</span></div>` : ""}</div>
      ${actions ? `<div class="actions">${actions}</div>` : ""}</section>
    <div class="split"><div>${missionPanels(m)}
      <div class="card"><h3>Drone eligibility checks</h3><p class="small muted" style="margin:4px 0 0">Checked against India's Drone Rules 2021 before booking.</p>${checkList(m.checks)}</div></div>
    <aside class="sticky"><div class="card"><h3>Journey</h3><ul class="timeline">${evs.map((e, i) => `<li class="done ${i === 0 && m.status !== "delivered" ? "current" : ""}"><span class="node">${ic("check")}</span><b>${esc(e.note)}</b><div class="small muted">${time(e.at)}</div></li>`).join("")}</ul></div>
      ${m.cold_chain ? `<div class="card"><h3>${ic("snow")} Temperature log</h3>${m.temperature_log.map((t) => `<div class="list-item"><div class="grow small">${time(t.at)}</div><b>${t.celsius} °C</b><span class="badge good">In range</span></div>`).join("") || `<p class="small muted">Logging starts at take-off.</p>`}</div>` : ""}
      ${m.received_by ? `<div class="notice good">${ic("check")}<span>Received by ${esc(m.received_by)}</span></div>` : ""}
    </aside></div>`;
  if (back) $("#back").onclick = back;
  if (["in_flight", "in_transit"].includes(m.status)) state.poll = setInterval(() => refreshMission(m.id), 10000);
}

/* -------------------------------------------------------------- hospital */
const CATS = [["medicines", "Medicines", "pills"], ["blood", "Blood units", "alert"], ["vaccines", "Vaccines", "snow"], ["lab_samples", "Lab samples", "file"], ["antivenom", "Anti-snake venom", "shield"]];
const URG = [["routine", "Routine"], ["urgent", "Urgent"], ["emergency", "Emergency"]];

SCREENS.shipments = async () => {
  const list = await api("/api/shipments");
  const active = list.filter((s) => s.mission.status !== "delivered");
  const byDrone = list.filter((s) => s.mission.mode === "drone").length;
  const isHosp = state.role === "hospital";
  view().innerHTML = `<section class="hero"><div class="eyebrow">${esc(state.name)}</div><h1>${isHosp ? "Hospital deliveries" : "Drone shipments to hospitals"}</h1>
      <p>${isHosp ? "Medicines, blood, vaccines and samples between pharmacies and hospitals. Drone where India's Drone Rules allow it, road courier everywhere else." : "Consignments hospitals have requested from your pharmacy."}</p>
      <div class="stats"><div class="stat"><b>${active.length}</b><span>In progress</span></div><div class="stat"><b>${byDrone}</b><span>By drone</span></div><div class="stat"><b>${list.length - byDrone}</b><span>By road</span></div></div>
      ${isHosp ? `<div class="actions"><button class="btn primary" data-go="send">${ic("drone")} Send or request</button><button class="btn" data-go="coverage">${ic("pin")} Drone coverage</button></div>` : ""}</section>` +
    (list.map((s) => `<article class="card lift ship" data-ship="${s.id}"><div class="card-head"><div class="row"><div class="pill sm ${s.mission.mode === "drone" ? "" : "c2"}">${ic(MODE[s.mission.mode][0])}</div>
        <div><h3>${esc(s.category_label)} · ${esc(s.ref)}</h3><div class="meta"><span>${esc(shortName(s.origin_name))} → ${esc(shortName(s.destination))}</span></div></div></div>
        <span class="badge ${STATUS_CLS[s.mission.status] || ""}">${esc(s.mission.status_label)}</span></div>
      <div class="row small"><span class="badge">${ic(MODE[s.mission.mode][0])} ${MODE[s.mission.mode][1]}</span>${s.urgency !== "routine" ? `<span class="badge bad">${ic("bolt")} ${esc(s.urgency)}</span>` : ""}
        ${s.cold_chain ? `<span class="badge info">${ic("snow")} 2–8 °C</span>` : ""}<span class="badge">${s.weight_kg} kg</span><span class="badge">${ic("clock")} ${s.mission.status === "delivered" ? "Delivered" : "ETA " + time(s.mission.eta)}</span></div>
      ${s.mission.fallback_reason ? `<div class="tiny muted" style="margin-top:8px">${ic("info")} ${esc(s.mission.fallback_reason)}</div>` : ""}</article>`).join("") ||
      empty("drone", "No deliveries yet", isHosp ? "Request medicines from a pharmacy or send to another hospital." : "Hospital requests from your pharmacy will appear here."));
  $$("[data-go]").forEach((b) => (b.onclick = () => go(b.dataset.go)));
  $$("[data-ship]").forEach((c) => (c.onclick = () => guard(() => shipmentDetail(list.find((s) => s.id === +c.dataset.ship)))));
};

async function refreshMission(id) {
  if (!["shipments", "orders"].includes(state.tab) || !state.ctx.shipment) return;
  const list = await api("/api/shipments");
  const s = list.find((x) => x.id === state.ctx.shipment);
  if (s) { clearInterval(state.poll); shipmentDetail(s); }
}

function shipmentDetail(s) {
  clearInterval(state.poll);
  state.ctx.shipment = s.id;
  const m = s.mission, receiver = state.role === "hospital" && state.hospitalId === s.dest_hospital_id;
  const btn = (a, label, icon, cls = "") => `<button class="btn ${cls}" data-act="${a}">${ic(icon)} ${label}</button>`;
  let actions = "";
  if (m.status === "scheduled") actions = btn("launch", m.mode === "drone" ? "Simulate take-off" : "Simulate pickup", MODE[m.mode][0], "primary") + (m.mode === "drone" ? btn("divert", "Weather hold: send by road", "truck") : "");
  if (["in_flight", "in_transit"].includes(m.status)) actions = btn("arrive", m.mode === "drone" ? "Simulate landing" : "Simulate arrival", "pin", "primary");
  if (m.status === "arrived" && receiver) actions = btn("confirm", "Confirm received", "check", "primary");
  if (m.status === "arrived" && !receiver) actions = `<span class="badge">Waiting for ${esc(shortName(s.destination))} to confirm</span>`;
  missionScreen(`${s.category_label} · ${s.ref}`, `${esc(s.contents)} · ${s.weight_kg} kg${s.urgency !== "routine" ? ` · ${esc(s.urgency)}` : ""}`, m, () => { state.ctx.shipment = null; SCREENS.shipments(); }, actions);
  $$("[data-act]").forEach((b) => (b.onclick = () => guard(async () => {
    const a = b.dataset.act; let body = {};
    if (a === "divert") body = { reason: prompt("Why can't the drone fly?", "Weather hold: rain at the launch pad") || "Weather hold before take-off." };
    if (a === "confirm") {
      const who = prompt("Received by (name)", state.name.split(" (")[0]); if (!who) return;
      body = { received_by: who, temperature_ok: s.cold_chain ? confirm("Does the cold-chain indicator show 2–8 °C?") : null };
    }
    const nm = await post(`/api/missions/${m.id}/${a}`, body);
    toast({ launch: "On its way", arrive: "Arrived", divert: "Switched to road courier", confirm: "Receipt confirmed" }[a]);
    shipmentDetail({ ...s, mission: nm });
  })));
}

SCREENS.send = async () => {
  const net = await api("/api/hospital/network");
  const me = net.hospital;
  const f = state.ctx.sendForm || { dir: "in", origin: net.pharmacies.find((p) => p.coverage.drone)?.id, dest: net.hospitals.find((h) => h.coverage.drone)?.id, category: "medicines", contents: "", weight: 1.0, urgency: "urgent", cold: false, controlled: false };
  state.ctx.sendForm = f;
  const body = () => ({ origin_kind: f.dir === "in" ? "pharmacy" : "hospital", origin_id: f.dir === "in" ? +f.origin : me.id, dest_hospital_id: f.dir === "in" ? me.id : +f.dest,
    category: f.category, contents: f.contents, weight_kg: +f.weight || 0.1, cold_chain: f.cold, controlled: f.controlled, urgency: f.urgency });
  const opts = (rows, sel) => rows.map((r) => `<option value="${r.id}" ${+sel === r.id ? "selected" : ""}>${esc(shortName(r.name))} · ${r.coverage.distance_km} km${r.coverage.drone ? " · drone" : ""}</option>`).join("");
  view().innerHTML = pageHead("Send or request", `From ${esc(shortName(me.name))}`) + `<div class="split"><div>
    <div class="card"><div class="step-label"><span class="n">1</span><h3>Route</h3></div>
      <div class="seg"><button class="${f.dir === "in" ? "on" : ""}" data-dir="in">${ic("store")} Pharmacy → my hospital</button><button class="${f.dir === "out" ? "on" : ""}" data-dir="out">${ic("drone")} My hospital → another hospital</button></div>
      <label class="field" style="margin-top:14px">${f.dir === "in" ? "From pharmacy" : "To hospital"}
        <select id="place">${f.dir === "in" ? opts(net.pharmacies, f.origin) : opts(net.hospitals, f.dest)}</select></label></div>
    <div class="card"><div class="step-label"><span class="n">2</span><h3>What's going</h3></div>
      <div class="choice-grid">${CATS.map(([k, l, i]) => `<button class="choice ${f.category === k ? "on" : ""}" data-cat="${k}"><span class="ico">${ic(i)}</span><div><b>${l}</b>${["blood", "vaccines"].includes(k) ? "<span>Always 2–8 °C</span>" : ""}</div></button>`).join("")}</div>
      <div class="form-grid" style="margin-top:14px"><label class="wide">Contents<input id="contents" value="${esc(f.contents)}" placeholder="e.g. 4 × insulin pens, 2 units O-negative blood"></label>
        <label>Packed weight (kg)<input id="weight" type="number" step="0.1" min="0.1" max="50" value="${f.weight}"></label></div>
      <label class="check" style="margin-top:12px"><input type="checkbox" id="cold" ${f.cold || ["blood", "vaccines"].includes(f.category) ? "checked" : ""} ${["blood", "vaccines"].includes(f.category) ? "disabled" : ""}><span>Needs cold chain (2–8 °C)</span></label>
      <label class="check" style="margin-top:8px"><input type="checkbox" id="controlled" ${f.controlled ? "checked" : ""}><span>Contains controlled medicines (needs ID check, goes by road)</span></label></div>
    <div class="card"><div class="step-label"><span class="n">3</span><h3>Urgency</h3></div><div class="seg">${URG.map(([k, l]) => `<button class="${f.urgency === k ? "on" : ""}" data-urg="${k}">${l}</button>`).join("")}</div></div>
  </div><aside class="sticky"><div class="card featured" id="quote"><div class="skeleton" style="height:200px"></div></div></aside></div>`;
  $$("[data-dir]").forEach((b) => (b.onclick = () => { f.dir = b.dataset.dir; SCREENS.send(); }));
  $$("[data-cat]").forEach((b) => (b.onclick = () => { f.category = b.dataset.cat; SCREENS.send(); }));
  $$("[data-urg]").forEach((b) => (b.onclick = () => { f.urgency = b.dataset.urg; SCREENS.send(); }));
  $("#place").onchange = (e) => { if (f.dir === "in") f.origin = e.target.value; else f.dest = e.target.value; quote(); };
  $("#contents").oninput = (e) => (f.contents = e.target.value);
  $("#weight").oninput = (e) => { f.weight = e.target.value; clearTimeout(f.t); f.t = setTimeout(quote, 350); };
  $("#cold").onchange = (e) => { f.cold = e.target.checked; quote(); };
  $("#controlled").onchange = (e) => { f.controlled = e.target.checked; quote(); };
  async function quote() {
    const box = $("#quote"); if (!box) return;
    try {
      const q = await post("/api/shipments/quote", body());
      box.innerHTML = `<div class="row between"><h3>${q.eligible ? "Drone can fly this" : "Goes by road"}</h3><span class="badge ${q.eligible ? "good" : "warn"}">${ic(q.eligible ? "drone" : "truck")} ${q.eligible ? "Drone" : "Road"}</span></div>
        <div class="kv two" style="margin-top:12px"><div><span>By drone</span><b>${q.eligible ? mins(q.flight_minutes + (q.needs_permission ? 20 : 5)) : "—"}</b><small>${q.eligible ? `${esc(q.drone.uin)}` : "Not eligible"}</small></div>
          <div><span>By road</span><b>${mins(q.road_minutes)}</b><small>${q.distance_km} km</small></div></div>
        ${q.needs_permission ? `<div class="notice info small">${ic("info")}<span>Crosses a yellow zone. ATC permission is requested automatically (about 15 min).</span></div>` : ""}
        ${checkList(q.checks)}
        <button class="btn primary block" id="book" style="margin-top:12px">${ic(q.eligible ? "drone" : "truck")} ${q.eligible ? "Book drone" : "Book road courier"}</button>
        ${q.eligible ? `<button class="btn ghost block" id="bookRoad" style="margin-top:6px">Send by road instead</button>` : ""}`;
      const book = (mode) => guard(async () => {
        if (!f.contents.trim()) { $("#contents").focus(); throw new Error("Describe what is being sent."); }
        const s = await post("/api/shipments", { ...body(), mode });
        state.ctx.sendForm = null; toast(s.mission.mode === "drone" ? "Drone booked" : "Road courier booked", s.mission.mode === "drone" ? "drone" : "truck");
        state.tab = "shipments"; renderNav(); shipmentDetail(s);
      });
      $("#book").onclick = () => book("auto");
      if ($("#bookRoad")) $("#bookRoad").onclick = () => book("road");
    } catch (e) { box.innerHTML = `<div class="notice bad">${ic("alert")}<span>${esc(e.message)}</span></div>`; }
  }
  quote();
};

SCREENS.coverage = async () => {
  const net = await api("/api/hospital/network");
  const me = net.hospital, all = [...net.hospitals, ...net.pharmacies];
  const pts = [{ ...me, cls: "hub", big: true }, ...all.map((p) => ({ ...p, cls: p.coverage.drone ? (p.type === "pharmacy" ? "pharm" : "ok") : "road" }))];
  const lines = all.map((p) => ({ a: me, b: p, cls: p.coverage.drone ? "drone" : "road" }));
  const row = (p) => `<div class="list-item"><div class="avatar ${p.coverage.drone ? "" : "muted-av"}">${ic(p.coverage.drone ? "drone" : "truck")}</div>
    <div class="grow"><b>${esc(shortName(p.name))}</b><div class="tiny muted">${p.coverage.distance_km} km · ${esc(p.coverage.zone)} zone${p.type === "hospital" && !p.drone_pad ? " · no drone pad" : ""}</div>
      ${p.coverage.drone ? "" : `<div class="tiny" style="color:var(--warn);margin-top:2px">${esc(p.coverage.reason)}</div>`}</div>
    <div style="text-align:right">${p.coverage.drone ? `<span class="badge good">${ic("drone")} ${mins(p.coverage.flight_minutes)}</span>` : `<span class="badge">${ic("truck")} ${mins(p.coverage.road_minutes)}</span>`}
      ${p.coverage.needs_permission ? `<div class="tiny muted" style="margin-top:4px">ATC permission</div>` : ""}</div></div>`;
  view().innerHTML = `<section class="hero"><div class="eyebrow">Drone coverage from ${esc(shortName(me.name))}</div><h1>${net.summary.drone} of ${net.summary.total} sites reachable by drone</h1>
      <p>Every hospital is served: by drone where the route passes India's Drone Rules 2021 checks, and by road courier everywhere else.</p>
      <div class="stats"><div class="stat"><b>${net.summary.drone}</b><span>Drone</span></div><div class="stat"><b>${net.summary.road_only}</b><span>Road only</span></div><div class="stat"><b>${net.zones.length}</b><span>Restricted zones nearby</span></div></div></section>
    <div class="card">${routeMap({ points: pts, lines, zones: net.zones })}
      <div class="row tiny muted" style="gap:14px"><span class="key"><i class="k hub"></i>Your hospital</span><span class="key"><i class="k ok"></i>Hospital by drone</span><span class="key"><i class="k pharm"></i>Pharmacy by drone</span><span class="key"><i class="k road"></i>Road only</span></div></div>
    <div class="grid"><div class="card"><h3>Hospitals</h3>${net.hospitals.map(row).join("")}</div><div class="card"><h3>Pharmacies</h3>${net.pharmacies.map(row).join("")}</div></div>
    <div class="notice info small">${ic("info")}<span>Demo rules, fictional airspace. A real launch needs a DGCA-authorised operator, drones with a UIN and type certificate, certified remote pilots, BVLOS permission, and the live Digital Sky airspace map.</span></div>`;
};

/* ------------------------------------------------------------------ yana */
function openYana() { $("#yanaPanel").classList.add("open"); setTimeout(() => $("#yanaInput").focus(), 50); }
function setupYana() {
  const log = $("#yanaLog");
  const add = (text, who, cls = "") => { const d = document.createElement("div"); d.className = `bubble ${who} ${cls}`; d.textContent = text; log.appendChild(d); log.scrollTop = log.scrollHeight; };
  add("Hi, I'm Yana. I can show your prescription, find and compare pharmacies, change how many tablets you buy, and track your delivery.\n\nI can't change your prescription or treatment. Only your doctor can.", "yana");
  const examples = ["Show the medicines my doctor prescribed", "Find a pharmacy near my home", "I only want to purchase three tablets instead of five", "Show the cheapest eligible pharmacy", "When will my medicine arrive?"];
  $("#yanaChips").innerHTML = examples.map((e) => `<button type="button">${esc(e)}</button>`).join("");
  $$("#yanaChips button").forEach((b) => (b.onclick = () => send(b.textContent)));
  $("#yanaBtn").onclick = () => ($("#yanaPanel").classList.contains("open") ? $("#yanaPanel").classList.remove("open") : openYana());
  $("#yanaClose").onclick = () => $("#yanaPanel").classList.remove("open");
  $("#yanaForm").onsubmit = (e) => { e.preventDefault(); const v = $("#yanaInput").value.trim(); if (v) send(v); $("#yanaInput").value = ""; };
  async function send(text) {
    add(text, "me");
    try {
      const r = await post("/api/yana", { message: text });
      add(r.reply, "yana", r.intent === "refused" ? "refused" : "");
      if (["change_quantity", "remove_item"].includes(r.intent) && ["cart", "home"].includes(state.tab)) SCREENS[state.tab]();
    } catch (e) { add(e.message, "yana", "refused"); }
  }
}

/* boot() runs from live.js once every screen is registered. */
