"""Provider earnings (Dasher style): pay per completed job, today/week totals, balance and cash out."""
from test_dispatch import _ready_delivery_order, _status


def test_doctor_earns_visit_fee_and_can_cash_out(env, as_):
    doc = as_("doctor")
    before = doc.get("/api/provider/earnings").json()
    assert before["week"]["days"][0]["label"] == "Mon" and len(before["week"]["days"]) == 7
    assert before["balance"] > 0 and before["payouts"]  # seeded history: last week already paid out

    vid = env["ids"]["visits"]["meera"]
    for a in ("accept", "start", "complete"):
        assert doc.post(f"/api/doctor/visits/{vid}/{a}").status_code == 200
    after = doc.get("/api/provider/earnings").json()
    job = after["jobs"][0]
    assert job["total"] == 600 and job["base"] == 600 and job["kind"] == "visit"
    assert after["today"]["total"] == before["today"]["total"] + 600
    assert after["balance"] == before["balance"] + 600
    assert any(n["title"] == "You earned ₹600" for n in doc.get("/api/notifications").json())
    # Completing twice can't pay twice.
    assert doc.post(f"/api/doctor/visits/{vid}/complete").status_code == 409

    paid = doc.post("/api/provider/earnings/cash-out").json()
    assert paid["balance"] == 0 and paid["payouts"][0]["amount"] == after["balance"]
    assert paid["payouts"][0]["kind"] == "instant" and all(j["paid_out"] for j in paid["jobs"])
    assert doc.post("/api/provider/earnings/cash-out").status_code == 409


def test_doctor_now_bonus(as_):
    patient, carter = as_("patient"), as_("doctor")
    v = patient.post("/api/patient/visits/now", {"reason": "Fever"}).json()
    oid = next(o for o in _status(carter)["offers"] if o["on_demand"])["id"]
    carter.post(f"/api/provider/offers/{oid}/accept")
    carter.post(f"/api/doctor/visits/{v['id']}/start")
    carter.post(f"/api/doctor/visits/{v['id']}/complete")
    job = carter.get("/api/provider/earnings").json()["jobs"][0]
    assert job["bonus"] == 100 and job["total"] == v["fee"] + 100


def test_courier_earns_offer_pay(env, as_, signed_rx):
    asha = as_("courier")
    oid = _ready_delivery_order(as_, signed_rx)
    offer = _status(asha)["offers"][0]
    asha.post(f"/api/provider/offers/{offer['id']}/accept")
    asha.post(f"/api/pharmacy/orders/{oid}/dispatch")
    code = as_("patient").get(f"/api/orders/{oid}").json()["delivery"]["handover_code"]
    asha.post(f"/api/orders/{oid}/handover", {"code": code, "recipient_name": "Meera Demo"})
    job = asha.get("/api/provider/earnings").json()["jobs"][0]
    assert job["kind"] == "delivery" and job["total"] == offer["earning"]


def test_earnings_are_private_to_providers(as_):
    assert as_("patient").get("/api/provider/earnings").status_code == 403
    assert as_("pharmacist").get("/api/provider/earnings").status_code == 403
    assert as_("courier2").get("/api/provider/earnings").json()["jobs"][0]["title"].startswith("Delivery")
