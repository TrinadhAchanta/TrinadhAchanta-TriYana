/* Triyana — Offers & rewards: ₹99 first visit, Triyana Family membership, cashless insurance,
   refer a friend (₹200 each), partner organisations, and the "promise kept" guarantee. */
"use strict";

Object.assign(P, {
  gift: '<rect x="3" y="8" width="18" height="4" rx="1"/><path d="M12 8v13M5 12v9h14v-9"/><path d="M12 8S10.5 3 8 3a2.5 2.5 0 0 0 0 5h4zM12 8s1.5-5 4-5a2.5 2.5 0 0 1 0 5h-4z"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><circle cx="17" cy="9" r="2.5"/><path d="M16 14.2a5 5 0 0 1 5.5 4.8"/>',
  building: '<rect x="4" y="3" width="16" height="18" rx="1.5"/><path d="M9 7h2M13 7h2M9 11h2M13 11h2M9 15h2M13 15h2M10 21v-3h4v3"/>',
  umbrella: '<path d="M3 12a9 9 0 0 1 18 0z"/><path d="M12 12v7a2 2 0 0 1-4 0"/>',
});

TABS.patient.splice(3, 0, ["perks", "Offers & rewards", "gift", "desktop"]);
Object.assign(SHORT, { "Offers & rewards": "Offers" });

const PERKS = { data: null };
const loadPerks = async () => (PERKS.data = await api("/api/perks"));
const del = (p) => api(p, { method: "DELETE" });
const inr = (n) => `₹${Number(n).toLocaleString("en-IN")}`; // whole rupees for headlines

/* A friend's link (/?ref=CODE) is remembered until they are signed in, then used once. */
(() => {
  try {
    const ref = new URLSearchParams(location.search).get("ref");
    if (ref) localStorage.setItem("triyana-ref", ref.toUpperCase().slice(0, 16));
  } catch {}
})();
async function usePendingReferral() {
  let code = null; try { code = localStorage.getItem("triyana-ref"); } catch {}
  if (!code || state.role !== "patient") return;
  try { localStorage.removeItem("triyana-ref"); } catch {}
  try { await post("/api/perks/referral", { code }); toast(`Referral code applied. You'll both get ₹200 after your first visit.`, "gift"); }
  catch (e) { if (!["already_referred", "not_new", "own_code"].includes(e.detail?.code)) toast(e.message, "info"); }
}

/* What the patient pays, shown on every visit card. */
function billLine(v) {
  const b = v.bill;
  if (!b || b.patient_pays === b.base_fee) return `<span><b>${money(v.fee)}</b> <span class="muted">pay after the visit</span></span>`;
  const tag = b.promise === "late" ? `<span class="badge good">Free: we were late</span>`
    : b.cashless ? `<span class="badge info">${ic("umbrella")} Cashless</span>`
    : b.lines.some((l) => l.code === "membership") ? `<span class="badge premium">Triyana Family</span>` : "";
  return `<span class="bill-mini" title="${esc(b.lines.map((l) => `${l.label}: ${money(l.amount)}`).join("\n"))}">${tag}
    <s class="muted">${money(b.base_fee)}</s> <b>${b.patient_pays ? money(b.patient_pays) : "Free"}</b>
    <span class="muted">${b.patient_pays ? "pay after the visit" : b.cashless ? "billed to your insurer" : "nothing to pay"}</span></span>`;
}

function billTable(lines, pays) {
  return `<table class="price perk-price">${lines.map((l) => `<tr class="${l.amount < 0 ? "good-text" : ""}"><td>${esc(l.label)}</td><td>${l.amount < 0 ? "−" : ""}${money(Math.abs(l.amount))}</td></tr>`).join("")}
    <tr class="total"><td>You pay</td><td>${pays ? money(pays) : "₹0"}</td></tr></table>`;
}

/* Price box for a booking: fills `el` with the patient's real price and a cashless switch. */
async function perkQuote(el, fee, opt, onChange) {
  if (!el) return;
  const perks = PERKS.data || await loadPerks().catch(() => null);
  const policy = perks?.insurance.policies[0];
  const q = await api(`/api/perks/quote?fee=${fee}&cashless=${opt.cashless ? 1 : 0}`).catch(() => null);
  if (!el.isConnected || !q) return;
  el.innerHTML = `${billTable(q.lines, q.patient_pays)}
    ${policy ? `<label class="perk-toggle"><input type="checkbox" id="cashlessBox" ${opt.cashless ? "checked" : ""}> ${ic("umbrella")} <span>Cashless with <b>${esc(policy.insurer_name)}</b> <span class="tiny muted">(${esc(policy.policy_no)})</span></span></label>`
      : `<p class="tiny muted" style="margin:6px 0 0">${ic("umbrella")} Have health insurance? <a href="#" data-goperks>Add it</a> for cashless visits.</p>`}`;
  const box = $("#cashlessBox", el);
  if (box) box.onchange = () => { opt.cashless = box.checked; onChange?.(); perkQuote(el, fee, opt, onChange); };
  $$("[data-goperks]", el).forEach((a) => (a.onclick = (e) => { e.preventDefault(); document.querySelector(".sheet-wrap")?.remove(); go("perks"); }));
}

/* Home: one card that points new patients to ₹99 and everyone to their rewards. */
async function perkHomeCard() {
  const slot = $("#perkSlot"); if (!slot) return;
  const p = await loadPerks().catch(() => null);
  if (!p || !slot.isConnected) return;
  const [title, sub] = p.first_visit.eligible
    ? [`Your first doctor visit is just ${inr(p.first_visit.price)}`, "Applied automatically when you book. A verified doctor at your door in 10 minutes."]
    : p.membership.active ? ["Triyana Family is active", `Visit fees covered until ${day(p.membership.ends_at)}.`]
    : [`Invite a friend, you both get ${inr(p.referral.reward)}`, `Your code ${p.referral.code}. ${p.credit.balance ? `You have ${money(p.credit.balance)} credit.` : ""}`];
  slot.innerHTML = `<button class="perk-banner" data-go="perks"><span class="ico">${ic("gift", "lg")}</span><span class="grow"><b>${esc(title)}</b><span class="small">${esc(sub)}</span></span><span class="btn sm">See offers</span></button>`;
  $("[data-go]", slot).onclick = () => go("perks");
}

SCREENS.perks = async () => {
  await usePendingReferral();
  const p = await loadPerks();
  const ORG_ICON = { society: "home", office: "building", old_age_home: "heart" };
  const shareUrl = `${location.origin}/?ref=${p.referral.code}`;
  const shareText = `I use Triyana: a verified doctor at your door in 10 minutes. Join with my code ${p.referral.code} and we both get ₹${p.referral.reward} after your first visit. ${shareUrl}`;
  view().innerHTML = pageHead("Offers & rewards", "Ways to pay less for a doctor at your door.") + `
    <div class="perk-grid">
      <article class="card perk ${p.first_visit.eligible ? "featured" : ""}">
        <div class="perk-head"><span class="ico">${ic("bolt")}</span><div><h3>First visit for ${inr(p.first_visit.price)}</h3><span class="small muted">For new patients, applied automatically</span></div></div>
        ${p.first_visit.eligible ? `<p class="small">Your first home visit costs just ${money(p.first_visit.price)}, whichever doctor comes. The doctor still gets their full fee.</p>
          <button class="btn primary sm" data-svc-now>${ic("bolt")} Get a doctor in ${p.promise_min} min</button>`
          : `<p class="small muted">You've already had your first visit. Invite friends below so they can get it too.</p>`}
      </article>

      <article class="card perk">
        <div class="perk-head"><span class="ico">${ic("clock")}</span><div><h3>Promise kept, or it's free</h3><span class="small muted">Our ${p.promise_min}-minute guarantee</span></div></div>
        <p class="small">When you use <b>Doctor in ${p.promise_min} min</b> and we promise ${p.promise_min} minutes, the clock starts when you tap. If the doctor reaches your door late, that visit is free. No forms, no asking: it happens automatically.</p>
      </article>

      <article class="card perk ${p.membership.active ? "featured" : ""}">
        <div class="perk-head"><span class="ico">${ic("users")}</span><div><h3>Triyana Family</h3><span class="small muted">${inr(p.membership.price)} a year</span></div>${p.membership.active ? `<span class="badge good">${ic("check")} Active</span>` : ""}</div>
        <ul class="perk-list small"><li>Unlimited doctor visits: visit fees covered for everyone you book for</li><li>Includes "Doctor in ${p.promise_min} min"</li><li>One yearly payment, no per-visit bills</li></ul>
        ${p.membership.active ? `<p class="small muted">Active since ${day(p.membership.since)}, renews or ends on ${day(p.membership.ends_at)}.</p>`
          : `<button class="btn primary sm" id="buyFamily">${ic("wallet")} Join for ${inr(p.membership.price)} a year</button><p class="tiny muted" style="margin:6px 0 0">Demo payment: no money moves.</p>`}
      </article>

      <article class="card perk">
        <div class="perk-head"><span class="ico">${ic("gift")}</span><div><h3>Refer a friend: ${inr(p.referral.reward)} each</h3><span class="small muted">You both get credit after their first visit</span></div></div>
        <div class="perk-code"><code>${esc(p.referral.code)}</code><button class="btn sm" id="shareRef">${ic("chat")} Share</button><button class="btn ghost sm" id="copyRef">Copy link</button></div>
        ${p.credit.balance ? `<p class="small"><b>${money(p.credit.balance)} credit</b> ready. It comes off your next visit automatically.</p>` : ""}
        ${p.referral.friends.length ? `<div class="tiny muted">Friends: ${p.referral.friends.map((f) => `${esc(f.name)} (${f.status === "rewarded" ? "rewarded" : "waiting for first visit"})`).join(", ")}</div>` : ""}
        ${p.referral.referred_by ? `<p class="tiny muted">You joined with ${esc(p.referral.referred_by)}'s code${p.referral.referred_status === "pending" ? ". Your reward arrives after your first visit." : "."}</p>`
          : p.referral.can_redeem ? `<form class="row perk-form" id="refForm"><input id="refCode" placeholder="Friend's code" maxlength="16" autocomplete="off"><button class="btn sm">Apply</button></form>` : ""}
      </article>

      <article class="card perk">
        <div class="perk-head"><span class="ico">${ic("umbrella")}</span><div><h3>Health insurance, cashless</h3><span class="small muted">Visits billed straight to your insurer</span></div></div>
        ${p.insurance.policies.map((x) => `<div class="perk-policy"><div class="grow"><b>${esc(x.insurer_name)}</b><div class="tiny muted">Policy ${esc(x.policy_no)}${x.member_name ? ` · ${esc(x.member_name)}` : ""} · valid until ${esc(x.valid_until)}</div></div><span class="badge good">Verified</span><button class="btn ghost sm" data-rmpol="${x.id}">Remove</button></div>`).join("")}
        <details ${p.insurance.policies.length ? "" : "open"}><summary class="small">${p.insurance.policies.length ? "Use a different policy" : "Add your policy"}</summary>
          <form class="perk-form-grid" id="polForm">
            <label class="field">Insurer<select id="polIns">${p.insurance.insurers.map((i) => `<option value="${i.code}">${esc(i.name)}</option>`).join("")}</select></label>
            <label class="field">Policy number<input id="polNo" required minlength="4" maxlength="40" autocomplete="off"></label>
            <label class="field">Name on policy<input id="polName" maxlength="120" value="${esc(state.name)}"></label>
            <label class="field">Valid until<input id="polDate" type="date" required></label>
            <button class="btn primary sm">Check and add</button>
          </form></details>
        <p class="tiny muted" style="margin:8px 0 0">Demo: the insurer check is simulated. Real cashless needs agreements with each insurer.</p>
      </article>

      <article class="card perk">
        <div class="perk-head"><span class="ico">${ic("building")}</span><div><h3>Your society, office or care home</h3><span class="small muted">Partner members get discounts and priority</span></div></div>
        ${p.org ? `<div class="perk-policy"><span class="ico">${ic(ORG_ICON[p.org.kind] || "building")}</span><div class="grow"><b>${esc(p.org.name)}</b><div class="tiny muted">${esc(p.org.kind_label)}${p.org.area ? ` · ${esc(p.org.area)}` : ""}</div></div>
            <span class="badge good">${p.org.discount_pct}% off</span>${p.org.priority ? `<span class="badge premium">Priority</span>` : ""}</div>
            <p class="small muted">${p.org.discount_pct}% off visits that don't already have a bigger offer${p.org.priority ? ", and doctors see your request marked as priority" : ""}.</p>
            <button class="btn ghost sm" id="leaveOrg">Leave</button>`
          : `<p class="small">Ask your housing society, office or old-age home for its Triyana code.</p>
            <form class="row perk-form" id="orgForm"><input id="orgCode" placeholder="Partner code" maxlength="20" autocomplete="off"><button class="btn sm">Join</button></form>`}
      </article>
    </div>
    ${p.credit.history.length ? `<div class="section-title">Credit history</div><div class="card">${p.credit.history.map((h) => `<div class="list-item"><div class="grow"><b>${esc(h.note || h.kind)}</b><div class="tiny muted">${when(h.at)}</div></div><b class="${h.amount > 0 ? "good-text" : ""}">${h.amount > 0 ? "+" : "−"}${money(Math.abs(h.amount))}</b></div>`).join("")}</div>` : ""}`;

  const again = () => SCREENS.perks();
  $("[data-svc-now]")?.addEventListener("click", () => doctorNowSheet());
  const buy = $("#buyFamily");
  if (buy) buy.onclick = () => guard(async () => {
    if (!confirm(`Join Triyana Family for ${money(p.membership.price)} a year? (Demo: no money moves.)`)) return;
    await post("/api/perks/membership", { payment_method: "upi" }); toast("Welcome to Triyana Family", "users"); again();
  });
  $("#copyRef").onclick = () => { navigator.clipboard?.writeText(shareUrl).then(() => toast("Link copied"), () => toast(shareUrl, "info")); };
  $("#shareRef").onclick = () => {
    if (navigator.share) navigator.share({ title: "Triyana", text: shareText, url: shareUrl }).catch(() => {});
    else window.open(`https://wa.me/?text=${encodeURIComponent(shareText)}`, "_blank", "noopener");
  };
  const rf = $("#refForm");
  if (rf) rf.onsubmit = (e) => { e.preventDefault(); guard(async () => { await post("/api/perks/referral", { code: $("#refCode").value }); toast(`Code applied. ${money(p.referral.reward)} each after your first visit.`, "gift"); again(); }); };
  $("#polForm").onsubmit = (e) => { e.preventDefault(); guard(async () => {
    await post("/api/perks/insurance", { insurer: $("#polIns").value, policy_no: $("#polNo").value, member_name: $("#polName").value, valid_until: $("#polDate").value });
    toast("Policy verified. Choose cashless when you book.", "umbrella"); again();
  }); };
  $$("[data-rmpol]").forEach((b) => (b.onclick = () => guard(async () => { await del(`/api/perks/insurance/${b.dataset.rmpol}`); again(); })));
  const of = $("#orgForm");
  if (of) of.onsubmit = (e) => { e.preventDefault(); guard(async () => { const s = await post("/api/perks/org", { code: $("#orgCode").value }); toast(`You're now a ${s.org.name} member`, "building"); again(); }); };
  const lo = $("#leaveOrg"); if (lo) lo.onclick = () => guard(async () => { await del("/api/perks/org"); again(); });
};

/* Pick up a friend's referral link on the home screen too, then show the offers card. */
const _homeScreen = SCREENS.home;
SCREENS.home = async (...a) => { await _homeScreen(...a); if (state.role === "patient") usePendingReferral().then(perkHomeCard); };
