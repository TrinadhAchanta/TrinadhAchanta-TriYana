"""Email sign-up / sign-in for patients and providers, with data tied to the account."""
import os

from app.services import accounts


_n = iter(range(10**6))


def _phone():
    return f"98480{next(_n):05d}"


def otp(client, phone):
    r = client.post("/api/auth/otp", json={"phone": phone})
    assert r.status_code == 200, r.text
    return r.json()["demo_code"]


def _patient(client, email="asha.k@example.com", **kw):
    phone = kw.pop("phone", None) or _phone()
    body = {"app": "patient", "name": "Asha Kumar", "email": email, "password": "Secret123", "phone": phone,
            "otp": otp(client, phone), "gender": "female",
            "address": "21 Jasmine Street, Demo City", "date_of_birth": "1992-03-04"} | kw
    return client.post("/api/auth/register", json=body)


def _doctor(client, email="dr.neha@example.com", licence="TSMC-12345"):
    phone = _phone()
    return client.post("/api/auth/register", json={
        "app": "provider", "role": "doctor", "name": "Neha Rao", "email": email, "password": "Secret123",
        "phone": phone, "otp": otp(client, phone),
        "address": "Lake View", "doctor": {"license_no": licence, "medical_council": "Telangana State Medical Council",
                                           "qualification": "MBBS, MD", "specialty": "General Medicine",
                                           "registration_year": 2015}})


def H(token, app):
    return {"Authorization": f"Bearer {token}", "X-Triyana-App": app}


def test_patient_registers_signs_in_and_sees_own_history(env):
    c = env["client"]
    r = _patient(c)
    assert r.status_code == 201, r.text
    first = r.json()["token"]
    assert first.startswith("tys_") and r.json()["account"]["patient"]["address"].startswith("21 Jasmine")
    h = H(first, "patient")
    assert c.post("/api/consents", headers=h, json={"purpose": "care", "granted": True}).status_code in (200, 201)
    slots = c.get("/api/visit-slots", headers=h).json()
    booked = c.post("/api/patient/visits", headers=h, json={"reason": "Cough", "scheduled_for": slots[-1]})
    assert booked.status_code == 201, booked.text

    # Sign out, sign back in on another device: the visit is still there; nobody else sees it.
    assert c.post("/api/auth/logout", headers=h).status_code == 200
    assert c.get("/api/me", headers=h).status_code == 401
    r = c.post("/api/auth/login", json={"app": "patient", "email": "ASHA.K@example.com", "password": "Secret123"})
    assert r.status_code == 200, r.text
    h2 = H(r.json()["token"], "patient")
    visits = c.get("/api/patient/visits", headers=h2).json()
    assert [v["reason"] for v in visits] == ["Cough"]
    meera = c.get("/api/patient/visits", headers=H("demo-patient-meera", "patient")).json()
    assert all(v["reason"] != "Cough" for v in meera)


def test_duplicate_email_wrong_password_and_weak_password(env):
    c = env["client"]
    assert _patient(c).status_code == 201
    assert _patient(c, email="Asha.K@example.com").json()["detail"]["code"] == "email_taken"
    assert _patient(c, email="new@example.com", password="short").json()["detail"]["code"] == "weak_password"
    bad = c.post("/api/auth/login", json={"app": "patient", "email": "asha.k@example.com", "password": "nope12345"})
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "bad_credentials"


def test_apps_keep_their_own_accounts(env):
    c = env["client"]
    assert _patient(c).status_code == 201
    r = c.post("/api/auth/login", json={"app": "provider", "email": "asha.k@example.com", "password": "Secret123"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "wrong_app"


def test_new_doctor_must_be_verified_before_going_online(env):
    c = env["client"]
    r = _doctor(c)
    assert r.status_code == 201, r.text
    acct = r.json()["account"]
    assert acct["verification_status"] == "pending" and acct["doctor"]["license_verified"] is False
    assert acct["name"] == "Dr. Neha Rao"
    h = H(r.json()["token"], "provider")
    st = c.get("/api/provider/status", headers=h).json()
    assert st["verification_status"] == "pending"
    off = c.post("/api/provider/duty", headers=h, json={"online": True})
    assert off.status_code == 403 and off.json()["detail"]["code"] == "not_verified"

    # Triyana's ops team approves the registration (admin key), then the doctor can go online.
    os.environ["TRIYANA_ADMIN_KEY"] = "ops-test-key"
    try:
        assert c.get("/api/admin/providers/pending", headers={"X-Admin-Key": "wrong"}).status_code == 403
        pend = c.get("/api/admin/providers/pending", headers={"X-Admin-Key": "ops-test-key"}).json()
        assert [p["email"] for p in pend] == ["dr.neha@example.com"]
        assert pend[0]["verification"]["stage"] == "needs_documents"
        r = c.post("/api/account/verification/identity", headers=h,
                   json={"id_number": "ABCPR1234F", "date_of_birth": "1988-02-01", "consent": True})
        assert r.json()["stage"] == "ready_for_review", r.text
        ok = c.post(f"/api/admin/providers/{acct['id']}/verification", headers={"X-Admin-Key": "ops-test-key"},
                    json={"status": "verified"})
        assert ok.json()["doctor"]["license_verified"] is True
    finally:
        del os.environ["TRIYANA_ADMIN_KEY"]
    on = c.post("/api/provider/duty", headers=h, json={"online": True})
    assert on.status_code == 200, on.text


def test_demo_self_verify_and_duplicate_licence(env):
    c = env["client"]
    r = _doctor(c)
    assert _doctor(c, email="other@example.com").json()["detail"]["code"] == "licence_taken"
    h = H(r.json()["token"], "provider")
    assert c.post("/api/account/demo-verify", headers=h).json()["verification_status"] == "verified"


def test_courier_signup_pending(env):
    c = env["client"]
    phone = _phone()
    r = c.post("/api/auth/register", json={"app": "provider", "role": "courier", "name": "Ravi Teja",
                                           "email": "ravi@example.com", "password": "Bike2024!", "vehicle": "Bike",
                                           "phone": phone, "otp": otp(c, phone)})
    assert r.status_code == 201, r.text
    h = H(r.json()["token"], "provider")
    assert c.post("/api/provider/duty", headers=h, json={"online": True}).status_code == 403


def test_demo_accounts_still_work_and_unknown_tokens_rejected(env):
    c = env["client"]
    assert c.get("/api/me", headers=H("demo-patient-meera", "patient")).json()["demo"] is True
    # A registered user's internal token column is never a valid bearer token.
    r = _patient(c)
    Session = env["Session"]
    from app.models import User
    with Session() as s:
        internal = s.query(User).filter(User.email == "asha.k@example.com").one().token
    assert c.get("/api/me", headers=H(internal, "patient")).status_code == 401
    assert c.get("/api/me", headers=H("tys_made_up", "patient")).status_code == 401
    assert r.status_code == 201


def test_password_hashing_roundtrip():
    h = accounts.hash_password("Secret123")
    assert "Secret123" not in h
    assert accounts.check_password("Secret123", h) and not accounts.check_password("Secret124", h)


def test_profile_update_moves_patient(env):
    c = env["client"]
    h = H(_patient(c).json()["token"], "patient")
    r = c.patch("/api/account", headers=h, json={"address": "5 New Road, Demo City", "lat": 17.45, "lng": 78.37})
    assert r.json()["patient"]["address"] == "5 New Road, Demo City"
    code = c.post("/api/account/phone/otp", headers=h, json={"phone": "90000 00000"}).json()["demo_code"]
    r = c.post("/api/account/phone", headers=h, json={"phone": "9000000000", "otp": code})
    assert r.json()["phone"] == "+919000000000" and r.json()["phone_verified"] is True


def test_signup_needs_a_verified_phone(env):
    c = env["client"]
    base = {"app": "patient", "name": "Kiran", "email": "kiran@example.com", "password": "Secret123",
            "address": "1 Main Road, Demo City"}
    assert c.post("/api/auth/register", json=base).json()["detail"]["code"] == "phone_required"
    assert c.post("/api/auth/otp", json={"phone": "12345"}).json()["detail"]["code"] == "invalid_phone"
    code = otp(c, "+91 98765 43210")
    # Asking again straight away is throttled.
    assert c.post("/api/auth/otp", json={"phone": "9876543210"}).status_code == 429
    wrong = "000000" if code != "000000" else "111111"
    r = c.post("/api/auth/register", json=base | {"phone": "9876543210", "otp": wrong})
    assert r.json()["detail"]["code"] == "otp_wrong"
    r = c.post("/api/auth/register", json=base | {"phone": "9876543210", "otp": code})
    assert r.status_code == 201, r.text
    acct = r.json()["account"]
    assert acct["phone"] == "+919876543210" and acct["phone_verified"]
    # The code is single use, and the number now belongs to Kiran.
    assert c.post("/api/auth/otp", json={"phone": "9876543210"}).json()["detail"]["code"] == "phone_taken"


def test_phone_normalisation():
    assert accounts.normalize_phone("098480 12345") == "+919848012345"
    assert accounts.normalize_phone("+91-98480-12345") == "+919848012345"
    assert accounts.normalize_phone("+1 415 555 0100") == "+14155550100"


def test_physio_signup_needs_verification(env):
    c = env["client"]
    phone = _phone()
    r = c.post("/api/auth/register", json={
        "app": "provider", "role": "physio", "name": "Lakshmi Iyer", "email": "lakshmi@example.com",
        "password": "Secret123", "phone": phone, "otp": otp(c, phone),
        "doctor": {"license_no": "IAP-L-99881", "medical_council": "Indian Association of Physiotherapists (IAP)",
                   "qualification": "MPT"}})
    assert r.status_code == 201, r.text
    assert r.json()["account"]["physio"]["verified"] is False
    h = H(r.json()["token"], "provider")
    assert c.post("/api/provider/duty", headers=h, json={"online": True}).status_code == 403
    assert c.post("/api/account/demo-verify", headers=h).json()["physio"]["verified"] is True
    assert c.post("/api/provider/duty", headers=h, json={"online": True}).status_code == 200


def test_sign_up_from_any_country(env):
    c = env["client"]
    names = {x["iso"]: x for x in c.get("/api/countries").json()}
    assert len(names) > 200 and names["US"]["dial"] == "+1" and names["IN"]["dial"] == "+91"
    r = c.post("/api/auth/otp", json={"phone": "07400 123456", "country": "GB"})
    assert r.status_code == 200, r.text
    assert r.json()["phone"] == "+447400123456" and r.json()["masked"].startswith("+44 ")
    r2 = c.post("/api/auth/register", json={"app": "patient", "name": "Amelia Jones", "email": "amelia@example.co.uk",
                                            "password": "Secret123", "phone": "+447400123456",
                                            "otp": r.json()["demo_code"], "address": "10 Baker Street, London"})
    assert r2.status_code == 201, r2.text
    assert r2.json()["account"]["phone"] == "+447400123456"
    bad = c.post("/api/auth/otp", json={"phone": "12345", "country": "US"})
    assert bad.json()["detail"]["code"] == "invalid_phone" and "United States" in bad.json()["detail"]["message"]


def test_other_country_numbers():
    assert accounts.normalize_phone("050 123 4567", "AE") == "+971501234567"
    assert accounts.normalize_phone("2015550123", "US") == "+12015550123"
    assert accounts.normalize_phone("+14155550100", "IN") == "+14155550100"  # an explicit + wins
