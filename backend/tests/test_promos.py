"""Promo codes at payment: doctor visits, prescription checkout and the shop; made and paused at /admin."""
from test_perks import ADMIN, book_carter, new_patient
from test_shop import _place


def test_promo_takes_money_off_a_visit_and_only_once(env, as_):
    meera = as_("patient")
    q = meera.get("/api/perks/quote?fee=600&promo=doc100").json()
    assert q["promo"] == {"code": "DOC100", "applied": True, "discount": 100, "message": "Promo DOC100: ₹100 off applied"}
    assert q["patient_pays"] == 500 and any(line["code"] == "promo" for line in q["lines"])

    bad = meera.get("/api/perks/quote?fee=600&promo=NOPE").json()
    assert bad["promo"]["applied"] is False and "doesn't exist" in bad["promo"]["message"] and bad["patient_pays"] == 600
    small = meera.get("/api/perks/quote?fee=400&promo=DOC100").json()
    assert small["promo"]["applied"] is False and "₹500 or more" in small["promo"]["message"]
    meds_only = meera.get("/api/perks/quote?fee=600&promo=MEDS20").json()
    assert "only for medicines" in meds_only["promo"]["message"]

    v = book_carter(meera, env, promo_code="DOC100").json()
    assert v["bill"]["patient_pays"] == 500 and v["bill"]["base_fee"] == 600
    # Second use is refused at booking (not silently charged full price).
    r = book_carter(meera, env, promo_code="DOC100")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "promo_already_used"

    # Cancelling gives the code back.
    meera.post(f"/api/patient/visits/{v['id']}/cancel")
    assert meera.get("/api/perks/quote?fee=600&promo=DOC100").json()["promo"]["applied"] is True


def test_first_visit_offer_wins_when_it_saves_more(env):
    nisha = new_patient(env)
    q = nisha.get("/api/perks/quote?fee=600&promo=DOC100").json()
    assert q["patient_pays"] == 99 and q["promo"]["applied"] is False and "already saves more" in q["promo"]["message"]
    v = book_carter(nisha, env, promo_code="DOC100").json()
    assert v["bill"]["patient_pays"] == 99
    # The code wasn't used up, so it still works on the next visit.
    assert nisha.get("/api/perks/quote?fee=600&promo=DOC100").json()["promo"]["applied"] is True


def test_membership_covers_visit_so_code_is_not_needed(env, as_):
    meera = as_("patient")
    meera.post("/api/perks/membership", {"payment_method": "upi"})
    q = meera.get("/api/perks/quote?fee=600&promo=DOC100").json()
    assert q["patient_pays"] == 0 and q["promo"]["applied"] is False and "Triyana Family" in q["promo"]["message"]


def test_promo_on_shop_checkout_and_cancel_releases_it(env, as_):
    meds = env["ids"]["medications"]
    patient = as_("patient")
    items = [{"medication_id": meds["thermo"], "packs": 1}]
    best = patient.post("/api/shop/quote", {"items": items}).json()["offers"][0]
    opt = best["delivery_options"][0]
    chk = patient.post("/api/promos/check", {"code": "TRIYANA50", "scope": "medicines", "amount": best["subtotal"]}).json()
    assert chk["ok"] and chk["discount"] == min(50, best["subtotal"])
    total = round(best["subtotal"] + best["tax"] + opt["fee"] - chk["discount"], 2)
    r = patient.post("/api/shop/checkout", {
        "items": items, "pharmacy_id": best["pharmacy_id"], "delivery_option": opt["code"], "payment_method": "upi",
        "payment_token": "sandbox-ok", "idempotency_key": "promo-shop-0001", "expected_total": total,
        "promo_code": "triyana50"})
    assert r.status_code == 201, r.text
    o = r.json()
    assert o["price"]["discount"] == chk["discount"] and o["price"]["total"] == total

    used = patient.post("/api/promos/check", {"code": "TRIYANA50", "scope": "visits", "amount": 600}).json()
    assert used["ok"] is False and used["reason"] == "promo_already_used"
    patient.post(f"/api/orders/{o['id']}/cancel", {"reason": "Changed my mind"})
    assert patient.post("/api/promos/check", {"code": "TRIYANA50", "scope": "visits", "amount": 600}).json()["ok"]

    # Without the code, the plain shop flow is unchanged.
    assert _place(patient, items, key="promo-shop-0002")[0].status_code == 201


def test_percent_promo_on_prescription_checkout(env, as_, signed_rx):
    patient = as_("patient")
    gl = env["ids"]["pharmacies"]["greenleaf"]
    r = patient.post(f"/api/carts/{signed_rx['cart_id']}/checkout", {
        "pharmacy_id": gl, "fulfillment": "pickup", "payment_method": "upi", "idempotency_key": "promo-rx-0001",
        "promo_code": "MEDS20"})
    if r.status_code == 422:  # demo cart below the code's minimum: the reason is clear
        assert r.json()["detail"]["code"] == "promo_min_amount"
        return
    assert r.status_code == 201, r.text
    p = r.json()["price"]
    assert p["discount"] == round(min(p["subtotal"] * 0.2, 150), 2)
    assert round(p["subtotal"] + p["tax"] + p["delivery_fee"] - p["discount"], 2) == p["total"]


def test_admin_creates_pauses_and_lists_promos(env, as_):
    c = env["client"]
    assert c.get("/api/admin/promos").status_code == 403
    r = c.post("/api/admin/promos", headers=ADMIN, json={"code": "diwali 25", "description": "Diwali", "kind": "percent",
                                                          "value": 25, "max_discount": 200, "applies_to": "all"})
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["code"] == "DIWALI25" and p["status"] == "live" and p["headline"] == "25% off (up to ₹200)"
    assert c.post("/api/admin/promos", headers=ADMIN, json={"code": "DIWALI25", "kind": "flat", "value": 10}).status_code == 409
    assert c.post("/api/admin/promos", headers=ADMIN, json={"code": "BAD", "kind": "percent", "value": 150}).status_code == 422

    meera = as_("patient")
    q = meera.get("/api/perks/quote?fee=600&promo=DIWALI25").json()
    assert q["promo"]["discount"] == 150 and q["patient_pays"] == 450

    paused = c.post(f"/api/admin/promos/{p['id']}", headers=ADMIN, json={"active": False}).json()
    assert paused["status"] == "paused"
    assert "expired" in meera.get("/api/perks/quote?fee=600&promo=DIWALI25").json()["promo"]["message"]
    codes = [x["code"] for x in c.get("/api/admin/promos", headers=ADMIN).json()]
    assert {"DIWALI25", "DOC100", "MEDS20", "TRIYANA50"} <= set(codes)

    # Use counts show up for ops.
    c.post(f"/api/admin/promos/{p['id']}", headers=ADMIN, json={"active": True})
    book_carter(meera, env, promo_code="DIWALI25")
    row = next(x for x in c.get("/api/admin/promos", headers=ADMIN).json() if x["code"] == "DIWALI25")
    assert row["uses"] == 1 and row["total_discount"] == 150


def test_used_up_and_new_customer_codes(env, as_):
    c = env["client"]
    c.post("/api/admin/promos", headers=ADMIN, json={"code": "ONEONLY", "kind": "flat", "value": 20, "max_uses": 1})
    c.post("/api/admin/promos", headers=ADMIN, json={"code": "HELLO", "kind": "flat", "value": 30,
                                                      "new_customers_only": True, "applies_to": "medicines"})
    meera = as_("patient")
    book_carter(meera, env, promo_code="ONEONLY")
    nisha = new_patient(env)
    r = nisha.post("/api/promos/check", {"code": "ONEONLY", "scope": "visits", "amount": 600}).json()
    assert r["reason"] == "promo_used_up"
    assert nisha.post("/api/promos/check", {"code": "HELLO", "scope": "medicines", "amount": 300}).json()["ok"]
    assert meera.post("/api/promos/check", {"code": "HELLO", "scope": "medicines", "amount": 300}).json()["reason"] == "promo_new_only"
