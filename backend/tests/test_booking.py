"""Patient books a home visit -> nearest verified doctor -> doctor sees and runs the visit."""


def test_nearby_doctors_sorted_and_verified_only(as_):
    r = as_("patient").get("/api/doctors")
    assert r.status_code == 200
    docs = r.json()["doctors"]
    assert docs, "expected nearby doctors"
    assert all(d["license_verified"] for d in docs)
    assert "Dr. Pending Check" not in [d["name"] for d in docs]
    dists = [d["distance_km"] for d in docs]
    assert dists == sorted(dists)
    assert docs[0]["name"] == "Dr. Emily Carter"
    assert all(d["next_slot"] for d in docs)


def test_book_specific_doctor_shows_in_doctor_app_and_flows_to_visit(as_):
    patient, doctor = as_("patient2"), as_("doctor")
    carter = next(d for d in patient.get("/api/doctors").json()["doctors"] if d["name"] == "Dr. Emily Carter")
    slot = patient.get("/api/visit-slots", params={"doctor_id": carter["id"]}).json()[0]
    r = patient.post("/api/patient/visits", {"doctor_id": carter["id"], "scheduled_for": slot,
                                             "reason": "Fever since yesterday"})
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["status"] == "requested" and v["booking_ref"].startswith("BK-") and v["fee"] == carter["visit_fee"]
    assert v["address"]  # defaults to the patient's saved address

    # The doctor sees the booking and the slot is no longer offered.
    visits = doctor.get("/api/doctor/visits").json()
    mine = next(x for x in visits if x["id"] == v["id"])
    assert mine["reason"] == "Fever since yesterday" and mine["booking_ref"] == v["booking_ref"]
    assert slot not in patient.get("/api/visit-slots", params={"doctor_id": carter["id"]}).json()
    assert any(n["title"] == "New home visit request" for n in doctor.get("/api/notifications").json())

    # Double booking the same slot is refused.
    again = as_("patient").post("/api/patient/visits", {"doctor_id": carter["id"], "scheduled_for": slot, "reason": "x x"})
    assert again.status_code == 409

    # Doctor accepts -> patient is told.
    assert doctor.post(f"/api/doctor/visits/{v['id']}/accept").status_code == 200
    assert any(n["title"] == "Doctor confirmed your visit" for n in patient.get("/api/notifications").json())
    assert next(x for x in patient.get("/api/patient/visits").json() if x["id"] == v["id"])["status"] == "accepted"


def test_nearest_available_doctor_auto_match(as_):
    patient = as_("patient")
    slots = patient.get("/api/visit-slots").json()
    r = patient.post("/api/patient/visits", {"doctor_id": None, "scheduled_for": slots[-1], "reason": "General check-up"})
    assert r.status_code == 201, r.text
    assert r.json()["doctor"]["name"] == "Dr. Emily Carter"  # nearest, and free at that time


def test_cannot_book_unverified_or_bad_slot_and_cancel_rules(as_, env):
    patient = as_("patient")
    unverified = env["ids"]["doctors"]["unverified"]
    slot = patient.get("/api/visit-slots", params={"doctor_id": env["ids"]["doctors"]["carter"]}).json()[0]
    assert patient.post("/api/patient/visits", {"doctor_id": unverified, "scheduled_for": slot, "reason": "test"}).status_code == 404
    carter = env["ids"]["doctors"]["carter"]
    assert patient.post("/api/patient/visits", {"doctor_id": carter, "scheduled_for": "2000-01-01T09:00:00", "reason": "test"}).status_code == 409
    assert patient.post("/api/patient/visits", {"doctor_id": carter, "scheduled_for": "not-a-time", "reason": "test"}).status_code == 422

    v = patient.post("/api/patient/visits", {"doctor_id": carter, "scheduled_for": slot, "reason": "Cough"}).json()
    # Someone else cannot cancel it.
    assert as_("patient2").post(f"/api/patient/visits/{v['id']}/cancel").status_code == 404
    assert patient.post(f"/api/patient/visits/{v['id']}/cancel").json()["status"] == "cancelled"
    assert patient.post(f"/api/patient/visits/{v['id']}/cancel").status_code == 409
    # The slot is free again.
    assert slot in patient.get("/api/visit-slots", params={"doctor_id": carter}).json()


def test_only_patients_can_book(as_):
    assert as_("doctor").get("/api/doctors").status_code == 403
    assert as_("pharmacist").post("/api/patient/visits", {"scheduled_for": "2030-01-01T09:00:00", "reason": "xx"}).status_code == 403
