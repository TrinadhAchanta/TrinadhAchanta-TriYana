"""Online medicine shop: OTC sold freely, prescription medicines only via a valid prescription,
and delivery by the nearest online rider with live tracking."""
from datetime import timedelta

from app.models import PharmacyInventory, PharmacyOrder, utcnow


def _product(cat, name):
    return next(p for p in cat["products"] if p["name"] == name)


def _status(api):
    r = api.get("/api/provider/status")
    assert r.status_code == 200, r.text
    return r.json()


def _place(patient, items, decline=False, key="shop-test-0001"):
    q = patient.post("/api/shop/quote", {"items": items})
    assert q.status_code == 200, q.text
    q = q.json()
    best = q["offers"][0]
    opt = best["delivery_options"][0]
    total = round(best["subtotal"] + best["tax"] + opt["fee"], 2)
    return patient.post("/api/shop/checkout", {
        "items": items, "pharmacy_id": best["pharmacy_id"], "delivery_option": opt["code"],
        "payment_method": "upi", "payment_token": "sandbox-decline" if decline else "sandbox-ok",
        "idempotency_key": key, "expected_total": total,
    }), best


def _age_order(env, oid, seconds):
    with env["Session"]() as s:
        o = s.get(PharmacyOrder, oid)
        o.created_at = o.created_at - timedelta(seconds=seconds)
        s.commit()


def test_catalog_shows_otc_freely_and_gates_prescription_medicines(as_, signed_rx):
    cat = as_("patient").get("/api/shop/products").json()
    names = {p["name"]: p for p in cat["products"]}
    assert names["Hydrademo ORS"]["kind"] == "otc" and names["Hydrademo ORS"]["in_stock"]
    assert names["Hydrademo ORS"]["price"] > 0 and names["Hydrademo ORS"]["pack_size"] == 5
    assert names["Cetrizet"]["kind"] == "otc"
    # Prescription medicines are listed but link to the patient's prescription cart (Meera has Dolo + Pantodemo).
    assert names["Dolo"]["kind"] == "rx" and names["Dolo"]["rx_cart"]["cart_id"] == signed_rx["cart_id"]
    assert names["Amoxidemo"]["kind"] == "rx" and names["Amoxidemo"]["rx_cart"] is None
    assert names["Ritademo"]["kind"] == "blocked"
    assert {"Digestive care", "First aid"} <= {c["name"] for c in cat["categories"]}
    # Search and aisle filters.
    found = as_("patient").get("/api/shop/products", params={"q": "vitamin"}).json()["products"]
    assert {p["name"] for p in found} == {"Vitademo C", "Dailydemo Multivitamin"}
    aisle = as_("patient").get("/api/shop/products", params={"category": "First aid"}).json()["products"]
    assert {p["category"] for p in aisle} == {"First aid"}
    # Only patients use the shop.
    assert as_("courier").get("/api/shop/products").status_code == 403


def test_prescription_and_schedule_x_medicines_cannot_be_bought_from_the_shop(env, as_):
    meds = env["ids"]["medications"]
    p = as_("patient")
    r = p.post("/api/shop/quote", {"items": [{"medication_id": meds["dolo"], "packs": 1}]})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "prescription_required"
    r = p.post("/api/shop/quote", {"items": [{"medication_id": meds["rita"], "packs": 1}]})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "schedule_x_online_sale"
    r = p.post("/api/shop/quote", {"items": [{"medication_id": meds["cetri"], "packs": 11}]})
    assert r.status_code == 422


def test_shop_order_is_packed_and_delivered_by_nearest_rider_with_live_tracking(env, as_):
    meds = env["ids"]["medications"]
    patient, asha, kiran = as_("patient"), as_("courier"), as_("courier2")
    items = [{"medication_id": meds["ors"], "packs": 2}, {"medication_id": meds["thermo"], "packs": 1}]
    r, best = _place(patient, items)
    assert r.status_code == 201, r.text
    o = r.json()
    assert best["name"].startswith("GreenLeaf")  # only GreenLeaf stocks the thermometer
    assert o["source"] == "shop" and o["status"] == "order_accepted" and o["prescription_id"] is None
    assert o["payment"]["status"] == "captured" and o["fulfillment"] == "delivery"
    assert {i["approved_quantity"] for i in o["items"]} == {10, 1}

    # The pharmacist sees it as a no-prescription order.
    queue = as_("pharmacist").get("/api/pharmacy/orders").json()
    row = next(x for x in queue if x["id"] == o["id"])
    assert row["prescription"] is None and row["patient"]["name"]

    # Stand-in for the pharmacy's own system: packs it, then the nearest online rider is offered the job.
    _age_order(env, o["id"], 3600)
    assert patient.get(f"/api/orders/{o['id']}/live").json()["phase"] == "searching"
    assert patient.get(f"/api/orders/{o['id']}").json()["status"] == "ready_for_pickup"
    off = _status(asha)["offers"]
    assert len(off) == 1 and off[0]["kind"] == "delivery"
    assert not _status(kiran)["offers"]
    acc = asha.post(f"/api/provider/offers/{off[0]['id']}/accept").json()
    assert acc["trip"]["leg"] == "to_pharmacy"
    assert asha.post(f"/api/pharmacy/orders/{o['id']}/dispatch").json()["status"] == "out_for_delivery"
    live = patient.get(f"/api/orders/{o['id']}/live").json()
    assert live["phase"] == "on_the_way" and live["provider"]["name"] == "Asha"
    code = patient.get(f"/api/orders/{o['id']}").json()["delivery"]["handover_code"]
    done = asha.post(f"/api/orders/{o['id']}/handover", {"code": code, "recipient_name": "Meera Demo"}).json()
    assert done["status"] == "delivered"
    shop_orders = patient.get("/api/shop/orders").json()
    assert shop_orders[0]["id"] == o["id"] and shop_orders[0]["status"] == "delivered"
    # My Medicines still works with shop orders in the history.
    assert patient.get("/api/patient/medicines").json()["purchase_history"][0]["source"] == "shop"


def test_pharmacist_can_pack_by_hand_and_cancel_refunds(env, as_):
    meds = env["ids"]["medications"]
    patient, ravi = as_("patient"), as_("pharmacist")
    items = [{"medication_id": meds["thermo"], "packs": 1}]
    o = _place(patient, items)[0].json()
    assert ravi.post(f"/api/pharmacy/orders/{o['id']}/prepare").json()["status"] == "preparing"
    assert ravi.post(f"/api/pharmacy/orders/{o['id']}/ready").json()["status"] == "ready_for_pickup"
    assert _status(as_("courier"))["offers"]

    o2 = _place(patient, items, key="shop-test-0002")[0].json()
    with env["Session"]() as s:
        before = s.query(PharmacyInventory).filter_by(pharmacy_id=o2["pharmacy"]["id"], medication_id=meds["thermo"]).one().units_in_stock
    c = patient.post(f"/api/orders/{o2['id']}/cancel", {"reason": "Changed my mind"}).json()
    assert c["status"] == "cancelled" and c["payment"]["status"] == "refunded"
    with env["Session"]() as s:
        after = s.query(PharmacyInventory).filter_by(pharmacy_id=o2["pharmacy"]["id"], medication_id=meds["thermo"]).one().units_in_stock
    assert after == before + 1


def test_declined_payment_and_price_change_place_no_order(env, as_):
    meds = env["ids"]["medications"]
    patient = as_("patient")
    items = [{"medication_id": meds["vitc"], "packs": 1}]
    r, _ = _place(patient, items, decline=True)
    assert r.status_code == 402
    q = patient.post("/api/shop/quote", {"items": items}).json()["offers"][0]
    r = patient.post("/api/shop/checkout", {"items": items, "pharmacy_id": q["pharmacy_id"],
                                            "delivery_option": q["delivery_options"][0]["code"],
                                            "payment_method": "upi", "payment_token": "sandbox-ok",
                                            "idempotency_key": "shop-test-0003", "expected_total": 1.0})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "price_changed"
    assert patient.get("/api/shop/orders").json() == []


def test_idempotent_checkout(as_, env):
    meds = env["ids"]["medications"]
    patient = as_("patient")
    items = [{"medication_id": meds["bandage"], "packs": 1}]
    a = _place(patient, items, key="shop-test-0004")[0].json()
    b = _place(patient, items, key="shop-test-0004")[0].json()
    assert a["id"] == b["id"]


def _expire_offers(env):
    from app.models import DispatchOffer
    with env["Session"]() as s:
        for o in s.query(DispatchOffer).filter_by(status="offered", kind="delivery"):
            o.expires_at = utcnow() - timedelta(seconds=1)
        s.commit()


def test_missed_offers_go_round_again_and_riders_coming_online_get_waiting_orders(env, as_):
    meds = env["ids"]["medications"]
    patient, asha, kiran = as_("patient"), as_("courier"), as_("courier2")
    kiran.post("/api/provider/duty", {"online": False})
    asha.post("/api/provider/duty", {"online": False})
    o = _place(patient, [{"medication_id": meds["ors"], "packs": 1}])[0].json()
    _age_order(env, o["id"], 3600)
    assert patient.get(f"/api/orders/{o['id']}").json()["status"] == "ready_for_pickup"
    # Nobody online: the order waits. Asha comes online and gets it.
    assert asha.post("/api/provider/duty", {"online": True}).json()["offers"]
    kiran.post("/api/provider/duty", {"online": True})
    # Asha misses it -> Kiran; Kiran misses it -> back to Asha (nearest) instead of being stuck.
    _expire_offers(env)
    assert _status(kiran)["offers"] and not _status(asha)["offers"]
    _expire_offers(env)
    off = _status(asha)["offers"]
    assert len(off) == 1
    assert asha.post(f"/api/provider/offers/{off[0]['id']}/accept").json()["status"] == "accepted"
