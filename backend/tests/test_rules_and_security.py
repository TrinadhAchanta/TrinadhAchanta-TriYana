"""Quantity rules, pharmacy validation, payments, refunds, privacy and tamper protection."""
from conftest import rx_items
from sqlalchemy import select

from app.models import Prescription, PrescriptionItem, PharmacyInventory


def _checkout(patient, cart_id, pharmacy_id, key, **kw):
    body = {"pharmacy_id": pharmacy_id, "fulfillment": "delivery", "delivery_option": "standard",
            "payment_method": "card", "payment_token": "sandbox-ok", "idempotency_key": key}
    body.update(kw)
    return patient.post(f"/api/carts/{cart_id}/checkout", body)


def _sign_new(env, as_, *items, visit="arjun"):
    doc = as_("doctor")
    vid = env["ids"]["visits"][visit]
    for a in ("accept", "start"):
        doc.post(f"/api/doctor/visits/{vid}/{a}")
    rx = doc.post("/api/prescriptions", {"visit_id": vid, "items": rx_items(env["ids"], *items)}).json()
    doc.post(f"/api/prescriptions/{rx['id']}/sign", {"confirm_reviewed": True})
    return rx


# ------------------------------------------------------------ prescriptions
def test_unverified_doctor_cannot_prescribe(env, as_):
    r = as_("doctor_unverified").post("/api/prescriptions", {
        "visit_id": env["ids"]["visits"]["unverified_doctor"], "items": rx_items(env["ids"], ("dolo", 5))})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "doctor_not_verified"


def test_draft_is_invisible_and_has_no_cart(env, as_):
    doc, patient = as_("doctor"), as_("patient")
    vid = env["ids"]["visits"]["meera"]
    doc.post(f"/api/doctor/visits/{vid}/accept")
    assert doc.post("/api/prescriptions", {"visit_id": vid, "items": rx_items(env["ids"], ("dolo", 5))}).status_code == 409
    doc.post(f"/api/doctor/visits/{vid}/start")
    rx = doc.post("/api/prescriptions", {"visit_id": vid, "items": rx_items(env["ids"], ("dolo", 5))}).json()
    assert patient.get("/api/patient/carts").json() == []
    assert patient.get("/api/patient/prescriptions").json() == []
    assert patient.get(f"/api/prescriptions/{rx['id']}").status_code == 404
    assert doc.post(f"/api/prescriptions/{rx['id']}/sign", {"confirm_reviewed": False}).status_code == 422


def test_prescription_appears_only_in_correct_patient_account(env, as_, signed_rx):
    other = as_("patient2")
    assert other.get("/api/patient/prescriptions").json() == []
    assert other.get(f"/api/prescriptions/{signed_rx['rx']['id']}").status_code == 404
    assert other.get(f"/api/carts/{signed_rx['cart_id']}").status_code == 404
    item_id = as_("patient").get(f"/api/carts/{signed_rx['cart_id']}").json()["items"][0]["id"]
    assert other.post(f"/api/cart-items/{item_id}/remove").status_code == 404
    assert other.put(f"/api/cart-items/{item_id}/quantity", {"requested_quantity": 1}).status_code == 404


def test_unauthorized_prescription_modification(env, as_, signed_rx):
    rx_id = signed_rx["rx"]["id"]
    body = {"items": rx_items(env["ids"], ("dolo", 50))}
    assert as_("patient").patch(f"/api/prescriptions/{rx_id}", body).status_code == 403
    assert as_("pharmacist").patch(f"/api/prescriptions/{rx_id}", body).status_code == 403
    assert as_("doctor_unverified").patch(f"/api/prescriptions/{rx_id}", body).status_code == 404
    r = as_("doctor").patch(f"/api/prescriptions/{rx_id}", body)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "prescription_locked"


def test_amendment_supersedes_original(env, as_, signed_rx):
    doc, patient = as_("doctor"), as_("patient")
    rx_id = signed_rx["rx"]["id"]
    new = doc.post(f"/api/prescriptions/{rx_id}/amend",
                   {"reason": "Clarified quantity", "items": rx_items(env["ids"], ("dolo", 6))}).json()
    assert new["status"] == "draft" and new["supersedes_id"] == rx_id
    doc.post(f"/api/prescriptions/{new['id']}/sign", {"confirm_reviewed": True})
    statuses = {p["id"]: p["status"] for p in patient.get("/api/patient/prescriptions").json()}
    assert statuses == {rx_id: "superseded", new["id"]: "signed"}
    r = _checkout(patient, signed_rx["cart_id"], env["ids"]["pharmacies"]["greenleaf"], "amend-0001")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "prescription_not_dispensable"


def test_tampered_prescription_is_rejected_by_pharmacy(env, as_, signed_rx):
    patient, pharmacist = as_("patient"), as_("pharmacist")
    order = _checkout(patient, signed_rx["cart_id"], env["ids"]["pharmacies"]["greenleaf"], "tamper-001").json()
    with env["Session"]() as s:  # simulate a direct DB tamper
        item = s.scalars(select(PrescriptionItem)).first()
        item.quantity = 500
        s.commit()
    queue = pharmacist.get("/api/pharmacy/orders").json()
    assert queue[0]["prescription"]["valid"] is False
    r = pharmacist.post(f"/api/pharmacy/orders/{order['id']}/review", {"decision": "approve"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "prescription_invalid"
    r = pharmacist.post(f"/api/pharmacy/orders/{order['id']}/review",
                        {"decision": "reject", "notes": "Prescription failed signature check"})
    assert r.json()["status"] == "rejected" and r.json()["payment"]["status"] == "voided"


# ------------------------------------------------------------- quantity rules
def test_cannot_increase_quantity(env, as_, signed_rx):
    patient = as_("patient")
    item = patient.get(f"/api/carts/{signed_rx['cart_id']}").json()["items"][0]
    r = patient.put(f"/api/cart-items/{item['id']}/quantity", {"requested_quantity": 9}).json()
    assert r["status"] == "rejected" and r["rule"] == "EXCEEDS_PRESCRIPTION"
    assert r["current_purchase_quantity"] == 5


def test_partial_rejected_for_controlled_medicine(env, as_):
    _sign_new(env, as_, ("trama", 10))
    patient = as_("patient2")
    cart_id = patient.get("/api/patient/carts").json()[0]["id"]
    item = patient.get(f"/api/carts/{cart_id}").json()["items"][0]
    r = patient.put(f"/api/cart-items/{item['id']}/quantity", {"requested_quantity": 5}).json()
    assert r["status"] == "not_permitted" and r["rule"] == "CONTROLLED_MEDICINE"
    assert set(r["contact_options"]) == {"ask_pharmacist", "contact_doctor"}


def test_partial_rejected_for_pack_size(env, as_):
    _sign_new(env, as_, ("cetri", 20))
    patient = as_("patient2")
    cart_id = patient.get("/api/patient/carts").json()[0]["id"]
    item = patient.get(f"/api/carts/{cart_id}").json()["items"][0]
    r = patient.put(f"/api/cart-items/{item['id']}/quantity", {"requested_quantity": 7}).json()
    assert r["status"] == "not_permitted" and r["rule"] == "PACK_SIZE" and r["allowed_quantities"] == [10, 20]
    r = patient.put(f"/api/cart-items/{item['id']}/quantity", {"requested_quantity": 10}).json()
    assert r["status"] == "pending_pharmacist"


def test_partial_rejected_when_jurisdiction_prohibits(env, as_):
    from app.services.dispensing_rules import evaluate_quantity_request
    from app.models import Medication, MedSchedule
    med = Medication(brand_name="X", generic_name="x", strength="1", form="tablet", unit="tablets",
                     schedule=MedSchedule.rx, pack_sizes=[1], loose_units_allowed=True, reference_unit_price=1)
    d = evaluate_quantity_request(med=med, prescribed=5, requested=3, jurisdiction="DEMO-NOPARTIAL")
    assert not d.permitted and d.rule_code == "JURISDICTION_PROHIBITS"


def test_restricted_medicine_needs_prescriber_authorisation(env, as_):
    _sign_new(env, as_, ("amoxi", 10))
    patient, doc, pharmacist = as_("patient2"), as_("doctor"), as_("pharmacist")
    cart_id = patient.get("/api/patient/carts").json()[0]["id"]
    item = patient.get(f"/api/carts/{cart_id}").json()["items"][0]
    r = patient.put(f"/api/cart-items/{item['id']}/quantity", {"requested_quantity": 6}).json()
    assert r["status"] == "pending_prescriber"
    gl = env["ids"]["pharmacies"]["greenleaf"]
    r = _checkout(patient, cart_id, gl, "restricted-01")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "quantity_pending"
    clar = doc.get("/api/doctor/clarifications").json()[0]
    assert clar["reason"] == "partial_quantity_authorization"
    doc.post(f"/api/clarifications/{clar['id']}/respond", {"response": "OK for 6", "authorize": True})
    order = _checkout(patient, cart_id, gl, "restricted-02").json()
    # Amoxidemo is Schedule H1 (demo classification): the H1 register entry must be confirmed first.
    r = pharmacist.post(f"/api/pharmacy/orders/{order['id']}/review", {"decision": "approve"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "h1_register_required"
    r = pharmacist.post(f"/api/pharmacy/orders/{order['id']}/review", {"decision": "approve", "h1_register_confirmed": True})
    assert r.status_code == 200 and r.json()["items"][0]["approved_quantity"] == 6


def test_pharmacy_without_partial_policy_is_ineligible(env, as_, signed_rx):
    patient = as_("patient")
    item = patient.get(f"/api/carts/{signed_rx['cart_id']}").json()["items"][0]
    patient.put(f"/api/cart-items/{item['id']}/quantity", {"requested_quantity": 3})
    r = _checkout(patient, signed_rx["cart_id"], env["ids"]["pharmacies"]["wholepack"], "nopartial-1")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "pharmacy_not_eligible"


def test_unverified_pharmacy_hidden_and_unusable(env, as_, signed_rx):
    r = _checkout(as_("patient"), signed_rx["cart_id"], env["ids"]["pharmacies"]["unverified"], "unverif-01")
    assert r.status_code == 404


def test_pharmacy_sorting(env, as_, signed_rx):
    patient = as_("patient")
    url = f"/api/carts/{signed_rx['cart_id']}/pharmacies"
    by_price = [p for p in patient.get(url + "?sort=price").json()["pharmacies"] if p["eligible"]]
    assert [p["total"] for p in by_price] == sorted(p["total"] for p in by_price)
    by_rating = [p for p in patient.get(url + "?sort=rating").json()["pharmacies"] if p["eligible"]]
    assert [p["rating"] for p in by_rating] == sorted((p["rating"] for p in by_rating), reverse=True)
    unconfirmed = [p for p in patient.get(url).json()["pharmacies"] if p["name"].startswith("WholePack")][0]
    assert all(i["stock_status"] == "unconfirmed" for i in unconfirmed["items"])
    assert sum(p["recommended"] for p in patient.get(url).json()["pharmacies"]) == 1


# --------------------------------------------------- remove / buy later / msgs
def test_remove_and_buy_later_never_touch_prescription(env, as_, signed_rx):
    patient = as_("patient")
    items = patient.get(f"/api/carts/{signed_rx['cart_id']}").json()["items"]
    assert patient.post(f"/api/cart-items/{items[0]['id']}/remove").json()["status"] == "removed"
    assert patient.post(f"/api/cart-items/{items[1]['id']}/buy_later").json()["status"] == "buy_later"
    rx = patient.get(f"/api/prescriptions/{signed_rx['rx']['id']}").json()
    assert len(rx["items"]) == 2 and rx["integrity_verified"]
    r = _checkout(patient, signed_rx["cart_id"], env["ids"]["pharmacies"]["greenleaf"], "empty-0001")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "empty_cart"
    assert patient.post(f"/api/cart-items/{items[0]['id']}/add").json()["status"] == "in_cart"
    m = patient.post(f"/api/cart-items/{items[0]['id']}/messages", {"recipient": "doctor", "body": "Question"})
    assert m.status_code == 201
    assert any(n["title"] == "New patient message" for n in as_("doctor").get("/api/notifications").json())


# --------------------------------------------------- checkout / payment / stock
def test_inventory_changes_during_checkout(env, as_, signed_rx):
    with env["Session"]() as s:
        inv = s.scalars(select(PharmacyInventory).where(
            PharmacyInventory.pharmacy_id == env["ids"]["pharmacies"]["greenleaf"],
            PharmacyInventory.medication_id == env["ids"]["medications"]["dolo"])).first()
        inv.units_in_stock = 2
        s.commit()
    r = _checkout(as_("patient"), signed_rx["cart_id"], env["ids"]["pharmacies"]["greenleaf"], "stock-0001")
    # Matching sees the live stock -> ineligible; never charged.
    assert r.status_code in (409, 422)
    assert as_("patient").get("/api/patient/medicines").json()["active_orders"] == []


def test_stock_race_after_matching(env, as_, signed_rx, monkeypatch):
    from app.adapters import pharmacy as ph_mod
    monkeypatch.setattr(ph_mod.MockPharmacyNetwork, "reserve", lambda self, p, m, u: False)
    r = _checkout(as_("patient"), signed_rx["cart_id"], env["ids"]["pharmacies"]["greenleaf"], "race-00001")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "inventory_changed"


def test_payment_authorisation_fails(env, as_, signed_rx):
    patient = as_("patient")
    r = _checkout(patient, signed_rx["cart_id"], env["ids"]["pharmacies"]["greenleaf"], "declined-01",
                  payment_token="sandbox-decline")
    assert r.status_code == 402
    cart = patient.get(f"/api/carts/{signed_rx['cart_id']}").json()
    assert all(i["status"] == "in_cart" for i in cart["items"])
    # Stock was released.
    with env["Session"]() as s:
        inv = s.scalars(select(PharmacyInventory).where(
            PharmacyInventory.pharmacy_id == env["ids"]["pharmacies"]["greenleaf"],
            PharmacyInventory.medication_id == env["ids"]["medications"]["dolo"])).first()
        assert inv.units_in_stock == 200
    r = _checkout(patient, signed_rx["cart_id"], env["ids"]["pharmacies"]["greenleaf"], "declined-02")
    assert r.status_code == 201


def test_price_change_is_surfaced(env, as_, signed_rx):
    r = _checkout(as_("patient"), signed_rx["cart_id"], env["ids"]["pharmacies"]["greenleaf"], "price-0001",
                  expected_total=1.0)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "price_changed"


def test_pharmacist_adjusts_and_captures_lower_amount(env, as_, signed_rx):
    patient, pharmacist = as_("patient"), as_("pharmacist")
    order = _checkout(patient, signed_rx["cart_id"], env["ids"]["pharmacies"]["greenleaf"], "adjust-001").json()
    dolo = next(i for i in order["items"] if i["medicine"] == "Dolo 650 mg")
    r = pharmacist.post(f"/api/pharmacy/orders/{order['id']}/review",
                        {"decision": "adjust", "notes": "Only 4 strips' worth available", "adjustments": {dolo["id"]: 4}})
    o = r.json()
    assert o["payment"]["captured"] < o["payment"]["authorized"]
    assert o["payment"]["captured"] == o["price"]["total"]
    bad = pharmacist.post(f"/api/pharmacy/orders/{order['id']}/review", {"decision": "approve"})
    assert bad.status_code == 409


def test_cancellation_and_refund(env, as_, signed_rx):
    patient, pharmacist = as_("patient"), as_("pharmacist")
    gl = env["ids"]["pharmacies"]["greenleaf"]
    o = _checkout(patient, signed_rx["cart_id"], gl, "cancel-0001").json()
    c = patient.post(f"/api/orders/{o['id']}/cancel", {"reason": "Changed my mind"}).json()
    assert c["status"] == "cancelled" and c["payment"]["status"] == "voided"
    o2 = _checkout(patient, signed_rx["cart_id"], gl, "cancel-0002").json()  # items back in cart
    pharmacist.post(f"/api/pharmacy/orders/{o2['id']}/review", {"decision": "approve"})
    c2 = patient.post(f"/api/orders/{o2['id']}/cancel", {"reason": "Not needed"}).json()
    assert c2["payment"]["status"] == "refunded" and c2["payment"]["refunded"] == c2["payment"]["captured"]
    o3 = _checkout(patient, signed_rx["cart_id"], gl, "cancel-0003").json()
    pharmacist.post(f"/api/pharmacy/orders/{o3['id']}/review", {"decision": "approve"})
    pharmacist.post(f"/api/pharmacy/orders/{o3['id']}/prepare")
    assert patient.post(f"/api/orders/{o3['id']}/cancel", {}).status_code == 409


# ------------------------------------------------------------ duplicates
def test_duplicate_dispensing_prevented(env, as_, signed_rx):
    patient, pharmacist = as_("patient"), as_("pharmacist")
    gl = env["ids"]["pharmacies"]["greenleaf"]
    o = _checkout(patient, signed_rx["cart_id"], gl, "dup-000001").json()
    # Same idempotency key returns the same order, not a second one.
    again = _checkout(patient, signed_rx["cart_id"], gl, "dup-000001").json()
    assert again["id"] == o["id"]
    # A new key cannot reorder items already ordered.
    r = _checkout(patient, signed_rx["cart_id"], gl, "dup-000002")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "empty_cart"
    item_id = patient.get(f"/api/carts/{signed_rx['cart_id']}").json()["items"][0]["id"]
    assert patient.post(f"/api/cart-items/{item_id}/add").status_code == 409
    pharmacist.post(f"/api/pharmacy/orders/{o['id']}/review", {"decision": "approve"})
    pharmacist.post(f"/api/pharmacy/orders/{o['id']}/prepare")
    pharmacist.post(f"/api/pharmacy/orders/{o['id']}/ready")
    assert pharmacist.post(f"/api/pharmacy/orders/{o['id']}/ready").status_code == 409


def test_dispensing_limit_enforced_in_service(env, as_, signed_rx):
    from app.services.orders import max_dispensable
    with env["Session"]() as s:
        pi = s.scalars(select(PrescriptionItem)).first()
        assert max_dispensable(pi) == pi.quantity


# --------------------------------------------------------------- privacy
def test_cross_patient_and_cross_pharmacy_privacy(env, as_, signed_rx):
    o = _checkout(as_("patient"), signed_rx["cart_id"], env["ids"]["pharmacies"]["greenleaf"], "priv-00001").json()
    assert as_("patient2").get(f"/api/orders/{o['id']}").status_code == 404
    assert as_("patient2").post(f"/api/orders/{o['id']}/cancel", {}).status_code == 404
    assert as_("pharmacist2").get(f"/api/orders/{o['id']}").status_code == 404
    assert as_("pharmacist2").get("/api/pharmacy/orders").json() == []
    assert as_("pharmacist2").post(f"/api/pharmacy/orders/{o['id']}/review", {"decision": "approve"}).status_code == 404
    assert as_("pharmacist2").get(f"/api/prescriptions/{signed_rx['rx']['id']}").status_code == 404
    assert as_("pharmacist").get(f"/api/prescriptions/{signed_rx['rx']['id']}").status_code == 200
    assert as_("patient").post(f"/api/pharmacy/orders/{o['id']}/review", {"decision": "approve"}).status_code == 403
    assert env["client"].get(f"/api/orders/{o['id']}").status_code == 401


def test_phi_encrypted_at_rest(env, as_, signed_rx):
    from sqlalchemy import text
    with env["Session"]() as s:
        raw = s.execute(text("select instructions from prescription_items")).scalars().first()
        addr = s.execute(text("select address from patients")).scalars().first()
    assert "licensed doctor" not in raw and "Lotus" not in addr


# ------------------------------------------------------------ clarifications
def test_pharmacist_clarification_workflow(env, as_, signed_rx):
    patient, pharmacist, doc = as_("patient"), as_("pharmacist"), as_("doctor")
    o = _checkout(patient, signed_rx["cart_id"], env["ids"]["pharmacies"]["greenleaf"], "clar-00001").json()
    r = pharmacist.post(f"/api/pharmacy/orders/{o['id']}/clarify",
                        {"reason": "incomplete_prescription", "message": "Please confirm duration."})
    assert r.status_code == 201
    assert patient.get(f"/api/orders/{o['id']}").json()["status"] == "awaiting_clarification"
    clar = doc.get("/api/doctor/clarifications").json()[0]
    assert as_("doctor_unverified").post(f"/api/clarifications/{clar['id']}/respond",
                                         {"response": "x"}).status_code == 404
    doc.post(f"/api/clarifications/{clar['id']}/respond", {"response": "Duration confirmed as written."})
    assert patient.get(f"/api/orders/{o['id']}").json()["status"] == "pharmacist_reviewing"


# ---------------------------------------------------------------- yana
def test_yana_assistant(env, as_, signed_rx):
    patient = as_("patient")
    ask = lambda m: patient.post("/api/yana", {"message": m}).json()
    r = ask("Yana, show the medicines my doctor prescribed.")
    assert r["intent"] == "show_prescriptions" and "Dolo 650 mg" in r["reply"]
    r = ask("Yana, find a pharmacy near my home.")
    assert r["intent"] == "find_pharmacy" and "GreenLeaf" in r["reply"]
    r = ask("Yana, I only want to purchase three Dolo tablets instead of five.")
    assert r["intent"] == "change_quantity" and r["result"]["requested_quantity"] == 3
    r = ask("Yana, remove Pantodemo from my shopping cart.")
    assert r["intent"] == "remove_item"
    r = ask("Yana, show the cheapest eligible pharmacy.")
    assert r["intent"] == "cheapest_pharmacy"
    for bad in ("Should I stop taking Dolo?", "Change my dosage to twice a day",
                "Substitute Pantodemo with something cheaper", "Increase the quantity to 10"):
        assert ask(bad)["intent"] == "refused", bad
    rx = patient.get(f"/api/prescriptions/{signed_rx['rx']['id']}").json()
    assert [i["quantity"] for i in rx["items"]] == [5, 10] and rx["integrity_verified"]
