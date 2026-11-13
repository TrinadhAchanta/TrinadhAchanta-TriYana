"""Family booking, SOS, shared live tracking and the verified doctor card."""
from app.models import Notification, Patient, User

from conftest import face_pass


def _status(api):
    return api.get("/api/provider/status").json()


def _family(patient):
    r = patient.get("/api/patient/family")
    assert r.status_code == 200, r.text
    return r.json()


def test_seeded_family_and_adding_members_and_contacts(env, as_):
    meera = as_("patient")
    fam = _family(meera)
    names = {m["name"]: m for m in fam["members"]}
    assert names["Kamala Demo"]["relation"] == "Mother" and not names["Kamala Demo"]["same_home"]
    assert names["Raghav Demo"]["same_home"] is True
    assert len(fam["contacts"]) == 2

    r = meera.post("/api/patient/family/members", {"name": "Little Demo", "relation": "Daughter",
                                                    "date_of_birth": "2019-05-01", "same_home": True})
    assert r.status_code == 201, r.text
    kid = r.json()
    assert kid["age"] >= 5 and kid["same_home"]
    # Another home needs an address and a map pin.
    r = meera.post("/api/patient/family/members", {"name": "Aunt Demo", "relation": "Other", "same_home": False,
                                                    "address": "9 Far Road"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "location_required"
    assert meera.post("/api/patient/family/contacts", {"name": "X", "phone": "123"}).status_code == 422
    r = meera.post("/api/patient/family/contacts", {"name": "Sister Demo", "phone": "98480 12345"})
    assert r.status_code == 201 and r.json()["phone"] == "+919848012345"

    # Arjun can't see or book for Meera's family.
    arjun = as_("patient2")
    assert _family(arjun)["members"] == []
    r = arjun.post("/api/patient/visits/now", {"reason": "Fever", "member_id": kid["id"]})
    assert r.status_code == 404

    assert meera.delete(f"/api/patient/family/members/{kid['id']}").status_code == 200
    assert len(_family(meera)["members"]) == 2


def test_book_doctor_now_for_mother_goes_to_her_home_and_meera_tracks_it(env, as_):
    meera = as_("patient")
    mom = next(m for m in _family(meera)["members"] if m["relation"] == "Mother")
    q = meera.get(f"/api/patient/online-nearby?member={mom['id']}").json()
    assert q["home"] == [mom["lat"], mom["lng"]]
    r = meera.post("/api/patient/visits/now", {"reason": "Dizzy since morning", "member_id": mom["id"]})
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["patient"]["name"] == "Kamala Demo" and v["address"].startswith("4 Neem Street")

    live = meera.get(f"/api/patient/visits/{v['id']}/live").json()
    assert live["for"] == {"name": "Kamala Demo", "relation": "Mother"}
    assert live["home"]["lat"] == mom["lat"]
    # The visit shows in Meera's list, marked as her mother's.
    mine = next(x for x in meera.get("/api/patient/visits").json() if x["id"] == v["id"])
    assert mine["patient"]["relation"] == "Mother" and mine["patient"]["self"] is False
    # Arjun can't open it.
    assert as_("patient2").get(f"/api/patient/visits/{v['id']}/live").status_code == 404

    # Meera gets updates with her mother's name on them.
    with env["Session"]() as s:
        uid = s.query(User).filter_by(token=env["ids"]["tokens"]["patient"]).one().id
        titles = [n.title for n in s.query(Notification).filter_by(user_id=uid)]
    assert any(t.startswith("Kamala: Finding your doctor") for t in titles)

    # A booked time for Dad works too, and he lives with Meera.
    dad = next(m for m in _family(meera)["members"] if m["relation"] == "Father")
    slots = meera.get(f"/api/visit-slots?member={dad['id']}").json()
    r = meera.post("/api/patient/visits", {"doctor_id": None, "scheduled_for": slots[0], "reason": "BP check",
                                           "address": "", "member_id": dad["id"]})
    assert r.status_code == 201, r.text
    assert r.json()["patient"]["name"] == "Raghav Demo"


def test_share_live_tracking_link_for_family_without_the_app(env, as_):
    meera = as_("patient")
    v = meera.post("/api/patient/visits/now", {"reason": "Fever"}).json()
    r = meera.post(f"/api/patient/visits/{v['id']}/share", {"label": "Arjun"})
    assert r.status_code == 201, r.text
    share = r.json()
    assert share["path"].startswith("/track/")
    token = share["path"].split("/")[-1]
    pub = env["client"].get(f"/api/track/{token}")  # no sign-in
    assert pub.status_code == 200, pub.text
    body = pub.json()
    assert body["phase"] == "searching" and body["patient_first_name"] == "Meera"
    assert "reason" not in body and "identity" not in body  # no health details or arrival code

    carter = as_("doctor")
    offer = next(o for o in _status(carter)["offers"] if o.get("visit_id") == v["id"])
    carter.post(f"/api/provider/offers/{offer['id']}/accept")
    body = env["client"].get(f"/api/track/{token}").json()
    assert body["doctor"]["name"] == "Dr. Emily Carter" and body["doctor"]["verified"] is True
    assert "photo" not in body["doctor"]

    assert meera.delete(f"/api/patient/visits/{v['id']}/shares/{share['id']}").status_code == 200
    assert env["client"].get(f"/api/track/{token}").status_code == 404
    assert env["client"].get("/api/track/not-a-token").status_code == 404


def test_verified_doctor_card_before_arrival(env, as_):
    meera = as_("patient")
    v = meera.post("/api/patient/visits/now", {"reason": "Fever"}).json()
    assert meera.get(f"/api/patient/visits/{v['id']}/live").json()["doctor_card"] is None  # nobody yet
    carter = as_("doctor")
    offer = next(o for o in _status(carter)["offers"] if o.get("visit_id") == v["id"])
    carter.post(f"/api/provider/offers/{offer['id']}/accept")

    card = meera.get(f"/api/patient/visits/{v['id']}/live").json()["doctor_card"]
    assert card["name"] == "Dr. Emily Carter" and card["rating"] == 4.9 and card["rating_count"] == 412
    assert card["license_no"] == "TSMC-DEMO-55821" and card["verified"] is True
    checks = {c["key"]: c for c in card["checks"]}
    assert checks["registration"]["ok"] and checks["background"]["ok"]
    assert checks["face"]["ok"] is False and card["face_verified"] is False

    face_pass(carter, v["id"])
    card = meera.get(f"/api/patient/visits/{v['id']}/doctor-card").json()["card"]
    assert card["face_verified"] is True and {c["key"]: c for c in card["checks"]}["face"]["at"]


def test_sos_for_mother_dispatches_first_alerts_family_and_hands_off_to_ambulance(env, as_):
    meera = as_("patient")
    opts = meera.get("/api/patient/sos/options").json()
    assert opts["emergency_number"] == "108" and any(r["key"] == "chest_pain" for r in opts["red_flags"])
    mom = next(m for m in opts["members"] if m["relation"] == "Mother")

    carter = as_("doctor")
    normal = meera.post("/api/patient/visits/now", {"reason": "Cough"}).json()  # an ordinary request first
    assert any(o.get("visit_id") == normal["id"] for o in _status(carter)["offers"])
    # Carter is now busy with a timed offer, so the SOS goes to the next nearest free doctor.
    r = meera.post("/api/patient/sos", {"member_id": mom["id"], "symptoms": ["chest_pain", "bogus"]})
    assert r.status_code == 422
    r = meera.post("/api/patient/sos", {"member_id": mom["id"], "symptoms": ["chest_pain"], "note": "Sweating"})
    assert r.status_code == 201, r.text
    sos = r.json()
    assert sos["serious"] is True and sos["ambulance"]["status"] == "advised"
    assert sos["visit_id"] and sos["patient"]["name"] == "Kamala Demo"
    assert {c["channel"] for c in sos["contacts_alerted"]} == {"sms"} and len(sos["contacts_alerted"]) == 2

    # The doctor sees it as an SOS, first in their list, with a short timer.
    offers = [o for u in ("doctor", "doctor_rohan", "doctor_vikram") for o in _status(as_(u))["offers"]
              if o.get("visit_id") == sos["visit_id"]]
    assert len(offers) == 1 and offers[0]["sos"] is True and offers[0]["title"].startswith("SOS")
    assert offers[0]["seconds_left"] <= 30

    live = meera.get(f"/api/patient/visits/{sos['visit_id']}/live").json()
    assert live["sos"]["id"] == sos["id"] and live["for"]["relation"] == "Mother"

    r = meera.post(f"/api/patient/sos/{sos['id']}/ambulance/request")
    assert r.status_code == 200, r.text
    assert r.json()["ambulance"]["status"] == "requested" and r.json()["ambulance"]["ref"].startswith("AMB-")
    assert meera.post(f"/api/patient/sos/{sos['id']}/ambulance/request").status_code == 409
    assert as_("patient2").get(f"/api/patient/sos/{sos['id']}").status_code == 404


def test_sos_goes_ahead_outside_the_ten_minute_zone_and_without_doctors(env, as_):
    meera = as_("patient")
    # Move Meera far away from every doctor: SOS still alerts family and advises 108.
    with env["Session"]() as s:
        u = s.query(User).filter_by(token=env["ids"]["tokens"]["patient"]).one()
        p = s.get(Patient, u.patient_id)
        p.lat, p.lng = 18.5, 79.5
        s.commit()
    r = meera.post("/api/patient/sos", {"symptoms": ["fever"]})
    assert r.status_code == 201, r.text
    sos = r.json()
    assert sos["visit_id"] is None and sos["doctor_status"] == "none_online"
    assert sos["ambulance"]["status"] == "advised" and len(sos["contacts_alerted"]) == 2
