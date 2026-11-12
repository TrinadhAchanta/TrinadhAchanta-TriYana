"""Provider verification: partner checks first, then a Triyana ops final review.

Flow for a provider who signs up in Triyana Partner:

1. Doctors and physios: the council registration is looked up on the registry
   (ABDM HPR) straight after sign-up.
2. Every provider adds a PAN (or driving licence for riders and collectors) with
   consent; the ID and a court-record search go to the background partner (IDfy).
3. When the checks are back, the account shows "Ready for review" to Triyana ops,
   who approve or reject it. Approving with a failed or missing check needs an
   explicit override and a note, and is audited.

Full ID numbers are never stored: only the type, a masked number and the partner's reference.
"""
from __future__ import annotations

import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..adapters import verification as partners
from ..errors import Conflict, Unprocessable
from ..models import Doctor, Physiotherapist, Role, User, VerificationCheck, utcnow

LABELS = {"registry": "Council registration", "identity": "ID check", "background": "Court records"}
PARTNER_NAMES = {"demo": "Demo partner", "hpr": "ABDM HPR", "idfy": "IDfy"}


def required_kinds(user: User) -> list[str]:
    kinds = ["registry"] if user.role in (Role.doctor, Role.physio) else []
    return kinds + ["identity", "background"]


def _registration(db: Session, user: User) -> tuple[str, str] | None:
    if user.doctor_id:
        d = db.get(Doctor, user.doctor_id)
        return d.license_no, d.medical_council
    if user.physio_id:
        p = db.get(Physiotherapist, user.physio_id)
        return p.registration_no, p.council
    return None


def _latest(db: Session, user_id: int) -> dict[str, VerificationCheck]:
    rows = db.scalars(select(VerificationCheck).where(VerificationCheck.user_id == user_id)
                      .order_by(VerificationCheck.id)).all()
    return {r.kind: r for r in rows}


def _save(db: Session, user: User, kind: str, partner: str, res: partners.Result | None,
          error: str | None = None) -> VerificationCheck:
    now = utcnow()
    row = VerificationCheck(user_id=user.id, kind=kind, partner=partner, created_at=now, updated_at=now,
                            status="error" if error else res.status, reference=res.reference if res else None,
                            summary=(error or res.summary)[:300], details=(res.details if res else {}))
    db.add(row)
    db.flush()
    audit.record(db, None, f"provider.check.{kind}.{row.status}", "user", user.id, partner=partner,
                 reference=row.reference)
    return row


def run_registry_check(db: Session, user: User) -> VerificationCheck | None:
    reg = _registration(db, user)
    if not reg:
        return None
    partner = partners.registry_partner()
    try:
        res = partners.lookup_registration(user.name, reg[0], reg[1])
        if res.status == "failed" and user.role == Role.physio and not res.details.get("found", True):
            # HPR does not list every allied-health council yet, so a miss is a manual check, not a rejection.
            res.status, res.summary = "needs_review", res.summary + " Check the state council register by hand."
        row = _save(db, user, "registry", partner, res)
    except partners.PartnerError as e:
        row = _save(db, user, "registry", partner, None, error=f"{e}. Retry later.")
    db.commit()
    return row


def submit_identity(db: Session, user: User, body: dict) -> dict:
    if user.role not in (Role.doctor, Role.physio, Role.courier, Role.phlebotomist, Role.pharmacist):
        raise Unprocessable("not_provider", "Only Triyana Partner accounts need ID checks.")
    if (user.verification_status or "verified") == "verified":
        raise Conflict("already_verified", "Your account is already verified.")
    if not body.get("consent"):
        raise Unprocessable("consent_required",
                            "Please agree to the ID and background check so we can verify you.")
    id_type = body.get("id_type") or "pan"
    try:
        number = partners.clean_id(id_type, body.get("id_number") or "")
    except ValueError as e:
        raise Unprocessable("invalid_id", str(e))
    dob = (body.get("date_of_birth") or "").strip()
    if len(dob) != 10:
        raise Unprocessable("dob_required", "Enter your date of birth as on your ID.")
    current = _latest(db, user.id).get("identity")
    if current and current.status in ("passed", "in_progress"):
        raise Conflict("already_submitted", "Your ID is already submitted.")
    address = (body.get("address") or "").strip()
    partner = partners.background_partner()
    audit.record(db, user, "provider.background_consent", "user", user.id, id_type=id_type,
                 id_masked=partners.mask(number), partner=partner)
    try:
        _save(db, user, "identity", partner, partners.verify_id(user.name, dob, id_type, number))
    except partners.PartnerError as e:
        _save(db, user, "identity", partner, None, error=f"{e}. Retry later.")
    try:
        court = partners.court_record_check(user.name, dob, address, None, number)
        if court:
            _save(db, user, "background", partner, court)
        else:
            _save(db, user, "background", partner,
                  partners.Result("needs_review", "No automated court-record check on this contract. "
                                  "Check police verification by hand."))
    except partners.PartnerError as e:
        _save(db, user, "background", partner, None, error=f"{e}. Retry later.")
    db.commit()
    return status(db, user)


def refresh(db: Session, user: User) -> None:
    """Pick up results of checks still running at the partner."""
    changed = False
    for kind, row in _latest(db, user.id).items():
        if row.status != "in_progress":
            continue
        try:
            res = partners.poll(kind, row.reference or "")
        except partners.PartnerError:
            continue
        if res:
            row.status, row.summary, row.updated_at = res.status, res.summary[:300], utcnow()
            row.details = {**(row.details or {}), **res.details}
            audit.record(db, None, f"provider.check.{kind}.{row.status}", "user", user.id, reference=row.reference)
            changed = True
    if changed:
        db.commit()


def rerun(db: Session, user: User) -> dict:
    """Ops: run the registry lookup again (e.g. after the provider fixed a typo or the partner was down)."""
    run_registry_check(db, user)
    refresh(db, user)
    return status(db, user)


def status(db: Session, user: User) -> dict:
    latest = _latest(db, user.id)
    checks = []
    for kind in required_kinds(user):
        row = latest.get(kind)
        checks.append({"kind": kind, "label": LABELS[kind],
                       "status": row.status if row else "not_started",
                       "partner": PARTNER_NAMES.get(row.partner, row.partner) if row else None,
                       "summary": row.summary if row else ("Add your ID below to start this check."
                                                           if kind != "registry" else "Not checked yet."),
                       "reference": row.reference if row else None,
                       "details": row.details if row else {},
                       "checked_at": row.updated_at.isoformat() + "Z" if row else None})
    states = {c["status"] for c in checks}
    if (user.verification_status or "verified") != "pending":
        stage = user.verification_status or "verified"
    elif "not_started" in states:
        stage = "needs_documents"
    elif states & {"in_progress", "error"}:
        stage = "checking"
    elif states == {"passed"}:
        stage = "ready_for_review"
    else:
        stage = "flagged"
    return {"stage": stage, "checks": checks, "id_needed": latest.get("identity") is None
            or latest["identity"].status in ("failed", "error"),
            "id_types": ["pan"] if user.role in (Role.doctor, Role.physio) else ["pan", "driving_licence"]}


def all_passed(db: Session, user: User) -> bool:
    return status(db, user)["stage"] == "ready_for_review"


def demo_admin_key_allowed() -> bool:
    return os.environ.get("TRIYANA_DEMO", "1") == "1" and not os.environ.get("TRIYANA_ADMIN_KEY")
