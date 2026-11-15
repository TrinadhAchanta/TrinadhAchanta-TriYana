"""Prescription -> pay -> pharmacy ready -> rider -> doorstep, as the patient sees it on the tracker."""
from datetime import datetime, timedelta

from test_dispatch import _ready_delivery_order, _status


def _eta(order):
    return datetime.fromisoformat(order["delivery"]["eta"])


def test_demo_payment_is_accepted_by_default(env, as_, signed_rx):
    patient = as_("patient")
    cart_id = signed_rx["cart_id"]
    gl = env["ids"]["pharmacies"]["greenleaf"]
    for method in ("upi", "card", "netbanking", "wallet"):
        r = patient.post(f"/api/carts/{cart_id}/checkout", {
            "pharmacy_id": gl, "fulfillment": "delivery", "delivery_option": "standard",
            "payment_method": method, "payment_token": "sandbox-ok", "idempotency_key": f"pay-ok-{method}"})
        assert r.status_code == 201, r.text
        assert r.json()["payment"]["status"] == "authorized"
        patient.post(f"/api/orders/{r.json()['id']}/cancel", {"reason": "testing each method"})


def test_home_keeps_a_way_back_to_unordered_medicines(env, as_, signed_rx):
    patient = as_("patient")
    rx = patient.get("/api/patient/medicines").json()["prescriptions"][0]
    assert rx["cart_id"] == signed_rx["cart_id"] and rx["cart_items_to_order"] == 2
    _ready_delivery_order(as_, signed_rx)
    rx = patient.get("/api/patient/medicines").json()["prescriptions"][0]
    assert rx["cart_items_to_order"] == 0


def test_tracker_names_the_rider_and_gives_their_real_eta(env, as_, signed_rx):
    patient, asha = as_("patient"), as_("courier")
    oid = _ready_delivery_order(as_, signed_rx)
    booked_eta = _eta(patient.get(f"/api/orders/{oid}").json())

    offer = _status(asha)["offers"][0]
    assert asha.post(f"/api/provider/offers/{offer['id']}/accept").status_code == 200
    o = patient.get(f"/api/orders/{oid}").json()
    assert o["status"] == "ready_for_pickup" and o["delivery"]["courier"] == "Asha"
    assert "Asha accepted your delivery" in o["timeline"][-1]["note"]
    # The rider's ETA (a few minutes away), not the hours-long courier booking estimate.
    now = datetime.utcnow()
    assert _eta(o) < booked_eta and _eta(o) - now < timedelta(minutes=30)

    asha.post(f"/api/pharmacy/orders/{oid}/dispatch")
    o = patient.get(f"/api/orders/{oid}").json()
    assert o["status"] == "out_for_delivery" and _eta(o) - now < timedelta(minutes=20)
    done = asha.post(f"/api/orders/{oid}/handover", {"code": o["delivery"]["handover_code"], "recipient_name": "Meera"})
    assert done.json()["status"] == "delivered"


def test_pharmacy_launches_patient_drone_and_patient_confirms_receipt(env, as_, signed_rx):
    from app.models import DeliveryMission
    from test_drones import _order_to_ready
    patient, pharmacist, asha = as_("patient"), as_("pharmacist"), as_("courier")
    oid, _ = _order_to_ready(env, as_, signed_rx, "drone")
    ready = pharmacist.post(f"/api/pharmacy/orders/{oid}/ready").json()
    assert ready["mission"]["mode"] == "drone"
    assert not _status(asha)["offers"]  # no rider needed for a drone

    # The pharmacy loads and launches it from the order queue.
    sent = pharmacist.post(f"/api/pharmacy/orders/{oid}/dispatch")
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "out_for_delivery" and sent.json()["mission"]["status"] == "in_flight"
    assert patient.post(f"/api/orders/{oid}/received").status_code == 409  # still in the air

    # It reaches the door: the patient is told, then confirms they collected it.
    with env["Session"]() as s:
        m = s.query(DeliveryMission).filter_by(order_id=oid).one()
        m.eta = datetime.utcnow() - timedelta(seconds=1)
        s.commit()
    o = patient.get(f"/api/orders/{oid}").json()
    assert o["mission"]["status"] == "arrived" and "lowered your medicines" in o["timeline"][-1]["note"]
    done = patient.post(f"/api/orders/{oid}/received").json()
    assert done["status"] == "delivered" and done["mission"]["status"] == "delivered"
    assert as_("patient2").post(f"/api/orders/{oid}/received").status_code == 404


def test_only_drone_orders_can_be_launched_by_the_pharmacy(env, as_, signed_rx):
    pharmacist = as_("pharmacist")
    oid = _ready_delivery_order(as_, signed_rx)
    assert pharmacist.post(f"/api/pharmacy/orders/{oid}/dispatch").status_code == 403
