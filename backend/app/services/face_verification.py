"""Mandatory doctor face verification: enrolment at sign-up and a live check before every home visit.

The rules, all enforced here on the server (the app only shows them):

* A doctor needs an **active face enrolment** (live capture + consent, approved by Triyana ops
  with the rest of their verification) before they can go online or accept a visit.
* Before **Start journey** on a visit, the doctor passes a live check for *that* visit: a random
  liveness prompt, camera frames bound to a one-time challenge, then a match against the enrolled
  face. A pass is valid for that one visit for ``FACE_PASS_MINUTES`` (default 15).
* Starting the visit at the door needs the patient's **arrival code** and a journey that was
  started after a pass (or a fresh pass).
* Failures: 3 non-matching / non-live attempts on a visit, or any sign of spoofing, lock the doctor
  out of journeys and open a case for the security team. Only ops can clear it ("approved recovery"),
  including approving an equivalent manual check (e.g. a video call with ID) for one visit.
* No images are stored from visit checks; the enrolment keeps one small encrypted profile photo.
  Biometric templates stay with the face partner. Patients see the photo, name and credentials
  only, and only once the doctor has passed the check for their visit.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..adapters import face as partner
from ..errors import Conflict, Forbidden, NotFound, Unprocessable
from ..models import (
    Consent,
    Doctor,
    FaceCheck,
    FaceEnrollment,
    HomeVisit,
    IdentityCase,
    Role,
    Trip,
    User,
    VerificationCheck,
    VisitStatus,
    utcnow,
)
from .common import notify, users_for_patient

log = logging.getLogger("triyana.face")

CONSENT_VERSION = "bio-2026-11"
CHALLENGE_SECONDS = 120
FACE_PASS_MINUTES = int(os.environ.get("TRIYANA_FACE_PASS_MINUTES", "15"))
MANUAL_PASS_MINUTES = 60
MAX_FAILED = 3          # wrong face / not live, per visit, before a lockout
MAX_ATTEMPTS = 8        # any outcome incl. poor lighting, per visit, before a lockout
ARRIVAL_CODE_TRIES = 5
REPLAY_WINDOW_DAYS = 30

ACTIONS = {
    "turn_left": "Slowly turn your head to your left, then back",
    "turn_right": "Slowly turn your head to your right, then back",
    "nod": "Nod your head slowly",
    "blink": "Blink twice, then move your head a little",
    "smile": "Smile, then turn your head slightly",
}
CONSENT_TEXT = (
    "I agree that Triyana and its identity partner may capture my face with the camera to create a face "
    "template, check that I am a live person, and compare my face with this template before each home visit. "
    "This is used only to confirm my identity to patients and keep visits safe. Triyana keeps one small "
    "encrypted profile photo that patients see during my verified visits, and the results and times of each "
    "check. I can withdraw this consent at any time, but I can't take home visits without it or an approved "
    "alternative check."
)


# ------------------------------------------------------------------ helpers
def _is_demo_persona(user: User) -> bool:
    return user.email is None and (user.token or "").startswith("demo-")


def _hash(nonce: str) -> str:
    return hashlib.sha256(nonce.encode()).hexdigest()


def current_enrollment(db: Session, user: User) -> FaceEnrollment | None:
    return db.scalars(select(FaceEnrollment).where(FaceEnrollment.user_id == user.id,
                                                   FaceEnrollment.status != "revoked")
                      .order_by(FaceEnrollment.id.desc())).first()


def active_enrollment(db: Session, user: User) -> FaceEnrollment | None:
    return db.scalars(select(FaceEnrollment).where(FaceEnrollment.user_id == user.id,
                                                   FaceEnrollment.status == "active")
                      .order_by(FaceEnrollment.id.desc())).first()


def blocking_case(db: Session, user: User) -> IdentityCase | None:
    return db.scalars(select(IdentityCase).where(IdentityCase.user_id == user.id, IdentityCase.status == "open",
                                                 IdentityCase.blocking.is_(True))
                      .order_by(IdentityCase.id)).first()


def require_enrolled(db: Session, user: User) -> None:
    """Doctors can't go online or accept visits without an active, approved face enrolment
    or while a security case has them locked out."""
    if user.role != Role.doctor:
        return
    case = blocking_case(db, user)
    if case:
        raise _locked_error(case)
    if active_enrollment(db, user) is None:
        pending = current_enrollment(db, user)
        raise Forbidden("face_enrollment_required",
                        "Your face enrolment is waiting for Triyana's approval." if pending else
                        "Enrol your face in the Partner app before you take home visits.")


def _locked_error(case: IdentityCase) -> Forbidden:
    return Forbidden("identity_locked",
                     "Your identity needs to be confirmed by Triyana before you can start a journey. "
                     "Our team has been told and will contact you.", case_id=case.id)


def _seen_digests(db: Session) -> set[str]:
    since = utcnow() - timedelta(days=REPLAY_WINDOW_DAYS)
    seen: set[str] = set()
    for ds in db.scalars(select(FaceCheck.frame_digests).where(FaceCheck.created_at >= since)):
        seen.update(ds or [])
    return seen


def _visit_for(db: Session, user: User, visit_id: int) -> HomeVisit:
    v = db.get(HomeVisit, visit_id)
    if v is None or user.role != Role.doctor or v.doctor_id != user.doctor_id:
        raise NotFound("not_found", "Visit not found.")
    return v


def _counts(db: Session, user: User, visit_id: int) -> tuple[int, int]:
    rows = db.scalars(select(FaceCheck).where(FaceCheck.user_id == user.id, FaceCheck.visit_id == visit_id,
                                              FaceCheck.purpose == "visit", FaceCheck.counted.is_(True))).all()
    failed = sum(1 for r in rows if r.status in ("failed", "spoof"))
    attempts = sum(1 for r in rows if r.status in ("failed", "spoof", "poor_quality", "expired"))
    return failed, attempts


# ------------------------------------------------------------------ security alerts and cases
def alert_security(db: Session, case: IdentityCase) -> None:
    """Tell the security team. Always audited and logged; also posted to TRIYANA_SECURITY_WEBHOOK_URL
    (e.g. a Slack/Teams/PagerDuty webhook) when set. Only ids and the kind of alert are sent."""
    audit.record(db, None, "security.alert", "identity_case", case.id, kind=case.kind, severity=case.severity,
                 user_id=case.user_id, visit_id=case.visit_id)
    log.warning("SECURITY ALERT case=%s kind=%s severity=%s user=%s visit=%s", case.id, case.kind, case.severity,
                case.user_id, case.visit_id)
    url = os.environ.get("TRIYANA_SECURITY_WEBHOOK_URL")
    if url:
        try:
            import httpx
            httpx.post(url, timeout=3, json={"text": f"Triyana identity alert #{case.id}: {case.kind} "
                                                     f"({case.severity}). Review it in Triyana Ops.",
                                             "case_id": case.id, "kind": case.kind, "severity": case.severity})
        except Exception as e:  # noqa: BLE001 - an alert outage must never unblock anything
            log.error("Security webhook failed: %s", e)


def open_case(db: Session, user: User, kind: str, summary: str, *, visit_id: int | None = None,
              severity: str = "medium", blocking: bool = True, alert: bool = True) -> IdentityCase:
    existing = db.scalars(select(IdentityCase).where(IdentityCase.user_id == user.id, IdentityCase.kind == kind,
                                                     IdentityCase.status == "open",
                                                     IdentityCase.visit_id == visit_id)).first()
    if existing:
        return existing
    case = IdentityCase(user_id=user.id, visit_id=visit_id, kind=kind, severity=severity, blocking=blocking,
                        summary=summary[:300])
    db.add(case)
    db.flush()
    audit.record(db, None, f"identity.case.{kind}", "identity_case", case.id, user_id=user.id, visit_id=visit_id,
                 blocking=blocking)
    if blocking:
        user.on_duty = False  # no new requests while locked out
    if alert:
        alert_security(db, case)
    return case


# ------------------------------------------------------------------ challenges
def start_challenge(db: Session, user: User, purpose: str, visit_id: int | None = None,
                    consent: bool = False) -> dict:
    if user.role != Role.doctor:
        raise Forbidden("forbidden_role", "Face checks are for doctors in the Partner app.")
    if purpose not in ("visit", "enroll"):
        raise Unprocessable("bad_purpose", "Unknown face check.")
    case = blocking_case(db, user)
    if case:
        raise _locked_error(case)
    if purpose == "enroll":
        if not consent:
            raise Unprocessable("consent_required", "Please agree to the face check before we use your camera.")
        db.add(Consent(user_id=user.id, purpose="biometric_face", granted=True, notice_version=CONSENT_VERSION))
        audit.record(db, user, "face.consent", "user", user.id, version=CONSENT_VERSION)
    else:
        v = _visit_for(db, user, visit_id or 0)
        if v.status != VisitStatus.accepted:
            raise Conflict("bad_visit_state", "You can verify for a visit once you've accepted it and before you start it.")
        require_enrolled(db, user)
        failed, attempts = _counts(db, user, v.id)
        if failed >= MAX_FAILED or attempts >= MAX_ATTEMPTS:
            raise _locked_error(open_case(db, user, "repeated_failures",
                                          "Too many face check attempts for one visit.", visit_id=v.id))
    now = utcnow()
    for old in db.scalars(select(FaceCheck).where(FaceCheck.user_id == user.id, FaceCheck.status == "issued")):
        old.status, old.completed_at, old.counted = "expired", now, False
    nonce = secrets.token_urlsafe(18)
    action = secrets.choice(list(ACTIONS))
    chk = FaceCheck(user_id=user.id, visit_id=visit_id if purpose == "visit" else None, purpose=purpose,
                    nonce_hash=_hash(nonce), action=action, status="issued", partner=partner.face_partner(),
                    created_at=now, expires_at=now + timedelta(seconds=CHALLENGE_SECONDS))
    db.add(chk)
    db.flush()
    audit.record(db, user, f"face.challenge.{purpose}", "face_check", chk.id, visit_id=chk.visit_id)
    db.commit()
    failed, _ = _counts(db, user, visit_id) if purpose == "visit" else (0, 0)
    return {"id": chk.id, "nonce": nonce, "action": action, "prompt": ACTIONS[action], "purpose": purpose,
            "visit_id": chk.visit_id, "expires_in": CHALLENGE_SECONDS, "attempts_left": MAX_FAILED - failed,
            "demo": partner.face_partner() == "demo" and partner.demo_mode(),
            "demo_scenarios": list(partner.DEMO_SCENARIOS) if partner.demo_mode() else []}


def submit(db: Session, user: User, check_id: int, nonce: str, frames: list[str], scenario: str | None = None) -> dict:
    chk = db.get(FaceCheck, check_id)
    if chk is None or chk.user_id != user.id:  # a challenge can't be finished from another account
        raise NotFound("not_found", "Face check not found. Start again.")
    if chk.status != "issued":
        raise Conflict("challenge_used", "This face check was already used. Start a new one.")
    if not hmac.compare_digest(chk.nonce_hash or "", _hash(nonce or "")):
        raise Forbidden("bad_challenge", "This face check doesn't match. Start a new one.")
    now = utcnow()
    if chk.expires_at and now > chk.expires_at:
        chk.status, chk.completed_at, chk.reason = "expired", now, "Challenge expired before frames arrived."
        audit.record(db, user, "face.check.expired", "face_check", chk.id, visit_id=chk.visit_id)
        db.commit()
        raise Conflict("challenge_expired", "That took too long (or the connection dropped). Try again.")
    case = blocking_case(db, user)
    if case:
        chk.status, chk.completed_at, chk.counted = "expired", now, False
        db.commit()
        raise _locked_error(case)
    try:
        raw = partner.decode_frames(frames)
    except ValueError as e:
        chk.status, chk.completed_at, chk.reason, chk.counted = "error", now, str(e)[:300], False
        db.commit()
        raise Unprocessable("bad_frames", str(e))
    scenario = scenario if partner.demo_mode() and scenario in partner.DEMO_SCENARIOS else None
    seen = _seen_digests(db)
    chk.frame_digests = partner.digests(raw)
    try:
        if chk.purpose == "enroll":
            res = partner.enroll(user.id, raw, scenario, seen)
        else:
            enr = active_enrollment(db, user)
            if enr is None:
                raise Forbidden("face_enrollment_required", "Enrol your face before you take home visits.")
            res = partner.verify(enr.template_ref or "", raw, scenario, seen)
    except ValueError as e:
        chk.status, chk.completed_at, chk.reason, chk.counted = "error", now, str(e)[:300], False
        db.commit()
        raise Unprocessable("bad_frames", str(e))
    except partner.PartnerError as e:
        chk.status, chk.completed_at, chk.reason, chk.counted = "error", now, str(e)[:300], False
        audit.record(db, user, "face.check.error", "face_check", chk.id, visit_id=chk.visit_id)
        db.commit()
        raise Conflict("face_partner_unavailable", "The identity service didn't answer. Check your connection "
                                                   "and try again. Your journey stays locked until a check passes.")
    chk.status, chk.reason, chk.completed_at = res.status, res.reason[:300], now
    chk.liveness_score, chk.match_score = res.liveness, res.match
    audit.record(db, user, f"face.check.{res.status}", "face_check", chk.id, purpose=chk.purpose,
                 visit_id=chk.visit_id, liveness=res.liveness, match=res.match,
                 signal=res.details.get("signal"))
    out = {"status": res.status, "reason": res.reason, "liveness": res.liveness, "match": res.match,
           "locked": False, "case_id": None}
    if res.status == "spoof":
        case = open_case(db, user, "spoof_suspected", f"Possible spoofing during a face check: {res.reason}",
                         visit_id=chk.visit_id, severity="high")
        out.update(locked=True, case_id=case.id)
    elif chk.purpose == "enroll" and res.status == "passed":
        out["enrollment"] = _create_enrollment(db, user, res, raw)
    elif chk.purpose == "visit":
        failed, attempts = _counts(db, user, chk.visit_id)
        out["attempts_left"] = max(0, MAX_FAILED - failed)
        if res.status == "passed":
            _on_visit_pass(db, user, db.get(HomeVisit, chk.visit_id), "face")
        elif failed >= MAX_FAILED or attempts >= MAX_ATTEMPTS:
            case = open_case(db, user, "repeated_failures",
                             f"{failed} failed face checks for one visit. Last: {res.reason}", visit_id=chk.visit_id)
            out.update(locked=True, case_id=case.id)
    db.commit()
    return out


def _create_enrollment(db: Session, user: User, res: partner.FaceResult, raw: list[bytes]) -> dict:
    # Demo personas skip ops approval, except after ops asked them to re-enrol.
    auto = _is_demo_persona(user) and partner.demo_mode() and db.scalars(select(IdentityCase.id).where(
        IdentityCase.user_id == user.id, IdentityCase.resolution == "require_reenrol")).first() is None
    status = "active" if auto else "pending_review"
    enr = FaceEnrollment(user_id=user.id, status=status, partner=partner.face_partner(), template_ref=res.reference,
                         photo=partner.profile_photo(raw), consent_version=CONSENT_VERSION,
                         liveness_score=res.liveness, activated_at=utcnow() if auto else None)
    db.add(enr)
    db.flush()
    if auto:
        _revoke_others(db, user, enr)
    now = utcnow()
    db.add(VerificationCheck(user_id=user.id, kind="face", partner=enr.partner, status="passed",
                             reference=enr.template_ref, summary="Live face captured with consent and enrolled.",
                             details={"liveness": res.liveness}, created_at=now, updated_at=now))
    audit.record(db, user, f"face.enroll.{status}", "face_enrollment", enr.id)
    if not auto and user.is_verified:
        # An approved doctor re-enrolling: ops compares the new face before it replaces the old one.
        open_case(db, user, "enrollment_review", "New face enrolment to approve.", severity="low",
                  blocking=False, alert=False)
    return enrollment_dict(enr)


def _revoke_others(db: Session, user: User, keep: FaceEnrollment) -> None:
    for e in db.scalars(select(FaceEnrollment).where(FaceEnrollment.user_id == user.id,
                                                     FaceEnrollment.id != keep.id,
                                                     FaceEnrollment.status != "revoked")):
        e.status, e.revoked_at, e.photo = "revoked", utcnow(), None  # minimise: drop the old photo


def _on_visit_pass(db: Session, user: User, v: HomeVisit, method: str) -> None:
    ensure_arrival_code(v)
    doc = db.get(Doctor, user.doctor_id)
    notify(db, users_for_patient(db, v.patient_id), "Your doctor's identity is verified",
           f"{doc.name} just passed Triyana's live face check for your visit. Check their photo in the app "
           f"when they arrive and ask for your arrival code.", f"visit:{v.id}")
    audit.record(db, user, "visit.identity_verified", "home_visit", v.id, method=method)


# ------------------------------------------------------------------ gates
def visit_pass(db: Session, user: User, visit_id: int) -> FaceCheck | None:
    now = utcnow()
    for chk in db.scalars(select(FaceCheck).where(FaceCheck.user_id == user.id, FaceCheck.visit_id == visit_id,
                                                  FaceCheck.purpose == "visit", FaceCheck.status == "passed")
                          .order_by(FaceCheck.id.desc())):
        valid = MANUAL_PASS_MINUTES if chk.method == "manual" else FACE_PASS_MINUTES
        if chk.completed_at and now - chk.completed_at <= timedelta(minutes=valid):
            return chk
    return None


def ever_passed(db: Session, user_id: int, visit_id: int) -> FaceCheck | None:
    return db.scalars(select(FaceCheck).where(FaceCheck.user_id == user_id, FaceCheck.visit_id == visit_id,
                                              FaceCheck.purpose == "visit", FaceCheck.status == "passed")
                      .order_by(FaceCheck.id.desc())).first()


def require_for_journey(db: Session, user: User, v: HomeVisit) -> None:
    """Start journey: needs a fresh pass for this exact visit by this exact account."""
    case = blocking_case(db, user)
    if case:
        raise _locked_error(case)
    require_enrolled(db, user)
    if visit_pass(db, user, v.id) is None:
        raise Forbidden("face_check_required",
                        "Verify your face for this visit before you start the journey.", visit_id=v.id)


def require_for_start(db: Session, user: User, v: HomeVisit, code: str | None) -> None:
    """Start visit at the door: a journey begun after a pass (or a fresh pass), plus the patient's code."""
    case = blocking_case(db, user)
    if case:
        raise _locked_error(case)
    passed = ever_passed(db, user.id, v.id)
    travelled = passed is not None and db.scalars(select(Trip.id).where(
        Trip.visit_id == v.id, Trip.user_id == user.id, Trip.started_at >= passed.completed_at)).first() is not None
    if not travelled and visit_pass(db, user, v.id) is None:
        raise Forbidden("face_check_required", "Verify your face for this visit before you start it.", visit_id=v.id)
    confirm_arrival(db, user, v, code)


def ensure_arrival_code(v: HomeVisit) -> str:
    if not v.arrival_code:
        v.arrival_code = f"{secrets.randbelow(10000):04d}"
        v.arrival_code_attempts = 0
    return v.arrival_code


def confirm_arrival(db: Session, user: User, v: HomeVisit, code: str | None) -> None:
    if v.arrival_confirmed_at:
        return
    expected = ensure_arrival_code(v)
    if (v.arrival_code_attempts or 0) >= ARRIVAL_CODE_TRIES:
        raise _locked_error(open_case(db, user, "arrival_code", "Too many wrong arrival codes.", visit_id=v.id))
    if not code or not hmac.compare_digest(str(code).strip(), expected):
        v.arrival_code_attempts = (v.arrival_code_attempts or 0) + 1
        audit.record(db, user, "visit.arrival_code.wrong", "home_visit", v.id, attempts=v.arrival_code_attempts)
        if v.arrival_code_attempts >= ARRIVAL_CODE_TRIES:
            open_case(db, user, "arrival_code", "Too many wrong arrival codes at the door.", visit_id=v.id)
        db.commit()
        raise Unprocessable("wrong_arrival_code", "Ask the patient for the 4-digit arrival code shown in their "
                                                  "Triyana app." if code else "Enter the patient's arrival code.",
                            attempts_left=max(0, ARRIVAL_CODE_TRIES - v.arrival_code_attempts))
    v.arrival_confirmed_at = utcnow()
    audit.record(db, user, "visit.arrival_code.confirmed", "home_visit", v.id)


def request_alternative(db: Session, user: User, visit_id: int | None, reason: str) -> dict:
    if user.role != Role.doctor:
        raise Forbidden("forbidden_role", "Only doctors use this.")
    if visit_id:
        _visit_for(db, user, visit_id)
    reasons = {"camera_unavailable": "Camera not available or permission denied",
               "accessibility": "Needs an accessible alternative to the face check",
               "keeps_failing": "Face check keeps failing",
               "other": "Other"}
    case = open_case(db, user, "alternative_requested", reasons.get(reason, reasons["other"]), visit_id=visit_id,
                     severity="low", blocking=False, alert=False)
    db.commit()
    return {"case_id": case.id, "status": case.status}


# ------------------------------------------------------------------ views
def enrollment_dict(e: FaceEnrollment | None, with_photo: bool = False) -> dict | None:
    if e is None:
        return None
    out = {"id": e.id, "status": e.status, "partner": e.partner, "created_at": e.created_at.isoformat() + "Z",
           "activated_at": e.activated_at.isoformat() + "Z" if e.activated_at else None}
    if with_photo:
        out["photo"] = e.photo
    return out


def provider_state(db: Session, user: User) -> dict:
    case = blocking_case(db, user)
    return {"required": user.role == Role.doctor, "consent_text": CONSENT_TEXT, "consent_version": CONSENT_VERSION,
            "enrollment": enrollment_dict(current_enrollment(db, user), with_photo=True),
            "active": active_enrollment(db, user) is not None,
            "locked": case is not None,
            "case": {"id": case.id, "kind": case.kind, "summary": case.summary} if case else None,
            "pass_minutes": FACE_PASS_MINUTES}


def visit_state(db: Session, user: User, visit_id: int) -> dict:
    v = _visit_for(db, user, visit_id)
    passed = visit_pass(db, user, v.id)
    failed, attempts = _counts(db, user, v.id)
    return {"visit_id": v.id, "verified": passed is not None,
            "verified_at": passed.completed_at.isoformat() + "Z" if passed else None,
            "method": passed.method if passed else None, "attempts_left": max(0, MAX_FAILED - failed),
            "locked": blocking_case(db, user) is not None, "arrival_confirmed": v.arrival_confirmed_at is not None}


def patient_view(db: Session, v: HomeVisit, doc_user: User | None) -> dict:
    """What the patient sees: never scores, templates or documents."""
    chk = ever_passed(db, doc_user.id, v.id) if doc_user else None
    open_visit = v.status in (VisitStatus.accepted, VisitStatus.in_progress)
    return {"verified": chk is not None,
            "verified_at": chk.completed_at.isoformat() + "Z" if chk else None,
            "method": ("Live face check" if chk.method == "face" else "Approved alternative check") if chk else None,
            "arrival_code": v.arrival_code if chk and open_visit and not v.arrival_confirmed_at else None,
            "arrival_confirmed": v.arrival_confirmed_at is not None}


def patient_profile(db: Session, patient_user: User, visit_id: int) -> dict:
    from .family import can_view_patient
    v = db.get(HomeVisit, visit_id)
    if v is None or not can_view_patient(db, patient_user, v.patient_id) or not v.doctor_id:
        raise NotFound("not_found", "Visit not found.")
    doc_user = db.scalars(select(User).where(User.doctor_id == v.doctor_id)).first()
    view = patient_view(db, v, doc_user)
    if not view["verified"] or v.status not in (VisitStatus.accepted, VisitStatus.in_progress):
        return {"verified": False}
    d = db.get(Doctor, v.doctor_id)
    enr = active_enrollment(db, doc_user)
    return {"verified": True, "verified_at": view["verified_at"], "method": view["method"], "name": d.name,
            "specialty": d.specialty, "qualification": d.qualification, "license_no": d.license_no,
            "medical_council": d.medical_council, "photo": enr.photo if enr else None}


# ------------------------------------------------------------------ approval + ops
def on_account_approved(db: Session, user: User) -> None:
    """Called when ops approves a provider: a doctor's pending face enrolment becomes active."""
    if user.role != Role.doctor:
        return
    if active_enrollment(db, user):
        return
    enr = current_enrollment(db, user)
    if enr is None:
        raise Conflict("face_enrollment_required",
                       "The doctor must enrol their face first. In the Partner app, open Home and tap "
                       "Enrol my face, then approve again.")
    enr.status, enr.activated_at = "active", utcnow()
    _revoke_others(db, user, enr)
    audit.record(db, None, "face.enroll.active", "face_enrollment", enr.id)


def withdraw_consent(db: Session, user: User) -> dict:
    for e in db.scalars(select(FaceEnrollment).where(FaceEnrollment.user_id == user.id,
                                                     FaceEnrollment.status != "revoked")):
        e.status, e.revoked_at, e.photo = "revoked", utcnow(), None
    db.add(Consent(user_id=user.id, purpose="biometric_face", granted=False, notice_version=CONSENT_VERSION))
    user.on_duty = False
    audit.record(db, user, "face.consent.withdrawn", "user", user.id)
    db.commit()
    return provider_state(db, user)


def case_dict(db: Session, c: IdentityCase) -> dict:
    u = db.get(User, c.user_id)
    enr = current_enrollment(db, u)
    checks = db.scalars(select(FaceCheck).where(FaceCheck.user_id == u.id).order_by(FaceCheck.id.desc()).limit(8))
    return {"id": c.id, "kind": c.kind, "severity": c.severity, "blocking": c.blocking, "status": c.status,
            "summary": c.summary, "visit_id": c.visit_id, "created_at": c.created_at.isoformat() + "Z",
            "resolution": c.resolution, "resolution_note": c.resolution_note,
            "resolved_at": c.resolved_at.isoformat() + "Z" if c.resolved_at else None,
            "provider": {"id": u.id, "name": u.name, "email": u.email, "verification_status": u.verification_status},
            "enrollment": enrollment_dict(enr, with_photo=True),
            "recent_checks": [check_dict(x) for x in checks]}


def check_dict(c: FaceCheck) -> dict:
    return {"id": c.id, "user_id": c.user_id, "visit_id": c.visit_id, "purpose": c.purpose, "method": c.method,
            "status": c.status, "reason": c.reason, "action": c.action, "liveness": c.liveness_score,
            "match": c.match_score, "partner": c.partner, "approved_by": c.approved_by,
            "at": (c.completed_at or c.created_at).isoformat() + "Z"}


def list_cases(db: Session, status: str = "open") -> list[dict]:
    rows = db.scalars(select(IdentityCase).where(IdentityCase.status == status).order_by(IdentityCase.id.desc())
                      .limit(100))
    return [case_dict(db, c) for c in rows]


def recent_checks(db: Session, limit: int = 100) -> list[dict]:
    rows = db.scalars(select(FaceCheck).where(FaceCheck.status != "issued").order_by(FaceCheck.id.desc())
                      .limit(min(limit, 500))).all()
    names = {u.id: u.name for u in db.scalars(select(User).where(User.id.in_({r.user_id for r in rows})))}
    return [check_dict(r) | {"provider": names.get(r.user_id)} for r in rows]


RESOLUTIONS = ("allow_retry", "approve_alternative", "require_reenrol", "approve_enrollment", "reject_enrollment",
               "suspend", "dismiss")


def resolve_case(db: Session, case_id: int, action: str, note: str) -> dict:
    case = db.get(IdentityCase, case_id)
    if case is None:
        raise NotFound("not_found", "Case not found.")
    if case.status != "open":
        raise Conflict("case_closed", "This case is already resolved.")
    if action not in RESOLUTIONS:
        raise Unprocessable("bad_action", "Unknown action.")
    note = (note or "").strip()
    if len(note) < 5:
        raise Unprocessable("note_required", "Add a note saying what you checked.")
    user = db.get(User, case.user_id)
    now = utcnow()
    if action in ("allow_retry", "approve_alternative", "dismiss"):
        for chk in db.scalars(select(FaceCheck).where(FaceCheck.user_id == user.id, FaceCheck.counted.is_(True))):
            chk.counted = False
        if case.kind == "arrival_code" and case.visit_id:
            db.get(HomeVisit, case.visit_id).arrival_code_attempts = 0
    if action == "approve_alternative":
        v = db.get(HomeVisit, case.visit_id) if case.visit_id else None
        if v is None or v.status != VisitStatus.accepted:
            raise Conflict("no_visit", "An alternative check is approved for one accepted visit. This case has none.")
        chk = FaceCheck(user_id=user.id, visit_id=v.id, purpose="visit", method="manual", status="passed",
                        reason="Identity confirmed by Triyana ops through an approved alternative check.",
                        partner="ops", approved_by=note[:300], created_at=now, completed_at=now)
        db.add(chk)
        db.flush()
        _on_visit_pass(db, user, v, "manual")
    elif action == "require_reenrol":
        for e in db.scalars(select(FaceEnrollment).where(FaceEnrollment.user_id == user.id,
                                                         FaceEnrollment.status != "revoked")):
            e.status, e.revoked_at, e.photo = "revoked", now, None
        user.on_duty = False
    elif action in ("approve_enrollment", "reject_enrollment"):
        enr = current_enrollment(db, user)
        if enr is None or enr.status != "pending_review":
            raise Conflict("no_enrollment", "There's no new face enrolment waiting.")
        if action == "approve_enrollment":
            enr.status, enr.activated_at = "active", now
            _revoke_others(db, user, enr)
        else:
            enr.status, enr.revoked_at, enr.photo = "revoked", now, None
    elif action == "suspend":
        user.verification_status, user.verification_note, user.on_duty = "rejected", f"Suspended: {note}"[:300], False
        if user.doctor_id:
            db.get(Doctor, user.doctor_id).license_verified = False
        audit.record(db, None, "provider.verification.rejected", "user", user.id, note=note)
    case.status, case.resolution, case.resolution_note, case.resolved_at = "resolved", action, note[:300], now
    audit.record(db, None, f"identity.case.resolved.{action}", "identity_case", case.id, user_id=user.id, note=note)
    db.commit()
    return case_dict(db, case)


def seed_demo_enrollments(db: Session) -> None:
    """Demo doctors start enrolled (no photo), so the demo works straight after a reset."""
    if not partner.demo_mode():
        return
    for u in db.scalars(select(User).where(User.role == Role.doctor, User.email.is_(None))):
        if current_enrollment(db, u) is None and (u.verification_status or "verified") == "verified":
            db.add(FaceEnrollment(user_id=u.id, status="active", partner="demo",
                                  template_ref=f"FACE-DEMO-SEED-{u.id}", consent_version=CONSENT_VERSION,
                                  activated_at=utcnow(), note="Demo persona, enrolled at seed"))
    db.flush()
