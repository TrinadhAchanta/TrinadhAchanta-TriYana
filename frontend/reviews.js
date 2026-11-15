/* Triyana: patient reviews of doctors and physios.
   Patients rate a finished visit out of 5 with a comment; the next patient sees the stars and recent comments
   when choosing or being matched with that doctor. Heros see their own rating. */

const STAR_WORDS = ["", "Very poor", "Poor", "Okay", "Good", "Excellent"];
const starRow = (n) => `<span class="stars" aria-label="${n} out of 5 stars">${"★".repeat(n)}<span class="stars-off">${"★".repeat(5 - n)}</span></span>`;

// Short average line used on doctor and physio cards: "★ 4.9 (412 reviews)" or "New on Triyana".
function ratingLine(p) {
  return p.rating_count ? `<span class="stars">★ ${Number(p.rating).toFixed(1)}</span> <span class="muted">(${p.rating_count} review${p.rating_count === 1 ? "" : "s"})</span>`
    : `<span class="muted">New on Triyana</span>`;
}

// One or two recent comments, shown under a doctor's name while booking.
function reviewQuotes(list, max = 1) {
  const rows = (list || []).filter((r) => r.comment).slice(0, max);
  return rows.map((r) => `<div class="review-quote"><span class="stars">★ ${r.stars}</span> “${esc(r.comment)}” <span class="muted">· ${esc(r.name)}</span></div>`).join("");
}

// A sheet listing every review for one doctor ("doctor") or physio ("physio").
async function reviewsSheet(kind, id) {
  const r = await api(`/api/${kind === "physio" ? "physios" : "doctors"}/${id}/reviews`);
  const s = sheet(`<div class="sheet-head"><div><h2>${esc(r.name)}</h2><p class="small">${ratingLine(r)}</p></div><button class="x" aria-label="Close">${ic("x")}</button></div>
    <div class="review-list">${r.reviews.map((x) => `<div class="review-item"><div class="row between">${starRow(x.stars)}<span class="tiny muted">${when(x.at)}</span></div>
      ${x.comment ? `<p class="small" style="margin:6px 0 2px">${esc(x.comment)}</p>` : ""}<div class="tiny muted">${esc(x.name)}${x.sample ? " · sample review" : ""}</div></div>`).join("")
      || `<p class="muted small">No written reviews yet.</p>`}</div>
    ${r.demo_samples ? `<p class="tiny muted" style="margin:10px 0 0">${ic("info")} Demo: some of these are sample reviews so the profile isn't empty.</p>` : ""}`);
  $(".x", s.el).onclick = s.close;
}

// Wire "Read reviews" links inside any container. They sit inside clickable cards, so don't select the card.
function wireReviewLinks(root = document) {
  $$("[data-reviews]", root).forEach((x) => (x.onclick = (e) => {
    e.preventDefault(); e.stopPropagation();
    const [kind, id] = x.dataset.reviews.split(":");
    guard(() => reviewsSheet(kind, +id));
  }));
}

// The rate sheet: tap 1-5 stars, optionally write a comment, send.
function rateSheet({ kind, job_id, provider, for_name }, start = 0, after = () => {}) {
  let stars = start;
  const who = kind === "physio" ? "your physiotherapist" : "your doctor";
  const s = sheet(`<div class="sheet-head"><div><h2>How was ${esc(provider)}?</h2><p class="small muted">${for_name ? `Visit for ${esc(for_name.split(" ")[0])}. ` : ""}Your rating helps the next patient choose. Only your first name and initial are shown.</p></div><button class="x" aria-label="Close">${ic("x")}</button></div>
    <div class="rate-stars" role="radiogroup" aria-label="Stars">${[1, 2, 3, 4, 5].map((n) => `<button type="button" role="radio" data-star="${n}" aria-label="${n} star${n > 1 ? "s" : ""}">★</button>`).join("")}</div>
    <div class="rate-word" id="rateWord">Tap a star</div>
    <label class="field">Tell others about ${who} (optional)<textarea id="rateText" rows="3" maxlength="500" placeholder="For example: came on time, explained everything clearly"></textarea></label>
    <button class="btn primary block" id="rateGo" disabled>${ic("check")} Send review</button>`);
  const draw = () => {
    $$("[data-star]", s.el).forEach((b) => { const on = +b.dataset.star <= stars; b.classList.toggle("on", on); b.setAttribute("aria-checked", String(+b.dataset.star === stars)); });
    $("#rateWord", s.el).textContent = stars ? STAR_WORDS[stars] : "Tap a star";
    $("#rateGo", s.el).disabled = !stars;
  };
  $$("[data-star]", s.el).forEach((b) => (b.onclick = () => { stars = +b.dataset.star; draw(); }));
  $(".x", s.el).onclick = s.close;
  $("#rateGo", s.el).onclick = () => guard(async () => {
    await post("/api/patient/reviews", { kind, job_id, stars, comment: $("#rateText", s.el).value });
    s.close(); toast("Thank you! Your review is live.", "check"); after();
  });
  draw();
}

// Home: "How was your visit with Dr. Sana?" with tappable stars, for the newest unrated finished visit.
function reviewPromptHTML(p) {
  if (!p) return "";
  return `<div class="card rate-prompt" data-rate-kind="${p.kind}" data-rate-job="${p.job_id}">
    <div class="row" style="flex-wrap:nowrap;gap:12px"><div class="avatar">${esc(initials(p.provider))}</div>
      <div class="grow"><b>How was your ${p.kind === "physio" ? "physiotherapy" : "visit"} with ${esc(p.provider)}?</b>
        <div class="tiny muted">${p.for_name ? `For ${esc(p.for_name.split(" ")[0])} · ` : ""}${esc(p.role)} · ${when(p.at)}</div></div></div>
    <div class="rate-stars sm">${[1, 2, 3, 4, 5].map((n) => `<button type="button" data-pstar="${n}" aria-label="${n} star${n > 1 ? "s" : ""}">★</button>`).join("")}</div></div>`;
}
async function mountReviewPrompt(slot, after) {
  if (!slot) return;
  const list = await api("/api/patient/reviews/pending").catch(() => []);
  const p = list[0];
  slot.innerHTML = reviewPromptHTML(p);
  if (p) $$("[data-pstar]", slot).forEach((b) => (b.onclick = () => rateSheet(p, +b.dataset.pstar, after)));
}

// A finished visit or physio package: "You rated ★★★★★" or a "Rate" button.
function myReviewHTML(review, attrs) {
  if (review) return `<div class="my-review small">${starRow(review.stars)} <span class="muted">You rated this${review.hidden ? " (hidden by Triyana's team)" : ""}</span>${review.comment ? `<div class="tiny muted">“${esc(review.comment)}”</div>` : ""}</div>`;
  return attrs ? `<button class="btn sm" ${attrs}>★ Rate</button>` : "";
}
function wireRateButtons(root, after) {
  $$("[data-rate]", root).forEach((b) => (b.onclick = () => {
    const [kind, id] = b.dataset.rate.split(":");
    rateSheet({ kind, job_id: +id, provider: b.dataset.provider || (kind === "physio" ? "your physiotherapist" : "your doctor") }, 0, after);
  }));
}

/* ------------------------------------------------------------------ Heros: my rating */
async function heroRatingCard(slot) {
  if (!slot) return;
  const r = await api("/api/provider/reviews").catch(() => null);
  if (!r) { slot.innerHTML = ""; return; }
  slot.innerHTML = `<button class="card hero-rating" id="myReviews"><div class="row between"><span class="eyebrow-sm">★ Your rating</span><span class="tiny muted">${r.rating_count} review${r.rating_count === 1 ? "" : "s"}</span></div>
    <div class="earn-big">${r.rating_count ? Number(r.rating).toFixed(1) : "—"} <span class="stars" style="font-size:18px">${r.rating_count ? starRow(Math.round(r.rating)) : ""}</span></div>
    ${reviewQuotes(r.reviews, 2) || `<p class="tiny muted" style="margin:6px 0 0">Patients can rate you after each finished visit.</p>`}
    <div class="row between small" style="margin-top:6px"><span class="muted">What patients said</span><span class="strong" style="color:var(--brand)">All reviews ›</span></div></button>`;
  $("#myReviews", slot).onclick = () => {
    const s = sheet(`<div class="sheet-head"><div><h2>Your reviews</h2><p class="small">${ratingLine(r)}</p></div><button class="x" aria-label="Close">${ic("x")}</button></div>
      <div class="review-list">${r.reviews.map((x) => `<div class="review-item"><div class="row between">${starRow(x.stars)}<span class="tiny muted">${when(x.at)}</span></div>
        ${x.comment ? `<p class="small" style="margin:6px 0 2px">${esc(x.comment)}</p>` : ""}<div class="tiny muted">${esc(x.name)}${x.sample ? " · sample review" : ""}</div></div>`).join("") || `<p class="muted small">No reviews yet.</p>`}</div>
      <p class="tiny muted" style="margin:10px 0 0">${ic("info")} Patients rate you out of 5 after a finished visit. Triyana's team removes abusive reviews.${r.demo_samples ? " Demo: some are sample reviews." : ""}</p>`);
    $(".x", s.el).onclick = s.close;
  };
}
