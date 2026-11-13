"""Provider verification: HPR registry lookup + IDfy ID / court-record checks, then ops final review."""
import os

import pytest

from app.adapters import verification as partners
from tests.test_accounts import H, _doctor, _phone, enrol, otp

ADMIN = {"X-Admin-Key": "demo-admin"}


@pytest.fixture(autouse=True)
def _no_admin_key(monkeypatch):
    monkeypatch.delenv("TRIYANA_ADMIN_KEY", raising=False)
    monkeypatch.setenv("TRIYANA_DEMO", "1")


def _id(c, h, number="ABCPR1234F", **kw):
    return c.post("/api/account/verification/identity", headers=h,
                  json={"id_number": number, "date_of_birth": "1988-02-01", "consent": True} | kw)


def test_registry_lookup_runs_at_signup_and_ops_approve_after_checks(env):
    c = env["client"]
    r = _doctor(c)
    h = H(r.json()["token"], "provider")
    v = c.get("/api/account/verification", headers=h).json()
    assert v["stage"] == "needs_documents" and v["id_types"] == ["pan"]
    reg = v["checks"][0]
    assert reg["kind"] == "registry" and reg["status"] == "passed" and reg["partner"] == "Demo partner"

    assert _id(c, h, consent=False).json()["detail"]["code"] == "consent_required"
    assert _id(c, h, number="12345").json()["detail"]["code"] == "invalid_id"
    v = _id(c, h).json()
    assert v["stage"] == "needs_documents" and not v["id_needed"] and v["face_needed"]
    enrol(c, h)
    v = c.get("/api/account/verification", headers=h).json()
    assert v["stage"] == "ready_for_review" and not v["face_needed"]
    assert all(ch["status"] == "passed" for ch in v["checks"])
    # Only a masked ID is kept.
    assert v["checks"][1]["details"]["id_masked"].endswith("234F") and "ABCPR" not in str(v)
    assert _id(c, h).json()["detail"]["code"] == "already_submitted"

    pend = c.get("/api/admin/providers/pending", headers=ADMIN).json()
    assert pend[0]["verification"]["stage"] == "ready_for_review"
    ok = c.post(f"/api/admin/providers/{pend[0]['id']}/verification", headers=ADMIN, json={"status": "verified"})
    assert ok.status_code == 200 and ok.json()["doctor"]["license_verified"] is True
    assert c.post("/api/provider/duty", headers=h, json={"online": True}).status_code == 200


def test_failed_registry_needs_override_with_note(env):
    c = env["client"]
    r = _doctor(c, licence="TSMC-FAIL-1")
    h, uid = H(r.json()["token"], "provider"), r.json()["account"]["id"]
    _id(c, h)
    enrol(c, h)
    v = c.get("/api/account/verification", headers=h).json()
    assert v["stage"] == "flagged" and v["checks"][0]["status"] == "failed"
    url = f"/api/admin/providers/{uid}/verification"
    assert c.post(url, headers=ADMIN, json={"status": "verified"}).json()["detail"]["code"] == "checks_incomplete"
    assert c.post(url, headers=ADMIN, json={"status": "verified", "override": True}).status_code == 422
    ok = c.post(url, headers=ADMIN, json={"status": "verified", "override": True,
                                          "note": "Checked TSMC register by phone"})
    assert ok.json()["verification_status"] == "verified"
    assert ok.json()["verification_note"].startswith("Override:")
    # Rejecting never needs the checks.
    assert c.post(url, headers=ADMIN, json={"status": "rejected", "note": "x"}).status_code == 200


def test_name_mismatch_and_court_record_are_flagged(env):
    c = env["client"]
    r = _doctor(c, licence="TSMC-MISMATCH-2")
    h = H(r.json()["token"], "provider")
    enrol(c, h)
    v = _id(c, h, number="ABCPR9999F").json()
    assert v["stage"] == "flagged"
    assert [ch["status"] for ch in v["checks"]] == ["needs_review", "passed", "needs_review", "passed"]


def test_rider_uses_driving_licence_and_has_no_registry_check(env):
    c = env["client"]
    phone = _phone()
    r = c.post("/api/auth/register", json={"app": "provider", "role": "courier", "name": "Ravi Teja",
                                           "email": "ravi@example.com", "password": "Secret123", "phone": phone,
                                           "otp": otp(c, phone)})
    h = H(r.json()["token"], "provider")
    v = c.get("/api/account/verification", headers=h).json()
    assert [ch["kind"] for ch in v["checks"]] == ["identity", "background"]
    assert "driving_licence" in v["id_types"]
    v = _id(c, h, id_type="driving_licence", number="TS09 2019 0012345").json()
    assert v["stage"] == "ready_for_review"


def test_admin_key_rules(env, monkeypatch):
    c = env["client"]
    assert c.get("/api/admin/providers/pending", headers=ADMIN).status_code == 200
    monkeypatch.setenv("TRIYANA_ADMIN_KEY", "real-key")
    assert c.get("/api/admin/providers/pending", headers=ADMIN).status_code == 403
    monkeypatch.delenv("TRIYANA_ADMIN_KEY")
    monkeypatch.setenv("TRIYANA_DEMO", "0")
    assert c.get("/api/admin/providers/pending", headers=ADMIN).status_code == 403


def test_partner_outage_is_recorded_as_error_and_rerun(env, monkeypatch):
    c = env["client"]

    def down(*a, **k):
        raise partners.PartnerError("The HPR registry could not be reached")
    monkeypatch.setattr(partners, "lookup_registration", down)
    r = _doctor(c)
    uid, h = r.json()["account"]["id"], H(r.json()["token"], "provider")
    _id(c, h)
    enrol(c, h)
    v = c.get("/api/account/verification", headers=h).json()
    assert v["stage"] == "checking" and v["checks"][0]["status"] == "error"
    monkeypatch.undo()
    os.environ["TRIYANA_DEMO"] = "1"
    v = c.post(f"/api/admin/providers/{uid}/checks/rerun", headers=ADMIN).json()
    assert v["stage"] == "ready_for_review"


def test_idfy_async_results_are_polled(env, monkeypatch):
    c = env["client"]
    r = _doctor(c)
    h = H(r.json()["token"], "provider")
    monkeypatch.setenv("TRIYANA_BACKGROUND_PROVIDER", "idfy")
    monkeypatch.setenv("IDFY_ACCOUNT_ID", "acc")
    monkeypatch.setenv("IDFY_API_KEY", "key")
    monkeypatch.setenv("IDFY_COURT_TASK", "ind_court_record")
    started = []

    def fake_start(path, data, details, summary):
        started.append(path)
        return partners.Result("in_progress", summary, f"req-{len(started)}", details)
    monkeypatch.setattr(partners, "_idfy_start", fake_start)
    enrol(c, h)
    v = _id(c, h).json()
    assert v["stage"] == "checking" and started[0].endswith("/verify_with_source/ind_pan")

    def fake_poll(kind, ref):
        return partners.Result("passed", "ok", ref)
    monkeypatch.setattr(partners, "poll", fake_poll)
    assert c.get("/api/account/verification", headers=h).json()["stage"] == "ready_for_review"


def test_names_match():
    assert partners.names_match("Dr. Neha Rao", "NEHA RAO")
    assert partners.names_match("Dr. N Rao", "Neha Rao")
    assert not partners.names_match("Neha Rao", "Someone Else")


def test_newly_approved_doctor_gets_doctor_now_and_booked_requests(env):
    """A doctor who signs up, is approved and goes online receives patients' requests."""
    from tests.test_accounts import _patient
    c = env["client"]
    r = _doctor(c)
    h = H(r.json()["token"], "provider")
    _id(c, h)
    enrol(c, h)
    uid = r.json()["account"]["id"]
    assert c.post(f"/api/admin/providers/{uid}/verification", headers=ADMIN, json={"status": "verified"}).status_code == 200
    assert c.post("/api/provider/duty", headers=h, json={"online": True}).json()["online"] is True
    ph = H(_patient(c, email="new.patient@example.com").json()["token"], "patient")
    c.post("/api/consents", headers=ph, json={"purpose": "care", "granted": True})
    me = next(d for d in c.get("/api/doctors", headers=ph).json()["doctors"] if d["name"] == "Dr. Neha Rao")
    slot = c.get(f"/api/visit-slots?doctor_id={me['id']}", headers=ph).json()[0]
    v = c.post("/api/patient/visits", headers=ph, json={"doctor_id": me["id"], "scheduled_for": slot, "reason": "Fever"})
    assert v.status_code == 201, v.text
    offers = c.get("/api/provider/status", headers=h).json()["offers"]
    assert [o["visit_id"] for o in offers] == [v.json()["id"]]
