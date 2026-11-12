"""Mandatory doctor face verification before every home visit (Tri's test list, end to end via the API)."""
from datetime import timedelta

import pytest

from app.models import AuditLog, FaceCheck, utcnow
from tests.conftest import arrival_code, face_check, face_pass, live_frames

ADMIN = {"X-Admin-Key": "demo-admin"}


@pytest.fixture(autouse=True)
def _demo(monkeypatch):
    monkeypatch.delenv("TRIYANA_ADMIN_KEY", raising=False)
    monkeypatch.setenv("TRIYANA_DEMO", "1")
    monkeypatch.delenv("TRIYANA_FACE_PROVIDER", raising=False)


def _accepted(env, as_, *keys):
    doc = as_("doctor")
    vids = [env["ids"]["visits"][k] for k in keys]
    for vid in vids:
        assert doc.post(f"/api/doctor/visits/{vid}/accept").status_code == 200
    return doc, vids


def _code(r):
    return r.json()["detail"]["code"]


def _alerts(env):
    with env["Session"]() as s:
        return [a.details for a in s.query(AuditLog).filter(AuditLog.action == "security.alert")]


def _case(env, kind):
    cases = env["client"].get("/api/admin/identity/cases", headers=ADMIN).json()
    return next(c for c in cases if c["kind"] == kind)


def _resolve(env, case_id, action, note="Video call, checked Aadhaar in person"):
    return env["client"].post(f"/api/admin/identity/cases/{case_id}/resolve", headers=ADMIN,
                              json={"action": action, "note": note})


# ------------------------------------------------------------------ the happy path
def test_successful_verification_unlocks_journey_and_tells_the_patient(env, as_):
    doc, (vid,) = _accepted(env, as_, "meera")
    patient = as_("patient")
    # Nothing to see before the check: no photo, no code.
    assert patient.get(f"/api/patient/visits/{vid}/doctor-identity").json() == {"verified": False}
    assert patient.get(f"/api/patient/visits/{vid}/live").json()["identity"]["arrival_code"] is None

    ch = doc.post("/api/provider/face/challenges", {"purpose": "visit", "visit_id": vid}).json()
    assert ch["prompt"] and ch["attempts_left"] == 3 and ch["expires_in"] == 120
    r = doc.post(f"/api/provider/face/challenges/{ch['id']}/submit", {"nonce": ch["nonce"], "frames": live_frames()})
    assert r.json()["status"] == "passed" and r.json()["liveness"] > 0.8 and r.json()["match"] > 0.9
    assert doc.get(f"/api/provider/visits/{vid}/identity").json()["verified"] is True

    trip = doc.post(f"/api/provider/visits/{vid}/depart")
    assert trip.status_code == 200 and trip.json()["leg"] == "to_patient"

    # Patient: notified, sees photo/name/credentials and an arrival code, but no biometrics.
    assert any(n["title"] == "Your doctor's identity is verified" for n in patient.get("/api/notifications").json())
    prof = patient.get(f"/api/patient/visits/{vid}/doctor-identity").json()
    assert prof["verified"] and prof["name"] == "Dr. Emily Carter" and prof["license_no"] and prof["medical_council"]
    assert not {"liveness", "match", "template_ref", "frame_digests", "reference"} & set(prof)
    live = patient.get(f"/api/patient/visits/{vid}/live").json()
    assert live["identity"]["verified"] and len(live["identity"]["arrival_code"]) == 4
    assert as_("patient2").get(f"/api/patient/visits/{vid}/doctor-identity").status_code == 404

    # At the door: the patient's code is needed to start the visit.
    wrong = "0000" if live["identity"]["arrival_code"] != "0000" else "1111"
    assert _code(doc.post(f"/api/doctor/visits/{vid}/start", {"arrival_code": wrong})) == "wrong_arrival_code"
    ok = doc.post(f"/api/doctor/visits/{vid}/start", {"arrival_code": live["identity"]["arrival_code"]})
    assert ok.json()["status"] == "in_progress"
    assert patient.get(f"/api/patient/visits/{vid}/live").json()["identity"]["arrival_confirmed"] is True

    # Ops sees the outcome and time, never an image.
    checks = env["client"].get("/api/admin/identity/checks", headers=ADMIN).json()
    assert checks[0]["status"] == "passed" and checks[0]["at"] and "photo" not in checks[0] and "frames" not in str(checks)


def test_no_bypass_without_a_check(env, as_):
    doc, (vid,) = _accepted(env, as_, "meera")
    assert _code(doc.post(f"/api/provider/visits/{vid}/depart")) == "face_check_required"
    assert _code(doc.post(f"/api/doctor/visits/{vid}/start", {"arrival_code": arrival_code(env, vid) or "1234"})) \
        == "face_check_required"
    # A made-up "scenario" from the client is ignored; it can never make a check pass.
    r = face_check(doc, vid, frames=live_frames(move=False), scenario="pass")
    assert r.json()["status"] == "failed"
    assert _code(doc.post(f"/api/provider/visits/{vid}/depart")) == "face_check_required"


def test_production_without_a_real_partner_fails_closed(env, as_, monkeypatch):
    doc, (vid,) = _accepted(env, as_, "meera")
    monkeypatch.setenv("TRIYANA_DEMO", "0")
    r = face_check(doc, vid)
    assert r.status_code == 409 and _code(r) == "face_partner_unavailable"
    assert _code(doc.post(f"/api/provider/visits/{vid}/depart")) == "face_check_required"


# ------------------------------------------------------------------ failures
def test_incorrect_face_is_refused_and_counts_down(env, as_):
    doc, (vid,) = _accepted(env, as_, "meera")
    r = face_check(doc, vid, scenario="other_person").json()
    assert r["status"] == "failed" and r["attempts_left"] == 2 and not r["locked"]
    assert _code(doc.post(f"/api/provider/visits/{vid}/depart")) == "face_check_required"
    face_pass(doc, vid)  # the real doctor can still pass
    assert doc.post(f"/api/provider/visits/{vid}/depart").status_code == 200


def test_printed_photo_is_spoofing_locks_out_and_alerts_security(env, as_):
    doc, (vid, vid2) = _accepted(env, as_, "meera", "arjun")
    r = face_check(doc, vid, scenario="printed_photo").json()
    assert r["status"] == "spoof" and r["locked"] and r["case_id"]
    assert _alerts(env) and _alerts(env)[0]["kind"] == "spoof_suspected" and _alerts(env)[0]["severity"] == "high"
    # Locked everywhere until the security team clears it: no checks, no journeys, can't go online.
    for path, body in ((f"/api/provider/visits/{vid}/depart", None), (f"/api/provider/visits/{vid2}/depart", None),
                       ("/api/provider/face/challenges", {"purpose": "visit", "visit_id": vid2}),
                       ("/api/provider/duty", {"online": True})):
        assert _code(doc.post(path, body)) == "identity_locked", path
    assert as_("patient").get(f"/api/patient/visits/{vid}/live").json()["identity"]["verified"] is False


def test_replay_attempts_are_spoofing(env, as_):
    doc, (vid,) = _accepted(env, as_, "meera")
    frames = live_frames()
    face_check(doc, vid, frames=frames)  # passes once
    replay = face_check(doc, vid, frames=frames).json()  # the same frames again
    assert replay["status"] == "spoof" and replay["locked"]
    assert _case(env, "spoof_suspected")["summary"].lower().count("replay") >= 1


def test_injected_still_image_is_spoofing(env, as_):
    doc, (vid,) = _accepted(env, as_, "meera")
    one = live_frames(n=1)[0]
    assert face_check(doc, vid, frames=[one, one, one]).json()["status"] == "spoof"


def test_screen_replay_video_is_spoofing(env, as_):
    doc, (vid,) = _accepted(env, as_, "meera")
    assert face_check(doc, vid, scenario="replay_video").json()["status"] == "spoof"


def test_poor_lighting_asks_to_retry_without_using_up_attempts(env, as_):
    doc, (vid,) = _accepted(env, as_, "meera")
    dark = face_check(doc, vid, frames=live_frames(brightness=12)).json()
    assert dark["status"] == "poor_quality" and "dark" in dark["reason"] and dark["attempts_left"] == 3
    assert face_check(doc, vid, scenario="poor_lighting").json()["status"] == "poor_quality"
    covered = face_check(doc, vid, frames=_blank_frames()).json()
    assert covered["status"] == "poor_quality" and "can't see a face" in covered["reason"]
    face_pass(doc, vid)


def _blank_frames():
    import base64
    import io

    from PIL import Image
    out = []
    for i in range(4):  # a covered camera: flat grey, each frame a tiny bit different
        img = Image.new("RGB", (160, 120), (100 + i, 100 + i, 100 + i))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        out.append("data:image/png;base64," + base64.b64encode(buf.getvalue()).decode())
    return out


def test_bad_frames_are_rejected(env, as_):
    doc, (vid,) = _accepted(env, as_, "meera")
    r = face_check(doc, vid, frames=["data:image/jpeg;base64,bm90IGFuIGltYWdl"] * 3)
    assert r.status_code == 422 and _code(r) == "bad_frames"


def test_network_interruption_expired_and_reused_challenges(env, as_):
    doc, (vid,) = _accepted(env, as_, "meera")
    ch = doc.post("/api/provider/face/challenges", {"purpose": "visit", "visit_id": vid}).json()
    with env["Session"]() as s:  # the upload never arrived in time
        s.get(FaceCheck, ch["id"]).expires_at = utcnow() - timedelta(seconds=1)
        s.commit()
    r = doc.post(f"/api/provider/face/challenges/{ch['id']}/submit", {"nonce": ch["nonce"], "frames": live_frames()})
    assert r.status_code == 409 and _code(r) == "challenge_expired"
    ch = doc.post("/api/provider/face/challenges", {"purpose": "visit", "visit_id": vid}).json()
    assert _code(doc.post(f"/api/provider/face/challenges/{ch['id']}/submit",
                          {"nonce": "wrong", "frames": live_frames()})) == "bad_challenge"
    ok = doc.post(f"/api/provider/face/challenges/{ch['id']}/submit", {"nonce": ch["nonce"], "frames": live_frames()})
    assert ok.json()["status"] == "passed"
    again = doc.post(f"/api/provider/face/challenges/{ch['id']}/submit", {"nonce": ch["nonce"], "frames": live_frames()})
    assert _code(again) == "challenge_used"


def test_repeated_failures_lock_out_until_ops_allows_retry(env, as_):
    doc, (vid,) = _accepted(env, as_, "meera")
    for left in (2, 1):
        assert face_check(doc, vid, scenario="other_person").json()["attempts_left"] == left
    last = face_check(doc, vid, scenario="other_person").json()
    assert last["locked"] and last["attempts_left"] == 0
    assert _alerts(env)[-1]["kind"] == "repeated_failures"
    assert _code(doc.post("/api/provider/face/challenges", {"purpose": "visit", "visit_id": vid})) == "identity_locked"
    assert doc.get("/api/provider/face").json()["locked"] is True

    case = _case(env, "repeated_failures")
    assert case["recent_checks"][0]["status"] == "failed" and case["provider"]["name"]
    assert _resolve(env, case["id"], "allow_retry", "x").status_code == 422  # a note is required
    assert _resolve(env, case["id"], "allow_retry").json()["status"] == "resolved"
    face_pass(doc, vid)
    assert doc.post(f"/api/provider/visits/{vid}/depart").status_code == 200


# ------------------------------------------------------------------ recovery + alternatives
def test_camera_denied_alternative_check_approved_by_ops_for_one_visit(env, as_):
    doc, (vid, vid2) = _accepted(env, as_, "meera", "arjun")
    r = doc.post("/api/provider/face/alternative", {"visit_id": vid, "reason": "camera_unavailable"})
    assert r.status_code == 201
    # Asking for help doesn't lock or unlock anything by itself.
    assert _code(doc.post(f"/api/provider/visits/{vid}/depart")) == "face_check_required"
    case = _case(env, "alternative_requested")
    assert case["blocking"] is False and case["summary"].startswith("Camera")
    assert _resolve(env, case["id"], "approve_alternative").json()["resolution"] == "approve_alternative"
    assert doc.post(f"/api/provider/visits/{vid}/depart").status_code == 200
    # ...for that visit only.
    assert _code(doc.post(f"/api/provider/visits/{vid2}/depart")) == "face_check_required"
    prof = as_("patient").get(f"/api/patient/visits/{vid}/doctor-identity").json()
    assert prof["verified"] and prof["method"] == "Approved alternative check"


def test_recovery_by_re_enrolment(env, as_):
    doc, (vid,) = _accepted(env, as_, "meera")
    face_check(doc, vid, scenario="printed_photo")
    case = _case(env, "spoof_suspected")
    _resolve(env, case["id"], "require_reenrol", "Asked doctor to re-enrol after a call")
    assert doc.get("/api/provider/face").json()["active"] is False
    assert _code(doc.post("/api/provider/duty", {"online": True})) == "face_enrollment_required"
    assert _code(doc.post("/api/provider/face/challenges", {"purpose": "visit", "visit_id": vid})) \
        == "face_enrollment_required"
    # Re-enrol needs consent, then ops approves the new face.
    assert _code(doc.post("/api/provider/face/challenges", {"purpose": "enroll"})) == "consent_required"
    r = face_check(doc, None, purpose="enroll", consent=True).json()
    assert r["enrollment"]["status"] == "pending_review"
    review = _case(env, "enrollment_review")
    assert review["enrollment"]["photo"].startswith("data:image/jpeg")
    _resolve(env, review["id"], "approve_enrollment", "Matches ID photo on file")
    assert doc.get("/api/provider/face").json()["active"] is True
    face_pass(doc, vid)
    assert doc.post(f"/api/provider/visits/{vid}/depart").status_code == 200


def test_suspend_from_a_case(env, as_):
    doc, (vid,) = _accepted(env, as_, "meera")
    face_check(doc, vid, scenario="replay_video")
    _resolve(env, _case(env, "spoof_suspected")["id"], "suspend", "Confirmed impersonation attempt")
    assert doc.get("/api/provider/status").json()["verification_status"] == "rejected"
    assert doc.post("/api/provider/duty", {"online": True}).status_code == 403


def test_wrong_arrival_codes_lock_and_alert(env, as_):
    doc, (vid,) = _accepted(env, as_, "meera")
    face_pass(doc, vid)
    doc.post(f"/api/provider/visits/{vid}/depart")
    real = arrival_code(env, vid)
    wrong = "0000" if real != "0000" else "1111"
    for _ in range(5):
        r = doc.post(f"/api/doctor/visits/{vid}/start", {"arrival_code": wrong})
    assert _code(r) == "wrong_arrival_code"
    assert _code(doc.post(f"/api/doctor/visits/{vid}/start", {"arrival_code": real})) == "identity_locked"
    assert _alerts(env)[-1]["kind"] == "arrival_code"


def test_withdrawing_biometric_consent_stops_visits(env, as_):
    doc, (vid,) = _accepted(env, as_, "meera")
    r = env["client"].delete("/api/provider/face/enrollment", headers=doc.h)
    assert r.json()["active"] is False and r.json()["enrollment"] is None
    assert _code(doc.post("/api/provider/duty", {"online": True})) == "face_enrollment_required"


# ------------------------------------------------------------------ every visit, every account
def test_every_appointment_needs_its_own_check(env, as_):
    doc, (vid, vid2) = _accepted(env, as_, "meera", "arjun")
    face_pass(doc, vid)
    assert _code(doc.post(f"/api/provider/visits/{vid2}/depart")) == "face_check_required"
    assert doc.post(f"/api/provider/visits/{vid}/depart").status_code == 200
    doc.post(f"/api/doctor/visits/{vid}/start", {"arrival_code": arrival_code(env, vid)})
    doc.post(f"/api/doctor/visits/{vid}/complete")
    face_pass(doc, vid2)
    assert doc.post(f"/api/provider/visits/{vid2}/depart").status_code == 200


def test_a_pass_goes_stale(env, as_):
    doc, (vid,) = _accepted(env, as_, "meera")
    face_pass(doc, vid)
    with env["Session"]() as s:
        for c in s.query(FaceCheck).filter(FaceCheck.visit_id == vid):
            c.completed_at = utcnow() - timedelta(minutes=16)
        s.commit()
    assert _code(doc.post(f"/api/provider/visits/{vid}/depart")) == "face_check_required"


def test_doctor_now_requires_a_check_after_accepting(env, as_):
    patient, carter = as_("patient"), as_("doctor")
    v = patient.post("/api/patient/visits/now", {"reason": "Fever"}).json()
    oid = next(o for o in carter.get("/api/provider/status").json()["offers"] if o["on_demand"])["id"]
    assert carter.post(f"/api/provider/offers/{oid}/accept").json()["trip"] is None
    assert patient.get(f"/api/patient/visits/{v['id']}/live").json()["phase"] == "verifying"
    face_pass(carter, v["id"])
    carter.post(f"/api/provider/visits/{v['id']}/depart")
    assert patient.get(f"/api/patient/visits/{v['id']}/live").json()["phase"] == "on_the_way"


def test_account_switching_cannot_borrow_a_check(env, as_):
    carter, (vid,) = _accepted(env, as_, "meera")
    rohan = as_("doctor_rohan")
    # Another doctor on the same phone can't check in for Carter's visit...
    assert rohan.post("/api/provider/face/challenges", {"purpose": "visit", "visit_id": vid}).status_code == 404
    # ...or finish a challenge Carter started.
    ch = carter.post("/api/provider/face/challenges", {"purpose": "visit", "visit_id": vid}).json()
    r = rohan.post(f"/api/provider/face/challenges/{ch['id']}/submit", {"nonce": ch["nonce"], "frames": live_frames()})
    assert r.status_code == 404
    assert _code(carter.post(f"/api/provider/visits/{vid}/depart")) == "face_check_required"
    # Carter's own pass doesn't let Rohan depart Carter's visit either.
    face_pass(carter, vid)
    assert rohan.post(f"/api/provider/visits/{vid}/depart").status_code == 404
    # Patients and couriers can't use the doctor endpoints at all.
    assert as_("patient").post("/api/provider/face/challenges", {"purpose": "visit", "visit_id": vid}).status_code == 403


def test_unenrolled_doctor_cannot_accept_or_go_online(env, as_):
    from app.models import FaceEnrollment
    with env["Session"]() as s:
        s.query(FaceEnrollment).delete()
        s.commit()
    doc = as_("doctor")
    assert _code(doc.post("/api/provider/duty", {"online": True})) == "face_enrollment_required"
    vid = env["ids"]["visits"]["meera"]
    assert _code(doc.post(f"/api/doctor/visits/{vid}/accept")) == "face_enrollment_required"


def test_admin_identity_endpoints_need_the_key(env):
    c = env["client"]
    for path in ("/api/admin/identity/cases", "/api/admin/identity/checks"):
        assert c.get(path).status_code == 403
        assert c.get(path, headers={"X-Admin-Key": "nope"}).status_code == 403
