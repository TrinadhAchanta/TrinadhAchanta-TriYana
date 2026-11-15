"""Push alerts to phones and browsers (Web Push), so a doctor hears a new request with the phone locked.

How it works:

* The app asks permission, subscribes through the browser's push service (Google FCM on
  Android/Chrome, Apple on iPhone home-screen apps, Mozilla on Firefox) and sends us that
  subscription. Nothing else is needed: no Firebase project, no app store build.
* Every in-app notification (``common.notify``) is also pushed to that person's devices, but
  only once the database transaction that created it has committed, so a rolled-back request
  never buzzes anyone's phone.
* Payloads are encrypted for the device (RFC 8291, aes128gcm) and signed with our VAPID key
  (RFC 8292). The push service can't read them.

The VAPID key comes from ``TRIYANA_VAPID_PRIVATE_KEY`` (base64url of the 32-byte P-256 private
value) when set, otherwise it is derived from ``TRIYANA_SECRET``, so it survives redeploys
without any extra setting. Changing the secret changes the key: devices then re-subscribe the
next time the app is opened.

iPhone: Apple only delivers web push to apps added to the Home Screen (iOS 16.4+); the app
tells iPhone users how.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import delete, event, select
from sqlalchemy.orm import Session

from .. import config
from ..errors import Unprocessable
from ..models import PushSubscription, User, utcnow

log = logging.getLogger("triyana.push")

# Only the browsers' own push services: never let a client make us POST to an arbitrary URL.
PUSH_HOSTS = ("fcm.googleapis.com", "android.googleapis.com", ".push.apple.com", "push.services.mozilla.com",
              ".push.services.mozilla.com", ".notify.windows.com")
MAX_PER_USER = 10
_P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64u_dec(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


# ------------------------------------------------------------------ VAPID key
_key_cache: dict[str, ec.EllipticCurvePrivateKey] = {}


def _private_key() -> ec.EllipticCurvePrivateKey:
    raw = os.environ.get("TRIYANA_VAPID_PRIVATE_KEY", "").strip()
    cache_key = raw or "derived:" + config.secret()
    if cache_key not in _key_cache:
        if raw:
            d = int.from_bytes(b64u_dec(raw), "big")
        else:
            seed = hmac.new(config.secret().encode(), b"triyana-web-push-vapid", hashlib.sha256).digest()
            d = int.from_bytes(seed, "big") % (_P256_ORDER - 1) + 1
        _key_cache[cache_key] = ec.derive_private_key(d, ec.SECP256R1())
    return _key_cache[cache_key]


def _point(pub: ec.EllipticCurvePublicKey) -> bytes:
    return pub.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def public_key() -> str:
    """The application server key the browser needs to subscribe (base64url, uncompressed P-256 point)."""
    return b64u(_point(_private_key().public_key()))


def _subject() -> str:
    return os.environ.get("TRIYANA_VAPID_SUBJECT") or os.environ.get(
        "TRIYANA_PUBLIC_URL", "https://triyana-demo.onrender.com").rstrip("/")


def vapid_header(endpoint: str, now: float | None = None) -> str:
    u = urlparse(endpoint)
    claims = {"aud": f"{u.scheme}://{u.netloc}", "exp": int((now or time.time()) + 12 * 3600), "sub": _subject()}
    signing_input = (b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode()) + "."
                     + b64u(json.dumps(claims, separators=(",", ":")).encode()))
    r, s = decode_dss_signature(_private_key().sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
    jwt = signing_input + "." + b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={jwt}, k={public_key()}"


# --------------------------------------------------------- payload encryption
def _hmac(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def encrypt(p256dh: str, auth: str, payload: bytes, *, salt: bytes | None = None,
            server_key: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    """RFC 8291 message encryption with the aes128gcm content coding (RFC 8188), one record."""
    ua_public = b64u_dec(p256dh)
    auth_secret = b64u_dec(auth)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    as_key = server_key or ec.generate_private_key(ec.SECP256R1())
    as_public = _point(as_key.public_key())
    shared = as_key.exchange(ec.ECDH(), ua_key)
    ikm = _hmac(_hmac(auth_secret, shared), b"WebPush: info\x00" + ua_public + as_public + b"\x01")
    salt = salt or os.urandom(16)
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    record = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + struct.pack("!IB", 4096, len(as_public)) + as_public + record


# ------------------------------------------------------------- subscriptions
def _check_endpoint(endpoint: str) -> None:
    u = urlparse(endpoint or "")
    host = (u.hostname or "").lower()
    ok = u.scheme == "https" and any(host == h.lstrip(".") or (h.startswith(".") and host.endswith(h))
                                     for h in PUSH_HOSTS)
    if not ok:
        raise Unprocessable("bad_push_endpoint", "This browser's push service isn't supported.")


def subscribe(db: Session, user: User, endpoint: str, p256dh: str, auth: str, app: str) -> dict:
    _check_endpoint(endpoint)
    try:
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b64u_dec(p256dh))
        if len(b64u_dec(auth)) != 16:
            raise ValueError
    except (ValueError, TypeError):
        raise Unprocessable("bad_push_keys", "The browser sent invalid push keys. Try turning alerts on again.")
    sub = db.scalars(select(PushSubscription).where(PushSubscription.endpoint == endpoint)).first()
    if sub is None:
        sub = PushSubscription(endpoint=endpoint)
        db.add(sub)
    # A shared phone: whoever signed in last gets the alerts.
    sub.user_id, sub.p256dh, sub.auth, sub.app, sub.created_at = user.id, p256dh, auth, app, utcnow()
    db.flush()
    extra = db.scalars(select(PushSubscription).where(PushSubscription.user_id == user.id)
                       .order_by(PushSubscription.created_at.desc()).offset(MAX_PER_USER)).all()
    for old in extra:
        db.delete(old)
    db.commit()
    return {"ok": True, "devices": count(db, user.id)}


def unsubscribe(db: Session, user: User, endpoint: str) -> None:
    db.execute(delete(PushSubscription).where(PushSubscription.user_id == user.id,
                                              PushSubscription.endpoint == endpoint))
    db.commit()


def forget_user(db: Session, user_id: int) -> None:
    db.execute(delete(PushSubscription).where(PushSubscription.user_id == user_id))


def count(db: Session, user_id: int) -> int:
    return len(db.scalars(select(PushSubscription.id).where(PushSubscription.user_id == user_id)).all())


# ------------------------------------------------------------------- sending
def _style(link: str, title: str) -> tuple[int, str]:
    """(time to live in seconds, urgency) for a notification."""
    if link.startswith("offer:"):
        return int(os.environ.get("TRIYANA_OFFER_SECONDS", "45")) + 15, "high"
    if "SOS" in title:
        return 600, "high"
    return 3600, "normal"


def queue(db: Session, user_ids: list[int], title: str, body: str, link: str = "") -> None:
    """Push to these users' devices once ``db`` commits. Called from ``common.notify``."""
    if not user_ids:
        return
    subs = db.scalars(select(PushSubscription).where(PushSubscription.user_id.in_(user_ids))).all()
    if not subs:
        return
    ttl, urgency = _style(link, title)
    for s in subs:
        url = "/provider" if s.app == "provider" else "/"
        msg = {"title": title, "body": body, "link": link, "url": url, "tag": link or title,
               "urgent": urgency == "high"}
        db.info.setdefault("push_outbox", []).append(
            (s.endpoint, s.p256dh, s.auth, json.dumps(msg).encode(), ttl, urgency))


_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="push")


def _submit(fn, *args) -> None:
    """Send off the request thread; tests replace this to run inline."""
    _pool.submit(fn, *args)


def deliver(endpoint: str, p256dh: str, auth: str, payload: bytes, ttl: int, urgency: str) -> int:
    """POST one encrypted message to the push service. Returns the HTTP status (0 on a network error)."""
    try:
        r = httpx.post(endpoint, content=encrypt(p256dh, auth, payload), timeout=10, headers={
            "Authorization": vapid_header(endpoint), "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream", "TTL": str(ttl), "Urgency": urgency})
    except httpx.HTTPError as e:
        log.warning("Push to %s failed: %s", urlparse(endpoint).hostname, e)
        return 0
    if r.status_code in (404, 410):
        _drop(endpoint)  # the person turned alerts off or uninstalled the app
    elif r.status_code >= 400:
        log.warning("Push to %s refused: %s %s", urlparse(endpoint).hostname, r.status_code, r.text[:200])
    return r.status_code


def _drop(endpoint: str) -> None:
    from ..db import SessionLocal
    try:
        with SessionLocal() as db:
            db.execute(delete(PushSubscription).where(PushSubscription.endpoint == endpoint))
            db.commit()
    except Exception as e:  # never let cleanup break anything
        log.warning("Could not remove expired push subscription: %s", e)


@event.listens_for(Session, "after_commit")
def _flush_outbox(session: Session) -> None:
    for item in session.info.pop("push_outbox", []):
        _submit(deliver, *item)


@event.listens_for(Session, "after_rollback")
def _drop_outbox(session: Session) -> None:
    session.info.pop("push_outbox", None)
