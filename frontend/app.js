/* Triyana Home — Prescription to Delivery demo client (no build step). */
"use strict";

const state = { token: null, role: null, tab: null, ctx: {}, accounts: [], currency: "INR" };
const $ = (s, el = document) => el.querySelector(s);
const view = () => $("#view");
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (n) => (n == null ? "—" : new Intl.NumberFormat(undefined, { style: "currency", currency: state.currency }).format(n));
const when = (iso) => (iso ? new Date(iso + (iso.endsWith("Z") ? "" : "Z")).toLocaleString() : "—");
const mins = (m) => (m == null ? "—" : m < 90 ? `${m} min` : `${Math.round(m / 60)} h`);

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.style.display = "block";
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.style.display = "none"), 4000);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    method: opts.method || "GET",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${state.token}` },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data.detail || {};
    const msg = typeof d === "string" ? d : d.message || (Array.isArray(d) ? "Please check the form." : "Something went wrong.");
    const err = new Error(msg); err.detail = d; err.status = res.status; throw err;
  }
  return data;
}
const post = (p, body) => api(p, { method: "POST", body });
const put = (p, body) => api(p, { method: "PUT", body });

async function guard(fn) {
  try { await fn(); } catch (e) { toast(e.message); }
}

/* ------------------------------------------------------------------ shell */
const TABS = {
  patient: [["home", "Home"], ["rx", "Prescription"], ["cart", "Medicine cart"], ["pharmacies", "Pharmacies"], ["orders", "Track order"], ["meds", "My Medicines"]],
  doctor: [["visits", "Home visits"], ["prescriptions", "Prescriptions"], ["clarifications", "Clarifications"]],
  pharmacist: [["queue", "Order queue"]],
  courier: [["deliveries", "Deliveries"]],
};

async function boot() {
  const r = await fetch("/api/demo/accounts");
  state.accounts = await r.json();
  const sel = $("#account");
  sel.innerHTML = state.accounts.map((a) => `<option value="${esc(a.token)}">${esc(a.label)}</option>`).join("");
  const saved = (() => { try { return localStorage.getItem("triyana.token"); } catch { return null; } })();
  if (saved && state.accounts.some((a) => a.token === saved)) sel.value = saved;
  sel.onchange = () => signIn(sel.value);
  $("#reset").onclick = () => guard(async () => { await fetch("/api/demo/reset", { method: "POST" }); state.ctx = {}; toast("Demo data restored."); signIn(sel.value); });
  setupYana();
  signIn(sel.value);
}

async function signIn(token) {
  state.token = token;
  try { localStorage.setItem("triyana.token", token); } catch {}
  const me = await api("/api/me");
  state.role = me.role;
  state.ctx = {};
  $("#yanaBtn").hidden = me.role !== "patient";
  $("#yanaPanel").classList.remove("open");
  go(TABS[me.role][0][0]);
}

function go(tab, ctx = {}) {
  state.tab = tab; Object.assign(state.ctx, ctx);
  $("#tabs").innerHTML = TABS[state.role].map(([k, l]) => `<button class="${k === tab ? "active" : ""}" data-tab="${k}">${l}</button>`).join("");
  $("#tabs").querySelectorAll("button").forEach((b) => (b.onclick = () => go(b.dataset.tab)));
  view().innerHTML = `<div class="empty">Loading…</div>`;
  guard(() => SCREENS[tab]());
}

/* ---------------------------------------------------------------- patient */
async function latestCartId() {
  if (state.ctx.cartId) return state.ctx.cartId;
  const carts = await api("/api/patient/carts");
  state.ctx.cartId = carts[0]?.id || null;
  return state.ctx.cartId;
}

const SCREENS = {};

SCREENS.home = async () => {
  const [notes, dash] = await Promise.all([api("/api/notifications"), api("/api/patient/medicines")]);
  const ready = notes.find((n) => n.link.startsWith("cart:") && !n.read);
  view().innerHTML = `
    ${ready ? `<div class="card" style="border-color:var(--brand)">
      <span class="badge brand">New</span>
      <h2 style="margin-top:6px">${esc(ready.title)}</h2>
      <p>${esc(ready.body)}</p>
      <div class="row"><button class="btn primary" id="openCart">Review my medicines</button>
      <button class="btn" id="openRx">View prescription</button></div></div>` : ""}
    <div class="grid">
      <div class="card"><h3>Active prescriptions</h3><p class="muted">${dash.prescriptions.filter((p) => p.status === "signed").length} active</p>
        <button class="btn" data-go="rx">View</button></div>
      <div class="card"><h3>Orders in progress</h3><p class="muted">${dash.active_orders.length ? esc(dash.active_orders[0].status_label) : "None"}</p>
        <button class="btn" data-go="orders">Track</button></div>
      <div class="card"><h3>Ask Yana</h3><p class="muted">"Find a pharmacy near my home"</p>
        <button class="btn" id="openYana">Open Yana</button></div>
    </div>
    <div class="card"><h3>Notifications</h3>${notes.length ? notes.slice(0, 8).map((n) => `
      <div class="rx-item"><div class="row between"><b>${esc(n.title)}</b><span class="small muted">${when(n.at)}</span></div>
      <div class="small">${esc(n.body)}</div></div>`).join("") : `<p class="muted">No notifications yet. Your doctor's prescription will appear here once signed.</p>`}</div>`;
  view().querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => go(b.dataset.go)));
  $("#openYana").onclick = () => $("#yanaPanel").classList.add("open");
  if (ready) {
    const markRead = () => post(`/api/notifications/${ready.id}/read`).catch(() => {});
    $("#openCart").onclick = () => { markRead(); go("cart", { cartId: +ready.link.split(":")[1] }); };
    $("#openRx").onclick = () => { markRead(); go("rx"); };
  }
};

SCREENS.rx = async () => {
  const list = await api("/api/patient/prescriptions");
  if (!list.length) { view().innerHTML = `<div class="card empty">No prescriptions yet.</div>`; return; }
  view().innerHTML = list.map((rx) => `
    <div class="card">
      <div class="row between"><h2>Official prescription · ${esc(rx.reference_no)}</h2>
        ${rx.status === "signed" ? `<span class="badge ${rx.integrity_verified ? "good" : "bad"}">${rx.integrity_verified ? "Signed & verified" : "Signature check failed"}</span>` : `<span class="badge">${esc(rx.status)}</span>`}</div>
      <p class="small muted">Patient ${esc(rx.patient.name)} (${esc(rx.patient.patient_ref)}) · ${esc(rx.doctor.name)}, ${esc(rx.doctor.specialty)} · Licence ${esc(rx.doctor.license_no)} ${rx.doctor.license_verified ? "✓ verified" : ""}<br>
      Consultation ${when(rx.consultation_date)} · Valid until ${when(rx.valid_until)}</p>
      <table><tr><th>Medicine</th><th>Dosage</th><th>Frequency</th><th>Duration</th><th>Qty</th></tr>
      ${rx.items.map((i) => `<tr><td><b>${esc(i.medicine)}</b> ${esc(i.strength)}<div class="small muted">${esc(i.generic_name)} · ${esc(i.route)}</div>
        ${i.instructions ? `<div class="small">${esc(i.instructions)}</div>` : ""}${i.refills_allowed ? `<div class="small muted">Refills: ${i.refills_allowed}</div>` : ""}</td>
        <td>${esc(i.dosage)}</td><td>${esc(i.frequency)}</td><td>${i.duration_days} days</td><td>${i.quantity} ${esc(i.unit)}</td></tr>`).join("")}</table>
      <p class="small muted">This record can only be changed by your prescribing doctor. Cart choices never alter it.</p>
    </div>`).join("");
};

const QTY_LABEL = {
  full: ["Full prescribed quantity", "good"], pending_pharmacist: ["Pharmacist will confirm", "warn"],
  pending_prescriber: ["Waiting for your doctor", "warn"], approved: ["Smaller quantity approved", "good"],
  rejected: ["Not permitted", "bad"], not_permitted: ["Not permitted", "bad"],
};

SCREENS.cart = async () => {
  const id = await latestCartId();
  if (!id) { view().innerHTML = `<div class="card empty">Your medicine cart appears after your doctor signs a prescription.</div>`; return; }
  const cart = await api(`/api/carts/${id}`);
  state.currency = cart.currency;
  const inCart = cart.items.filter((i) => i.status === "in_cart");
  view().innerHTML = `
    <div class="card">
      <div class="row between"><h2>Suggested medicine cart</h2><span class="badge">${esc(cart.prescription.reference_no)} · ${esc(cart.prescription.doctor)}</span></div>
      <p class="small muted">${esc(cart.disclaimer)} You are free to buy all, some or none of these medicines here.</p>
    </div>
    ${cart.items.map((i) => {
      const [ql, qc] = QTY_LABEL[i.quantity_status] || [i.quantity_status, ""];
      const statusBadge = { in_cart: "", removed: `<span class="badge">Removed from cart</span>`, buy_later: `<span class="badge">Saved for later</span>`, ordered: `<span class="badge brand">Ordered</span>` }[i.status];
      return `<div class="card" data-item="${i.id}" style="${i.status !== "in_cart" ? "opacity:.75" : ""}">
        <div class="row between"><div><h3>${esc(i.medicine)} ${esc(i.strength)}</h3>
          <div class="small muted">${esc(i.generic_name)} · ${esc(i.form)}${i.cold_chain ? " · ❄ temperature controlled" : ""}${i.id_check_required ? " · ID check on delivery" : ""}</div></div>
          ${statusBadge}</div>
        <div class="qty"><div><span class="small muted">Prescribed quantity</span><b>${i.prescribed.quantity} ${esc(i.unit)}</b></div>
          <div><span class="small muted">Requested purchase quantity</span><b>${i.requested_quantity} ${esc(i.unit)}</b></div></div>
        <div class="small"><b>Doctor's instructions:</b> ${esc(i.prescribed.dosage)}, ${esc(i.prescribed.frequency)}, ${i.prescribed.duration_days} days. ${esc(i.prescribed.instructions)}</div>
        <div class="row small" style="margin-top:6px"><span class="badge ${qc}">${ql}</span>
          <span class="muted">Est. ${money(i.estimated_line_total)} · packs of ${i.pack_sizes.join(", ")} · ${i.pharmacies_with_stock} pharmacies list it</span></div>
        ${i.quantity_note && i.quantity_status !== "full" ? `<div class="notice ${qc}">${esc(i.quantity_note)}</div>` : ""}
        ${i.status === "ordered" ? "" : `<div class="item-actions">
          ${i.status !== "in_cart" ? `<button class="btn primary" data-act="add">Add to cart</button>` : ""}
          <button class="btn" data-act="qty">Request different quantity</button>
          ${i.status === "in_cart" ? `<button class="btn" data-act="remove">Remove from cart</button><button class="btn" data-act="buy_later">Buy later</button>` : ""}
          <button class="btn" data-act="pharmacist">Ask pharmacist</button>
          <button class="btn" data-act="doctor">Contact doctor</button></div>
          <div class="qty-form"></div>`}
      </div>`;
    }).join("")}
    <div class="card"><h3>Estimated total</h3>
      <table class="price"><tr><td>Medicines (${inCart.length})</td><td>${money(cart.estimate.subtotal)}</td></tr>
      <tr><td>Delivery (from)</td><td>${money(cart.estimate.delivery_fee)}</td></tr>
      <tr><td>Taxes</td><td>${money(cart.estimate.tax)}</td></tr>
      <tr class="total"><td>Estimated total</td><td>${money(cart.estimate.total)}</td></tr></table>
      <p class="small muted">${esc(cart.estimate.note)} Fastest delivery around ${mins(cart.estimate.fastest_eta_minutes)}.</p>
      <button class="btn primary big" id="toPharm" ${inCart.length ? "" : "disabled"}>Choose a pharmacy</button></div>`;
  $("#toPharm").onclick = () => go("pharmacies");
  view().querySelectorAll("[data-item]").forEach((card) => {
    const itemId = +card.dataset.item;
    const item = cart.items.find((x) => x.id === itemId);
    card.querySelectorAll("[data-act]").forEach((b) => (b.onclick = () => guard(async () => {
      const act = b.dataset.act;
      if (["add", "remove", "buy_later"].includes(act)) {
        const r = await post(`/api/cart-items/${itemId}/${act}`);
        toast(r.message); return SCREENS.cart();
      }
      if (act === "pharmacist" || act === "doctor") {
        const body = prompt(`Your message to the ${act} about ${item.medicine}:`);
        if (!body) return;
        await post(`/api/cart-items/${itemId}/messages`, { recipient: act, body });
        return toast(`Message sent securely to the ${act}.`);
      }
      const f = $(".qty-form", card);
      f.innerHTML = `<div class="notice warn">Buying fewer than prescribed may leave you without the full course. Your doctor's prescription stays unchanged, and the pharmacist makes the final decision.</div>
        <div class="row"><label class="small">Buy <select id="q${itemId}">${item.allowed_quantities.slice().reverse().map((q) => `<option ${q === item.requested_quantity ? "selected" : ""}>${q}</option>`).join("")}</select> of ${item.prescribed.quantity} ${esc(item.unit)}</label>
        <button class="btn primary" id="qs${itemId}">Request</button></div><div id="qr${itemId}"></div>`;
      $(`#qs${itemId}`).onclick = () => guard(async () => {
        const r = await put(`/api/cart-items/${itemId}/quantity`, { requested_quantity: +$(`#q${itemId}`).value });
        const ok = !["rejected", "not_permitted"].includes(r.status);
        $(`#qr${itemId}`).innerHTML = `<div class="notice ${ok ? "good" : "bad"}">${esc(r.explanation)}</div>` +
          (ok ? "" : `<div class="row"><button class="btn" data-c="pharmacist">Contact pharmacy</button><button class="btn" data-c="doctor">Contact doctor</button></div>`);
        $(`#qr${itemId}`).querySelectorAll("[data-c]").forEach((c) => (c.onclick = () => card.querySelector(`[data-act="${c.dataset.c}"]`).click()));
        if (ok) setTimeout(SCREENS.cart, 1400);
      });
    })));
  });
};

const SORT_LABELS = [["nearest", "Nearest"], ["price", "Lowest total price"], ["fastest", "Fastest delivery"], ["rating", "Highest rated"], ["pickup", "Pickup available"]];

SCREENS.pharmacies = async () => {
  const id = await latestCartId();
  if (!id) { view().innerHTML = `<div class="card empty">No cart yet.</div>`; return; }
  const sort = state.ctx.sort || "nearest";
  const data = await api(`/api/carts/${id}/pharmacies?sort=${sort}`);
  state.currency = data.currency;
  view().innerHTML = `
    <div class="card"><h2>Licensed pharmacies serving your address</h2>
      <div class="row">${SORT_LABELS.map(([k, l]) => `<button class="btn ${k === sort ? "primary" : ""}" data-sort="${k}">${l}</button>`).join("")}</div>
      <p class="small muted">Only verified, licensed pharmacies are shown. Stock marked "unconfirmed" will be checked by the pharmacy before you're charged.</p></div>
    <div class="grid">${data.pharmacies.map((p) => `
      <div class="card" style="${p.eligible ? "" : "opacity:.65"}">
        <div class="row between"><h3>${esc(p.name)}</h3>${p.recommended ? `<span class="badge brand">Recommended</span>` : ""}</div>
        <div class="small muted">${esc(p.address)} · ${p.distance_km} km · ${esc(p.hours)} · ★ ${p.rating} (${p.rating_count})</div>
        <div class="small muted">Licence ${esc(p.verified.license_no)} ✓ · Reg. ${esc(p.verified.business_reg_no)}</div>
        <ul class="small" style="padding-left:18px;margin:8px 0">${p.items.map((i) => `<li>${esc(i.medication)} × ${i.quantity}:
          <span class="badge ${i.stock_status === "confirmed" ? "good" : i.stock_status === "unconfirmed" ? "warn" : "bad"}">${{ confirmed: "In stock (live)", unconfirmed: "Stock unconfirmed", out_of_stock: "Out of stock", not_carried: "Not stocked" }[i.stock_status]}</span></li>`).join("")}</ul>
        <table class="price small"><tr><td>Medicines</td><td>${money(p.subtotal)}</td></tr><tr><td>Delivery</td><td>${p.delivery_available ? money(p.delivery_fee) : "—"}</td></tr>
          <tr><td>Taxes</td><td>${money(p.tax)}</td></tr><tr class="total"><td>Total</td><td>${money(p.total)}</td></tr></table>
        <div class="row small" style="margin:6px 0">${p.delivery_available ? `<span class="badge">Delivery ~${mins(p.eta_minutes)}</span>` : `<span class="badge">No delivery</span>`}
          ${p.pickup_available ? `<span class="badge">Pickup</span>` : ""}</div>
        ${p.eligible ? `<button class="btn primary big" data-pick="${p.pharmacy_id}">Choose this pharmacy</button>` :
          `<div class="notice bad small">${p.reasons.map(esc).join("<br>")}</div>`}
      </div>`).join("")}</div>`;
  view().querySelectorAll("[data-sort]").forEach((b) => (b.onclick = () => { state.ctx.sort = b.dataset.sort; SCREENS.pharmacies(); }));
  view().querySelectorAll("[data-pick]").forEach((b) => (b.onclick = () => checkoutScreen(data.pharmacies.find((p) => p.pharmacy_id === +b.dataset.pick))));
};

async function checkoutScreen(p) {
  const methods = await api("/api/payment-methods");
  const opt = { fulfillment: p.delivery_available ? "delivery" : "pickup", delivery_option: p.delivery_options[0]?.code || null, method: methods[0].code };
  const key = `chk-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const mult = { standard: 1, same_day: 1.4, scheduled: 1, priority: 2, drone: 2.5 };
  const render = () => {
    const fee = opt.fulfillment === "delivery" ? Math.round(p.delivery_fee * (mult[opt.delivery_option] || 1) * 100) / 100 : 0;
    const total = Math.round((p.subtotal + p.tax + fee) * 100) / 100;
    view().innerHTML = `
      <div class="card"><h2>Checkout · ${esc(p.name)}</h2>
        <table><tr><th>Medicine</th><th>Qty</th><th>Price</th></tr>${p.items.map((i) => `<tr><td>${esc(i.medication)}</td><td>${i.quantity}</td><td>${money(i.line_total)}</td></tr>`).join("")}</table></div>
      <div class="card"><h3>How would you like to receive it?</h3><div class="row">
        ${p.delivery_available ? `<button class="btn ${opt.fulfillment === "delivery" ? "primary" : ""}" data-f="delivery">Home delivery</button>` : ""}
        ${p.pickup_available ? `<button class="btn ${opt.fulfillment === "pickup" ? "primary" : ""}" data-f="pickup">Pickup at pharmacy</button>` : ""}</div>
        ${opt.fulfillment === "delivery" ? `<div class="row" style="margin-top:10px">${p.delivery_options.map((o) => `<button class="btn ${o.code === opt.delivery_option ? "primary" : ""}" data-d="${o.code}">${esc(o.label)}</button>`).join("")}</div>
          ${opt.delivery_option === "scheduled" ? `<label class="small">Deliver at <input type="datetime-local" id="sched"></label>` : ""}` : ""}</div>
      <div class="card"><h3>Payment</h3><div class="row">${methods.map((m) => `<button class="btn ${m.code === opt.method ? "primary" : ""}" data-m="${m.code}">${esc(m.label)}</button>`).join("")}</div>
        <label class="small row" style="margin-top:8px"><input type="checkbox" id="decline"> Simulate a declined payment (sandbox)</label></div>
      <div class="card"><table class="price"><tr><td>Medicine subtotal</td><td>${money(p.subtotal)}</td></tr>
        <tr><td>Delivery fee</td><td>${money(fee)}</td></tr><tr><td>Taxes</td><td>${money(p.tax)}</td></tr>
        <tr><td>Discounts</td><td>${money(0)}</td></tr><tr class="total"><td>Final payable</td><td>${money(total)}</td></tr></table>
        <div class="notice small">Your payment is <b>authorised, not charged</b>. You're charged only after a licensed pharmacist accepts the order, and only for what they approve. If it's rejected, the hold is released.</div>
        <button class="btn primary big" id="pay">Authorise ${money(total)}</button></div>`;
    view().querySelectorAll("[data-f]").forEach((b) => (b.onclick = () => { opt.fulfillment = b.dataset.f; render(); }));
    view().querySelectorAll("[data-d]").forEach((b) => (b.onclick = () => { opt.delivery_option = b.dataset.d; render(); }));
    view().querySelectorAll("[data-m]").forEach((b) => (b.onclick = () => { opt.method = b.dataset.m; render(); }));
    $("#pay").onclick = () => guard(async () => {
      $("#pay").disabled = true;
      try {
        const sched = $("#sched")?.value;
        const order = await post(`/api/carts/${state.ctx.cartId}/checkout`, {
          pharmacy_id: p.pharmacy_id, fulfillment: opt.fulfillment, delivery_option: opt.fulfillment === "delivery" ? opt.delivery_option : null,
          scheduled_for: sched ? new Date(sched).toISOString().slice(0, 19) : null, payment_method: opt.method,
          payment_token: $("#decline").checked ? "sandbox-decline" : "sandbox-ok", idempotency_key: key, expected_total: total,
        });
        toast("Order placed. A pharmacist will review it shortly.");
        go("orders", { orderId: order.id });
      } catch (e) {
        $("#pay").disabled = false;
        if (e.detail?.code === "inventory_changed") toast("Stock changed during checkout. Please review your cart.");
        throw e;
      }
    });
  };
  render();
}

const PATIENT_STEPS = ["prescription_received", "pharmacist_reviewing", "order_accepted", "preparing", "ready_for_pickup", "out_for_delivery", "delivered"];
const STEP_LABELS = ["Prescription Received", "Pharmacist Reviewing", "Order Accepted", "Preparing Medicines", "Ready for Pickup", "Out for Delivery", "Delivered"];

SCREENS.orders = async () => {
  const dash = await api("/api/patient/medicines");
  const all = [...dash.active_orders, ...dash.purchase_history];
  if (!all.length) { view().innerHTML = `<div class="card empty">No orders yet.</div>`; return; }
  const o = all.find((x) => x.id === state.ctx.orderId) || all[0];
  const seen = new Set(o.timeline.map((e) => e.status));
  const steps = o.fulfillment === "pickup" ? PATIENT_STEPS.slice(0, 5).concat(["picked_up"]) : PATIENT_STEPS;
  const labels = o.fulfillment === "pickup" ? STEP_LABELS.slice(0, 5).concat(["Collected"]) : STEP_LABELS;
  const terminalBad = ["rejected", "cancelled"].includes(o.status);
  view().innerHTML = `
    ${all.length > 1 ? `<div class="row" style="margin-bottom:10px">${all.map((x) => `<button class="btn ${x.id === o.id ? "primary" : ""}" data-o="${x.id}">${esc(x.order_no)}</button>`).join("")}</div>` : ""}
    <div class="card"><div class="row between"><h2>${esc(o.order_no)} · ${esc(o.pharmacy.name)}</h2><span class="badge ${terminalBad ? "bad" : "brand"}">${esc(o.status_label)}</span></div>
      ${terminalBad ? `<div class="notice bad">${esc(o.timeline[o.timeline.length - 1].note)}</div>` : `
      <ul class="timeline">${steps.map((s, i) => `<li class="${seen.has(s) ? "done" : ""}"><b>${labels[i]}</b>
        <div class="small muted">${esc(o.timeline.filter((e) => e.status === s).map((e) => `${when(e.at)} · ${e.note}`).join(" "))}</div></li>`).join("")}</ul>`}
      ${o.status === "awaiting_clarification" ? `<div class="notice warn">The pharmacist asked your doctor a question. We'll notify you when it's answered.</div>` : ""}
      ${o.delivery ? `<div class="card" style="background:var(--surface-2)"><div class="row between"><div>
        <div class="small muted">Courier ${esc(o.delivery.courier)} · ${esc(o.delivery.tracking_ref)} · ETA ${when(o.delivery.eta)}</div>
        ${o.delivery.cold_chain ? `<div class="small">❄ Temperature-controlled handling</div>` : ""}${o.delivery.id_check_required ? `<div class="small">Photo ID required at the door</div>` : ""}</div>
        ${o.status !== "delivered" ? `<div><div class="small muted">Share this code with the courier</div><div class="code">${esc(o.delivery.handover_code)}</div></div>` :
          `<span class="badge good">Delivered to ${esc(o.delivery.proof_of_delivery?.recipient)}</span>`}</div></div>` : ""}
    </div>
    <div class="card"><h3>Items</h3><table><tr><th>Medicine</th><th>Prescribed</th><th>Requested</th><th>Approved</th></tr>
      ${o.items.map((i) => `<tr><td>${esc(i.medicine)}</td><td>${i.prescribed_quantity}</td><td>${i.requested_quantity}</td><td>${i.approved_quantity ?? "Pending"}</td></tr>`).join("")}</table>
      <table class="price" style="margin-top:10px"><tr><td>Total</td><td>${money(o.price.total)}</td></tr>
      <tr><td>Payment</td><td>${esc(o.payment.method)} · ${esc(o.payment.status)}${o.payment.refunded ? ` · refunded ${money(o.payment.refunded)}` : ""}</td></tr></table>
      ${["prescription_received", "pharmacist_reviewing", "awaiting_clarification", "order_accepted"].includes(o.status) ? `<button class="btn danger" id="cancel">Cancel order</button>` : ""}</div>`;
  view().querySelectorAll("[data-o]").forEach((b) => (b.onclick = () => { state.ctx.orderId = +b.dataset.o; SCREENS.orders(); }));
  const c = $("#cancel");
  if (c) c.onclick = () => guard(async () => { if (!confirm("Cancel this order? Any payment will be released or refunded.")) return; await post(`/api/orders/${o.id}/cancel`, { reason: "Cancelled by patient" }); toast("Order cancelled."); SCREENS.orders(); });
};

SCREENS.meds = async () => {
  const d = await api("/api/patient/medicines");
  view().innerHTML = `
    <div class="notice">${esc(d.note)}</div>
    ${d.prescriptions.map((rx) => `<div class="card"><div class="row between"><h2>${esc(rx.reference_no)}</h2><span class="badge ${rx.status === "signed" ? "good" : ""}">${esc(rx.status)}</span></div>
      <p class="small muted">${esc(rx.doctor)} · Expires ${when(rx.valid_until)}</p>
      <table><tr><th>Medicine</th><th>Prescribed</th><th>Ordered</th><th>Dispensed</th><th>Refill</th></tr>
      ${rx.items.map((i) => `<tr><td>${esc(i.medicine)}<div class="small muted">${esc(i.dosage)}, ${esc(i.frequency)}</div></td><td>${i.prescribed_quantity}</td><td>${i.ordered_quantity}</td><td>${i.dispensed_quantity}</td>
        <td>${i.refill_eligible ? `<span class="badge good">Eligible</span>` : i.refills_allowed ? `${i.refills_allowed} allowed` : "—"}</td></tr>`).join("")}</table></div>`).join("") || `<div class="card empty">No prescriptions yet.</div>`}
    <div class="card"><h3>Pending pharmacy orders</h3>${d.active_orders.map((o) => `<div class="row between rx-item"><span>${esc(o.order_no)} · ${esc(o.pharmacy.name)}</span><button class="btn" data-o="${o.id}">${esc(o.status_label)}</button></div>`).join("") || `<p class="muted">None</p>`}</div>
    <div class="card"><h3>Purchase history</h3>${d.purchase_history.map((o) => `<div class="row between rx-item"><span>${esc(o.order_no)} · ${money(o.price.total)}</span><span class="badge">${esc(o.status_label)}</span></div>`).join("") || `<p class="muted">None</p>`}</div>
    <div class="card"><h3>Messages</h3>${d.messages.map((m) => `<div class="rx-item small"><b>To ${esc(m.recipient)}</b> · ${when(m.at)}<div>${esc(m.body)}</div></div>`).join("") || `<p class="muted">No messages</p>`}</div>
    <div class="card row between"><span>Need to see your doctor again?</span><button class="btn primary" onclick="toast('Follow-up booking opens the Home Visits flow.')">${esc(d.doctor_follow_up.label)}</button></div>`;
  view().querySelectorAll("[data-o]").forEach((b) => (b.onclick = () => go("orders", { orderId: +b.dataset.o })));
};

/* ----------------------------------------------------------------- doctor */
SCREENS.visits = async () => {
  const visits = await api("/api/doctor/visits");
  const next = { requested: ["accept", "Accept booking"], accepted: ["start", "Start visit"], in_progress: ["complete", "Complete consultation"] };
  view().innerHTML = visits.map((v) => `<div class="card"><div class="row between"><div><h3>${esc(v.patient.name)} <span class="small muted">${esc(v.patient.patient_ref)}</span></h3>
      <div class="small muted">${esc(v.reason)} · ${when(v.scheduled_for)}</div></div><span class="badge">${esc(v.status.replace("_", " "))}</span></div>
      <div class="row" style="margin-top:8px">${next[v.status] ? `<button class="btn primary" data-v="${v.id}" data-a="${next[v.status][0]}">${next[v.status][1]}</button>` : ""}
      ${["in_progress", "completed"].includes(v.status) ? `<button class="btn" data-rx="${v.id}">Write prescription</button>` : ""}</div></div>`).join("") || `<div class="card empty">No visits.</div>`;
  view().querySelectorAll("[data-a]").forEach((b) => (b.onclick = () => guard(async () => { await post(`/api/doctor/visits/${b.dataset.v}/${b.dataset.a}`); SCREENS.visits(); })));
  view().querySelectorAll("[data-rx]").forEach((b) => (b.onclick = () => guard(() => prescribeScreen(+b.dataset.rx, visits.find((v) => v.id === +b.dataset.rx)))));
};

async function prescribeScreen(visitId, visit) {
  const meds = await api("/api/catalog/medications");
  const rows = [{ medication_id: meds.find((m) => m.brand_name === "Dolo")?.id || meds[0].id, dosage: "1 tablet", frequency: "Every 8 hours if needed", duration_days: 2, quantity: 5, route: "oral", instructions: "As entered and approved by the licensed doctor (illustrative demo data).", refills_allowed: 0 }];
  const render = () => {
    view().innerHTML = `<div class="card"><h2>New prescription · ${esc(visit.patient.name)}</h2>
      <p class="small muted">Illustrative demo data only — not a medical recommendation.</p>
      <label class="small muted">Clinical note<textarea id="note" rows="2" style="width:100%">Demo consultation</textarea></label></div>
      ${rows.map((r, i) => `<div class="card" data-row="${i}"><div class="form-grid">
        <label>Medicine<select data-k="medication_id">${meds.map((m) => `<option value="${m.id}" ${m.id === r.medication_id ? "selected" : ""}>${esc(m.brand_name)} ${esc(m.strength)} (${esc(m.generic_name)})${m.schedule === "controlled" ? " · controlled" : ""}</option>`).join("")}</select></label>
        <label>Dosage<input data-k="dosage" value="${esc(r.dosage)}"></label><label>Frequency<input data-k="frequency" value="${esc(r.frequency)}"></label>
        <label>Duration (days)<input type="number" min="1" data-k="duration_days" value="${r.duration_days}"></label><label>Quantity<input type="number" min="1" data-k="quantity" value="${r.quantity}"></label>
        <label>Route<input data-k="route" value="${esc(r.route)}"></label><label>Refills<input type="number" min="0" data-k="refills_allowed" value="${r.refills_allowed}"></label></div>
        <label class="small muted">Special instructions<input data-k="instructions" style="width:100%" value="${esc(r.instructions)}"></label>
        ${rows.length > 1 ? `<button class="btn danger small" data-del="${i}">Remove</button>` : ""}</div>`).join("")}
      <div class="row"><button class="btn" id="addRow">Add medicine</button><button class="btn primary" id="save">Review prescription</button></div>`;
    view().querySelectorAll("[data-row]").forEach((card) => card.querySelectorAll("[data-k]").forEach((inp) => (inp.onchange = () => {
      const k = inp.dataset.k; rows[+card.dataset.row][k] = ["medication_id", "duration_days", "quantity", "refills_allowed"].includes(k) ? +inp.value : inp.value;
    })));
    view().querySelectorAll("[data-del]").forEach((b) => (b.onclick = () => { rows.splice(+b.dataset.del, 1); render(); }));
    $("#addRow").onclick = () => { rows.push({ ...rows[0], medication_id: meds[1].id, quantity: 10, frequency: "Once daily", instructions: "" }); render(); };
    $("#save").onclick = () => guard(async () => {
      const rx = await post("/api/prescriptions", { visit_id: visitId, diagnosis_note: $("#note").value, items: rows });
      reviewAndSign(rx);
    });
  };
  render();
}

function reviewAndSign(rx) {
  view().innerHTML = `<div class="card"><div class="row between"><h2>Review ${esc(rx.reference_no)}</h2><span class="badge warn">Draft · not visible to patient</span></div>
    <p class="small muted">${esc(rx.patient.name)} · ${esc(rx.doctor.name)} · Licence ${esc(rx.doctor.license_no)}</p>
    <table><tr><th>Medicine</th><th>Dosage</th><th>Frequency</th><th>Days</th><th>Qty</th></tr>${rx.items.map((i) => `<tr><td>${esc(i.medicine)} ${esc(i.strength)}<div class="small muted">${esc(i.instructions)}</div></td><td>${esc(i.dosage)}</td><td>${esc(i.frequency)}</td><td>${i.duration_days}</td><td>${i.quantity}</td></tr>`).join("")}</table>
    <label class="row small" style="margin:12px 0"><input type="checkbox" id="ok"> I have reviewed this prescription and authorise it with my electronic signature.</label>
    <button class="btn primary big" id="sign">Sign & send to patient</button></div>`;
  $("#sign").onclick = () => guard(async () => {
    const signed = await post(`/api/prescriptions/${rx.id}/sign`, { confirm_reviewed: $("#ok").checked });
    toast(`Signed. ${signed.patient.name} has been notified.`); go("prescriptions");
  });
}

SCREENS.prescriptions = async () => {
  const list = await api("/api/doctor/prescriptions");
  view().innerHTML = list.map((rx) => `<div class="card"><div class="row between"><h3>${esc(rx.reference_no)} · ${esc(rx.patient.name)}</h3><span class="badge ${rx.status === "signed" ? "good" : rx.status === "draft" ? "warn" : ""}">${esc(rx.status)}</span></div>
    <div class="small">${rx.items.map((i) => `${esc(i.medicine)} × ${i.quantity}`).join(" · ")}</div>
    <div class="row" style="margin-top:8px">${rx.status === "draft" ? `<button class="btn primary" data-sign="${rx.id}">Review & sign</button>` : ""}
    <button class="btn" data-audit="${rx.id}">Audit trail</button></div><div id="audit${rx.id}"></div></div>`).join("") || `<div class="card empty">No prescriptions yet.</div>`;
  view().querySelectorAll("[data-sign]").forEach((b) => (b.onclick = () => reviewAndSign(list.find((r) => r.id === +b.dataset.sign))));
  view().querySelectorAll("[data-audit]").forEach((b) => (b.onclick = () => guard(async () => {
    const a = await api(`/api/audit/prescriptions/${b.dataset.audit}`);
    $(`#audit${b.dataset.audit}`).innerHTML = `<div class="notice ${a.chain_valid ? "good" : "bad"} small">Audit chain ${a.chain_valid ? "intact" : "BROKEN"}</div>` +
      a.entries.map((e) => `<div class="small">${when(e.at)} · ${esc(e.actor_role)} · ${esc(e.action)}</div>`).join("");
  })));
};

SCREENS.clarifications = async () => {
  const list = await api("/api/doctor/clarifications");
  view().innerHTML = list.map((c) => `<div class="card"><div class="row between"><h3>${esc(c.reason.replaceAll("_", " "))}</h3><span class="badge ${c.status === "open" ? "warn" : "good"}">${esc(c.status)}</span></div>
    <p>${esc(c.message)}</p>${c.response ? `<p class="small muted">Your response: ${esc(c.response)}</p>` : `
    <textarea id="resp${c.id}" rows="2" style="width:100%" placeholder="Response to the pharmacist / patient"></textarea>
    <div class="row">${c.reason === "partial_quantity_authorization" ? `<button class="btn primary" data-r="${c.id}" data-auth="1">Authorise smaller quantity</button><button class="btn" data-r="${c.id}" data-auth="0">Decline</button>` : `<button class="btn primary" data-r="${c.id}">Send response</button>`}</div>
    <p class="small muted">To change the prescription itself, create a signed amendment.</p>`}</div>`).join("") || `<div class="card empty">No clarification requests.</div>`;
  view().querySelectorAll("[data-r]").forEach((b) => (b.onclick = () => guard(async () => {
    await post(`/api/clarifications/${b.dataset.r}/respond`, { response: $(`#resp${b.dataset.r}`).value || "Reviewed.", authorize: b.dataset.auth === undefined ? null : b.dataset.auth === "1" });
    toast("Response sent."); SCREENS.clarifications();
  })));
};

/* ------------------------------------------------------------- pharmacist */
SCREENS.queue = async () => {
  const orders = await api("/api/pharmacy/orders");
  view().innerHTML = orders.map((o) => `<div class="card" data-order="${o.id}"><div class="row between"><h3>${esc(o.order_no)} · ${esc(o.patient.name)}</h3><span class="badge brand">${esc(o.status_label)}</span></div>
    <div class="small muted">Rx ${esc(o.prescription.reference_no)} · ${esc(o.prescription.doctor)} (${esc(o.prescription.license_no)}) · ${esc(o.fulfillment)}${o.delivery_option ? " · " + esc(o.delivery_option) : ""}</div>
    <div class="notice ${o.prescription.valid ? "good" : "bad"} small">${o.prescription.valid ? "Prescription signature and validity verified" : "Invalid prescription: " + esc(o.prescription.issue)}</div>
    <table><tr><th>Medicine</th><th>Prescribed</th><th>Requested</th><th>Approve qty</th></tr>${o.items.map((i) => `<tr><td>${esc(i.medicine)}</td><td>${i.prescribed_quantity}</td><td>${i.requested_quantity}${i.requested_quantity < i.prescribed_quantity ? ` <span class="badge warn">partial</span>` : ""}</td>
      <td>${i.approved_quantity ?? (["prescription_received", "pharmacist_reviewing"].includes(o.status) ? `<input type="number" min="0" max="${i.requested_quantity}" value="${i.requested_quantity}" data-adj="${i.id}" style="width:70px">` : "—")}</td></tr>`).join("")}</table>
    <div class="row" style="margin-top:8px">${pharmacistActions(o)}</div><div class="clar"></div></div>`).join("") || `<div class="card empty">No orders yet.</div>`;
  view().querySelectorAll("[data-order]").forEach((card) => {
    const id = +card.dataset.order; const o = orders.find((x) => x.id === id);
    card.querySelectorAll("[data-x]").forEach((b) => (b.onclick = () => guard(async () => {
      const x = b.dataset.x;
      if (x === "start-review" || x === "prepare" || x === "ready") await post(`/api/pharmacy/orders/${id}/${x}`);
      else if (x === "approve") {
        const adj = {}; let changed = false;
        card.querySelectorAll("[data-adj]").forEach((inp) => { const it = o.items.find((i) => i.id === +inp.dataset.adj); adj[inp.dataset.adj] = +inp.value; if (+inp.value !== it.requested_quantity) changed = true; });
        await post(`/api/pharmacy/orders/${id}/review`, changed ? { decision: "adjust", notes: prompt("Note for the patient about the adjustment:") || "Quantity adjusted by pharmacist", adjustments: adj } : { decision: "approve", notes: "Approved by pharmacist" });
      } else if (x === "reject") {
        const notes = prompt("Reason for rejection (shown to patient):"); if (!notes) return;
        await post(`/api/pharmacy/orders/${id}/review`, { decision: "reject", notes });
      } else if (x === "clarify") {
        $(".clar", card).innerHTML = `<div class="row"><select id="cr${id}">${["quantity_not_dispensable", "medicine_unavailable", "incomplete_prescription", "substitution_requires_authorization", "refill_authorization"].map((r) => `<option value="${r}">${r.replaceAll("_", " ")}</option>`).join("")}</select>
          <input id="cm${id}" placeholder="Message to prescriber" style="flex:1"><button class="btn primary" id="cs${id}">Send</button></div>`;
        $(`#cs${id}`).onclick = () => guard(async () => { await post(`/api/pharmacy/orders/${id}/clarify`, { reason: $(`#cr${id}`).value, message: $(`#cm${id}`).value || "Please clarify." }); toast("Sent to prescriber."); SCREENS.queue(); });
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
  const b = (x, l, cls = "") => `<button class="btn ${cls}" data-x="${x}">${l}</button>`;
  switch (o.status) {
    case "prescription_received": return b("start-review", "Start review", "primary") + b("reject", "Reject", "danger");
    case "pharmacist_reviewing": return b("approve", "Approve / adjust", "primary") + b("clarify", "Ask prescriber") + b("reject", "Reject", "danger");
    case "order_accepted": return b("prepare", "Start preparing", "primary") + b("cancel", "Cancel & refund", "danger");
    case "preparing": return b("ready", "Dispense & mark ready", "primary") + b("cancel", "Cancel & refund", "danger");
    case "ready_for_pickup": return o.fulfillment === "pickup" ? b("pickup", "Hand over to patient", "primary") : `<span class="small muted">Waiting for courier</span>`;
    default: return "";
  }
}

/* ----------------------------------------------------------------- courier */
SCREENS.deliveries = async () => {
  const orders = (await api("/api/pharmacy/orders")).filter((o) => o.fulfillment === "delivery" && ["ready_for_pickup", "out_for_delivery", "delivered"].includes(o.status));
  view().innerHTML = orders.map((o) => `<div class="card"><div class="row between"><h3>${esc(o.order_no)} · ${esc(o.patient.name)}</h3><span class="badge brand">${esc(o.status_label)}</span></div>
    <div class="small muted">${esc(o.delivery?.tracking_ref)} · ${esc(o.delivery_option)}${o.delivery?.cold_chain ? " · ❄ keep cold" : ""}${o.delivery?.id_check_required ? " · ID check required" : ""}</div>
    <div class="row" style="margin-top:8px">${o.status === "ready_for_pickup" ? `<button class="btn primary" data-dispatch="${o.id}">Collect & start delivery</button>` : ""}
    ${o.status === "out_for_delivery" ? `<input id="code${o.id}" placeholder="Patient's code" style="width:130px"><input id="who${o.id}" placeholder="Received by"><label class="small"><input type="checkbox" id="id${o.id}"> ID checked</label><button class="btn primary" data-deliver="${o.id}">Confirm delivery</button>` : ""}</div></div>`).join("") || `<div class="card empty">No deliveries assigned.</div>`;
  view().querySelectorAll("[data-dispatch]").forEach((b) => (b.onclick = () => guard(async () => { await post(`/api/pharmacy/orders/${b.dataset.dispatch}/dispatch`); SCREENS.deliveries(); })));
  view().querySelectorAll("[data-deliver]").forEach((b) => (b.onclick = () => guard(async () => {
    const id = b.dataset.deliver;
    await post(`/api/orders/${id}/handover`, { code: $(`#code${id}`).value, recipient_name: $(`#who${id}`).value || "Patient", id_verified: $(`#id${id}`).checked });
    toast("Delivered — proof of delivery recorded."); SCREENS.deliveries();
  })));
};

/* -------------------------------------------------------------------- yana */
function setupYana() {
  const log = $("#yanaLog");
  const add = (text, who) => { const d = document.createElement("div"); d.className = `bubble ${who}`; d.textContent = text; log.appendChild(d); log.scrollTop = log.scrollHeight; };
  add("Hi, I'm Yana. I can show your prescription, find pharmacies, adjust what you buy, and track deliveries. I can't change your prescription or treatment.", "yana");
  const examples = ["Show the medicines my doctor prescribed", "Find a pharmacy near my home", "I only want to purchase three tablets instead of five", "Show the cheapest eligible pharmacy", "When will my medicine arrive?"];
  $("#yanaChips").innerHTML = examples.map((e) => `<button>${esc(e)}</button>`).join("");
  $("#yanaChips").querySelectorAll("button").forEach((b) => (b.onclick = () => send(b.textContent)));
  $("#yanaBtn").onclick = () => $("#yanaPanel").classList.toggle("open");
  $("#yanaForm").onsubmit = (e) => { e.preventDefault(); const v = $("#yanaInput").value.trim(); if (v) send(v); $("#yanaInput").value = ""; };
  async function send(text) {
    add(text, "me");
    try {
      const r = await post("/api/yana", { message: text });
      add(r.reply, "yana");
      if (["change_quantity", "remove_item"].includes(r.intent) && ["cart", "home"].includes(state.tab)) SCREENS[state.tab]();
    } catch (e) { add(e.message, "yana"); }
  }
}

boot();
