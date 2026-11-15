"""A "Doctor now" request reaches the doctor who has Triyana Heros open (Tri's report, 2026-11-15)."""
from datetime import timedelta

from app.models import DispatchOffer, User, utcnow
from conftest import face_pass


def _offers(api):
    r = api.get("/api/provider/status")
    assert r.status_code == 200, r.text
    return r.json()


def _move(env, token, lat, lng):
    with env["Session"]() as s:
        u = s.query(User).filter(User.token == token).one()
        u.lat, u.lng = lat, lng
        s.commit()


def _expire(env, offer_id):
    with env["Session"]() as s:
        s.get(DispatchOffer, offer_id).expires_at = utcnow() - timedelta(seconds=1)
        s.commit()


def test_doctor_with_app_open_is_asked_before_a_nearer_doctor_nobody_is_using(env, as_):
    tokens = env["ids"]["tokens"]
    carter, rohan, patient = as_("doctor"), as_("doctor_rohan"), as_("patient")
    # Dr. Carter is a little further from Meera than Dr. Rohan, but Carter is the one with Heros open.
    _move(env, tokens["doctor"], 17.4560, 78.3650)
    assert _offers(carter)["online"] is True
    v = patient.post("/api/patient/visits/now", {"reason": "Fever"}).json()
    mine = [o for o in _offers(carter)["offers"] if o.get("visit_id") == v["id"]]
    assert mine and mine[0]["seconds_left"] > 0
    with env["Session"]() as s:  # nobody else was asked
        assert s.query(DispatchOffer).filter(DispatchOffer.visit_id == v["id"]).count() == 1
    assert not [o for o in _offers(rohan)["offers"] if o.get("visit_id") == v["id"]]


def test_nearest_still_wins_among_doctors_with_the_app_open(env, as_):
    tokens = env["ids"]["tokens"]
    carter, rohan, patient = as_("doctor"), as_("doctor_rohan"), as_("patient")
    _move(env, tokens["doctor"], 17.4560, 78.3650)
    _offers(carter), _offers(rohan)  # both have the app open
    v = patient.post("/api/patient/visits/now", {"reason": "Fever"}).json()
    assert [o for o in _offers(rohan)["offers"] if o.get("visit_id") == v["id"]]
    assert not [o for o in _offers(carter)["offers"] if o.get("visit_id") == v["id"]]


def test_heros_says_when_requests_are_paused_because_the_doctor_is_on_a_job(env, as_):
    carter, patient = as_("doctor"), as_("patient")
    assert _offers(carter)["busy_note"] is None
    vid = env["ids"]["visits"]["meera"]  # the seeded booked visit
    offer = next(o for o in _offers(carter)["offers"] if o.get("visit_id") == vid)
    assert carter.post(f"/api/provider/offers/{offer['id']}/accept").status_code == 200
    face_pass(carter, vid)
    assert carter.post(f"/api/provider/visits/{vid}/depart").status_code == 200
    st = _offers(carter)
    assert st["online"] is True and "finish" in st["busy_note"]
    # A new "Doctor now" goes to someone else while Carter is on the way to the other patient.
    v = patient.post("/api/patient/visits/now", {"reason": "Cough", "accept_longer": True}).json()
    assert not [o for o in _offers(carter)["offers"] if o.get("visit_id") == v["id"]]


def test_doctor_who_missed_the_timer_gets_one_more_chance_before_the_patient_is_turned_away(env, as_):
    carter, patient = as_("doctor"), as_("patient")
    _offers(carter)
    v = patient.post("/api/patient/visits/now", {"reason": "Fever"}).json()
    first = next(o for o in _offers(carter)["offers"] if o.get("visit_id") == v["id"])
    _expire(env, first["id"])
    # It moves on to the other online doctors; they don't answer either.
    for _ in range(5):
        patient.get(f"/api/patient/visits/{v['id']}/live")
        with env["Session"]() as s:
            open_ = [o for o in s.query(DispatchOffer).filter(DispatchOffer.visit_id == v["id"],
                                                              DispatchOffer.status == "offered")]
            others = [o.id for o in open_ if o.user_id != first_user(env)]
        if not others:
            break
        for oid in others:
            _expire(env, oid)
    _offers(carter)  # Carter still has the app open
    again = [o for o in _offers(carter)["offers"] if o.get("visit_id") == v["id"]]
    assert again and again[0]["id"] != first["id"]
    assert carter.post(f"/api/provider/offers/{again[0]['id']}/accept").status_code == 200
    # If he misses it a second time, the patient is told honestly instead of waiting forever.


def first_user(env):
    with env["Session"]() as s:
        return s.query(User).filter(User.token == env["ids"]["tokens"]["doctor"]).one().id
