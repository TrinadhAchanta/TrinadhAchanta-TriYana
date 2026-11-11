"""Drone delivery: hospital accounts, Drone Rules 2021 eligibility, road fallback, tracking."""
import pytest

from app.adapters.drones import drone_provider


@pytest.fixture(autouse=True)
def calm_weather():
    drone_provider.wind_kmh_now = 12.0
    yield
    drone_provider.wind_kmh_now = 12.0


def ship(api, ids, origin_kind, origin_key, dest_key, **kw):
    origin_id = ids["pharmacies" if origin_kind == "pharmacy" else "hospitals"][origin_key]
    body = {"origin_kind": origin_kind, "origin_id": origin_id, "dest_hospital_id": ids["hospitals"][dest_key],
            "category": "medicines", "contents": "Demo consignment", "weight_kg": 1.0, **kw}
    return api.post("/api/shipments", body)


def checks(mission):
    return {c["code"]: c for c in mission["checks"]}


def test_coverage_map_explains_every_hospital(env, as_):
    net = as_("hospital").get("/api/hospital/network").json()
    assert net["hospital"]["name"].startswith("Lotus")
    cov = {h["name"]: h["coverage"] for h in net["hospitals"]}
    assert cov["Demo City District Hospital"]["drone"] is True
    assert cov["Demo City District Hospital"]["zone"] == "green"
    kids = cov["Ring Road Children's Hospital (Demo)"]
    assert kids["drone"] is True and kids["zone"] == "yellow" and kids["needs_permission"] is True
    assert "red zone" in cov["Lakeside Cancer Centre (Demo)"]["reason"]
    assert "beyond drone range" in cov["Hill Park Rural PHC (Demo)"]["reason"]
    assert "no registered drone pad" in cov["Riverside Nursing Home (Demo)"]["reason"]
    # Every hospital still gets a road time, so nobody is left unserved.
    assert all(h["coverage"]["road_minutes"] > 0 for h in net["hospitals"])
    pcov = {p["name"]: p["coverage"] for p in net["pharmacies"]}
    assert pcov["GreenLeaf Pharmacy (Demo)"]["drone"] is True
    assert pcov["WholePack Pharmacy (Demo)"]["drone"] is False
    assert net["summary"]["drone"] + net["summary"]["road_only"] == net["summary"]["total"]


def test_only_hospital_accounts_see_network(env, as_):
    assert as_("patient").get("/api/hospital/network").status_code == 403
    assert as_("pharmacist").post("/api/shipments", {}).status_code in (403, 422)


def test_pharmacy_to_hospital_cold_chain_drone_flow(env, as_):
    ids, nisha, ravi = env["ids"], as_("hospital"), as_("pharmacist")
    q = nisha.post("/api/shipments/quote", {"origin_kind": "pharmacy", "origin_id": ids["pharmacies"]["greenleaf"],
                                            "dest_hospital_id": ids["hospitals"]["lotus"], "category": "vaccines",
                                            "weight_kg": 1.2}).json()
    assert q["eligible"] is True and q["cold_chain"] is True  # vaccines are always cold chain
    assert checks(q)["cold_chain"]["ok"]

    r = ship(nisha, ids, "pharmacy", "greenleaf", "lotus", category="vaccines", weight_kg=1.2,
             contents="Hep-B vaccine vials (demo)", urgency="urgent")
    assert r.status_code == 201, r.text
    s = r.json()
    m = s["mission"]
    assert s["route"] == "pharmacy_to_hospital" and m["mode"] == "drone" and m["status"] == "scheduled"
    assert m["vehicle"]["uin"].startswith("UA-DEMO") and "RPC" in m["compliance"]["remote_pilot"]
    assert m["compliance"]["max_altitude_m"] <= 120 and m["zones"]

    # The origin pharmacy sees it too and can launch it (demo operator controls).
    assert any(x["ref"] == s["ref"] for x in ravi.get("/api/shipments").json())
    mid = m["id"]
    assert ravi.post(f"/api/missions/{mid}/launch").json()["status"] == "in_flight"
    tracked = nisha.get(f"/api/missions/{mid}").json()
    assert 0 < tracked["progress"] < 1 and tracked["temperature_log"]
    assert nisha.post(f"/api/missions/{mid}/arrive").json()["status"] == "arrived"

    # Only the receiving hospital confirms, and only after the 2–8 °C check.
    assert ravi.post(f"/api/missions/{mid}/confirm", {"received_by": "Ravi"}).status_code == 403
    assert nisha.post(f"/api/missions/{mid}/confirm", {"received_by": "Nisha"}).status_code == 422
    done = nisha.post(f"/api/missions/{mid}/confirm", {"received_by": "Nisha", "temperature_ok": True}).json()
    assert done["status"] == "delivered" and done["received_by"] == "Nisha"


def test_hospital_to_hospital_yellow_zone_gets_permission(env, as_):
    m = ship(as_("hospital"), env["ids"], "hospital", "lotus", "children").json()["mission"]
    assert m["mode"] == "drone"
    assert m["compliance"]["permission_ref"].startswith("DS-PERM-")
    assert m["compliance"]["zone"] == "yellow"


@pytest.mark.parametrize("dest,kw,expect", [
    ("lakeside", {}, "red zone"),
    ("hillpark", {}, "beyond drone range"),
    ("riverside", {}, "no registered drone pad"),
    ("district", {"weight_kg": 9.0}, "over the"),
    ("district", {"controlled": True}, "Controlled medicines"),
])
def test_ineligible_routes_fall_back_to_road(env, as_, dest, kw, expect):
    r = ship(as_("hospital"), env["ids"], "hospital", "lotus", dest, **kw)
    assert r.status_code == 201, r.text
    m = r.json()["mission"]
    assert m["mode"] == "road" and expect in m["fallback_reason"]
    assert m["vehicle"]["courier"] and m["eta"]


def test_weather_hold_falls_back_to_road(env, as_):
    drone_provider.wind_kmh_now = 45
    m = ship(as_("hospital"), env["ids"], "hospital", "lotus", "district").json()["mission"]
    assert m["mode"] == "road" and "Wind 45 km/h" in m["fallback_reason"]


def test_divert_before_takeoff(env, as_):
    nisha = as_("hospital")
    m = ship(nisha, env["ids"], "hospital", "lotus", "district").json()["mission"]
    assert m["mode"] == "drone"
    d = nisha.post(f"/api/missions/{m['id']}/divert", {"reason": "Rain at the launch pad"}).json()
    assert d["mode"] == "road" and d["fallback_reason"] == "Rain at the launch pad"
    nisha.post(f"/api/missions/{m['id']}/launch")
    assert nisha.post(f"/api/missions/{m['id']}/divert").status_code == 409


def test_hospitals_only_send_from_or_receive_at_their_own_site(env, as_):
    ids = env["ids"]
    dev = as_("hospital2")  # District Hospital
    assert ship(dev, ids, "hospital", "lotus", "children").status_code == 403
    s = ship(as_("hospital"), ids, "hospital", "lotus", "children").json()
    assert dev.get(f"/api/missions/{s['mission']['id']}").status_code == 404
    assert as_("patient").get(f"/api/missions/{s['mission']['id']}").status_code == 404
    # Inbound to District from Lotus: both sides see it.
    s2 = ship(as_("hospital"), ids, "hospital", "lotus", "district").json()
    assert any(x["id"] == s2["id"] for x in dev.get("/api/shipments").json())


def _order_to_ready(env, as_, signed_rx, option):
    patient, pharmacist = as_("patient"), as_("pharmacist")
    cart_id = signed_rx["cart_id"]
    gl = next(p for p in patient.get(f"/api/carts/{cart_id}/pharmacies").json()["pharmacies"]
              if p["name"].startswith("GreenLeaf"))
    assert "drone" in [o["code"] for o in gl["delivery_options"]], gl["drone_note"]
    order = patient.post(f"/api/carts/{cart_id}/checkout", {
        "pharmacy_id": gl["pharmacy_id"], "fulfillment": "delivery", "delivery_option": option,
        "payment_method": "upi", "idempotency_key": f"drone-{option}-1"}).json()
    oid = order["id"]
    pharmacist.post(f"/api/pharmacy/orders/{oid}/review", {"decision": "approve"})
    pharmacist.post(f"/api/pharmacy/orders/{oid}/prepare")
    return oid, order


def test_patient_home_drone_delivery(env, as_, signed_rx):
    patient, pharmacist, courier = as_("patient"), as_("pharmacist"), as_("courier")
    oid, _ = _order_to_ready(env, as_, signed_rx, "drone")
    ready = pharmacist.post(f"/api/pharmacy/orders/{oid}/ready").json()
    assert ready["delivery"]["courier"].startswith("Drone UA-DEMO")
    assert ready["mission"]["mode"] == "drone" and ready["mission"]["destination"]["kind"] == "patient_home"
    courier.post(f"/api/pharmacy/orders/{oid}/dispatch")
    tracked = patient.get(f"/api/orders/{oid}").json()
    assert tracked["mission"]["status"] == "in_flight"
    code = tracked["delivery"]["handover_code"]
    done = courier.post(f"/api/orders/{oid}/handover", {"code": code, "recipient_name": "Meera"}).json()
    assert done["status"] == "delivered" and done["mission"]["status"] == "delivered"
    # Patients can view, not drive, the mission.
    assert patient.get(f"/api/missions/{done['mission']['id']}").status_code == 200


def test_patient_drone_order_falls_back_and_refunds_fee_difference(env, as_, signed_rx):
    patient, pharmacist = as_("patient"), as_("pharmacist")
    oid, order = _order_to_ready(env, as_, signed_rx, "drone")
    drone_provider.wind_kmh_now = 50  # weather turns at packing time
    ready = pharmacist.post(f"/api/pharmacy/orders/{oid}/ready").json()
    assert ready["delivery_option"] == "priority" and ready["mission"] is None
    assert ready["delivery"]["tracking_ref"].startswith("TRK-")
    assert ready["price"]["delivery_fee"] < order["price"]["delivery_fee"]
    assert ready["payment"]["refunded"] == pytest.approx(order["price"]["delivery_fee"] - ready["price"]["delivery_fee"])
    assert "Drone delivery isn't possible" in ready["timeline"][-1]["note"]
    assert patient.get(f"/api/orders/{oid}").json()["delivery_option"] == "priority"


def test_patient_in_yellow_zone_is_not_offered_drone(env, as_):
    from app.services import drones as drone_svc
    Session = env["Session"]
    with Session() as db:
        from app.models import Patient, Pharmacy
        arjun = db.get(Patient, env["ids"]["patients"]["arjun"])
        gl = db.get(Pharmacy, env["ids"]["pharmacies"]["greenleaf"])
        a = drone_svc.assess(db, drone_svc.pharmacy_place(gl),
                             drone_svc.Place("home", arjun.lat, arjun.lng, "patient_home"),
                             drone_svc.Payload(0.4), "DEMO-IN")
    assert a.eligible is False and "yellow zone" in a.reason
