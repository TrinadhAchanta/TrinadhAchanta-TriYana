"""Patient booking of doctor home visits: nearest verified doctors, free slots, book and cancel."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..adapters.geo import haversine_km
from ..errors import Conflict, NotFound, Unprocessable
from ..models import Doctor, HomeVisit, Patient, User, VisitStatus, utcnow
from .common import new_ref, notify, users_for_doctor, users_for_patient

SERVICE_RADIUS_KM = 15.0
LOCAL_TZ = timezone(timedelta(hours=5, minutes=30))  # demo jurisdiction (DEMO-IN) runs on IST
FIRST_HOUR, LAST_HOUR = 9, 19
BOOKING_DAYS = 3
MIN_LEAD = timedelta(minutes=60)
OPEN_STATES = (VisitStatus.requested, VisitStatus.accepted, VisitStatus.in_progress)


def _distance(doc: Doctor, patient: Patient) -> float:
    return round(haversine_km(patient.lat, patient.lng, doc.lat, doc.lng), 1)


def _nearby_doctors(db: Session, patient: Patient) -> list[tuple[Doctor, float]]:
    docs = db.scalars(select(Doctor).where(Doctor.license_verified.is_(True))).all()
    rows = [(d, _distance(d, patient)) for d in docs]
    rows = [r for r in rows if r[1] <= SERVICE_RADIUS_KM and r[0].jurisdiction == patient.jurisdiction]
    return sorted(rows, key=lambda r: (r[1], -r[0].rating))


def _all_slots(now: datetime) -> list[datetime]:
    """Hourly slots for the next few days, in UTC (naive), from the local working day."""
    local_now = now.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)
    out = []
    for d in range(BOOKING_DAYS):
        day = (local_now + timedelta(days=d)).date()
        for h in range(FIRST_HOUR, LAST_HOUR + 1):
            local = datetime(day.year, day.month, day.day, h, tzinfo=LOCAL_TZ)
            utc = local.astimezone(timezone.utc).replace(tzinfo=None)
            if utc >= now + MIN_LEAD:
                out.append(utc)
    return out


def _booked(db: Session, doctor_id: int) -> set[datetime]:
    return set(db.scalars(select(HomeVisit.scheduled_for).where(
        HomeVisit.doctor_id == doctor_id, HomeVisit.status.in_(OPEN_STATES))))


def free_slots(db: Session, doctor_id: int) -> list[datetime]:
    taken = _booked(db, doctor_id)
    return [s for s in _all_slots(utcnow()) if s not in taken]


def travel_minutes(km: float) -> int:
    return int(10 + km * 4)


def doctor_to_dict(doc: Doctor, km: float | None, slots: list[datetime] | None = None) -> dict:
    return {
        "id": doc.id, "name": doc.name, "specialty": doc.specialty, "license_no": doc.license_no,
        "license_verified": doc.license_verified, "medical_council": doc.medical_council,
        "qualification": doc.qualification, "registration_year": doc.registration_year, "rating": doc.rating, "rating_count": doc.rating_count,
        "experience_years": doc.experience_years, "visit_fee": doc.visit_fee, "languages": doc.languages or [],
        "about": doc.about, "area": doc.area, "distance_km": km,
        "arrives_in_min": travel_minutes(km) if km is not None else None,
        "next_slot": slots[0].isoformat() if slots else None,
    }


def list_doctors(db: Session, patient: Patient) -> list[dict]:
    out = []
    for doc, km in _nearby_doctors(db, patient):
        out.append(doctor_to_dict(doc, km, free_slots(db, doc.id)))
    return out


def slots_for(db: Session, patient: Patient, doctor_id: int | None) -> list[str]:
    if doctor_id is None:
        union: set[datetime] = set()
        for doc, _ in _nearby_doctors(db, patient):
            union.update(free_slots(db, doc.id))
        return [s.isoformat() for s in sorted(union)]
    doc = _nearby_doctor_or_404(db, patient, doctor_id)
    return [s.isoformat() for s in free_slots(db, doc.id)]


def _nearby_doctor_or_404(db: Session, patient: Patient, doctor_id: int) -> Doctor:
    for doc, _ in _nearby_doctors(db, patient):
        if doc.id == doctor_id:
            return doc
    raise NotFound("not_found", "Doctor not found or not available in your area.")


def _parse(ts: str) -> datetime:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Unprocessable("bad_time", "Please pick a time from the list.") from exc
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.replace(second=0, microsecond=0)


def book(db: Session, user: User, doctor_id: int | None, scheduled_for: str, reason: str, address: str) -> HomeVisit:
    patient = db.get(Patient, user.patient_id)
    when = _parse(scheduled_for)
    if doctor_id is None:
        # "Nearest available doctor": closest verified doctor who is free at that time.
        doc = next((d for d, _ in _nearby_doctors(db, patient) if when in free_slots(db, d.id)), None)
        if doc is None:
            raise Conflict("slot_taken", "No nearby doctor is free at that time. Please pick another time.")
    else:
        doc = _nearby_doctor_or_404(db, patient, doctor_id)
        if when not in free_slots(db, doc.id):
            raise Conflict("slot_taken", "That time is no longer available. Please pick another time.")
    visit = HomeVisit(doctor_id=doc.id, patient_id=patient.id, status=VisitStatus.requested,
                      reason=reason.strip(), scheduled_for=when, booking_ref=new_ref("BK"),
                      address=(address.strip() or patient.address), fee=doc.visit_fee)
    db.add(visit)
    db.flush()
    local = when.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ).strftime("%a %d %b, %I:%M %p")
    notify(db, users_for_doctor(db, doc.id), "New home visit request",
           f"{patient.name} booked a home visit for {local}. Reason: {visit.reason}", f"visit:{visit.id}")
    notify(db, users_for_patient(db, patient.id), "Booking request sent",
           f"{doc.name} has your request for {local}. You'll be told as soon as it's confirmed.", f"visit:{visit.id}")
    audit.record(db, user, "visit.book", "home_visit", visit.id, doctor_id=doc.id, auto_matched=doctor_id is None)
    db.commit()
    return visit


def visit_to_dict(v: HomeVisit, patient: Patient | None = None) -> dict:
    km = _distance(v.doctor, patient) if patient else None
    return {
        "id": v.id, "booking_ref": v.booking_ref, "status": v.status.value, "reason": v.reason,
        "scheduled_for": v.scheduled_for.isoformat(), "address": v.address, "fee": v.fee,
        "doctor": doctor_to_dict(v.doctor, km),
        "can_cancel": v.status in (VisitStatus.requested, VisitStatus.accepted),
    }


def list_for_patient(db: Session, user: User) -> list[dict]:
    patient = db.get(Patient, user.patient_id)
    rows = db.scalars(select(HomeVisit).where(HomeVisit.patient_id == patient.id)
                      .order_by(HomeVisit.scheduled_for.desc())).all()
    return [visit_to_dict(v, patient) for v in rows]


def cancel(db: Session, user: User, visit_id: int) -> HomeVisit:
    v = db.get(HomeVisit, visit_id)
    if v is None or v.patient_id != user.patient_id:
        raise NotFound("not_found", "Visit not found.")
    if v.status not in (VisitStatus.requested, VisitStatus.accepted):
        raise Conflict("bad_visit_state", "This visit can no longer be cancelled.")
    v.status = VisitStatus.cancelled
    notify(db, users_for_doctor(db, v.doctor_id), "Home visit cancelled",
           f"{v.patient.name} cancelled their visit.", f"visit:{v.id}")
    audit.record(db, user, "visit.cancel", "home_visit", v.id)
    db.commit()
    return v
