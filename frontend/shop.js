/* Triyana — online medicine shop: browse, basket, pay, rider delivers to the door.
   Over-the-counter products are sold freely. Prescription medicines link to the patient's
   prescription cart (pharmacist-checked); without a prescription they can book a doctor. */
"use strict";

Object.assign(P, {
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  scooter: '<circle cx="6" cy="17" r="2.5"/><circle cx="18" cy="17" r="2.5"/><path d="M8.5 17h7M14 6h3l2 8M6 14.5V11h6l2 6"/>',
  drop: '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/>',
  bandage: '<rect x="2.5" y="8" width="19" height="8" rx="4" transform="rotate(-45 12 12)"/><path d="M10.5 10.5h.01M13.5 13.5h.01M13.5 10.5h.01M10.5 13.5h.01"/>',
  thermo: '<path d="M14 14.8V4a2 2 0 0 0-4 0v10.8a4 4 0 1 0 4 0z"/><path d="M12 10v7"/>',
  leaf: '<path d="M5 19c0-8 5-13 15-14-1 10-6 15-14 15"/><path d="M5 19l7-7"/>',
});

const AISLE_ICON = { "Cold & allergy": ["drop", "c2"], "Digestive care": ["pills", "c3"], "Vitamins & nutrition": ["leaf", ""],
  "First aid": ["bandage", "c4"], "Pain relief": ["heart", "c4"], "Devices & hygiene": ["thermo", "c2"], "Fever & pain": ["thermo", "c4"] };
const aisleIcon = (cat) => AISLE_ICON[cat] || ["pills", "c3"];

/* ------------------------------------------------------------------ basket (per signed-in patient) */
const basketKey = () => `triyana.basket.${state.token}`;
function basket() { try { return JSON.parse(localStorage.getItem(basketKey()) || "{}"); } catch { return {}; } }
function saveBasket(b) { try { localStorage.setItem(basketKey(), JSON.stringify(b)); } catch {} }
const basketLines = (b = basket()) => Object.entries(b).map(([id, l]) => ({ medication_id: +id, ...l })).filter((l) => l.packs > 0);
const basketCount = (b = basket()) => basketLines(b).reduce((n, l) => n + l.packs, 0);
const basketTotal = (b = basket()) => basketLines(b).reduce((n, l) => n + l.packs * l.price, 0);
function setPacks(p, packs) {
  const b = basket();
  if (packs <= 0) delete b[p.id];
  else b[p.id] = { packs: Math.min(packs, p.max_packs || 10), name: p.name, price: p.price, pack_label: p.pack_label, category: p.category };
  saveBasket(b);
}

/* ------------------------------------------------------------------ shop screen */
const shopState = { q: "", category: "" };

SCREENS.shop = async () => {
  const data = await api(`/api/shop/products?q=${encodeURIComponent(shopState.q)}&category=${encodeURIComponent(shopState.category)}`);
  const otc = data.products.filter((p) => p.kind === "otc");
  const rx = data.products.filter((p) => p.kind !== "otc");
  view().innerHTML = `
    <section class="hero shop-hero"><div class="eyebrow">Triyana Pharmacy</div>
      <h1>Medicines and essentials, at your door</h1>
      <p>Order from licensed pharmacies near you. A Triyana rider picks it up and you watch them arrive on the map.</p>
      <div class="stats"><div class="stat"><b>${data.pharmacies_nearby}</b><span>Licensed pharmacies nearby</span></div>
        <div class="stat"><b>&lt; 1 hour</b><span>Express rider delivery</span></div>
        <div class="stat"><b>${ic("shield")}</b><span>Pharmacist-checked prescriptions</span></div></div>
    </section>
    <div class="shop-search">${ic("search")}<input id="shopQ" type="search" placeholder="Search medicines and health products" value="${esc(shopState.q)}" autocomplete="off"></div>
    <div class="aisles" role="tablist">
      <button class="${shopState.category ? "" : "on"}" data-cat="">All</button>
      ${data.categories.map((c) => `<button class="${c.name === shopState.category ? "on" : ""}" data-cat="${esc(c.name)}">${esc(c.name)}</button>`).join("")}
    </div>
    ${otc.length ? `<div class="section-title">No prescription needed</div><div class="products">${otc.map(productCard).join("")}</div>` : ""}
    ${rx.length ? `<div class="section-title">Prescription medicines</div>
      <div class="notice info small">${ic("rx")}<span>${esc(data.rule)}</span></div>
      <div class="products">${rx.map(productCard).join("")}</div>` : ""}
    ${!otc.length && !rx.length ? empty("search", "Nothing found", "Try another name, like ORS or vitamin C.") : ""}
    <div id="basketBar"></div>`;
  let t;
  $("#shopQ").oninput = (e) => { clearTimeout(t); t = setTimeout(() => { shopState.q = e.target.value; refreshShop(true); }, 300); };
  $$("[data-cat]").forEach((b) => (b.onclick = () => { shopState.category = b.dataset.cat; refreshShop(); }));
  wireProducts(data.products);
  renderBasketBar();
};

async function refreshShop(keepFocus = false) {
  const pos = keepFocus ? $("#shopQ")?.selectionStart : null;
  await guard(() => SCREENS.shop());
  if (keepFocus) { const q = $("#shopQ"); q.focus(); q.setSelectionRange(pos, pos); }
}

function stepper(p, packs) {
  return `<div class="stepper"><button data-dec="${p.id}" aria-label="Remove one">${ic(packs > 1 ? "minus" : "x")}</button><b>${packs}</b><button data-inc="${p.id}" aria-label="Add one" ${packs >= p.max_packs ? "disabled" : ""}>${ic("plus")}</button></div>`;
}

function productCard(p) {
  const [icon, tone] = aisleIcon(p.category);
  const packs = basket()[p.id]?.packs || 0;
  let action;
  if (p.kind === "otc") action = !p.in_stock ? `<span class="badge">Out of stock nearby</span>` : packs ? stepper(p, packs) : `<button class="btn primary sm" data-add="${p.id}">${ic("plus")} Add</button>`;
  else if (p.kind === "blocked") action = `<span class="badge bad">Not sold online</span>`;
  else if (p.rx_cart) action = `<button class="btn sm" data-rx="${p.rx_cart.cart_id}">${ic("rx")} Buy with my prescription</button>`;
  else action = `<button class="btn ghost sm" data-go-book>${ic("stethoscope")} See a doctor</button>`;
  return `<article class="product ${p.kind}" data-p="${p.id}">
    <div class="product-art pill ${p.kind === "otc" ? tone : "off"}">${ic(icon, "lg")}</div>
    <div class="product-body">
      <div class="row" style="gap:6px">${p.kind === "otc" ? `<span class="badge good">OTC</span>` : schedBadge(p.india_schedule)}${p.cold_chain ? `<span class="badge info">${ic("snow")} Cold</span>` : ""}</div>
      <b class="product-name">${esc(p.name)}</b>
      <span class="tiny muted">${esc(p.generic_name)}${p.strength && p.form !== "device" ? ` · ${esc(p.strength)}` : ""}</span>
      <span class="tiny muted">${esc(p.pack_label)}</span>
      ${p.kind === "otc" ? `<p class="small muted product-desc">${esc(p.description)}</p>` : `<p class="small muted product-desc">${esc(p.rx_cart ? `On your prescription ${p.rx_cart.prescription} from ${p.rx_cart.doctor}.` : p.note)}</p>`}
    </div>
    <div class="product-foot">
      ${p.kind === "otc" ? `<div><b class="price-now">${money(p.price)}</b> <s class="tiny muted">${money(p.mrp)}</s></div>` : `<span></span>`}
      <div class="product-action">${action}</div>
    </div></article>`;
}

function wireProducts(products) {
  const byId = Object.fromEntries(products.map((p) => [p.id, p]));
  const redraw = (id) => {
    const card = $(`[data-p="${id}"]`);
    if (card) { card.outerHTML = productCard(byId[id]); wireProducts([byId[id]]); }
    renderBasketBar();
  };
  products.forEach((p) => {
    const card = $(`[data-p="${p.id}"]`); if (!card) return;
    $$("[data-add]", card).forEach((b) => (b.onclick = () => { setPacks(p, 1); toast(`${p.name} added to your basket`, "bag"); redraw(p.id); }));
    $$("[data-inc]", card).forEach((b) => (b.onclick = () => { setPacks(p, (basket()[p.id]?.packs || 0) + 1); redraw(p.id); }));
    $$("[data-dec]", card).forEach((b) => (b.onclick = () => { setPacks(p, (basket()[p.id]?.packs || 0) - 1); redraw(p.id); }));
    $$("[data-rx]", card).forEach((b) => (b.onclick = () => go("cart", { cartId: +b.dataset.rx })));
    $$("[data-go-book]", card).forEach((b) => (b.onclick = () => go("book")));
  });
}

function renderBasketBar() {
  const el = $("#basketBar"); if (!el) return;
  const n = basketCount();
  el.innerHTML = n ? `<button class="basket-bar" id="openBasket"><span class="basket-count">${n}</span><span class="grow">View basket</span><b>${money(basketTotal())}</b>${ic("arrow")}</button>` : "";
  if (n) $("#openBasket").onclick = () => go("basket");
}

/* ------------------------------------------------------------------ basket + checkout */
async function payShopWithRazorpay(body, total, method) {
  const intent = await post("/api/shop/payment-intent", body);
  if (Math.abs(intent.amount - total) > 0.009) throw new Error("The total changed. Please review the updated price.");
  await loadRazorpay();
  const r = await new Promise((resolve, reject) => {
    const rz = new window.Razorpay({
      key: intent.key_id, order_id: intent.order_id, amount: intent.amount_paise, currency: "INR", name: "Triyana",
      description: "Pharmacy order · rider delivery", prefill: { ...intent.prefill, method }, theme: { color: "#0b7a6c" }, handler: resolve,
      modal: { ondismiss: () => reject(new Error("Payment cancelled. You have not been charged.")) },
    });
    rz.on("payment.failed", (e) => reject(new Error(e?.error?.description || "Payment failed. You have not been charged.")));
    rz.open();
  });
  return `rzp:${r.razorpay_order_id}:${r.razorpay_payment_id}:${r.razorpay_signature}`;
}

SCREENS.basket = async () => {
  const lines = basketLines();
  if (!lines.length) {
    view().innerHTML = pageHead("Your basket", "", `<button class="btn ghost" data-back>← Shop</button>`) +
      empty("bag", "Your basket is empty", "Add ORS, vitamins, first-aid and more from the shop.") +
      `<div class="row" style="justify-content:center"><button class="btn primary" data-back>${ic("store")} Browse the shop</button></div>`;
    $$("[data-back]").forEach((b) => (b.onclick = () => go("shop")));
    return;
  }
  const items = lines.map((l) => ({ medication_id: l.medication_id, packs: l.packs }));
  let quote;
  try { quote = await post("/api/shop/quote", { items }); } catch (e) {
    if (e.detail?.code === "prescription_required" || e.detail?.code === "schedule_x_online_sale") {
      const b = basket(); lines.forEach((l) => { if (l.name === e.detail.medicine) delete b[l.medication_id]; }); saveBasket(b);
    }
    throw e;
  }
  const [methods, cfg] = await Promise.all([api("/api/payment-methods"), api("/api/payment-config")]);
  const rzp = cfg.gateway === "razorpay";
  const opt = { pharmacy: quote.offers[0]?.pharmacy_id, delivery: quote.offers[0]?.delivery_options[0]?.code, method: methods[0].code, decline: false, more: false };
  const key = `shop-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const render = () => {
    const offer = quote.offers.find((o) => o.pharmacy_id === opt.pharmacy);
    const d = offer?.delivery_options.find((x) => x.code === opt.delivery);
    const total = offer && d ? r2(offer.subtotal + offer.tax + d.fee) : null;
    const others = quote.offers.filter((o) => o.pharmacy_id !== opt.pharmacy);
    view().innerHTML = pageHead("Your basket", `${basketCount()} item${basketCount() === 1 ? "" : "s"} · delivered by a Triyana rider`, `<button class="btn ghost" data-back>← Keep shopping</button>`) + `
      <div class="split"><div>
        <div class="card"><h3>Items</h3>${quote.lines.map((l) => { const [icon, tone] = aisleIcon(basket()[l.medication_id]?.category);
          return `<div class="list-item"><div class="pill sm ${tone}">${ic(icon)}</div><div class="grow"><b>${esc(l.name)}</b><div class="tiny muted">${esc(l.pack_label)}</div></div>
          ${stepper({ id: l.medication_id, max_packs: 10 }, l.packs)}</div>`; }).join("")}</div>
        ${offer ? `<div class="card"><h3>Delivery</h3>
          <div class="list-item"><div class="avatar">${ic("store")}</div><div class="grow"><b>${esc(shortName(offer.name))}</b><div class="tiny muted">${offer.distance_km} km away · ★ ${offer.rating} · has everything in stock</div></div>
            ${others.length ? `<button class="btn ghost sm" id="morePh">${opt.more ? "Hide" : "Change"}</button>` : ""}</div>
          ${opt.more ? `<div class="choice-grid" style="margin:4px 0 12px">${others.map((o) => `<button class="choice" data-ph="${o.pharmacy_id}"><span class="ico">${ic("store")}</span><div><b>${esc(shortName(o.name))}</b><span>${o.distance_km} km · ${money(o.subtotal)}</span></div></button>`).join("")}</div>` : ""}
          <div class="choice-grid" style="margin-top:8px">${offer.delivery_options.map((x) => `<button class="choice ${x.code === opt.delivery ? "on" : ""}" data-d="${x.code}"><span class="ico">${ic(x.code === "priority" ? "scooter" : DELIV[x.code]?.[0] || "truck")}</span><div><b>${x.code === "priority" ? "Express rider" : esc(DELIV[x.code]?.[1] || x.label)}</b><span>~${mins(x.eta_minutes)} · ${money(x.fee)}</span></div></button>`).join("")}</div>
          <div class="notice good small" style="margin-top:12px">${ic("scooter")}<span>The nearest online rider picks it up from the pharmacy. You'll see them on a live map, and share a handover code at the door.</span></div></div>
        <div class="card"><h3>Payment method</h3><div class="choice-grid" style="margin-top:12px">${methods.map((m) => `<button class="choice ${m.code === opt.method ? "on" : ""}" data-m="${m.code}"><span class="ico">${ic(PAY_ICON[m.code] || "card")}</span><div><b>${esc(m.label)}</b></div></button>`).join("")}</div>
          ${rzp ? "" : `<label class="check" style="margin-top:14px"><input type="checkbox" id="decline" ${opt.decline ? "checked" : ""}> <span class="small muted">Sandbox: simulate a declined payment</span></label>`}</div>`
        : `<div class="notice warn">${ic("alert")}<span>${esc(quote.note)} ${quote.unavailable.map((u) => `${esc(shortName(u.pharmacy))}: missing ${u.missing.map(esc).join(", ")}`).join(" · ")}</span></div>`}
      </div><aside class="sticky">${offer ? `<div class="card featured"><h3>Bill summary</h3>
        <table class="price" style="margin-top:8px"><tr><td>Item total</td><td>${money(offer.subtotal)}</td></tr><tr><td>Delivery fee</td><td>${money(d.fee)}</td></tr>
          <tr><td>Taxes</td><td>${money(offer.tax)}</td></tr><tr class="total"><td>To pay</td><td>${money(total)}</td></tr></table>
        <button class="btn primary block" id="pay">${ic("lock")} Pay ${money(total)}</button>
        <p class="tiny muted" style="text-align:center;margin:10px 0 0">${rzp ? (cfg.test_mode ? "Secured by Razorpay · test mode, no real money moves" : "Secured by Razorpay") : "Sandbox payments · no real money moves"}</p>
      </div>` : ""}</aside></div>`;
    $$("[data-back]").forEach((b) => (b.onclick = () => go("shop")));
    $$("[data-inc],[data-dec]").forEach((b) => (b.onclick = () => {
      const id = +(b.dataset.inc || b.dataset.dec); const bk = basket(); const l = bk[id];
      l.packs += b.dataset.inc ? 1 : -1; if (l.packs <= 0) delete bk[id]; else l.packs = Math.min(l.packs, 10);
      saveBasket(bk); SCREENS.basket().catch((e) => toast(e.message, "alert"));
    }));
    const more = $("#morePh"); if (more) more.onclick = () => { opt.more = !opt.more; render(); };
    $$("[data-ph]").forEach((b) => (b.onclick = () => { opt.pharmacy = +b.dataset.ph; opt.more = false; const o = quote.offers.find((x) => x.pharmacy_id === opt.pharmacy); opt.delivery = o.delivery_options[0].code; render(); }));
    $$("[data-d]").forEach((b) => (b.onclick = () => { opt.delivery = b.dataset.d; render(); }));
    $$("[data-m]").forEach((b) => (b.onclick = () => { opt.method = b.dataset.m; render(); }));
    if ($("#decline")) $("#decline").onchange = (e) => (opt.decline = e.target.checked);
    const pay = $("#pay");
    if (pay) pay.onclick = () => guard(async () => {
      pay.disabled = true; pay.textContent = "Processing…";
      try {
        const body = { items, pharmacy_id: opt.pharmacy, delivery_option: opt.delivery };
        const token = rzp ? await payShopWithRazorpay(body, total, opt.method) : opt.decline ? "sandbox-decline" : "sandbox-ok";
        pay.textContent = "Placing order…";
        const order = await post("/api/shop/checkout", { ...body, payment_method: opt.method, payment_token: token, idempotency_key: key, expected_total: total });
        saveBasket({});
        toast("Order placed. A rider is assigned as soon as it's packed.", "scooter");
        go("orders", { orderId: order.id });
      } catch (e) { render(); throw e; }
    });
  };
  render();
};
