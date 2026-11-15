"""Separate Triyana Ops logins: each admin has their own email + password; the shared key only bootstraps."""
from app.models import AdminAccount, AuditLog
from app.services import admins

KEY = {"X-Admin-Key": "demo-admin"}


def B(token):
    return {"Authorization": f"Bearer {token}"}


def login(c, email, password):
    return c.post("/api/admin/login", json={"email": email, "password": password})


def test_first_admin_with_key_then_key_stops_working(env):
    c = env["client"]
    assert c.get("/api/admin/setup").json()["needs_first_admin"] is True
    # Before any admin exists, the shared key opens /admin so the first admin can be created.
    r = c.post("/api/admin/admins", headers=KEY, json={"name": "Tri", "email": "Tri@Example.com", "password": "triyana-1"})
    assert r.status_code == 201, r.text
    assert r.json()["email"] == "tri@example.com" and r.json()["created_by"] == "admin key"
    assert c.get("/api/admin/setup").json()["needs_first_admin"] is False
    # Now the key alone is refused everywhere.
    r = c.get("/api/admin/providers/pending", headers=KEY)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "use_admin_login"
    assert c.get("/api/admin/providers/pending").status_code == 403
    # Tri signs in with their own login.
    assert login(c, "tri@example.com", "wrong-pass1").status_code == 403
    tok = login(c, "tri@example.com", "triyana-1").json()["token"]
    assert c.get("/api/admin/providers/pending", headers=B(tok)).status_code == 200
    assert c.get("/api/admin/me", headers=B(tok)).json()["admin"]["name"] == "Tri"


def test_two_admins_add_remove_and_audit(env):
    c = env["client"]
    c.post("/api/admin/admins", headers=KEY, json={"name": "Tri", "email": "tri@example.com", "password": "triyana-1"})
    tri = login(c, "tri@example.com", "triyana-1").json()["token"]
    r = c.post("/api/admin/admins", headers=B(tri), json={"name": "Ravi", "email": "ravi@example.com", "password": "short"})
    assert r.json()["detail"]["code"] == "weak_password"
    r = c.post("/api/admin/admins", headers=B(tri), json={"name": "Ravi", "email": "ravi@example.com", "password": "partner-22"})
    assert r.status_code == 201 and r.json()["created_by"] == "tri@example.com"
    ravi_id = r.json()["id"]
    dup = c.post("/api/admin/admins", headers=B(tri), json={"email": "ravi@example.com", "password": "partner-22"})
    assert dup.json()["detail"]["code"] == "admin_exists"
    ravi = login(c, "ravi@example.com", "partner-22").json()["token"]
    assert {a["email"] for a in c.get("/api/admin/admins", headers=B(ravi)).json()} == {"tri@example.com", "ravi@example.com"}

    # Approvals record which admin made them.
    with env["Session"]() as s:
        from app.models import User
        doc = s.query(User).filter(User.verification_status == "verified", User.doctor_id.isnot(None)).first()
        doc_id = doc.id
    r = c.post(f"/api/admin/providers/{doc_id}/verification", headers=B(ravi), json={"status": "pending", "note": "recheck"})
    assert r.status_code == 200, r.text
    with env["Session"]() as s:
        log = s.query(AuditLog).filter(AuditLog.action == "provider.verification.pending").order_by(AuditLog.id.desc()).first()
        assert log.details["by"] == "ravi@example.com"

    # Nobody can remove themselves; removing someone signs them out at once.
    assert c.post(f"/api/admin/admins/{ravi_id}/remove", headers=B(ravi)).json()["detail"]["code"] == "cannot_remove_self"
    assert c.post(f"/api/admin/admins/{ravi_id}/remove", headers=B(tri)).status_code == 200
    r = c.get("/api/admin/providers/pending", headers=B(ravi))
    assert r.status_code == 401 and r.json()["detail"]["code"] == "admin_signed_out"
    assert login(c, "ravi@example.com", "partner-22").status_code == 403
    # Tri is now the only admin and can't be removed by anyone.
    tri_id = c.get("/api/admin/me", headers=B(tri)).json()["admin"]["id"]
    assert c.post(f"/api/admin/admins/{tri_id}/remove", headers=B(tri)).status_code == 409
    # Removed admins can be added back.
    r = c.post("/api/admin/admins", headers=B(tri), json={"name": "Ravi", "email": "ravi@example.com", "password": "partner-33"})
    assert r.status_code == 201 and login(c, "ravi@example.com", "partner-33").status_code == 200


def test_change_password_signs_out_other_browsers(env):
    c = env["client"]
    c.post("/api/admin/admins", headers=KEY, json={"email": "tri@example.com", "password": "triyana-1"})
    a = login(c, "tri@example.com", "triyana-1").json()["token"]
    b = login(c, "tri@example.com", "triyana-1").json()["token"]
    r = c.post("/api/admin/password", headers=B(a), json={"current_password": "triyana-1", "new_password": "triyana-2"})
    assert r.status_code == 200, r.text
    assert c.get("/api/admin/me", headers=B(a)).status_code == 200
    assert c.get("/api/admin/me", headers=B(b)).status_code == 401
    assert login(c, "tri@example.com", "triyana-2").status_code == 200
    c.post("/api/admin/logout", headers=B(a))
    assert c.get("/api/admin/me", headers=B(a)).status_code == 401


def test_env_seeding_survives_a_wiped_database_and_resets_passwords(env):
    c = env["client"]
    raw = "tri@example.com:first:pass,1 ;\n partner@example.com:Partner-pass9"
    with env["Session"]() as s:
        assert sorted(admins.seed_from_env(s, raw)) == ["partner@example.com", "tri@example.com"]
        assert admins.seed_from_env(s, raw) == []  # nothing changes on the next start
    assert c.get("/api/admin/setup").json()["needs_first_admin"] is False
    assert login(c, "tri@example.com", "first:pass,1").status_code == 200
    tok = login(c, "partner@example.com", "Partner-pass9").json()["token"]
    # A password changed in the app is kept across restarts while the env var is unchanged...
    c.post("/api/admin/password", headers=B(tok), json={"current_password": "Partner-pass9", "new_password": "mine-123"})
    with env["Session"]() as s:
        admins.seed_from_env(s, raw)
    assert login(c, "partner@example.com", "mine-123").status_code == 200
    # ...and changing the env var resets it (the way back in after a forgotten password).
    with env["Session"]() as s:
        assert admins.seed_from_env(s, raw.replace("Partner-pass9", "Reset-pass9")) == ["partner@example.com"]
    assert login(c, "partner@example.com", "Reset-pass9").status_code == 200
    # A typo never stops the app from starting.
    with env["Session"]() as s:
        assert admins.seed_from_env(s, "no-colon-here") == []
        assert s.query(AdminAccount).count() == 2


def test_patient_and_provider_tokens_cannot_open_admin(env):
    c = env["client"]
    c.post("/api/admin/admins", headers=KEY, json={"email": "tri@example.com", "password": "triyana-1"})
    r = c.get("/api/admin/providers/pending", headers=B("demo-doctor-carter"))
    assert r.status_code == 401
