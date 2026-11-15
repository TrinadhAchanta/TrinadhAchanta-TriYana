"""Triyana Pharmacy (/pharmacy) and Triyana Rider (/rider): one-job apps split out of Heros."""
from app import config
from test_accounts import H, _phone, otp


def test_pages_and_manifests_carry_their_own_name_and_icon(env):
    c = env["client"]
    for app_id in ("pharmacy", "rider"):
        ra = config.ROLE_APPS[app_id]
        page = c.get(f"/{app_id}").text
        assert f"<title>{ra['name']}</title>" in page
        assert f'href="/{app_id}.webmanifest"' in page and f"/static/icons/{app_id}-192.png" in page
        assert f'data-role-app="{app_id}"' in page and "__APP_" not in page and "__PROVIDER_APP" not in page
        m = c.get(f"/{app_id}.webmanifest")
        assert m.headers["content-type"].startswith("application/manifest+json")
        m = m.json()
        assert m["name"] == ra["name"] and m["short_name"] == ra["short"]
        assert m["start_url"] == f"/{app_id}" and m["scope"] == f"/{app_id}"
        assert c.get(m["icons"][0]["src"]).status_code == 200
    heros = c.get("/provider").text
    assert 'data-role-app=""' in heros and 'href="/pharmacy"' in heros and 'href="/rider"' in heros
    assert c.get("/provider.webmanifest").json()["start_url"] == "/provider"


def test_demo_accounts_are_only_that_apps_people(env):
    c = env["client"]
    ph = c.get("/api/demo/accounts?app=pharmacy").json()
    rd = c.get("/api/demo/accounts?app=rider").json()
    assert {a["key"] for a in ph} == {"pharmacist", "pharmacist2"}
    assert {a["key"] for a in rd} == {"courier", "courier2"}


def test_each_app_signs_in_only_its_own_role(env):
    c = env["client"]
    ravi, asha, carter = "demo-pharmacist-greenleaf", "demo-courier-greenleaf", "demo-doctor-carter"
    assert c.get("/api/me", headers=H(ravi, "pharmacy")).status_code == 200
    assert c.get("/api/me", headers=H(asha, "rider")).status_code == 200
    for tok, app in ((asha, "pharmacy"), (ravi, "rider"), (carter, "pharmacy"), (carter, "rider"),
                     ("demo-patient-meera", "rider")):
        r = c.get("/api/me", headers=H(tok, app))
        assert r.status_code == 403 and r.json()["detail"]["code"] == "wrong_app", (tok, app)
    # Heros still takes everyone it took before.
    for tok in (ravi, asha, carter):
        assert c.get("/api/me", headers=H(tok, "provider")).status_code == 200
    # The rider's job screens work through the Rider app.
    assert c.get("/api/provider/status", headers=H(asha, "rider")).status_code == 200
    assert c.get("/api/pharmacy/orders", headers=H(ravi, "pharmacy")).status_code == 200


def _register(c, app, **kw):
    phone = _phone()
    body = {"app": app, "name": kw.pop("name", "Kiran Das"), "email": kw.pop("email"), "password": "Secret123",
            "phone": phone, "otp": otp(c, phone)} | kw
    return c.post("/api/auth/register", json=body)


def test_rider_signs_up_in_rider_app_and_email_login_is_app_checked(env):
    c = env["client"]
    r = _register(c, "rider", email="kiran.rider@example.com", role="doctor", vehicle="Scooter")
    assert r.status_code == 201, r.text
    assert r.json()["account"]["role"] == "courier"  # the Rider app only signs up riders
    assert r.json()["account"]["verification_status"] == "pending"
    ok = c.post("/api/auth/login", json={"app": "rider", "email": "kiran.rider@example.com", "password": "Secret123"})
    assert ok.status_code == 200
    assert c.post("/api/auth/login", json={"app": "provider", "email": "kiran.rider@example.com",
                                           "password": "Secret123"}).status_code == 200
    bad = c.post("/api/auth/login", json={"app": "pharmacy", "email": "kiran.rider@example.com", "password": "Secret123"})
    assert bad.status_code == 403 and "Triyana Pharmacy" in bad.json()["detail"]["message"]


def test_new_pharmacy_signs_up_and_is_listed_once_approved(env, as_, signed_rx):
    c = env["client"]
    bad = _register(c, "pharmacy", email="owner@example.com", address="Shop 4, Lake View Road",
                    pharmacy={"name": "Lake View Medicals", "license_no": "X"})
    assert bad.json()["detail"]["code"] == "registration_required"
    r = _register(c, "pharmacy", name="Sita Rao", email="owner@example.com", address="Shop 4, Lake View Road",
                  pharmacy={"name": "Lake View Medicals", "license_no": "TS/HYD/2024/20-1234", "gstin": None})
    assert r.status_code == 201, r.text
    acct, token = r.json()["account"], r.json()["token"]
    assert acct["role"] == "pharmacist" and acct["verification_status"] == "pending"
    assert acct["pharmacy"]["name"] == "Lake View Medicals" and acct["pharmacy"]["license_verified"] is False
    dup = _register(c, "pharmacy", email="other@example.com", address="Shop 9, Ring Road",
                    pharmacy={"name": "Copy Cat", "license_no": "ts/hyd/2024/20-1234"})
    assert dup.json()["detail"]["code"] == "licence_taken"

    patient = as_("patient")
    names = lambda: {p["name"] for p in patient.get(f"/api/carts/{signed_rx['cart_id']}/pharmacies").json()["pharmacies"]}
    assert "Lake View Medicals" not in names()  # unverified pharmacies are never shown
    assert c.post("/api/account/demo-verify", headers=H(token, "pharmacy")).status_code == 200
    assert "Lake View Medicals" in names()
    assert c.get("/api/pharmacy/orders", headers=H(token, "pharmacy")).json() == []

    # A patient can now order from it, and the order lands in the new pharmacy's queue.
    with env["Session"]() as db:
        from app.models import Pharmacy
        ph_id = db.query(Pharmacy).filter(Pharmacy.name == "Lake View Medicals").one().id
    order = patient.post(f"/api/carts/{signed_rx['cart_id']}/checkout", {
        "pharmacy_id": ph_id, "fulfillment": "delivery", "delivery_option": "standard",
        "payment_method": "upi", "payment_token": "sandbox-ok", "idempotency_key": "lake-view-1"})
    assert order.status_code == 201, order.text
    queue = c.get("/api/pharmacy/orders", headers=H(token, "pharmacy")).json()
    assert [o["id"] for o in queue] == [order.json()["id"]]
