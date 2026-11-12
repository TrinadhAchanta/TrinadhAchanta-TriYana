"""Doctor's visit notes and vitals, linked to the visit and prescription, visible to the patient."""
from tests.conftest import rx_items

NOTE = {"chief_complaint": "Fever and body ache", "findings": "Fever 2 days, throat red, chest clear.",
        "diagnosis": "Viral fever", "advice": "Fluids and rest.", "follow_up_in_days": 3,
        "temperature_f": 101.3, "bp_systolic": 122, "bp_diastolic": 80, "pulse_bpm": 104,
        "spo2_pct": 97, "resp_rate": 18, "weight_kg": 64.5}


def _start(doc, vid):
    for a in ("accept", "start"):
        assert doc.post(f"/api/doctor/visits/{vid}/{a}").status_code == 200


def test_doctor_writes_notes_and_completes_patient_sees_them(env, as_):
    doc, pat = as_("doctor"), as_("patient")
    vid = env["ids"]["visits"]["meera"]
    # Not before the visit starts.
    assert doc.put(f"/api/doctor/visits/{vid}/notes", NOTE).status_code == 409
    _start(doc, vid)
    r = doc.put(f"/api/doctor/visits/{vid}/notes", NOTE)
    assert r.status_code == 200, r.text
    n = r.json()
    assert n["vitals"]["temperature_c"] == 38.5 and n["vitals"]["bp"] == "122/80"
    assert {f["label"] for f in n["flags"]} == {"Fever", "Fast pulse"}
    # Hidden from the patient until the visit is completed.
    assert pat.get(f"/api/patient/visits/{vid}/notes").json() is None

    # Prescription for the same visit is linked to the notes.
    rx = doc.post("/api/prescriptions", {"visit_id": vid, "diagnosis_note": "Viral fever",
                                         "items": rx_items(env["ids"], ("dolo", 5))}).json()
    r = doc.put(f"/api/doctor/visits/{vid}/notes", {**NOTE, "complete": True})
    assert r.status_code == 200
    assert [p["reference_no"] for p in r.json()["prescriptions"]] == [rx["reference_no"]]
    assert next(v for v in doc.get("/api/doctor/visits").json() if v["id"] == vid)["status"] == "completed"

    seen = pat.get(f"/api/patient/visits/{vid}/notes").json()
    assert seen["diagnosis"] == "Viral fever" and seen["vitals"]["spo2_pct"] == 97
    assert seen["prescriptions"] == []  # draft prescriptions stay private until signed
    doc.post(f"/api/prescriptions/{rx['id']}/sign", {"confirm_reviewed": True})
    assert len(pat.get(f"/api/patient/visits/{vid}/notes").json()["prescriptions"]) == 1

    hist = next(v for v in pat.get("/api/patient/visits").json() if v["id"] == vid)
    assert hist["notes"]["diagnosis"] == "Viral fever"
    assert any(n["title"] == "Your visit notes are ready" for n in pat.get("/api/notifications").json())
    assert any(x["visit_id"] == vid for x in pat.get("/api/patient/my-data").json()["visit_notes"])


def test_vitals_are_checked(env, as_):
    doc = as_("doctor")
    vid = env["ids"]["visits"]["meera"]
    _start(doc, vid)
    for bad in ({"spo2_pct": 140}, {"temperature_f": 150}, {"bp_systolic": 120, "bp_diastolic": None},
                {"bp_systolic": 80, "bp_diastolic": 120}, {"chief_complaint": " "}):
        r = doc.put(f"/api/doctor/visits/{vid}/notes", {**NOTE, **bad})
        assert r.status_code == 422, bad


def test_only_the_visit_doctor_and_patient(env, as_):
    vid = env["ids"]["visits"]["meera_past"]  # Dr. Sana's visit with Meera, seeded with notes
    assert as_("doctor").get(f"/api/doctor/visits/{vid}/notes").status_code == 403
    assert as_("doctor_sana").get(f"/api/doctor/visits/{vid}/notes").json()["diagnosis"]
    assert as_("patient").get(f"/api/patient/visits/{vid}/notes").json()["vitals"]["bp"] == "134/86"
    other = env["ids"]["visits"]["arjun_past"]
    assert as_("patient").get(f"/api/patient/visits/{other}/notes").status_code == 403
