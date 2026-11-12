"""Lab tests at home: catalog, slots, booking, phlebotomist dispatch, live map, collection, lab and report."""
from datetime import timedelta

from app.models import LabBooking, Trip, utcnow


def _arrive(env, trip_id):
    with env["Session"]() as s:
        t = s.get(Trip, trip_id)
        t.started_at = t.started_at - timedelta(hours=3)
        s.commit()


def _status(api):
    r = api.get("/api/provider/status")
    assert r.status_code == 200, r.text
    return r.json()


def test_catalog_and_quote(env, as_):
    p = as_("patient")
    cat = p.get("/api/labs/catalog").json()
    assert {x["code"] for x in cat["packages"]} >= {"PKG-FULL", "PKG-DIAB"}
    full = next(x for x in cat["packages"] if x["code"] == "PKG-FULL")
    assert full["parameter_count"] > 20 and "Lipid Profile (Cholesterol)" in full["includes"]
    t = env["ids"]["lab_tests"]
    # A test already inside a chosen package isn't charged twice; small orders pay a collection fee.
    q = p.post("/api/labs/quote", {"test_ids": [t["PKG-FULL"], t["CBC"]]}).json()
    assert [i["code"] for i in q["items"]] == ["PKG-FULL"] and q["removed_duplicates"] == ["Complete Blood Count (CBC)"]
    assert q["collection_fee"] == 0 and q["fasting_hours"] == 12 and set(q["samples"]) == {"Blood", "Urine"}
    q = p.post("/api/labs/quote", {"test_ids": [t["CBC"]]}).json()
    assert q["collection_fee"] == 75 and q["total"] == 374
    assert q["collectors_online"] == 2
    slots = p.get("/api/labs/slots", params={"fasting_hours": 12}).json()
    assert slots and all(s["available"] for s in slots)
    assert any(s["recommended"] for s in slots)


def test_collect_now_full_journey(env, as_):
    patient, priya, suresh = as_("patient"), as_("phlebotomist"), as_("phlebotomist2")
    t = env["ids"]["lab_tests"]
    r = patient.post("/api/labs/bookings", {"test_ids": [t["CBC"], t["THYROID"]], "slot": "now", "payment_method": "upi"})
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["status"] == "booked" and b["on_demand"] and len(b["collection_code"]) == 4
    assert b["payment_status"] == "authorized" and b["total"] == 299 + 349 + 99

    live = patient.get(f"/api/labs/bookings/{b['id']}/live").json()
    assert live["phase"] == "searching" and live["providers_asked"] == 1

    # Nearest online collector (Priya) gets it first; she declines, it moves to Suresh.
    offer = _status(priya)["offers"][0]
    assert offer["kind"] == "lab" and "Complete Blood Count" in offer["reason"] and offer["seconds_left"] > 0
    assert not _status(suresh)["offers"]
    assert priya.post(f"/api/provider/offers/{offer['id']}/decline").status_code == 200
    offer = _status(suresh)["offers"][0]
    r = suresh.post(f"/api/provider/offers/{offer['id']}/accept")
    assert r.status_code == 200, r.text
    trip = r.json()["trip"]
    assert trip["lab_booking_id"] == b["id"] and trip["leg"] == "to_patient"

    live = patient.get(f"/api/labs/bookings/{b['id']}/live").json()
    assert live["phase"] == "on_the_way" and live["provider"]["name"] == "Suresh" and live["trip"]["eta_min"] >= 1

    # Can't collect before arriving, or with the wrong code.
    assert suresh.post(f"/api/provider/labs/{b['id']}/collect", {"code": b["collection_code"]}).status_code == 409
    _arrive(env, trip["id"])
    assert patient.get(f"/api/labs/bookings/{b['id']}/live").json()["phase"] == "arrived"
    wrong = "0000" if b["collection_code"] != "0000" else "1111"
    assert suresh.post(f"/api/provider/labs/{b['id']}/collect", {"code": wrong}).status_code == 422
    r = suresh.post(f"/api/provider/labs/{b['id']}/collect", {"code": b["collection_code"]})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "collected" and r.json()["sample_ids"] and r.json()["trip"]["leg"] == "to_lab"
    assert "collection_code" not in r.json()

    live = patient.get(f"/api/labs/bookings/{b['id']}/live").json()
    assert live["phase"] == "to_lab" and live["collection_code"] is None
    jobs = suresh.get("/api/provider/jobs").json()
    assert jobs[0]["kind"] == "lab" and jobs[0]["trip_leg"] == "to_lab"

    assert suresh.post(f"/api/provider/labs/{b['id']}/handover").status_code == 200
    got = patient.get(f"/api/labs/bookings/{b['id']}").json()
    assert got["status"] == "at_lab" and got["payment_status"] == "captured" and "report" not in got

    # The lab finishes; the report shows in the app.
    with env["Session"]() as s:
        row = s.get(LabBooking, b["id"])
        row.at_lab_at = utcnow() - timedelta(minutes=10)
        s.commit()
    got = patient.get(f"/api/labs/bookings/{b['id']}").json()
    assert got["status"] == "report_ready"
    rep = got["report"]
    assert [s["code"] for s in rep["sections"]] == ["CBC", "THYROID"]
    assert all(r["flag"] in ("low", "high", "normal") for s in rep["sections"] for r in s["results"])
    assert rep["patient"]["name"] == "Meera Demo" and rep["lab"]["accreditation"].startswith("NABL")
    notes = patient.get("/api/notifications").json()
    assert any(n["title"] == "Your lab report is ready" for n in notes)


def test_booked_slot_offer_depart_and_cancel(env, as_):
    patient, priya = as_("patient2"), as_("phlebotomist")
    t = env["ids"]["lab_tests"]
    slot = next(s for s in patient.get("/api/labs/slots").json() if s["fasting_friendly"])
    r = patient.post("/api/labs/bookings", {"test_ids": [t["PKG-DIAB"]], "slot": slot["start"], "payment_method": "cash"})
    assert r.status_code == 201, r.text
    b = r.json()
    assert not b["on_demand"] and b["payment_status"] == "due" and b["collection_fee"] == 0
    # Booked times wait for an answer (no countdown) from the nearest collector to Arjun.
    offers = [o for s in ("phlebotomist", "phlebotomist2") for o in _status(as_(s))["offers"]]
    assert len(offers) == 1 and offers[0]["seconds_left"] is None
    who = "phlebotomist2" if _status(as_("phlebotomist2"))["offers"] else "phlebotomist"
    api = as_(who)
    assert api.post(f"/api/provider/offers/{offers[0]['id']}/accept").json()["trip"] is None
    assert patient.get(f"/api/labs/bookings/{b['id']}/live").json()["phase"] == "confirmed"
    r = api.post(f"/api/provider/labs/{b['id']}/depart")
    assert r.status_code == 200 and r.json()["lab_booking_id"] == b["id"]
    assert patient.get(f"/api/labs/bookings/{b['id']}/live").json()["phase"] == "on_the_way"
    # Fasting must be confirmed at the door.
    _arrive(env, r.json()["id"])
    code = patient.get(f"/api/labs/bookings/{b['id']}").json()["collection_code"]
    assert api.post(f"/api/provider/labs/{b['id']}/collect", {"code": code}).json()["detail"]["code"] == "fasting_unconfirmed"
    # Patient cancels before collection: trip ends, collector is told.
    assert patient.post(f"/api/labs/bookings/{b['id']}/cancel").json()["status"] == "cancelled"
    assert api.get("/api/provider/trip").json() is None
    assert priya.post(f"/api/provider/labs/{b['id']}/handover").status_code == 404


def test_rules(env, as_):
    patient = as_("patient")
    t = env["ids"]["lab_tests"]
    # Others can't see a patient's booking; providers can't book; declined cards don't book.
    b = patient.post("/api/labs/bookings", {"test_ids": [t["CBC"]], "slot": "now", "payment_method": "cash"}).json()
    assert as_("patient2").get(f"/api/labs/bookings/{b['id']}").status_code == 404
    assert as_("doctor").post("/api/labs/bookings", {"test_ids": [t["CBC"]]}).status_code == 403
    r = patient.post("/api/labs/bookings", {"test_ids": [t["CBC"]], "payment_method": "card", "payment_token": "decline"})
    assert r.status_code == 402
    assert patient.post("/api/labs/bookings", {"test_ids": [t["CBC"]], "slot": "2001-01-01T06:00:00"}).status_code == 422
    # Seeded past booking has a report; a collector can go online/offline; nobody online means pick a slot.
    past = patient.get(f"/api/labs/bookings/{env['ids']['lab_bookings']['meera_past']}").json()
    assert past["report"]["sections"]
    for who in ("phlebotomist", "phlebotomist2"):
        assert as_(who).post("/api/provider/duty", {"online": False}).status_code == 200
    r = patient.post("/api/labs/bookings", {"test_ids": [t["CBC"]], "slot": "now", "payment_method": "cash"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_collector_online"
    # The earlier collect-now request lost its collectors when they went offline, so it was cancelled.
    assert patient.get(f"/api/labs/bookings/{b['id']}").json()["status"] == "cancelled"


def test_collector_earns_on_handover(env, as_):
    patient, priya = as_("patient"), as_("phlebotomist")
    t = env["ids"]["lab_tests"]
    b = patient.post("/api/labs/bookings", {"test_ids": [t["CBC"]], "slot": "now", "payment_method": "cash"}).json()
    offer = _status(priya)["offers"][0]
    trip = priya.post(f"/api/provider/offers/{offer['id']}/accept").json()["trip"]
    _arrive(env, trip["id"])
    assert priya.post(f"/api/provider/labs/{b['id']}/collect", {"code": b["collection_code"]}).status_code == 200
    before = priya.get("/api/provider/earnings").json()["balance"]
    assert priya.post(f"/api/provider/labs/{b['id']}/handover").status_code == 200
    after = priya.get("/api/provider/earnings").json()
    assert round(after["balance"] - before, 2) == offer["earning"] and after["jobs"][0]["kind"] == "lab"
