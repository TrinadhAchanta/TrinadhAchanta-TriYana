"""Getting ready for real patients: live mode, forgot password and push alerts."""
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app import config, security
from app.services import accounts, push
from tests.test_accounts import H, _doctor, _patient

STRONG = "x7Qe-9fLm2Rk_ZpV4tYh8NcB1sWdJ6uGa3oE5iTq0xKv"


# ------------------------------------------------------------------ live mode
def test_live_mode_refuses_to_start_without_a_strong_secret(monkeypatch):
    monkeypatch.setenv("TRIYANA_DEMO", "0")
    monkeypatch.delenv("TRIYANA_SECRET", raising=False)
    with pytest.raises(config.UnsafeConfig, match="TRIYANA_SECRET"):
        config.check_startup()
    monkeypatch.setenv("TRIYANA_SECRET", "short-and-weak")
    with pytest.raises(config.UnsafeConfig):
        config.check_startup()
    monkeypatch.setenv("TRIYANA_SECRET", STRONG)
    config.check_startup()  # the other gaps (SMS, payments...) only warn
    monkeypatch.setenv("TRIYANA_DEMO", "1")
    monkeypatch.delenv("TRIYANA_SECRET")
    config.check_startup()  # the demo still starts with the default secret


def test_live_mode_switches_off_every_demo_shortcut(env, monkeypatch):
    c = env["client"]
    reg = _patient(c, email="live.one@example.com")  # sign up while it's still the demo
    assert reg.status_code == 201
    monkeypatch.setenv("TRIYANA_DEMO", "0")
    assert c.get("/api/health").json()["mode"] == "live"
    assert c.get("/api/demo/accounts").status_code == 404
    assert c.post("/api/demo/reset").status_code == 404
    # The built-in demo personas' fixed tokens stop signing anyone in.
    assert c.get("/api/me", headers={"Authorization": "Bearer " + env["ids"]["tokens"]["doctor"]}).status_code == 401
    # Real accounts keep working; SMS codes are never shown on screen.
    assert c.get("/api/me", headers=H(reg.json()["token"], "patient")).status_code == 200
    r = c.post("/api/auth/otp", json={"phone": "9848099991"})
    assert r.status_code == 200 and "demo_code" not in r.json()
    with env["Session"]() as db:
        assert accounts.retire_demo_people(db) > 0
        db.commit()
    from app.models import Doctor
    with env["Session"]() as db:
        assert not any(d.license_verified for d in db.query(Doctor).all())


def test_live_mode_hides_approve_me(env, monkeypatch):
    c = env["client"]
    tok = _doctor(c, email="dr.approve@example.com").json()["token"]
    monkeypatch.setenv("TRIYANA_DEMO", "0")
    assert c.post("/api/account/demo-verify", headers=H(tok, "provider")).status_code == 404


def test_old_secret_still_decrypts_and_verifies_after_rotation(monkeypatch):
    from cryptography.fernet import Fernet, MultiFernet
    import base64
    old = Fernet(base64.urlsafe_b64encode(security._derive("phi-encryption", "the-old-secret")))
    token = old.encrypt(b"BP 120/80").decode()
    sig = security.sign_prescription("TSMC-1", "abc", "the-old-secret")
    new = Fernet(base64.urlsafe_b64encode(security._derive("phi-encryption", STRONG)))
    monkeypatch.setattr(security, "_fernet", MultiFernet([new, old]))
    monkeypatch.setattr(security, "_ALL_SECRETS", [STRONG, "the-old-secret"])
    assert security.EncryptedText().process_result_value(token, None) == "BP 120/80"
    assert security.verify_prescription_signature("TSMC-1", "abc", sig)
    assert not security.verify_prescription_signature("TSMC-1", "abd", sig)


def test_admin_launch_check(env):
    c = env["client"]
    key = {"X-Admin-Key": "demo-admin"}
    r = c.get("/api/admin/launch-check", headers=key)
    assert r.status_code == 200
    checks = {x["key"]: x for x in r.json()["checks"]}
    assert checks["secret"]["blocking"] and "sms" in checks and "payments" in checks
    assert c.get("/api/admin/launch-check").status_code == 403


# ------------------------------------------------------------- forgot password
def _forgot(c, email, app="patient", env=None):
    if env:  # sign-up just texted this phone; let the 30-second resend wait pass
        from datetime import timedelta
        from app.models import PhoneOtp
        with env["Session"]() as db:
            for o in db.query(PhoneOtp).all():
                o.created_at -= timedelta(minutes=2)
            db.commit()
    return c.post("/api/auth/password/forgot", json={"app": app, "email": email})


def _reset(c, email, code, pw="NewSecret456", app="patient"):
    return c.post("/api/auth/password/reset", json={"app": app, "email": email, "otp": code, "new_password": pw})


@pytest.mark.parametrize("app", ["patient", "provider"])
def test_forgot_password_by_sms_code(env, app):
    c = env["client"]
    email = f"forgot.{app}@example.com"
    reg = _patient(c, email=email) if app == "patient" else _doctor(c, email=email, licence="TSMC-77" + app[:2])
    old_token = reg.json()["token"]
    r = _forgot(c, email.upper(), app, env)
    assert r.status_code == 200, r.text
    assert r.json()["masked"].endswith(reg.json()["account"]["phone"][-4:]) and "phone" not in r.json()
    code = r.json()["demo_code"]
    assert _reset(c, email, "000000" if code != "000000" else "111111", app=app).json()["detail"]["code"] == "otp_wrong"
    assert _reset(c, email, code, pw="short", app=app).json()["detail"]["code"] == "weak_password"
    r = _reset(c, email, code, app=app)
    assert r.status_code == 200, r.text
    assert c.get("/api/me", headers=H(r.json()["token"], app)).status_code == 200
    # Every other device is signed out, the code can't be reused, and only the new password works.
    assert c.get("/api/me", headers=H(old_token, app)).status_code == 401
    assert _reset(c, email, code, app=app).status_code == 422
    assert c.post("/api/auth/login", json={"app": app, "email": email, "password": "Secret123"}).status_code == 400
    assert c.post("/api/auth/login", json={"app": app, "email": email, "password": "NewSecret456"}).status_code == 200
    notes = c.get("/api/notifications", headers=H(r.json()["token"], app)).json()
    assert notes[0]["title"] == "Your password was changed"


def test_forgot_password_wrong_app_unknown_email_and_demo_accounts(env):
    c = env["client"]
    _patient(c, email="only.patient@example.com")
    assert _forgot(c, "only.patient@example.com", "provider").json()["detail"]["code"] == "wrong_app"
    assert _forgot(c, "nobody@example.com").json()["detail"]["code"] == "no_account"
    assert _reset(c, "nobody@example.com", "123456").json()["detail"]["code"] == "no_account"


def test_reset_guesses_are_limited(env):
    c = env["client"]
    _patient(c, email="guess@example.com")
    _forgot(c, "guess@example.com", env=env)
    codes = [_reset(c, "guess@example.com", f"{i:06d}").json()["detail"]["code"] for i in range(9)]
    assert "otp_locked" in codes or "too_many_attempts" in codes


# ------------------------------------------------------------------ push alerts
FCM = "https://fcm.googleapis.com/fcm/send/abc123"


def _device():
    """A fake phone: its own P-256 key pair and auth secret, like a browser's PushSubscription."""
    key = ec.generate_private_key(ec.SECP256R1())
    pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = b"0123456789abcdef"
    return key, {"p256dh": push.b64u(pub), "auth": push.b64u(auth)}


def _decrypt(key, keys, body: bytes) -> dict:
    """What the phone does with the push body (RFC 8291), written independently of the server code."""
    import hashlib, hmac as h
    salt, rs, idlen = body[:16], body[16:20], body[20]
    as_public = body[21:21 + idlen]
    shared = key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public))
    ua_public = push.b64u_dec(keys["p256dh"])
    mac = lambda k, d: h.new(k, d, hashlib.sha256).digest()  # noqa: E731
    ikm = mac(mac(push.b64u_dec(keys["auth"]), shared), b"WebPush: info\x00" + ua_public + as_public + b"\x01")
    prk = mac(salt, ikm)
    plain = AESGCM(mac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]).decrypt(
        mac(prk, b"Content-Encoding: nonce\x00\x01")[:12], body[21 + idlen:], None)
    assert plain.endswith(b"\x02")
    return json.loads(plain[:-1])


@pytest.fixture()
def sent(monkeypatch):
    out = []

    class Resp:
        status_code = 201
        text = ""

    def fake_post(url, content, headers, timeout):
        out.append({"url": url, "body": content, "headers": headers})
        return Resp()

    monkeypatch.setattr(push, "_submit", lambda fn, *a: fn(*a))
    monkeypatch.setattr(push.httpx, "post", fake_post)
    return out


def test_doctor_gets_new_request_pushed_to_locked_phone(env, as_, sent):
    doc = as_("doctor")
    key, keys = _device()
    assert doc.c.get("/api/push/key").json()["public_key"] == push.public_key()
    r = doc.post("/api/push/subscribe", {"endpoint": FCM, "keys": keys})
    assert r.status_code == 200 and r.json()["devices"] == 1
    # Patient asks for a doctor now: the nearest online doctor gets the offer as a push.
    assert doc.post("/api/provider/duty", {"online": True}).status_code == 200
    r = as_("patient").post("/api/patient/visits/now", {"reason": "High fever"})
    assert r.status_code in (200, 201), r.text
    pushes = [_decrypt(key, keys, s["body"]) for s in sent if s["url"] == FCM]
    offer = [p for p in pushes if p["link"].startswith("offer:")]
    assert offer, pushes
    assert offer[0]["urgent"] and offer[0]["url"] == "/provider"
    hdr = [s["headers"] for s in sent if s["url"] == FCM][0]
    assert hdr["Urgency"] == "high" and hdr["Content-Encoding"] == "aes128gcm"
    assert hdr["Authorization"].startswith("vapid t=") and int(hdr["TTL"]) <= 120


def test_vapid_token_is_signed_by_our_key(env):
    import base64
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    hdr = push.vapid_header(FCM)
    jwt = hdr.split("t=")[1].split(",")[0]
    head, claims, sig = jwt.split(".")
    assert json.loads(push.b64u_dec(claims))["aud"] == "https://fcm.googleapis.com"
    raw = push.b64u_dec(sig)
    pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), push.b64u_dec(push.public_key()))
    pub.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
               f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))


def test_push_only_to_real_push_services_and_only_after_commit(env, as_, sent):
    doc = as_("doctor")
    _, keys = _device()
    for bad in ("http://fcm.googleapis.com/x", "https://evil.example.com/push", "https://169.254.169.254/latest",
                "https://fcm.googleapis.com.evil.com/x"):
        assert doc.post("/api/push/subscribe", {"endpoint": bad, "keys": keys}).status_code == 422
    assert doc.post("/api/push/subscribe", {"endpoint": FCM, "keys": {"p256dh": "bad", "auth": "x"}}).status_code == 422
    doc.post("/api/push/subscribe", {"endpoint": FCM, "keys": keys})
    from app.models import User
    from app.services.common import notify
    with env["Session"]() as db:
        u = db.query(User).filter(User.token == env["ids"]["tokens"]["doctor"]).one()
        notify(db, [u], "Never sent", "rolled back")
        db.rollback()
        notify(db, [u], "Sent", "committed")
        assert not sent
        db.commit()
    assert len(sent) == 1


def test_signing_out_or_turning_off_stops_pushes(env, as_, sent):
    doc = as_("doctor")
    _, keys = _device()
    doc.post("/api/push/subscribe", {"endpoint": FCM, "keys": keys})
    assert doc.post("/api/push/test").json()["devices"] == 1 and len(sent) == 1
    doc.post("/api/push/unsubscribe", {"endpoint": FCM})
    doc.post("/api/push/test")
    assert len(sent) == 1
    # The same phone handed to another person moves the alerts to them.
    doc.post("/api/push/subscribe", {"endpoint": FCM, "keys": keys})
    as_("doctor_rohan").post("/api/push/subscribe", {"endpoint": FCM, "keys": keys})
    assert doc.get("/api/push/status").json()["devices"] == 0


def test_expired_subscription_is_removed(env, as_, monkeypatch):
    doc = as_("doctor")
    _, keys = _device()
    doc.post("/api/push/subscribe", {"endpoint": FCM, "keys": keys})
    dropped = []
    monkeypatch.setattr(push, "_drop", dropped.append)

    class Gone:
        status_code = 410
        text = "gone"
    monkeypatch.setattr(push.httpx, "post", lambda *a, **k: Gone())
    assert push.deliver(FCM, keys["p256dh"], keys["auth"], b"{}", 60, "high") == 410
    assert dropped == [FCM]


def test_encryption_matches_rfc8291_test_vector():
    """RFC 8291 Appendix A: proves phones will be able to read our pushes."""
    d = int.from_bytes(push.b64u_dec("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big")
    out = push.encrypt("BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
                       "BTBZMqHH6r4Tts7J_aSIgg", b"When I grow up, I want to be a watermelon",
                       salt=push.b64u_dec("DGv6ra1nlYgDCS1FRnbzlw"),
                       server_key=ec.derive_private_key(d, ec.SECP256R1()))
    assert push.b64u(out) == ("DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6"
                              "TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qul"
                              "cy4a-fN")
