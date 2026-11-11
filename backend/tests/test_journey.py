"""End-to-end: doctor visit -> signed prescription -> cart -> pharmacy -> payment -> delivery."""
from conftest import rx_items


def test_complete_user_journey(env, as_, signed_rx):
    patient, pharmacist, courier, doctor = as_("patient"), as_("pharmacist"), as_("courier"), as_("doctor")
    rx, cart_id = signed_rx["rx"], signed_rx["cart_id"]

    # Doctor side: signed, verified, stored.
    assert rx["status"] == "signed" and rx["integrity_verified"] is True
    assert rx["doctor"]["license_verified"] is True

    # 1. Patient receives and opens the notification.
    notes = patient.get("/api/notifications").json()
    assert notes[0]["title"] == "Your prescription is ready"
    assert "choose what you would like to order" in notes[0]["body"]
    assert notes[0]["link"] == f"cart:{cart_id}"

    # 2. Views the official prescription.
    official = patient.get(f"/api/prescriptions/{rx['id']}").json()
    assert [i["quantity"] for i in official["items"]] == [5, 10]

    # 3-4. Opens the suggested cart and sees five prescribed tablets. Nothing ordered/charged.
    cart = patient.get(f"/api/carts/{cart_id}").json()
    dolo = next(i for i in cart["items"] if i["medicine"] == "Dolo")
    panto = next(i for i in cart["items"] if i["medicine"] == "Pantodemo")
    assert dolo["prescribed"]["quantity"] == 5 and dolo["requested_quantity"] == 5
    assert cart["estimate"]["total"] > 0 and "Nothing is ordered" in cart["disclaimer"]
    assert patient.get("/api/patient/medicines").json()["active_orders"] == []

    # 5-7. Requests only three; system checks rules and routes to pharmacist.
    r = patient.put(f"/api/cart-items/{dolo['id']}/quantity", {"requested_quantity": 3}).json()
    assert r["status"] == "pending_pharmacist"
    assert r["prescribed_quantity"] == 5 and r["current_purchase_quantity"] == 3
    assert "full course" in r["course_warning"]
    assert r["official_prescription_unchanged"] is True

    # 8. Removes another medicine.
    r = patient.post(f"/api/cart-items/{panto['id']}/remove").json()
    assert r["status"] == "removed" and "doctor or pharmacist" in r["message"]

    # Official prescription is unchanged and still verifies.
    official2 = patient.get(f"/api/prescriptions/{rx['id']}").json()
    assert [i["quantity"] for i in official2["items"]] == [5, 10]
    assert official2["integrity_verified"] is True

    # 9. Selects an eligible nearby pharmacy.
    ph = patient.get(f"/api/carts/{cart_id}/pharmacies?sort=nearest").json()["pharmacies"]
    names = [p["name"] for p in ph]
    assert "Unverified Meds (Demo)" not in names
    greenleaf = next(p for p in ph if p["name"].startswith("GreenLeaf"))
    assert greenleaf["eligible"] and greenleaf["all_stock_confirmed"]
    wholepack = next(p for p in ph if p["name"].startswith("WholePack"))
    assert not wholepack["eligible"]  # no partial dispensing + unverified stock

    # 10-12. Home delivery, reviews price, authorises payment.
    r = patient.post(f"/api/carts/{cart_id}/checkout", {
        "pharmacy_id": greenleaf["pharmacy_id"], "fulfillment": "delivery", "delivery_option": "standard",
        "payment_method": "upi", "idempotency_key": "journey-0001",
    })
    assert r.status_code == 201, r.text
    order = r.json()
    assert order["status"] == "prescription_received"
    assert order["payment"]["status"] == "authorized" and order["payment"]["captured"] == 0
    assert [(i["prescribed_quantity"], i["requested_quantity"]) for i in order["items"]] == [(5, 3)]
    p = order["price"]
    assert round(p["subtotal"] + p["tax"] + p["delivery_fee"] - p["discount"], 2) == p["total"]

    # Pharmacy: receives, validates, reviews quantity, approves.
    queue = pharmacist.get("/api/pharmacy/orders").json()
    assert queue[0]["prescription"]["valid"] is True
    oid = order["id"]
    assert pharmacist.post(f"/api/pharmacy/orders/{oid}/start-review").json()["status"] == "pharmacist_reviewing"
    r = pharmacist.post(f"/api/pharmacy/orders/{oid}/review", {"decision": "approve", "notes": "Partial fill OK"})
    assert r.status_code == 200, r.text
    assert r.json()["payment"]["status"] == "captured"
    assert pharmacist.post(f"/api/pharmacy/orders/{oid}/prepare").json()["status"] == "preparing"
    ready = pharmacist.post(f"/api/pharmacy/orders/{oid}/ready").json()
    assert ready["status"] == "ready_for_pickup" and ready["delivery"]["tracking_ref"].startswith("TRK-")
    assert "handover_code" not in ready["delivery"]  # only the patient sees it

    # Courier collects; patient tracks.
    assert courier.post(f"/api/pharmacy/orders/{oid}/dispatch").json()["status"] == "out_for_delivery"
    tracked = patient.get(f"/api/orders/{oid}").json()
    code = tracked["delivery"]["handover_code"]
    labels = [e["label"] for e in tracked["timeline"]]
    assert labels == ["Prescription Received", "Pharmacist Reviewing", "Order Accepted", "Preparing Medicines",
                      "Ready for Pickup", "Out for Delivery"]
    yana = patient.post("/api/yana", {"message": "Yana, when will my medicine arrive?"}).json()
    assert yana["intent"] == "track_order" and "Out for Delivery" in yana["reply"]

    # Wrong code rejected; right code completes proof of delivery.
    assert courier.post(f"/api/orders/{oid}/handover", {"code": "xxxx", "recipient_name": "Meera"}).status_code == 422
    done = courier.post(f"/api/orders/{oid}/handover", {"code": code, "recipient_name": "Meera Demo"}).json()
    assert done["status"] == "delivered" and done["delivery"]["proof_of_delivery"]["code_matched"]
    assert any(n["title"].endswith("Delivery confirmed") or n["title"] == "Delivery confirmed"
               for n in pharmacist.get("/api/notifications").json())

    # Dashboard distinguishes prescribed / ordered / dispensed.
    dash = patient.get("/api/patient/medicines").json()
    items = {i["medicine"]: i for i in dash["prescriptions"][0]["items"]}
    assert items["Dolo 650 mg"]["prescribed_quantity"] == 5
    assert items["Dolo 650 mg"]["dispensed_quantity"] == 3
    assert items["Pantodemo 40 mg"]["ordered_quantity"] == 0
    assert "not the same as purchased or taken" in dash["note"]
    assert dash["purchase_history"][0]["status"] == "delivered"

    # Audit trail is intact.
    audit = doctor.get(f"/api/audit/prescriptions/{rx['id']}").json()
    assert audit["chain_valid"] is True
    assert [e["action"] for e in audit["entries"]][:2] == ["prescription.draft_created", "prescription.signed"]


def test_pickup_flow_requires_id(env, as_, signed_rx):
    patient, pharmacist = as_("patient"), as_("pharmacist")
    cart_id = signed_rx["cart_id"]
    gl = env["ids"]["pharmacies"]["greenleaf"]
    order = patient.post(f"/api/carts/{cart_id}/checkout", {
        "pharmacy_id": gl, "fulfillment": "pickup", "payment_method": "apple_pay", "idempotency_key": "pickup-001",
    }).json()
    oid = order["id"]
    pharmacist.post(f"/api/pharmacy/orders/{oid}/review", {"decision": "approve"})
    pharmacist.post(f"/api/pharmacy/orders/{oid}/prepare")
    pharmacist.post(f"/api/pharmacy/orders/{oid}/ready")
    assert pharmacist.post(f"/api/orders/{oid}/handover", {"recipient_name": "Meera"}).status_code == 422
    r = pharmacist.post(f"/api/orders/{oid}/handover", {"recipient_name": "Meera", "id_verified": True})
    assert r.json()["status"] == "picked_up"
