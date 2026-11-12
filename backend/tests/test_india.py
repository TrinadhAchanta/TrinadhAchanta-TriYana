"""India launch rules: drug schedules, NMC registration details."""
from conftest import rx_items, start_visit


def _sign(env, as_, *items):
    doc = as_("doctor")
    vid = env["ids"]["visits"]["arjun"]
    doc.post(f"/api/doctor/visits/{vid}/accept")
    start_visit(env, doc, vid)
    rx = doc.post("/api/prescriptions", {"visit_id": vid, "items": rx_items(env["ids"], *items)}).json()
    assert doc.post(f"/api/prescriptions/{rx['id']}/sign", {"confirm_reviewed": True}).status_code == 200
    return rx


def test_schedule_x_is_never_sold_online(env, as_):
    _sign(env, as_, ("rita", 10), ("dolo", 5))
    patient = as_("patient2")
    cart_id = patient.get("/api/patient/carts").json()[0]["id"]
    items = {i["medicine"]: i for i in patient.get(f"/api/carts/{cart_id}").json()["items"]}
    x = items["Ritademo"]
    assert x["status"] == "removed" and x["online_sale_blocked"] and x["india_schedule"]["code"] == "X"
    assert "in person" in x["quantity_note"]
    assert items["Dolo"]["india_schedule"]["code"] == "H" and not items["Dolo"]["online_sale_blocked"]
    # It can't be put back in the cart or have its quantity changed.
    r = patient.post(f"/api/cart-items/{x['id']}/add")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "schedule_x_online_sale"
    assert patient.put(f"/api/cart-items/{x['id']}/quantity", {"requested_quantity": 10}).status_code == 422
    # The prescription itself still lists it.
    rx = patient.get("/api/patient/prescriptions").json()[0]
    assert any(i["medicine"] == "Ritademo" for i in rx["items"])
    # The rest of the cart can still be ordered.
    gl = env["ids"]["pharmacies"]["greenleaf"]
    r = patient.post(f"/api/carts/{cart_id}/checkout", {"pharmacy_id": gl, "fulfillment": "delivery",
                     "delivery_option": "standard", "payment_method": "upi", "idempotency_key": "india-x-0001"})
    assert r.status_code == 201, r.text
    assert [i["medicine"] for i in r.json()["items"]] == ["Dolo 650 mg"]


def test_h1_needs_register_confirmation(env, as_):
    _sign(env, as_, ("trama", 10))
    patient, pharmacist = as_("patient2"), as_("pharmacist")
    cart_id = patient.get("/api/patient/carts").json()[0]["id"]
    gl = env["ids"]["pharmacies"]["greenleaf"]
    o = patient.post(f"/api/carts/{cart_id}/checkout", {"pharmacy_id": gl, "fulfillment": "delivery",
                     "delivery_option": "standard", "payment_method": "card", "idempotency_key": "india-h1-001"}).json()
    assert o["items"][0]["india_schedule"]["register_required"]
    r = pharmacist.post(f"/api/pharmacy/orders/{o['id']}/review", {"decision": "approve"})
    assert r.status_code == 422 and r.json()["detail"]["medicines"] == ["Tramademo"]
    # Rejecting doesn't need the register.
    r = pharmacist.post(f"/api/pharmacy/orders/{o['id']}/review", {"decision": "reject", "notes": "Need to see patient"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"


def test_doctor_registration_details_shown(env, as_, signed_rx):
    rx = as_("patient").get("/api/patient/prescriptions").json()[0]
    d = rx["doctor"]
    assert d["license_no"].startswith("TSMC-") and "Medical Council" in d["medical_council"]
    assert d["qualification"].startswith("MBBS") and d["registration_year"]
    doc = as_("patient").get("/api/doctors").json()["doctors"][0]
    assert doc["medical_council"] and doc["qualification"]


def test_dpdp_consent_required_and_withdrawable(env, as_, signed_rx):
    patient = as_("patient")
    c = patient.get("/api/consents").json()
    assert c["consents"] == {"care": True, "reminders": False}
    assert patient.get("/api/privacy/notice").json()["grievance_officer"]
    # Withdraw care consent: new bookings and orders are blocked; records stay.
    assert patient.post("/api/consents", {"purpose": "care", "granted": False}).json()["consents"]["care"] is False
    slot = patient.get("/api/visit-slots").json()[0]
    r = patient.post("/api/patient/visits", {"doctor_id": None, "scheduled_for": slot, "reason": "Fever"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "consent_required"
    gl = env["ids"]["pharmacies"]["greenleaf"]
    r = patient.post(f"/api/carts/{signed_rx['cart_id']}/checkout", {"pharmacy_id": gl, "fulfillment": "delivery",
                     "delivery_option": "standard", "payment_method": "upi", "idempotency_key": "dpdp-0001"})
    assert r.status_code == 403
    assert patient.get("/api/patient/prescriptions").json()  # existing records still visible
    # Give it again: works, and history keeps every change.
    patient.post("/api/consents", {"purpose": "care", "granted": True, "language": "hi"})
    assert patient.post("/api/patient/visits", {"doctor_id": None, "scheduled_for": slot, "reason": "Fever"}).status_code == 201
    hist = patient.get("/api/consents").json()["history"]
    assert [h["granted"] for h in hist[:2]] == [True, False] and hist[0]["language"] == "hi"


def test_dpdp_access_and_erasure_request(as_):
    patient = as_("patient")
    data = patient.get("/api/patient/my-data").json()
    assert data["profile"]["name"] == "Meera Demo" and "visits" in data and "consents" in data
    r = patient.post("/api/patient/data-requests", {"kind": "erasure", "details": "Delete my reminders data"})
    assert r.status_code == 201 and r.json()["reference"].startswith("DPR-")
    assert as_("doctor").get("/api/patient/my-data").status_code == 403
