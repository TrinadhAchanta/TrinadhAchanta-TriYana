"""Physiotherapy at home: book a session or package, nearest physio accepts, live map, session notes."""
from datetime import timedelta

from app.models import DispatchOffer, Trip, utcnow


def _offers(api):
    r = api.get("/api/provider/status")
    assert r.status_code == 200, r.text
    return [o for o in r.json()["offers"] if o["kind"] == "physio"]


def _arrive(env, trip_id):
    with env["Session"]() as s:
        t = s.get(Trip, trip_id)
        t.started_at = t.started_at - timedelta(hours=2)
        s.commit()


def test_catalogue_lists_plans_and_nearby_verified_physios(as_):
    c = as_("patient").get("/api/physio/catalogue").json()
    assert {p["key"] for p in c["plans"]} == {"single", "pack5", "pack10"}
    pack5 = next(p for p in c["plans"] if p["key"] == "pack5")
    assert pack5["sessions"] == 5 and pack5["price"] < pack5["full_price"]
    names = [p["name"] for p in c["physios"]]
    assert "Ananya Rao" in names and "Physio Pending Check" not in names
    assert c["online_nearby"] >= 2 and c["slots"]
    assert as_("doctor").get("/api/physio/catalogue").status_code == 403


def test_now_goes_to_nearest_online_physio_then_next_on_decline(env, as_):
    patient, priya, arun = as_("patient"), as_("physio"), as_("physio_arun")
    r = patient.post("/api/patient/physio/bookings", {"condition": "back_neck", "plan": "pack5", "when": "now",
                                                       "details": "Lower back pain after lifting"})
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["status"] == "searching" and b["sessions_total"] == 5 and len(b["sessions"]) == 5
    sid = b["sessions"][0]["id"]
    live = patient.get(f"/api/patient/physio/sessions/{sid}/live").json()
    assert live["phase"] == "searching" and live["kind"] == "physio"

    # Ananya is nearest to Meera; only she gets it, with a countdown.
    mine = _offers(priya)
    assert len(mine) == 1 and mine[0]["seconds_left"] > 0 and "Back or neck pain" in mine[0]["reason"]
    assert mine[0]["sessions_total"] == 5
    assert not _offers(arun)

    # Decline moves it to Arun, who accepts and is navigated to the patient.
    assert priya.post(f"/api/provider/offers/{mine[0]['id']}/decline").status_code == 200
    theirs = _offers(arun)
    assert len(theirs) == 1
    r = arun.post(f"/api/provider/offers/{theirs[0]['id']}/accept")
    assert r.status_code == 200, r.text
    trip = r.json()["trip"]
    assert trip and trip["physio_session_id"] == sid and trip["leg"] == "to_patient"

    b = patient.get(f"/api/patient/physio/bookings/{b['id']}").json()
    assert b["status"] == "active" and b["physio"]["name"] == "Arun Kumar"
    live = patient.get(f"/api/patient/physio/sessions/{sid}/live").json()
    assert live["phase"] == "on_the_way" and live["provider"]["name"] == "Arun Kumar" and live["trip"]["eta_min"] >= 1

    _arrive(env, trip["id"])
    assert patient.get(f"/api/patient/physio/sessions/{sid}/live").json()["phase"] == "arrived"
    titles = [n["title"] for n in patient.get("/api/notifications").json()]
    assert "Your physiotherapist has arrived" in titles


def test_timeout_moves_on_and_nobody_left_cancels(env, as_):
    patient, priya, arun = as_("patient"), as_("physio"), as_("physio_arun")
    b = patient.post("/api/patient/physio/bookings", {"condition": "sports", "plan": "single", "when": "now"}).json()
    with env["Session"]() as s:
        for o in s.query(DispatchOffer).filter(DispatchOffer.kind == "physio"):
            o.expires_at = utcnow() - timedelta(seconds=1)
        s.commit()
    assert not _offers(priya)
    theirs = _offers(arun)
    assert len(theirs) == 1
    arun.post(f"/api/provider/offers/{theirs[0]['id']}/decline")
    b = patient.get(f"/api/patient/physio/bookings/{b['id']}").json()
    assert b["status"] == "cancelled"
    assert any(n["title"] == "No physiotherapist available" for n in patient.get("/api/notifications").json())


def test_now_needs_someone_online(as_):
    for who in ("physio", "physio_arun"):
        assert as_(who).post("/api/provider/duty", {"online": False}).status_code == 200
    r = as_("patient").post("/api/patient/physio/bookings", {"condition": "elderly", "plan": "single", "when": "now"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_physio_online"


def test_booked_time_waits_for_answer_and_session_notes_reach_patient(env, as_):
    patient, priya = as_("patient"), as_("physio")
    slot = patient.get("/api/physio/catalogue").json()["slots"][5]
    r = patient.post("/api/patient/physio/bookings", {"condition": "knee_joint", "plan": "single", "when": slot})
    assert r.status_code == 201, r.text
    b = r.json()
    offer = _offers(priya)[0]
    assert offer["expires_at"] is None and offer["on_demand"] is False
    priya.post(f"/api/provider/offers/{offer['id']}/accept")
    sid = b["sessions"][0]["id"]
    jobs = [j for j in priya.get("/api/provider/jobs").json() if j["id"] == sid]
    assert jobs and jobs[0]["status"] == "scheduled"

    # Notes can't be written before the session starts.
    notes = {"pain_before": 6, "pain_after": 4, "exercises": ["Quad sets", "Step-ups"], "notes": "Good range today.",
             "home_plan": "Quad sets 3x10 daily", "next_focus": "Balance"}
    assert priya.post(f"/api/physio/sessions/{sid}/complete", notes).status_code == 409

    trip = priya.post(f"/api/physio/sessions/{sid}/depart").json()
    assert trip["physio_session_id"] == sid
    assert patient.get(f"/api/patient/physio/sessions/{sid}/live").json()["phase"] == "on_the_way"
    assert priya.post(f"/api/physio/sessions/{sid}/start").json()["status"] == "in_progress"
    assert patient.get(f"/api/patient/physio/sessions/{sid}/live").json()["phase"] == "with_you"
    assert priya.post(f"/api/physio/sessions/{sid}/complete", {**notes, "pain_after": 11}).status_code == 422
    r = priya.post(f"/api/physio/sessions/{sid}/complete", notes)
    assert r.status_code == 200, r.text

    b = patient.get(f"/api/patient/physio/bookings/{b['id']}").json()
    assert b["status"] == "completed" and b["sessions_done"] == 1
    n = b["sessions"][0]["notes"]
    assert n["pain_before"] == 6 and n["exercises"] == ["Quad sets", "Step-ups"] and n["home_plan"]
    assert any(x["title"] == "Session 1 notes are ready" for x in patient.get("/api/notifications").json())
    # Ananya is paid for the session in the Partner app, the same amount the request card showed.
    earn = priya.get("/api/provider/earnings").json()
    job = next(j for j in earn["jobs"] if j["kind"] == "physio" and "1/1" in j["title"])
    assert job["total"] == offer["earning"] and earn["balance"] >= job["total"]


def test_package_keeps_same_physio_and_patient_can_move_or_cancel(env, as_):
    arjun, priya = as_("patient2"), as_("physio")
    pkg = arjun.get("/api/patient/physio/bookings").json()[0]
    assert pkg["plan"] == "pack5" and pkg["sessions_done"] == 2 and pkg["physio"]["name"] == "Ananya Rao"
    assert pkg["sessions"][0]["notes"]["pain_before"] == 7
    upcoming = [s for s in pkg["sessions"] if s["status"] == "scheduled"]
    assert len(upcoming) == 3

    slots = arjun.get("/api/physio/catalogue").json()["slots"]
    target = next(s for s in slots if s not in [u["scheduled_for"] for u in upcoming])
    r = arjun.put(f"/api/patient/physio/sessions/{upcoming[0]['id']}/time", {"when": target})
    assert r.status_code == 200, r.text
    assert any(s["scheduled_for"] == target for s in r.json()["sessions"])

    # Ananya sees her patient's history for continuity.
    mine = priya.get("/api/physio/bookings").json()
    assert any(b["ref"] == "PT-DEMO0001" and b["sessions"][1]["notes"]["notes"] for b in mine)

    r = arjun.post(f"/api/patient/physio/bookings/{pkg['id']}/cancel")
    assert r.status_code == 200
    out = r.json()
    assert out["status"] == "completed" and all(s["status"] in ("completed", "cancelled") for s in out["sessions"])


def test_privacy_and_roles(env, as_):
    meera, arjun, arun = as_("patient"), as_("patient2"), as_("physio_arun")
    pkg = arjun.get("/api/patient/physio/bookings").json()[0]
    sid = pkg["sessions"][2]["id"]
    assert meera.get(f"/api/patient/physio/bookings/{pkg['id']}").status_code == 404
    assert meera.get(f"/api/patient/physio/sessions/{sid}/live").status_code == 404
    # Another physiotherapist can't act on Ananya's session.
    assert arun.post(f"/api/physio/sessions/{sid}/depart").status_code == 404
    assert not any(b["ref"] == "PT-DEMO0001" for b in arun.get("/api/physio/bookings").json())
    # Unverified physios can't go online; physios sign in to the Partner app only.
    assert as_("physio_unverified").post("/api/provider/duty", {"online": True}).status_code == 403
    tokens = env["ids"]["tokens"]
    r = env["client"].get("/api/me", headers={"Authorization": f"Bearer {tokens['physio']}", "X-Triyana-App": "patient"})
    assert r.status_code == 403
    providers = {a["key"] for a in env["client"].get("/api/demo/accounts", params={"app": "provider"}).json()}
    assert {"physio", "physio_arun"} <= providers
