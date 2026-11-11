"""Doctor-set availability, "whoever is available soonest", and follow-ups with the previous doctor."""
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def _local(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).astimezone(IST)


def test_doctor_sets_hours_and_patients_only_see_those(as_, env):
    doctor, patient = as_("doctor"), as_("patient")
    carter = env["ids"]["doctors"]["carter"]
    av = doctor.get("/api/doctor/availability").json()
    assert len(av["days"]) == 7 and av["days"][0]["hours"] == av["default_hours"]
    day = av["days"][3]["date"]  # well clear of today's lead time and the seeded bookings

    r = doctor.put("/api/doctor/availability", {"date": day, "hours": [8, 20, 14]})
    assert r.status_code == 200, r.text
    assert r.json()["hours"] == [8, 14, 20] and r.json()["custom"] is True

    slots = patient.get("/api/visit-slots", params={"doctor_id": carter}).json()
    hours_that_day = sorted(_local(s).hour for s in slots if _local(s).date().isoformat() == day)
    assert hours_that_day == [8, 14, 20]

    # A day off removes every slot that day.
    assert doctor.put("/api/doctor/availability", {"date": day, "hours": []}).status_code == 200
    slots = patient.get("/api/visit-slots", params={"doctor_id": carter}).json()
    assert not [s for s in slots if _local(s).date().isoformat() == day]


def test_availability_validation_and_booked_hours_are_kept(as_, env):
    doctor, patient = as_("doctor"), as_("patient")
    carter = env["ids"]["doctors"]["carter"]
    days = doctor.get("/api/doctor/availability").json()["days"]
    assert doctor.put("/api/doctor/availability", {"date": "2000-01-01", "hours": [9]}).status_code == 422
    assert doctor.put("/api/doctor/availability", {"date": days[2]["date"], "hours": [3]}).status_code == 422

    slot = next(s for s in patient.get("/api/visit-slots", params={"doctor_id": carter}).json()
                if _local(s).date().isoformat() == days[2]["date"])
    assert patient.post("/api/patient/visits", {"doctor_id": carter, "scheduled_for": slot, "reason": "Cough"}).status_code == 201
    booked_hour = _local(slot).hour
    day = next(d for d in doctor.get("/api/doctor/availability").json()["days"] if d["date"] == days[2]["date"])
    assert booked_hour in day["booked"]
    # Closing a booked hour is refused; keeping it open works.
    assert doctor.put("/api/doctor/availability", {"date": day["date"], "hours": []}).status_code == 409
    assert doctor.put("/api/doctor/availability", {"date": day["date"], "hours": [booked_hour]}).status_code == 200

    # Only doctors can set hours.
    assert patient.put("/api/doctor/availability", {"date": day["date"], "hours": [9]}).status_code == 403


def test_whoever_is_available_soonest(as_):
    patient = as_("patient2")
    soonest = patient.get("/api/doctors").json()["soonest"]
    assert soonest and soonest["slot"]
    earliest = patient.get("/api/visit-slots").json()[0]
    assert soonest["slot"] == earliest

    r = patient.post("/api/patient/visits", {"asap": True, "reason": "Fever or cold"})
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["scheduled_for"] == earliest and v["doctor"]["id"] == soonest["doctor"]["id"]


def test_follow_up_suggests_previous_doctor_when_available(as_, env):
    arjun = as_("patient2")
    fu = arjun.get("/api/patient/follow-up").json()
    assert fu["previous_visit"]["id"] == env["ids"]["visits"]["arjun_past"]
    assert fu["doctor"]["id"] == env["ids"]["doctors"]["carter"]
    assert fu["available_soon"] is True and fu["next_slot"] and fu["alternative"] is None

    r = arjun.post("/api/patient/visits", {"doctor_id": fu["doctor"]["id"], "scheduled_for": fu["next_slot"],
                                           "reason": "Follow-up visit", "follow_up_of": fu["previous_visit"]["id"]})
    assert r.status_code == 201, r.text
    assert r.json()["follow_up_of"]["same_doctor"] is True

    # The doctor's app shows it as a follow-up of a patient they saw before.
    mine = next(v for v in as_("doctor").get("/api/doctor/visits").json() if v["id"] == r.json()["id"])
    assert mine["follow_up_of"]["booking_ref"] == "BK-DEMO0009"
    assert any(n["title"] == "New follow-up visit request" for n in as_("doctor").get("/api/notifications").json())


def test_follow_up_when_previous_doctor_is_away_offers_appointment_or_someone_sooner(as_, env):
    meera = as_("patient")
    sana = env["ids"]["doctors"]["sana"]
    fu = meera.get("/api/patient/follow-up").json()
    assert fu["doctor"]["id"] == sana
    assert fu["available_soon"] is False
    assert fu["next_slot"], "the usual doctor should still have a later opening to book"
    assert fu["alternative"] and fu["alternative"]["doctor"]["id"] != sana
    assert fu["alternative"]["slot"] < fu["next_slot"]

    # Book a scheduled appointment with the usual doctor at her next opening.
    r = meera.post("/api/patient/visits", {"doctor_id": sana, "scheduled_for": fu["next_slot"],
                                           "reason": "Follow-up visit", "follow_up_of": fu["previous_visit"]["id"]})
    assert r.status_code == 201, r.text
    assert r.json()["doctor"]["id"] == sana


def test_follow_up_rules(as_, env):
    meera = as_("patient")
    slot = meera.get("/api/visit-slots").json()[0]
    # Someone else's visit, or one that hasn't happened yet, can't be followed up.
    other = env["ids"]["visits"]["arjun_past"]
    assert meera.post("/api/patient/visits", {"scheduled_for": slot, "reason": "x x", "follow_up_of": other}).status_code == 404
    open_visit = env["ids"]["visits"]["meera"]
    assert meera.post("/api/patient/visits", {"scheduled_for": slot, "reason": "x x", "follow_up_of": open_visit}).status_code == 409
    assert as_("doctor").get("/api/patient/follow-up").status_code == 403
