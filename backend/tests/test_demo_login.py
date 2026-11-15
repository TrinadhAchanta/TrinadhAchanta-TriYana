"""One shared demo login (TRIYANA_DEMO_LOGIN) opens every app on the demo site, and nothing in live mode."""
import pytest

from app.models import AdminAccount
from app.services import admins

EMAIL, PASSWORD = "demo@triyana.app", "shared-demo-42"


@pytest.fixture()
def shared(monkeypatch):
    monkeypatch.setenv("TRIYANA_DEMO_LOGIN", f"{EMAIL}:{PASSWORD}")
    monkeypatch.setenv("TRIYANA_DEMO", "1")


def login(c, app, email=EMAIL, password=PASSWORD):
    return c.post("/api/auth/login", json={"app": app, "email": email, "password": password})


def me(c, token, app):
    return c.get("/api/me", headers={"Authorization": f"Bearer {token}", "X-Triyana-App": app})


@pytest.mark.parametrize("app,role,token", [
    ("patient", "patient", "demo-patient-meera"),
    ("provider", "doctor", "demo-doctor-carter"),
    ("pharmacy", "pharmacist", "demo-pharmacist-greenleaf"),
    ("rider", "courier", "demo-courier-greenleaf"),
])
def test_one_login_opens_each_app_as_its_demo_person(env, shared, app, role, token):
    c = env["client"]
    r = login(c, app, email=EMAIL.upper())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["demo_login"] is True and body["token"] == token
    m = me(c, body["token"], app)
    assert m.status_code == 200 and m.json()["role"] == role


def test_wrong_password_and_sign_up_with_it_are_refused(env, shared):
    c = env["client"]
    r = login(c, "patient", password="not-the-one-1")
    assert r.status_code >= 400 and r.json()["detail"]["code"] == "bad_credentials"
    r = c.post("/api/auth/register", json={"app": "patient", "name": "Someone", "email": EMAIL, "password": "abcdefg12",
                                          "phone": "+919848012345", "otp": "123456", "address": "12 Some Street"})
    assert r.json()["detail"]["code"] == "email_taken"


def test_demo_login_also_opens_admin_in_demo_mode(env, shared):
    c = env["client"]
    with env["Session"]() as s:
        admins.seed_from_env(s, "")
    r = c.post("/api/admin/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200, r.text
    assert r.json()["demo_login"] is True
    tok = r.json()["token"]
    assert c.get("/api/admin/providers/pending", headers={"Authorization": f"Bearer {tok}"}).status_code == 200
    # Its password lives in the env var, so it can't be changed from /admin.
    r = c.post("/api/admin/password", headers={"Authorization": f"Bearer {tok}"},
               json={"current_password": PASSWORD, "new_password": "something-new-9"})
    assert r.status_code == 403


def test_nothing_works_in_live_mode(env, shared, monkeypatch):
    c = env["client"]
    with env["Session"]() as s:
        admins.seed_from_env(s, "")
    tok = c.post("/api/admin/login", json={"email": EMAIL, "password": PASSWORD}).json()["token"]
    monkeypatch.setenv("TRIYANA_DEMO", "0")
    # Even a session opened in demo mode stops working at once.
    assert c.get("/api/admin/providers/pending", headers={"Authorization": f"Bearer {tok}"}).status_code in (401, 403)
    assert c.post("/api/admin/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 403
    r = login(c, "patient")
    assert r.status_code >= 400 and r.json()["detail"]["code"] == "no_account"
    # And at the next startup the demo admin is switched off for good.
    with env["Session"]() as s:
        admins.seed_from_env(s, "")
        assert s.query(AdminAccount).filter_by(email=EMAIL).one().active is False


def test_off_when_env_var_missing(env, monkeypatch):
    monkeypatch.delenv("TRIYANA_DEMO_LOGIN", raising=False)
    r = login(env["client"], "patient")
    assert r.json()["detail"]["code"] == "no_account"
