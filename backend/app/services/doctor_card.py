"""The verified doctor card a patient sees before the doctor arrives.

Everything on it is backed by a check Triyana has done: the medical council registration (ABDM HPR or
the council register), the ID and background check, ops approval, and the live face check the doctor
must pass before setting off for *this* visit. The enrolled photo is shown only once the doctor has
accepted the visit, so a patient can recognise who is at the door.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Doctor, HomeVisit, User, VerificationCheck, VisitStatus
from . import face_verification as face

SHOWN_IN = (VisitStatus.requested, VisitStatus.accepted, VisitStatus.in_progress, VisitStatus.completed)


def _latest_check(db: Session, user_id: int, kind: str) -> VerificationCheck | None:
    return db.scalars(select(VerificationCheck).where(VerificationCheck.user_id == user_id,
                                                      VerificationCheck.kind == kind)
                      .order_by(VerificationCheck.id.desc())).first()


def card(db: Session, v: HomeVisit, *, with_photo: bool = True) -> dict | None:
    if not v.doctor_id or v.status not in SHOWN_IN:
        return None
    d = db.get(Doctor, v.doctor_id)
    user = db.scalars(select(User).where(User.doctor_id == d.id)).first()
    accepted = v.status in (VisitStatus.accepted, VisitStatus.in_progress, VisitStatus.completed)
    enr = face.active_enrollment(db, user) if user else None
    passed = face.ever_passed(db, user.id, v.id) if user and accepted else None

    reg = _latest_check(db, user.id, "registry") if user else None
    reg_source = ("Checked on India's Healthcare Professionals Registry (ABDM HPR)" if reg and reg.partner == "hpr"
                  else "Checked with the medical council register")
    # Ops only approve a doctor once their ID and background check cleared (any override is noted and audited).
    bg_ok = bool(user and user.is_verified)

    checks = [
        {"key": "registration", "ok": bool(d.license_verified),
         "label": "Medical registration verified" if d.license_verified else "Registration not verified",
         "detail": f"Reg. No. {d.license_no}" + (f" · {d.medical_council}" if d.medical_council else "")
                   + (f" · since {d.registration_year}" if d.registration_year else "") + f". {reg_source}."},
        {"key": "background", "ok": bg_ok, "label": "ID and background check cleared" if bg_ok else "Background check pending",
         "detail": "Government ID matched and court records checked, then approved by Triyana's team."},
    ]
    if accepted:
        checks.append({"key": "face", "ok": passed is not None,
                       "label": "Live face check passed" if passed else "Live face check before setting off",
                       "detail": ("Matched to their verified photo for this visit." if passed else
                                  "They must pass a live selfie check for this visit before they can leave."),
                       "at": passed.completed_at.isoformat() + "Z" if passed else None})
    return {
        "doctor_id": d.id, "name": d.name, "specialty": d.specialty, "qualification": d.qualification,
        "experience_years": d.experience_years, "languages": d.languages or [],
        "rating": d.rating, "rating_count": d.rating_count, "about": d.about,
        "license_no": d.license_no, "medical_council": d.medical_council, "registration_year": d.registration_year,
        "photo": enr.photo if (with_photo and accepted and enr) else None,
        "verified": all(c["ok"] for c in checks[:2]),
        "face_verified": passed is not None,
        "checks": checks,
    }
