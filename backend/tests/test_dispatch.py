"""DoorDash-style dispatch: online providers, nearest first, accept/decline/timeout, live map and navigation."""
from datetime import timedelta

from app.models import DispatchOffer, Trip, utcnow


def _status(api):
    r = api.get("/api/provider/status")
    assert r.status_code == 200, r.text
    return r.json()


def _age_trip(env, trip_id, seconds):
    with env["Session"]() as s:
        t = s.get(Trip, trip_id)
        t.started_at = t.started_at - timedelta(seconds=seconds)
        s.commit()


def test_two_apps_two_logins(env, as_):
    c = env["client"]
    patient_accounts = c.get("/api/demo/accounts", params={"app": "patient"}).json()
    provider_accounts = c.get("/api/demo/accounts", params={"app": "provider"}).json()
    assert {"patient", "patient2"} <= {a["key"] for a in patient_accounts}
    assert not {"doctor", "courier", "pharmacist"} & {a["key"] for a in patient_accounts}
    assert {"doctor", "courier", "courier2", "pharmacist"} <= {a["key"] for a in provider_accounts}
    tokens = env["ids"]["tokens"]
    # A patient can't sign in to the provider app, and a provider can't sign in to the patient app.
    r = c.get("/api/me", headers={"Authorization": f"Bearer {tokens['patient']}", "X-Triyana-App": "provider"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "wrong_app"
    r = c.get("/api/me", headers={"Authorization": f"Bearer {tokens['doctor']}", "X-Triyana-App": "patient"})
    assert r.status_code == 403
    assert c.get("/api/me", headers={"Authorization": f"Bearer {tokens['doctor']}", "X-Triyana-App": "provider"}).status_code == 200
    assert as_("patient").get("/api/provider/status").status_code == 403


def test_go_online_toggle(as_):
    doc = as_("doctor_sana")
    assert _status(doc)["online"] is False
    assert doc.post("/api/provider/duty", {"online": True}).json()["online"] is True
    assert doc.post("/api/provider/duty", {"online": False}).json()["online"] is False
    assert as_("pharmacist").post("/api/provider/duty", {"online": True}).status_code == 403
    assert as_("doctor_unverified").post("/api/provider/duty", {"online": True}).status_code == 403


def test_doctor_now_goes_to_nearest_online_then_next_on_decline_and_timeout(env, as_):
    patient = as_("patient")
    carter, rohan, vikram = as_("doctor"), as_("doctor_rohan"), as_("doctor_vikram")
    v = patient.post("/api/patient/visits/now", {"reason": "High fever"})
    assert v.status_code == 201, v.text
    v = v.json()
    assert v["doctor"] is None and v["on_demand"] is True
    live = patient.get(f"/api/patient/visits/{v['id']}/live").json()
    assert live["phase"] == "searching" and live["providers_asked"] == 1

    # Only the nearest online doctor (Dr. Carter) gets it.
    offers = _status(carter)["offers"]
    mine = next(o for o in offers if o["on_demand"])
    assert mine["seconds_left"] > 0 and mine["reason"] == "High fever"
    assert not _status(rohan)["offers"]

    # Carter declines -> next nearest (Dr. Rohan).
    assert carter.post(f"/api/provider/offers/{mine['id']}/decline").json()["status"] == "declined"
    ro = _status(rohan)["offers"]
    assert len(ro) == 1
    # Rohan ignores it -> it times out -> Dr. Vikram.
    with env["Session"]() as s:
        o = s.get(DispatchOffer, ro[0]["id"])
        o.expires_at = utcnow() - timedelta(seconds=1)
        s.commit()
    assert not _status(rohan)["offers"]
    vo = _status(vikram)["offers"]
    assert len(vo) == 1
    assert rohan.post(f"/api/provider/offers/{ro[0]['id']}/accept").status_code == 409  # too late

    # Vikram accepts -> trip starts, patient sees him on the map with an ETA.
    acc = vikram.post(f"/api/provider/offers/{vo[0]['id']}/accept").json()
    assert acc["status"] == "accepted" and acc["trip"]["steps"][0]["type"] == "depart"
    live = patient.get(f"/api/patient/visits/{v['id']}/live").json()
    assert live["phase"] == "on_the_way" and live["provider"]["name"] == "Dr. Vikram Demo"
    assert live["trip"]["eta_min"] >= 1 and len(live["trip"]["route"]) >= 2
    assert any(n["title"] == "Your doctor is on the way" for n in patient.get("/api/notifications").json())

    # Busy doctors aren't offered more on-demand work.
    assert vikram.get("/api/provider/status").json()["active_trip"]["visit_id"] == v["id"]

    # Simulated GPS moves along the route; the provider gets the next instruction.
    t1 = vikram.get("/api/provider/trip").json()
    _age_trip(env, t1["id"], t1["duration_s"] / t1["speedup"] / 2)
    t2 = vikram.get("/api/provider/trip").json()
    assert t2["remaining_m"] < t1["remaining_m"] and t2["position"] != t1["position"]
    assert t2["next_step"]["text"]
    # Arrival -> patient is told; doctor starts the visit, which ends the trip.
    _age_trip(env, t1["id"], 10_000)
    assert patient.get(f"/api/patient/visits/{v['id']}/live").json()["phase"] == "arrived"
    assert any(n["title"] == "Your doctor has arrived" for n in patient.get("/api/notifications").json())
    assert vikram.post(f"/api/doctor/visits/{v['id']}/start").json()["status"] == "in_progress"
    assert vikram.get("/api/provider/trip").json() is None
    assert patient.get(f"/api/patient/visits/{v['id']}/live").json()["phase"] == "with_you"


def test_offline_doctors_get_nothing_and_no_one_online(as_):
    patient = as_("patient")
    for who in ("doctor", "doctor_rohan", "doctor_vikram"):
        as_(who).post("/api/provider/duty", {"online": False})
    r = patient.post("/api/patient/visits/now", {"reason": "Cough"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_doctor_online"
    assert patient.get("/api/patient/online-nearby").json()["doctors"] == 0


def test_last_doctor_declines_cancels_and_tells_patient(as_):
    patient = as_("patient")
    for who in ("doctor_rohan", "doctor_vikram"):
        as_(who).post("/api/provider/duty", {"online": False})
    v = patient.post("/api/patient/visits/now", {"reason": "Cough"}).json()
    carter = as_("doctor")
    oid = next(o for o in _status(carter)["offers"] if o["on_demand"])["id"]
    carter.post(f"/api/provider/offers/{oid}/decline")
    assert patient.get(f"/api/patient/visits/{v['id']}/live").json()["phase"] == "cancelled"
    assert any(n["title"] == "No doctor available right now" for n in patient.get("/api/notifications").json())


def test_booked_time_offer_accept_depart_and_decline_reassigns(env, as_):
    patient, carter = as_("patient"), as_("doctor")
    # Seeded booking shows as a request in the provider app, and accepting it there confirms the visit.
    vid = env["ids"]["visits"]["meera"]
    offer = next(o for o in _status(carter)["offers"] if o["patient"] == "Meera Demo")
    assert offer["seconds_left"] is None  # booked times wait for an answer
    assert carter.post(f"/api/provider/offers/{offer['id']}/accept").status_code == 200
    assert patient.get(f"/api/patient/visits/{vid}/live").json()["phase"] == "confirmed"
    trip = carter.post(f"/api/provider/visits/{vid}/depart").json()
    assert trip["leg"] == "to_patient"
    assert patient.get(f"/api/patient/visits/{vid}/live").json()["phase"] == "on_the_way"

    # Arjun's booking: Carter declines -> reassigned to the next nearest doctor free at that time.
    vid2 = env["ids"]["visits"]["arjun"]
    off2 = next(o for o in _status(carter)["offers"])
    assert off2["patient"] == "Arjun Sample"
    carter.post(f"/api/provider/offers/{off2['id']}/decline")
    v2 = next(x for x in as_("patient2").get("/api/patient/visits").json() if x["id"] == vid2)
    assert v2["status"] == "requested" and v2["doctor"]["name"] != "Dr. Emily Carter"


def test_road_route_can_replace_synthetic_route(as_):
    patient, carter = as_("patient"), as_("doctor")
    v = patient.post("/api/patient/visits/now", {"reason": "Fever"}).json()
    oid = next(o for o in _status(carter)["offers"] if o["on_demand"])["id"]
    trip = carter.post(f"/api/provider/offers/{oid}/accept").json()["trip"]
    body = {"route": [trip["origin"], [17.443, 78.352], trip["destination"]], "distance_m": 1800, "duration_s": 420,
            "source": "osrm", "steps": [{"text": "Head west on Demo Road", "along_m": 0, "type": "depart"},
                                         {"text": "Arrive", "along_m": 1800, "type": "arrive"}]}
    t = carter.put(f"/api/provider/trips/{trip['id']}/route", body).json()
    assert t["source"] == "osrm" and t["distance_m"] == 1800
    assert as_("doctor_rohan").put(f"/api/provider/trips/{trip['id']}/route", body).status_code == 404
    # Real GPS overrides the simulation.
    carter.post("/api/provider/location", {"lat": 17.4431, "lng": 78.3521})
    assert patient.get(f"/api/patient/visits/{v['id']}/live").json()["provider_location"] == [17.4431, 78.3521]
    # Other patients can't watch it.
    assert as_("patient2").get(f"/api/patient/visits/{v['id']}/live").status_code == 404


def _ready_delivery_order(as_, signed_rx):
    patient, pharmacist = as_("patient"), as_("pharmacist")
    cart_id = signed_rx["cart_id"]
    ph = patient.get(f"/api/carts/{cart_id}/pharmacies?sort=nearest").json()["pharmacies"]
    gl = next(p for p in ph if p["name"].startswith("GreenLeaf"))
    order = patient.post(f"/api/carts/{cart_id}/checkout", {
        "pharmacy_id": gl["pharmacy_id"], "fulfillment": "delivery", "delivery_option": "standard",
        "payment_method": "upi", "idempotency_key": "dispatch-0001"}).json()
    oid = order["id"]
    pharmacist.post(f"/api/pharmacy/orders/{oid}/start-review")
    pharmacist.post(f"/api/pharmacy/orders/{oid}/review", {"decision": "approve"})
    pharmacist.post(f"/api/pharmacy/orders/{oid}/prepare")
    assert pharmacist.post(f"/api/pharmacy/orders/{oid}/ready").json()["status"] == "ready_for_pickup"
    return oid


def test_delivery_goes_to_nearest_courier_with_live_tracking(env, as_, signed_rx):
    patient, asha, kiran = as_("patient"), as_("courier"), as_("courier2")
    oid = _ready_delivery_order(as_, signed_rx)
    assert patient.get(f"/api/orders/{oid}/live").json()["phase"] == "searching"

    # Nearest online courier (Asha, next to GreenLeaf) is asked first; she declines -> Kiran.
    a_off = _status(asha)["offers"]
    assert len(a_off) == 1 and a_off[0]["kind"] == "delivery" and a_off[0]["pickup"]["label"].startswith("GreenLeaf")
    assert not _status(kiran)["offers"]
    # Kiran can't see the order until it's offered to him.
    assert kiran.get(f"/api/orders/{oid}").status_code == 404
    asha.post(f"/api/provider/offers/{a_off[0]['id']}/decline")
    k_off = _status(kiran)["offers"]
    assert len(k_off) == 1
    acc = kiran.post(f"/api/provider/offers/{k_off[0]['id']}/accept").json()
    assert acc["trip"]["leg"] == "to_pharmacy"
    live = patient.get(f"/api/orders/{oid}/live").json()
    assert live["phase"] == "to_pharmacy" and live["provider"]["name"] == "Kiran"

    # Asha can no longer take it.
    assert asha.post(f"/api/pharmacy/orders/{oid}/dispatch").status_code == 409

    # Kiran collects -> trip to the patient; patient sees the courier on the map.
    assert kiran.post(f"/api/pharmacy/orders/{oid}/dispatch").json()["status"] == "out_for_delivery"
    live = patient.get(f"/api/orders/{oid}/live").json()
    assert live["phase"] == "on_the_way" and live["trip"]["leg"] == "to_patient" and live["trip"]["eta_min"] >= 1
    jobs = kiran.get("/api/provider/jobs").json()
    assert jobs[0]["order_no"] and jobs[0]["trip_id"] == live["trip"]["id"]

    code = patient.get(f"/api/orders/{oid}").json()["delivery"]["handover_code"]
    done = kiran.post(f"/api/orders/{oid}/handover", {"code": code, "recipient_name": "Meera Demo"}).json()
    assert done["status"] == "delivered" and done["delivery"]["courier"] == "Kiran"
    assert kiran.get("/api/provider/trip").json() is None
    assert patient.get(f"/api/orders/{oid}/live").json()["phase"] == "done"
