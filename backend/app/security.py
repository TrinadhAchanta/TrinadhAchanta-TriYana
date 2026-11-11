"""Field-level encryption for health data and prescriber e-signatures.

Demo mode derives keys from TRIYANA_SECRET. In production these keys must come
from a managed KMS/HSM and be rotated; nothing here should be hard-coded.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os

from cryptography.fernet import Fernet
from sqlalchemy.types import Text, TypeDecorator

SECRET = os.environ.get("TRIYANA_SECRET", "triyana-demo-secret-change-me")


def _derive(purpose: str) -> bytes:
    return hashlib.sha256(f"{purpose}:{SECRET}".encode()).digest()


_fernet = Fernet(base64.urlsafe_b64encode(_derive("phi-encryption")))


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


def sign_prescription(doctor_license: str, content_hash: str) -> str:
    """HMAC e-signature bound to the doctor's licence and the exact content.

    A real deployment would use the jurisdiction's approved e-prescribing
    signature scheme (e.g. PKI certificates / EPCS two-factor signing).
    """
    key = _derive(f"prescriber-signature:{doctor_license}")
    return hmac.new(key, content_hash.encode(), hashlib.sha256).hexdigest()


def verify_prescription_signature(doctor_license: str, content_hash: str, signature: str) -> bool:
    return hmac.compare_digest(sign_prescription(doctor_license, content_hash), signature)
