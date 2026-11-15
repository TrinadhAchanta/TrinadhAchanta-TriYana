"""Field-level encryption for health data and prescriber e-signatures.

Keys are derived from TRIYANA_SECRET (see app/config.py). Live mode refuses to start
without a strong one. Old secrets in TRIYANA_OLD_SECRETS still decrypt and verify, so the
secret can be rotated; new data is always written with the current secret.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json

from cryptography.fernet import Fernet, MultiFernet
from sqlalchemy.types import Text, TypeDecorator

from . import config

SECRET = config.secret()
_ALL_SECRETS = [SECRET] + [s for s in config.old_secrets() if s != SECRET]


def _derive(purpose: str, secret: str = SECRET) -> bytes:
    return hashlib.sha256(f"{purpose}:{secret}".encode()).digest()


_fernet = MultiFernet([Fernet(base64.urlsafe_b64encode(_derive("phi-encryption", s))) for s in _ALL_SECRETS])


class EncryptedText(TypeDecorator):
    """Encrypts the value at rest; transparent to application code."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return _fernet.encrypt(str(value).encode()).decode()

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return _fernet.decrypt(value.encode()).decode()


def canonical_hash(payload: dict) -> str:
    """Stable SHA-256 over a JSON payload (sorted keys, no whitespace)."""
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(data.encode()).hexdigest()


def sign_prescription(doctor_license: str, content_hash: str, secret: str = SECRET) -> str:
    """HMAC e-signature bound to the doctor's licence and the exact content.

    A real deployment would use the jurisdiction's approved e-prescribing
    signature scheme (e.g. PKI certificates / EPCS two-factor signing).
    """
    key = _derive(f"prescriber-signature:{doctor_license}", secret)
    return hmac.new(key, content_hash.encode(), hashlib.sha256).hexdigest()


def verify_prescription_signature(doctor_license: str, content_hash: str, signature: str) -> bool:
    return any(hmac.compare_digest(sign_prescription(doctor_license, content_hash, s), signature or "")
               for s in _ALL_SECRETS)
