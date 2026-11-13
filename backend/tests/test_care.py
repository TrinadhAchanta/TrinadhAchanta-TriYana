"""Care plans, the free 48-hour follow-up call, the health records timeline and voice booking."""
from datetime import datetime, timedelta

from tests.conftest import start_visit

from app.services.voice import understand


def _complete(env, doc, vid, note=True):
    assert doc.post(f"/api/doctor/visits/{vid}/accept").status_code == 200
    start_visit(env, doc, vid)
    if note:
        r = doc.put(f"/api/doctor/visits/{vid}/notes", {"chief_complaint": "Fever", "diagnosis": "Viral fever",
                                                        "bp_systolic": 128, "bp_diastolic": 82, "complete": True})
        assert r.status_code == 200, r.text
    else:
        assert doc.post(f"/api/doctor/visits/{vid}/complete").status_code == 200


def _iso(s):
    return datetime.fromisoformat(s)


# ----------------------------------------------------------------------------- care plans
def test_catalog_and_enrol_books_first_checkup(as_):
    pat = as_("patient")
    cat = pat.get("/api/care-plans/catalog").json()
    assert {p["kind"] for p in cat} == {"diabetes", "bp", "bedridden", "elderly"}
    assert next(p for p in cat if p["kind"] == "bedridden")["visits_per_month"] == 4

    r = pat.post("/api/care-plans", {"kind": "diabetes", "preferred_hour": 11})
    assert r.status_code == 201, r.text
    plan = r.json()
    assert plan["status"] == "active" and len(plan["checkups"]) == 2
    first = plan["checkups"][0]
    assert first["visit_id"] and first["status"] == "requested"  # booked as a normal home visit
    assert plan["doctor"] is not None  # the doctor who took the first check-up becomes the regular doctor
    # Second check-up is ~15 days out, beyond the 7-day booking window: waits until it comes in range.
    assert plan["checkups"][1]["status"] == "waiting"
    visit = next(v for v in pat.get("/api/patient/visits").json() if v["id"] == first["visit_id"])
    assert visit["reason"] == "Diabetes care plan check-up"

    # One active plan of each kind.
    assert pat.post("/api/care-plans", {"kind": "diabetes"}).status_code == 409
    assert pat.post("/api/care-plans", {"kind": "gold"}).status_code == 422
    assert pat.post("/api/care-plans", {"kind": "bp", "preferred_hour": 23}).status_code == 422
    assert len(pat.get("/api/care-plans").json()) == 1


def test_cancel_plan_cancels_booked_checkups(as_):
    pat = as_("patient")
    plan = pat.post("/api/care-plans", {"kind": "bedridden"}).json()
    booked = [c["visit_id"] for c in plan["checkups"] if c["visit_id"]]
    assert booked
    assert as_("patient2").post(f"/api/care-plans/{plan['id']}/cancel").status_code == 404
    r = pat.post(f"/api/care-plans/{plan['id']}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    statuses = {v["id"]: v["status"] for v in pat.get("/api/patient/visits").json()}
    assert all(statuses[v] == "cancelled" for v in booked)
    # The same kind can be started again after cancelling.
    assert pat.post("/api/care-plans", {"kind": "bedridden"}).status_code == 201


def test_plan_renews_and_books_next_checkups(as_, env):
    from app.models import CarePlan
    pat = as_("patient")
    plan = pat.post("/api/care-plans", {"kind": "elderly"}).json()
    with env["Session"]() as s:
        p = s.get(CarePlan, plan["id"])
        p.renews_on = datetime.utcnow() - timedelta(minutes=1)  # the month is over
        s.commit()
    again = pat.get("/api/care-plans").json()[0]
    assert len(again["checkups"]) == 2 and _iso(again["renews_on"]) > datetime.utcnow()


# ------------------------------------------------------------------- follow-up call within 48 h
def test_completed_visit_gets_free_call_within_48h(as_, env):
    doc, pat = as_("doctor"), as_("patient")
    vid = env["ids"]["visits"]["meera"]
    _complete(env, doc, vid, note=False)
    calls = pat.get("/api/patient/follow-up-calls").json()
    assert len(calls) == 1
    c = calls[0]
    assert c["visit_id"] == vid and c["status"] == "scheduled" and c["free"] is True
    when, due = _iso(c["scheduled_for"]), _iso(c["due_by"])
    assert datetime.utcnow() < when <= due <= datetime.utcnow() + timedelta(hours=48, minutes=1)
    assert any(n["title"] == "Free follow-up call booked" for n in pat.get("/api/notifications").json())

    # Patient moves the call to another time inside the window.
    assert c["slots"] and all(_iso(s) <= due for s in c["slots"])
    r = pat.post(f"/api/patient/follow-up-calls/{c['id']}/time", {"scheduled_for": c["slots"][-1]})
    assert r.status_code == 200 and r.json()["scheduled_for"] == c["slots"][-1]
    late = (due + timedelta(hours=5)).isoformat()
    assert pat.post(f"/api/patient/follow-up-calls/{c['id']}/time", {"scheduled_for": late}).status_code == 422

    # Feeling worse goes straight to the doctor, who sees that patient first.
    r = pat.post(f"/api/patient/follow-up-calls/{c['id']}/feeling", {"feeling": "worse", "note": "Fever back"})
    assert r.status_code == 200
    assert any(n["title"] == "Patient feels worse" for n in doc.get("/api/notifications").json())
    dc = doc.get("/api/doctor/follow-up-calls").json()
    assert dc[0]["id"] == c["id"] and dc[0]["feeling"] == "worse" and dc[0]["patient"]["name"]

    # Only the visit's doctor can close it, with a note the patient then sees.
    assert as_("doctor_sana").post(f"/api/doctor/follow-up-calls/{c['id']}/done", {"note": "x"}).status_code == 404
    assert doc.post(f"/api/doctor/follow-up-calls/{c['id']}/done", {"note": " "}).status_code == 422
    r = doc.post(f"/api/doctor/follow-up-calls/{c['id']}/done", {"note": "Fever settling. Continue fluids."})
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert pat.get("/api/patient/follow-up-calls").json()[0]["doctor_note"] == "Fever settling. Continue fluids."
    assert as_("patient2").post(f"/api/patient/follow-up-calls/{c['id']}/feeling", {"feeling": "same"}).status_code == 404


def test_first_call_time_is_within_calling_hours():
    from app.services.care import CALL_HOURS, FOLLOW_UP_WINDOW, _first_call_time, _local
    base = datetime(2026, 11, 13, 0, 0)
    for h in range(24):
        done = base + timedelta(hours=h, minutes=17)
        t = _first_call_time(done)
        assert done < t <= done + FOLLOW_UP_WINDOW
        assert _local(t).hour in CALL_HOURS


# ------------------------------------------------------------------------------ health records
def test_records_timeline_has_visits_calls_and_vitals(as_, env):
    doc, pat = as_("doctor"), as_("patient")
    before = pat.get("/api/patient/records").json()
    assert before["counts"]["visit"] == 1 and before["vitals"][0]["bp_systolic"] == 134  # seeded past visit
    assert any(i["kind"] == "lab" for i in before["items"]) or before["counts"]["lab"] == 0

    vid = env["ids"]["visits"]["meera"]
    _complete(env, doc, vid)
    call = pat.get("/api/patient/follow-up-calls").json()[0]
    doc.post(f"/api/doctor/follow-up-calls/{call['id']}/done", {"note": "Doing better."})
    rec = pat.get("/api/patient/records").json()
    kinds = [i["kind"] for i in rec["items"]]
    assert rec["counts"]["visit"] == 2 and "call" in kinds
    assert kinds[0] == "call"  # newest first
    assert [v["bp_systolic"] for v in rec["vitals"]] == [134, 128]  # oldest first, for the trend
    assert next(i for i in rec["items"] if i["kind"] == "visit" and i["id"] == vid)["subtitle"] == "Viral fever"
    # Another patient sees only their own.
    other = as_("patient2").get("/api/patient/records").json()
    assert all(i["id"] != vid for i in other["items"] if i["kind"] == "visit")
    assert as_("doctor").get("/api/patient/records").status_code == 403


# ---------------------------------------------------------------------------------- voice booking
def test_voice_understands_four_languages():
    hi = understand("मुझे बुखार है, कल सुबह डॉक्टर भेजो", "hi")
    assert (hi["action"], hi["reason"], hi["day"], hi["part"]) == ("book", "Fever or cold", "tomorrow", "morning")
    roman = understand("mujhe bukhar hai abhi doctor chahiye", "hi")
    assert roman["action"] == "now" and roman["reason"] == "Fever or cold"
    te = understand("నాకు జ్వరం ఉంది వెంటనే రండి", "te")
    assert te["action"] == "now" and te["reason"] == "Fever or cold"
    ta = understand("அம்மாவுக்கு சர்க்கரை பரிசோதனை நாளை காலை", "ta")
    assert (ta["action"], ta["reason"], ta["day"]) == ("book", "Sugar (diabetes) check", "tomorrow")
    en = understand("BP check this evening", "en")
    assert (en["action"], en["reason"], en["day"], en["part"]) == ("book", "Blood pressure check", "today", "evening")
    sos = understand("my father has chest pain, come tomorrow", "en")
    assert sos["emergency"] and sos["action"] == "now" and sos["reason"].startswith("Urgent:")
    assert understand("hello", "en")["understood"] is False


def test_voice_endpoint(as_):
    r = as_("patient").post("/api/voice/understand", {"text": "naku jwaram, ventane", "lang": "te"})
    assert r.status_code == 200 and r.json()["action"] == "now"


def test_plan_checkups_are_covered_by_the_plan(as_):
    pat = as_("patient")
    plan = pat.post("/api/care-plans", {"kind": "bp"}).json()
    vid = plan["checkups"][0]["visit_id"]
    v = next(v for v in pat.get("/api/patient/visits").json() if v["id"] == vid)
    assert v["bill"]["patient_pays"] == 0 and v["bill"]["lines"][-1]["code"] == "care_plan"
