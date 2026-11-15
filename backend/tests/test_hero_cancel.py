"""Heros cancel at the door with a reason (Tri, 2026-11-15): visits, sample collections and physio sessions."""
from datetime import timedelta

import pytest

from app.models import Trip, utcnow
from tests.conftest import face_pass

ADMIN = {"X-Admin-Key": "demo-admin"}


@pytest.fixture(autouse=True)
def _demo(monkeypatch):
    monkeypatch.delenv("TRIYANA_ADMIN_KEY", raising=False)
    monkeypatch.setenv("TRIYANA_DEMO", "1")
    monkeypatch.delenv("TRIYANA_FACE_PROVIDER", raising=False)
    monkeypatch.delenv("TRIYANA_NO_SHOW_WAIT_MIN", raising=False)


def _arrive(env, trip_id, waited_min=0):
    with env["Session"]() as s:
        t = s.get(Trip, trip_id)
        t.started_at = t.started_at - timedelta(hours=3)
        if waited_min:
            t.arrived_at = utcnow() - timedelta(minutes=waited_min)
        s.commit()


def _code(r):
    return r.json()["detail"]["code"]


def _doctor_at_door(env, as_):
    doc = as_("doctor")
    vid = env["ids"]["visits"]["meera"]
    assert doc.post(f"/api/doctor/visits/{vid}/accept").status_code == 200
    face_pass(doc, vid)
    trip = doc.post(f"/api/provider/visits/{vid}/depart").json()
    return doc, vid, trip


def test_doctor_cancels_no_answer_after_calling_and_waiting(env, as_):
    doc, vid, trip = _doctor_at_door(env, as_)
    patient = as_("patient")
    url = f"/api/provider/jobs/visit/{vid}"
    # Not before arriving.
    assert _code(doc.post(f"{url}/cancel", {"reason": "wrong_address"})) == "not_arrived"
    _arrive(env, trip["id"])
    info = doc.get(f"{url}/cancel-info").json()
    assert info["arrived"] and info["calls"] == 0 and info["wait_s"] == 60
    assert [r["code"] for r in info["reasons"]][:2] == ["not_answering", "not_at_address"]
    # "Not answering" needs a call first, then the short wait at the door.
    assert _code(doc.post(f"{url}/cancel", {"reason": "not_answering"})) == "call_first"
    c = doc.post(f"{url}/call").json()
    assert c["calls"] == 1
    assert any(n["title"] == "Your Triyana Hero is calling you" for n in patient.get("/api/notifications").json())
    assert _code(doc.post(f"{url}/cancel", {"reason": "not_answering"})) == "wait_more"
    _arrive(env, trip["id"], waited_min=2)
    r = doc.post(f"{url}/cancel", {"reason": "not_answering"})
    assert r.status_code == 200, r.text
    assert r.json()["hero_paid"] == 100

    # Patient: visit cancelled, with the reason and no charge.
    live = patient.get(f"/api/patient/visits/{vid}/live").json()
    assert live["phase"] == "cancelled"
    why = live["cancelled_by_hero"]
    assert why["label"] == "Couldn't reach you" and "not been charged" in why["message"]
    v = next(x for x in patient.get("/api/patient/visits").json() if x["id"] == vid)
    assert v["status"] == "cancelled" and v["cancelled_by_hero"]["reason"] == "not_answering"
    assert any(n["title"] == "Your home visit was cancelled" for n in patient.get("/api/notifications").json())
    # Trip ended; the doctor got wasted-trip pay; a second cancel is refused.
    assert doc.get("/api/provider/trip").json() is None
    earn = doc.get("/api/provider/earnings").json()
    assert any(j["kind"] == "no_show" and j["total"] == 100 for j in earn["jobs"])
    assert doc.post(f"{url}/cancel", {"reason": "other", "note": "again"}).status_code == 409

    # Ops see it in /admin.
    rows = env["client"].get("/api/admin/hero-cancellations", headers=ADMIN).json()
    assert rows[0]["kind"] == "visit" and rows[0]["reason_label"] == "Patient not answering phone or door"
    assert rows[0]["calls"] == 1 and rows[0]["waited_min"] >= 2 and rows[0]["hero"]


def test_other_reason_needs_a_note_and_is_not_auto_paid(env, as_):
    doc, vid, trip = _doctor_at_door(env, as_)
    _arrive(env, trip["id"])
    url = f"/api/provider/jobs/visit/{vid}"
    assert _code(doc.post(f"{url}/cancel", {"reason": "nope"})) == "bad_reason"
    assert _code(doc.post(f"{url}/cancel", {"reason": "other"})) == "note_required"
    r = doc.post(f"{url}/cancel", {"reason": "other", "note": "Dog loose in the compound"})
    assert r.status_code == 200 and r.json()["hero_paid"] == 0
    live = as_("patient").get(f"/api/patient/visits/{vid}/live").json()
    assert "Dog loose" in live["cancelled_by_hero"]["message"]


def test_only_the_assigned_hero_and_no_admin_without_login(env, as_):
    doc, vid, trip = _doctor_at_door(env, as_)
    _arrive(env, trip["id"])
    assert as_("physio").post(f"/api/provider/jobs/visit/{vid}/cancel", {"reason": "unsafe"}).status_code in (403, 404)
    assert as_("patient").post(f"/api/provider/jobs/visit/{vid}/cancel", {"reason": "unsafe"}).status_code == 403
    assert env["client"].get("/api/admin/hero-cancellations").status_code in (401, 403)


def test_sample_collector_cancels_and_payment_hold_is_released(env, as_):
    patient, priya = as_("patient"), as_("phlebotomist")
    t = env["ids"]["lab_tests"]
    b = patient.post("/api/labs/bookings", {"test_ids": [t["CBC"]], "slot": "now", "payment_method": "upi"}).json()
    offer = priya.get("/api/provider/status").json()["offers"][0]
    trip = priya.post(f"/api/provider/offers/{offer['id']}/accept").json()["trip"]
    _arrive(env, trip["id"])
    r = priya.post(f"/api/provider/jobs/lab/{b['id']}/cancel", {"reason": "wrong_address"})
    assert r.status_code == 200, r.text
    out = patient.get(f"/api/labs/bookings/{b['id']}").json()
    assert out["status"] == "cancelled" and out["payment_status"] == "voided"
    assert out["cancelled_by_hero"]["label"] == "Address not found"
    assert patient.get(f"/api/labs/bookings/{b['id']}/live").json()["cancelled_by_hero"]


def test_physio_package_session_is_replaced(env, as_):
    arjun, priya = as_("patient2"), as_("physio")
    pkg = arjun.get("/api/patient/physio/bookings").json()[0]
    s = next(x for x in pkg["sessions"] if x["status"] == "scheduled")
    trip = priya.post(f"/api/physio/sessions/{s['id']}/depart").json()
    _arrive(env, trip["id"])
    r = priya.post(f"/api/provider/jobs/physio/{s['id']}/cancel", {"reason": "patient_refused"})
    assert r.status_code == 200, r.text
    after = arjun.get(f"/api/patient/physio/bookings/{pkg['id']}").json()
    assert after["status"] == "active"
    gone = next(x for x in after["sessions"] if x["id"] == s["id"])
    assert gone["status"] == "cancelled" and "replacement" in gone["cancelled_by_hero"]["message"]
    assert sum(1 for x in after["sessions"] if x["status"] == "scheduled") == \
        sum(1 for x in pkg["sessions"] if x["status"] == "scheduled")
