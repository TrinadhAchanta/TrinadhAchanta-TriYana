"""DPDP Act 2023 (India): consent notice, consent records, and data principal rights.

Consent is purpose-specific, recorded with the notice version, and can be
withdrawn as easily as it was given. Withdrawal stops new processing; records
that Indian law requires (prescriptions, dispensing and payment records) are
kept for the legally required period.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import Forbidden, Unprocessable
from ..models import Consent, DataRequest, User
from .common import new_ref

NOTICE_VERSION = "2026-11"
PURPOSES = {
    "care": {
        "required": True,
        "title": "Share my health information for my care",
        "body": "Triyana shares your name, phone, address, symptoms and prescriptions only with the doctor you book, "
                "the pharmacy you choose and the courier who delivers your order, so they can treat you and deliver "
                "your medicines.",
    },
    "reminders": {
        "required": False,
        "title": "Medicine and refill reminders",
        "body": "Send me reminders about doses and refills by SMS or WhatsApp. You can turn this off at any time.",
    },
}
NOTICE = {
    "version": NOTICE_VERSION,
    "data_fiduciary": "Triyana Home (demo)",
    "what_we_collect": ["Name, phone, date of birth and address", "Symptoms and reasons for visits",
                        "Prescriptions, orders and delivery details", "Payment status (never your card or UPI PIN)"],
    "retention": "We keep your data only as long as needed for your care. Prescriptions, dispensing and payment "
                 "records are kept for the period Indian law requires, even if you withdraw consent.",
    "rights": ["See a copy of your data", "Correct your data", "Ask us to erase data we don't need to keep",
               "Withdraw consent at any time", "Nominate someone to act for you", "Complain to our grievance "
               "officer, then to the Data Protection Board of India"],
    "grievance_officer": {"name": "Priya Demo (fictional)", "email": "privacy@triyana.example", "respond_within_days": 7},
    "languages": ["en", "hi", "te"],
}


def current(db: Session, user: User) -> dict[str, bool]:
    rows = db.scalars(select(Consent).where(Consent.user_id == user.id).order_by(Consent.id)).all()
    state = {p: False for p in PURPOSES}
    for r in rows:
        state[r.purpose] = r.granted
    return state


def history(db: Session, user: User) -> list[dict]:
    rows = db.scalars(select(Consent).where(Consent.user_id == user.id).order_by(Consent.id.desc())).all()
    return [{"purpose": r.purpose, "granted": r.granted, "notice_version": r.notice_version,
             "language": r.language, "at": r.created_at.isoformat()} for r in rows]


def record(db: Session, user: User, purpose: str, granted: bool, language: str = "en") -> dict[str, bool]:
    if purpose not in PURPOSES:
        raise Unprocessable("bad_purpose", "Unknown consent purpose.")
    db.add(Consent(user_id=user.id, purpose=purpose, granted=granted, notice_version=NOTICE_VERSION,
                   language=language[:8]))
    audit.record(db, user, "consent.granted" if granted else "consent.withdrawn", "user", user.id, purpose=purpose,
                 notice_version=NOTICE_VERSION)
    db.commit()
    return current(db, user)


def require_care(db: Session, user: User) -> None:
    if not current(db, user)["care"]:
        raise Forbidden("consent_required", "Please agree to share your health information for your care before "
                                            "booking a doctor or ordering medicines. You can review this under "
                                            "Privacy & consent.")


def data_request(db: Session, user: User, kind: str, details: str) -> DataRequest:
    if kind not in ("erasure", "correction"):
        raise Unprocessable("bad_kind", "Choose erasure or correction.")
    req = DataRequest(user_id=user.id, kind=kind, details=details.strip(), reference=new_ref("DPR"))
    db.add(req)
    audit.record(db, user, f"privacy.{kind}_requested", "user", user.id, reference=req.reference)
    db.commit()
    return req
