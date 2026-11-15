"""Heros cancel at the door: once a Hero has reached the patient and can't go ahead (no answer on the
phone or at the door, wrong address, refused, unsafe...), they cancel the job with a reason.

Covers the jobs Heros do at a patient's home: doctor visits (all specialties), lab sample collections
and physio sessions. Medicine deliveries are not covered (a failed delivery has to go back to the pharmacy).

Demo money rules (kept simple on purpose, see docs/HERO_CANCELLATIONS.md):
* The patient is never charged for a cancelled job: visits charge nothing, lab payment holds are voided,
  a missed physio session in a package is replaced at the end of the package.
* The Hero gets a flat "wasted trip" pay (TRIYANA_NO_SHOW_PAY, default ₹100) for every reason except
  "Other", which Triyana's team reviews in /admin.
* "Not answering" and "Not at the address" need at least one in-app call and a short wait at the door
  (TRIYANA_NO_SHOW_WAIT_MIN; 5 minutes live, 1 minute on the demo).
"""
from __future__ import annotations

import os
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import is_demo
from ..errors import Conflict, NotFound, Unprocessable
from ..models import (Earning, HeroCancellation, HomeVisit, LabBooking, Patient, PatientCallAttempt, PhysioBooking,
                      PhysioSession, Role, Trip, User, VisitStatus, utcnow)
from . import dispatch
from .common import notify, users_for_patient

KINDS = ("visit", "lab", "physio")

# code -> (what the Hero sees, a hint for the Hero, needs a call + wait first)
REASONS: dict[str, tuple[str, str, bool]] = {
    "not_answering": ("Patient not answering phone or door", "Call the patient and wait a few minutes first.", True),
    "not_at_address": ("Patient not at the address", "Call the patient and wait a few minutes first.", True),
    "wrong_address": ("Wrong or incomplete address", "You couldn't find the home from the address given.", False),
    "patient_refused": ("Patient refused the visit", "The patient or family said they don't want it now.", False),
    "unsafe": ("Unsafe to go in", "You don't feel safe at this location. Leave first, then cancel.", False),
    "other": ("Other reason", "Tell us what happened.", False),
}

KIND_LABEL = {"visit": "Home visit", "lab": "Sample collection", "physio": "Physio session"}


def wait_seconds() -> int:
    default = "1" if is_demo() else "5"
    try:
        return max(0, int(float(os.environ.get("TRIYANA_NO_SHOW_WAIT_MIN", default)) * 60))
    except ValueError:
        return 300


def no_show_pay() -> float:
    try:
        return max(0.0, float(os.environ.get("TRIYANA_NO_SHOW_PAY", "100")))
    except ValueError:
        return 100.0


# ------------------------------------------------------------------ finding the job
def _open_trip(db: Session, kind: str, job_id: int, user: User) -> Trip | None:
    col = {"visit": Trip.visit_id, "lab": Trip.lab_booking_id, "physio": Trip.physio_session_id}[kind]
    q = select(Trip).where(col == job_id, Trip.user_id == user.id, Trip.ended_at.is_(None), Trip.leg == "to_patient")
    return db.scalars(q.order_by(Trip.id.desc())).first()


def _job(db: Session, user: User, kind: str, job_id: int):
    """The job (still waiting to start), its patient id and booking ref, or 404/409."""
    if kind == "visit" and user.role == Role.doctor:
        v = db.get(HomeVisit, job_id)
        if v and v.doctor_id == user.doctor_id:
            if v.status != VisitStatus.accepted:
                raise Conflict("bad_visit_state", "This visit has already started or ended, so it can't be cancelled here.")
            return v, v.patient_id, v.booking_ref or f"V{v.id}"
    elif kind == "lab" and user.role == Role.phlebotomist:
        b = db.get(LabBooking, job_id)
        if b and b.phlebotomist_user_id == user.id:
            if b.status != "assigned":
                raise Conflict("bad_lab_state", "This collection has already happened or ended, so it can't be cancelled here.")
            return b, b.patient_id, b.booking_ref
    elif kind == "physio" and user.role == Role.physio:
        s = db.get(PhysioSession, job_id)
        if s and s.booking.physio_id == user.physio_id:
            if s.status != "scheduled" or s.booking.status != "active":
                raise Conflict("bad_session_state", "This session has already started or ended, so it can't be cancelled here.")
            return s, s.booking.patient_id, s.booking.ref
    raise NotFound("not_found", "Job not found.")


def _arrival(db: Session, kind: str, job_id: int, user: User):
    """When the Hero reached the patient's home on this job's trip, or None if they haven't yet."""
    t = _open_trip(db, kind, job_id, user)
    if t is None:
        return None
    if t.arrived_at is None and dispatch.tick(db, t)["remaining_m"] <= 0:
        t.arrived_at = t.arrived_at or utcnow()
    return t.arrived_at


def _calls(db: Session, user: User, kind: str, job_id: int) -> int:
    return db.scalar(select(func.count(PatientCallAttempt.id)).where(
        PatientCallAttempt.provider_user_id == user.id, PatientCallAttempt.kind == kind,
        PatientCallAttempt.job_id == job_id)) or 0


def _check_kind(kind: str) -> None:
    if kind not in KINDS:
        raise NotFound("not_found", "Job not found.")


# ------------------------------------------------------------------ Hero actions
def info(db: Session, user: User, kind: str, job_id: int) -> dict:
    _check_kind(kind)
    _, patient_id, ref = _job(db, user, kind, job_id)
    arrived_at = _arrival(db, kind, job_id, user)
    waited = int((utcnow() - arrived_at).total_seconds()) if arrived_at else 0
    need = wait_seconds()
    db.commit()
    return {"kind": kind, "job_id": job_id, "booking_ref": ref, "arrived": arrived_at is not None,
            "patient": db.get(Patient, patient_id).name, "calls": _calls(db, user, kind, job_id),
            "wait_s": need, "wait_left_s": max(0, need - waited) if arrived_at else need,
            "hero_pay": no_show_pay(),
            "reasons": [{"code": c, "label": lab, "hint": hint, "needs_call_and_wait": gate,
                         "paid": c != "other"} for c, (lab, hint, gate) in REASONS.items()]}


def call(db: Session, user: User, kind: str, job_id: int) -> dict:
    """Log an in-app call to the patient and hand back the number to dial (None if none on file)."""
    _check_kind(kind)
    _, patient_id, _ = _job(db, user, kind, job_id)
    db.add(PatientCallAttempt(provider_user_id=user.id, kind=kind, job_id=job_id))
    phone = next((u.phone for u in users_for_patient(db, patient_id) if u.phone), None)
    notify(db, users_for_patient(db, patient_id), "Your Triyana Hero is calling you",
           "They're at your address. Please pick up or open the door.", f"{kind}:{job_id}")
    audit.record(db, user, "hero.call_patient", kind, job_id)
    db.commit()
    return {"phone": phone, "calls": _calls(db, user, kind, job_id)}


def cancel(db: Session, user: User, kind: str, job_id: int, reason: str, note: str = "") -> HeroCancellation:
    _check_kind(kind)
    job, patient_id, ref = _job(db, user, kind, job_id)
    if reason not in REASONS:
        raise Unprocessable("bad_reason", "Pick a reason for cancelling.")
    note = (note or "").strip()[:300]
    if reason == "other" and len(note) < 5:
        raise Unprocessable("note_required", "Write a short note about what happened.")
    arrived_at = _arrival(db, kind, job_id, user)
    if arrived_at is None:
        raise Conflict("not_arrived", "You can cancel here once you've reached the patient's address.")
    waited = int((utcnow() - arrived_at).total_seconds())
    calls = _calls(db, user, kind, job_id)
    if REASONS[reason][2]:
        if calls < 1:
            raise Conflict("call_first", "Call the patient from the app first. They may be on their way to the door.")
        left = wait_seconds() - waited
        if left > 0:
            m, s = divmod(left, 60)
            raise Conflict("wait_more", f"Please wait {m} min {s:02d} s more at the door before cancelling for this reason.")

    pay = no_show_pay() if reason != "other" else 0.0
    rec = HeroCancellation(kind=kind, job_id=job_id, booking_ref=ref, provider_user_id=user.id, patient_id=patient_id,
                           reason=reason, note=note, calls=calls, waited_s=max(0, waited), hero_paid=pay)
    db.add(rec)
    db.flush()
    who = _hero_name(db, user)
    msg = patient_message(rec, who)
    if kind == "visit":
        _cancel_visit(db, job, msg)
    elif kind == "lab":
        from . import labs
        labs._cancel(db, job, "Sample collection cancelled", msg["text"])
    else:
        _cancel_physio_session(db, job, msg)
    if pay:
        p = db.get(Patient, patient_id)
        db.add(Earning(user_id=user.id, kind="no_show", title=f"Wasted trip · {p.name.split()[0]} ({ref})",
                       base=pay, total=pay))
        notify(db, [user], f"You earned ₹{pay:,.0f}", "Wasted trip pay for the cancelled job. Added to your balance.",
               "earnings")
    audit.record(db, user, "hero.cancel_at_door", kind, job_id, reason=reason, calls=calls, waited_s=waited)
    db.commit()
    return rec


def _cancel_visit(db: Session, v: HomeVisit, msg: dict) -> None:
    from . import perks
    v.status = VisitStatus.cancelled
    perks.on_cancel(db, v)
    dispatch.close_offers_for_visit(db, v)
    dispatch.end_trips_for(db, visit_id=v.id)
    notify(db, users_for_patient(db, v.patient_id), msg["title"], msg["text"], f"visit:{v.id}")


def _cancel_physio_session(db: Session, s: PhysioSession, msg: dict) -> None:
    from .physio import PACKAGE_GAP_DAYS
    s.status = "cancelled"
    for t in db.scalars(select(Trip).where(Trip.physio_session_id == s.id, Trip.ended_at.is_(None))):
        dispatch.end_trip(db, t)
    b: PhysioBooking = s.booking
    if b.sessions_total <= 1:
        b.status = "cancelled"
    else:  # the patient keeps the session they paid for: add a replacement at the end of the package
        last = max(b.sessions, key=lambda x: x.scheduled_for)
        db.add(PhysioSession(booking_id=b.id, number=max(x.number for x in b.sessions) + 1,
                             scheduled_for=max(last.scheduled_for, utcnow()) + timedelta(days=PACKAGE_GAP_DAYS),
                             status="scheduled"))
    notify(db, users_for_patient(db, b.patient_id), msg["title"], msg["text"], f"physio:{b.id}")


def _hero_name(db: Session, user: User) -> str:
    card = dispatch._provider_card(db, user) or {}
    return card.get("name") or user.name.split(" (")[0]


# ------------------------------------------------------------------ what the patient sees
_PATIENT_WHY = {
    "not_answering": "{who} reached your address but couldn't reach you by phone or at the door.",
    "not_at_address": "{who} reached your address but no one was there.",
    "wrong_address": "{who} couldn't find your home from the address on the booking. Please check it before booking again.",
    "patient_refused": "The visit was declined at the door.",
    "unsafe": "{who} couldn't safely reach your door.",
    "other": "{who} had to cancel at your address.",
}
_PATIENT_LABEL = {"not_answering": "Couldn't reach you", "not_at_address": "No one at the address",
                  "wrong_address": "Address not found", "patient_refused": "Declined at the door",
                  "unsafe": "Couldn't reach your door safely", "other": "Cancelled at your address"}


def _money_line(rec: HeroCancellation, db: Session | None = None) -> str:
    if rec.kind == "lab":
        return "Any payment hold has been released. You can book again any time."
    if rec.kind == "physio":
        s = db.get(PhysioSession, rec.job_id) if db else None
        if s and s.booking.sessions_total > 1:
            return "This session isn't counted: we added a replacement at the end of your package. You can move it to a time that suits you."
        return "You have not been charged. You can book again any time."
    return "You have not been charged. You can book again any time."


def patient_message(rec: HeroCancellation, who: str, db: Session | None = None) -> dict:
    from sqlalchemy.orm import object_session
    db = db or object_session(rec)
    why = _PATIENT_WHY[rec.reason].format(who=who)
    if rec.reason == "other" and rec.note:
        why += f' Their note: "{rec.note}"'
    title = {"visit": "Your home visit was cancelled", "lab": "Your sample collection was cancelled",
             "physio": "Your physio session was cancelled"}[rec.kind]
    return {"title": title, "text": f"{why} {_money_line(rec, db)}"}


def for_job(db: Session, kind: str, job_id: int) -> dict | None:
    """The Hero's cancellation of this job as the patient sees it, or None."""
    rec = db.scalars(select(HeroCancellation).where(HeroCancellation.kind == kind, HeroCancellation.job_id == job_id)
                     .order_by(HeroCancellation.id.desc())).first()
    if rec is None:
        return None
    m = patient_message(rec, _hero_name(db, rec.provider), db)
    return {"by": "provider", "reason": rec.reason, "label": _PATIENT_LABEL[rec.reason], "message": m["text"],
            "at": rec.created_at.isoformat()}


# ------------------------------------------------------------------ Triyana ops (/admin)
def admin_list(db: Session, limit: int = 200) -> list[dict]:
    rows = db.scalars(select(HeroCancellation).order_by(HeroCancellation.id.desc()).limit(limit)).all()
    return [{"id": r.id, "at": r.created_at.isoformat(), "kind": r.kind, "kind_label": KIND_LABEL[r.kind],
             "booking_ref": r.booking_ref, "hero": _hero_name(db, r.provider), "hero_role": r.provider.role.value,
             "patient": r.patient.name if r.patient else "", "reason": r.reason, "reason_label": REASONS[r.reason][0],
             "note": r.note, "calls": r.calls, "waited_min": round(r.waited_s / 60, 1), "hero_paid": r.hero_paid}
            for r in rows]
