"""Demo mode vs live mode, and the settings a live launch must have.

``TRIYANA_DEMO`` picks the mode (default ``1``, the public demo):

* **Demo** (``TRIYANA_DEMO=1``): built-in demo accounts, "Approve me", "Reset demo",
  on-screen SMS codes and the demo face check. Nothing here is safe for real patients.
* **Live** (``TRIYANA_DEMO=0``): demo accounts are switched off and their tokens no longer
  sign anyone in, the demo buttons are gone, SMS codes are never shown on screen, and the
  app refuses to start without a strong ``TRIYANA_SECRET``.

``TRIYANA_SECRET`` derives the key that encrypts health records at rest, the prescription
e-signatures and the web push key. Generate it once with
``python -c "import secrets; print(secrets.token_urlsafe(48))"``, keep a copy somewhere safe and
never change it casually: data encrypted with one secret can't be read with another. To rotate,
put the old value in ``TRIYANA_OLD_SECRETS`` (comma separated) and the new one in ``TRIYANA_SECRET``.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("triyana.config")

DEFAULT_SECRET = "triyana-demo-secret-change-me"
MIN_SECRET_LEN = 32


def is_demo() -> bool:
    return os.environ.get("TRIYANA_DEMO", "1") == "1"


def secret() -> str:
    return os.environ.get("TRIYANA_SECRET") or DEFAULT_SECRET


def old_secrets() -> list[str]:
    return [s.strip() for s in os.environ.get("TRIYANA_OLD_SECRETS", "").split(",") if s.strip()]


def secret_is_strong(value: str | None = None) -> bool:
    value = secret() if value is None else value
    return value != DEFAULT_SECRET and len(value) >= MIN_SECRET_LEN and len(set(value)) >= 10


def launch_checks() -> list[dict]:
    """What a live launch needs, each marked ok or not. ``blocking`` items stop a live app from starting."""
    from .adapters import sms
    admins = bool(os.environ.get("TRIYANA_ADMINS") or os.environ.get("TRIYANA_ADMIN_KEY"))
    db_url = os.environ.get("TRIYANA_DATABASE_URL", "sqlite:///./triyana_demo.db")
    return [
        {"key": "secret", "ok": secret_is_strong(), "blocking": True,
         "label": "Strong TRIYANA_SECRET (encrypts health records)",
         "fix": f"Set TRIYANA_SECRET to a random value of at least {MIN_SECRET_LEN} characters."},
        {"key": "database", "ok": not db_url.startswith("sqlite"), "blocking": False,
         "label": "Lasting database (accounts survive deploys)",
         "fix": "Set TRIYANA_DATABASE_URL to a Postgres database."},
        {"key": "sms", "ok": not sms.is_sandbox(), "blocking": False,
         "label": "Real SMS gateway (sign-up and forgot-password codes)",
         "fix": "Set TRIYANA_SMS_PROVIDER=msg91 with MSG91_AUTH_KEY and MSG91_TEMPLATE_ID."},
        {"key": "payments", "ok": bool(os.environ.get("RAZORPAY_KEY_ID") and os.environ.get("RAZORPAY_KEY_SECRET")),
         "blocking": False, "label": "Real payments", "fix": "Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET."},
        {"key": "admins", "ok": admins, "blocking": False, "label": "Triyana Ops admin logins",
         "fix": "Set TRIYANA_ADMINS to email:password pairs separated by ; so admin logins exist from the first boot."},
        {"key": "face", "ok": bool(os.environ.get("TRIYANA_FACE_PROVIDER")), "blocking": False,
         "label": "Face check vendor (doctors can't start visits without it in live mode)",
         "fix": "Connect a face-match vendor; until then live mode refuses every face check."},
    ]


class UnsafeConfig(RuntimeError):
    pass


def check_startup() -> None:
    """Live mode must not start with demo-grade secrets. Demo mode only warns."""
    problems = [c for c in launch_checks() if not c["ok"]]
    if is_demo():
        if not secret_is_strong():
            log.warning("Demo mode with the default TRIYANA_SECRET. Fine for the demo, never for real patients.")
        return
    for c in problems:
        print(f"[triyana] Live mode: {c['label']} is not set up. {c['fix']}", flush=True)
    blocking = [c for c in problems if c["blocking"]]
    if blocking:
        raise UnsafeConfig("Triyana won't start in live mode (TRIYANA_DEMO=0): "
                           + " ".join(c["fix"] for c in blocking))
