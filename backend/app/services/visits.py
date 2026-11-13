"""Patient booking of doctor home visits: nearest verified doctors, free slots, book and cancel."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..adapters.geo import haversine_km
from ..errors import Conflict, NotFound, Unprocessable
from ..models import Doctor, DoctorAvailability, HomeVisit, Patient, User, VisitStatus, utcnow
from . import dispatch, perks, visit_notes
from .common import new_ref, notify, users_for_doctor, users_for_patient

SERVICE_RADIUS_KM = 15.0
LOCAL_TZ = timezone(timedelta(hours=5, minutes=30))  # demo jurisdiction (DEMO-IN) runs on IST
FIRST_HOUR, LAST_HOUR = 9, 19
DEFAULT_HOURS = list(range(FIRST_HOUR, LAST_HOUR + 1))  # used on days a doctor hasn't set
OPENABLE_HOURS = list(range(7, 22))  # hours a doctor may open in the doctor app (7 AM to 9 PM starts)
BOOKING_DAYS = 7
MIN_LEAD = timedelta(minutes=60)
FOLLOW_UP_SOON = timedelta(hours=24)  # previous doctor counts as "available" if free within this
OPEN_STATES = (VisitStatus.requested, VisitStatus.accepted, VisitStatus.in_progress)


def _distance(doc: Doctor, patient: Patient) -> float:
    return round(haversine_km(patient.lat, patient.lng, doc.lat, doc.lng), 1)


def _nearby_doctors(db: Session, patient: Patient) -> list[tuple[Doctor, float]]:
    docs = db.scalars(select(Doctor).where(Doctor.license_verified.is_(True))).all()
    rows = [(d, _distance(d, patient)) for d in docs]
    rows = [r for r in rows if r[1] <= SERVICE_RADIUS_KM and r[0].jurisdiction == patient.jurisdiction]
    return sorted(rows, key=lambda r: (r[1], -r[0].rating))


def _local_days(now: datetime) -> list[date]:
    local_now = now.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)
    return [(local_now + timedelta(days=d)).date() for d in range(BOOKING_DAYS)]


def _to_utc(day: date, hour: int) -> datetime:
    local = datetime(day.year, day.month, day.day, hour, tzinfo=LOCAL_TZ)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def _all_slots(now: datetime, hours_for: dict[str, list[int]] | None = None) -> list[datetime]:
    """Bookable hourly slots for the next few days, in UTC (naive).

    `hours_for` maps a local date (YYYY-MM-DD) to the hours a doctor opened that day;
    days missing from it use the default working hours.
    """
    hours_for = hours_for or {}
    out = []
    for day in _local_days(now):
        for h in sorted(hours_for.get(day.isoformat(), DEFAULT_HOURS)):
            utc = _to_utc(day, h)
            if utc >= now + MIN_LEAD:
                out.append(utc)
    return out


def _schedule(db: Session, doctor_id: int) -> dict[str, list[int]]:
    rows = db.scalars(select(DoctorAvailability).where(DoctorAvailability.doctor_id == doctor_id)).all()
    return {r.day: list(r.hours or []) for r in rows}


def _booked(db: Session, doctor_id: int) -> set[datetime]:
    return set(db.scalars(select(HomeVisit.scheduled_for).where(
        HomeVisit.doctor_id == doctor_id, HomeVisit.status.in_(OPEN_STATES))))


def free_slots(db: Session, doctor_id: int) -> list[datetime]:
    taken = _booked(db, doctor_id)
    return [s for s in _all_slots(utcnow(), _schedule(db, doctor_id)) if s not in taken]


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


def soonest(db: Session, patient: Patient, exclude: int | None = None) -> tuple[Doctor, float, datetime] | None:
    """Whoever can come first: the earliest free slot across nearby doctors, nearest doctor on a tie."""
    best = None
    for doc, km in _nearby_doctors(db, patient):
        if doc.id == exclude:
            continue
        slots = free_slots(db, doc.id)
        if slots and (best is None or slots[0] < best[2]):
            best = (doc, km, slots[0])
    return best


def soonest_to_dict(db: Session, patient: Patient, exclude: int | None = None) -> dict | None:
    hit = soonest(db, patient, exclude)
    if hit is None:
        return None
    doc, km, slot = hit
    return {"doctor": doctor_to_dict(doc, km, [slot]), "slot": slot.isoformat()}


def _previous_visit(db: Session, patient_id: int) -> HomeVisit | None:
    return db.scalars(select(HomeVisit).where(HomeVisit.patient_id == patient_id,
                                              HomeVisit.status == VisitStatus.completed)
                      .order_by(HomeVisit.scheduled_for.desc(), HomeVisit.id.desc())).first()


def follow_up(db: Session, user: User) -> dict:
    """Suggest the doctor from the patient's last visit, and whether they can come soon."""
    patient = db.get(Patient, user.patient_id)
    prev = _previous_visit(db, patient.id)
    if prev is None:
        return {"previous_visit": None, "doctor": None, "available_soon": False, "next_slot": None,
                "alternative": soonest_to_dict(db, patient)}
    nearby = {d.id: km for d, km in _nearby_doctors(db, patient)}
    bookable = prev.doctor_id in nearby
    slots = free_slots(db, prev.doctor_id) if bookable else []
    nxt = slots[0] if slots else None
    soon = nxt is not None and nxt - utcnow() <= FOLLOW_UP_SOON
    return {
        "previous_visit": {"id": prev.id, "booking_ref": prev.booking_ref, "reason": prev.reason,
                           "date": prev.scheduled_for.isoformat()},
        "doctor": doctor_to_dict(prev.doctor, nearby.get(prev.doctor_id), slots),
        "bookable": bookable,
        "available_soon": soon,
        "next_slot": nxt.isoformat() if nxt else None,
        # Someone who can come sooner, offered when the usual doctor can't come soon.
        "alternative": None if soon else soonest_to_dict(db, patient, exclude=prev.doctor_id),
    }


def book(db: Session, user: User, doctor_id: int | None, scheduled_for: str, reason: str, address: str,
         asap: bool = False, follow_up_of: int | None = None, cashless: bool = False) -> HomeVisit:
    patient = db.get(Patient, user.patient_id)
    prev = None
    if follow_up_of is not None:
        prev = db.get(HomeVisit, follow_up_of)
        if prev is None or prev.patient_id != patient.id:
            raise NotFound("not_found", "Previous visit not found.")
        if prev.status != VisitStatus.completed:
            raise Conflict("bad_visit_state", "You can only book a follow-up after a completed visit.")
    if asap:
        # "Whoever is available soonest": the earliest free slot of any nearby doctor.
        hit = soonest(db, patient)
        if hit is None:
            raise Conflict("slot_taken", "No nearby doctor has a free time right now. Please pick a time.")
        doc, _, when = hit
    elif doctor_id is None:
        when = _parse(scheduled_for)
        # "Nearest available doctor": closest verified doctor who is free at that time.
        doc = next((d for d, _ in _nearby_doctors(db, patient) if when in free_slots(db, d.id)), None)
        if doc is None:
            raise Conflict("slot_taken", "No nearby doctor is free at that time. Please pick another time.")
    else:
        when = _parse(scheduled_for)
        doc = _nearby_doctor_or_404(db, patient, doctor_id)
        if when not in free_slots(db, doc.id):
            raise Conflict("slot_taken", "That time is no longer available. Please pick another time.")
    visit = HomeVisit(doctor_id=doc.id, patient_id=patient.id, status=VisitStatus.requested,
                      reason=reason.strip(), scheduled_for=when, booking_ref=new_ref("BK"),
                      address=(address.strip() or patient.address), fee=doc.visit_fee,
                      follow_up_of_id=prev.id if prev else None)
    db.add(visit)
    db.flush()
    perks.bill_visit(db, visit, cashless)
    dispatch.offer_booked_visit(db, visit)
    local = when.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ).strftime("%a %d %b, %I:%M %p")
    kind = "follow-up visit" if prev else "home visit"
    seen_before = " You saw them before." if prev and prev.doctor_id == doc.id else ""
    notify(db, users_for_doctor(db, doc.id), f"New {kind} request",
           f"{patient.name} booked a {kind} for {local}.{seen_before} Reason: {visit.reason}", f"visit:{visit.id}")
    notify(db, users_for_patient(db, patient.id), "Booking request sent",
           f"{doc.name} has your request for {local}. You'll be told as soon as it's confirmed.", f"visit:{visit.id}")
    audit.record(db, user, "visit.book", "home_visit", visit.id, doctor_id=doc.id, auto_matched=doctor_id is None,
                 asap=asap, follow_up_of=prev.id if prev else None)
    db.commit()
    return visit


def follow_up_info(v: HomeVisit) -> dict | None:
    p = v.follow_up_of
    if p is None:
        return None
    return {"id": p.id, "booking_ref": p.booking_ref, "date": p.scheduled_for.isoformat(),
            "same_doctor": p.doctor_id == v.doctor_id}


# ------------------------------------------------------------ doctor availability
def _day_dict(day: date, hours: list[int] | None, booked: set[datetime], now: datetime) -> dict:
    opened = sorted(hours) if hours is not None else DEFAULT_HOURS
    booked_hours = sorted(h for h in OPENABLE_HOURS if _to_utc(day, h) in booked)
    past = [h for h in OPENABLE_HOURS if _to_utc(day, h) < now + MIN_LEAD]
    return {"date": day.isoformat(), "hours": opened, "booked": booked_hours, "past": past,
            "custom": hours is not None}


def availability(db: Session, doctor_id: int) -> dict:
    now = utcnow()
    sched, booked = _schedule(db, doctor_id), _booked(db, doctor_id)
    return {"openable_hours": OPENABLE_HOURS, "default_hours": DEFAULT_HOURS,
            "days": [_day_dict(d, sched.get(d.isoformat()), booked, now) for d in _local_days(now)]}


def set_availability(db: Session, user: User, day: str, hours: list[int]) -> dict:
    now = utcnow()
    days = {d.isoformat(): d for d in _local_days(now)}
    if day not in days:
        raise Unprocessable("bad_day", f"You can set times for the next {BOOKING_DAYS} days only.")
    hours = sorted(set(hours))
    if any(h not in OPENABLE_HOURS for h in hours):
        raise Unprocessable("bad_hour", "Visit hours must start between 7 AM and 9 PM.")
    booked = _booked(db, user.doctor_id)
    missing = [h for h in OPENABLE_HOURS if _to_utc(days[day], h) in booked and h not in hours]
    if missing:
        raise Conflict("slot_booked", "A patient has already booked one of those times. "
                                      "Keep it open, or ask the patient to rebook first.")
    row = db.scalars(select(DoctorAvailability).where(DoctorAvailability.doctor_id == user.doctor_id,
                                                      DoctorAvailability.day == day)).first()
    if row is None:
        row = DoctorAvailability(doctor_id=user.doctor_id, day=day, hours=hours)
        db.add(row)
    else:
        row.hours = hours
    audit.record(db, user, "doctor.availability", "doctor", user.doctor_id, day=day, hours=hours)
    db.commit()
    return _day_dict(days[day], hours, booked, now)


def book_now(db: Session, user: User, reason: str, address: str, accept_longer: bool = False,
             cashless: bool = False) -> HomeVisit:
    """"Doctor now": a doctor at the door in 10 minutes.

    Offered to the nearest online doctor, who has a short time to accept (DoorDash style). When no doctor
    can make it inside the 10-minute promise, the patient is told the real wait and must choose to go ahead.
    """
    patient = db.get(Patient, user.patient_id)
    quote = dispatch.doctor_quote(db, patient)
    if not quote["available"]:
        raise Conflict("no_doctor_online", "No doctors are online near you right now. Please book a time instead.")
    if not quote["within_promise"] and not accept_longer:
        raise Conflict("outside_promise",
                       f"No doctor can reach you within {quote['promise_min']} minutes right now. "
                       f"The nearest is about {quote['nearest_min']} minutes away.",
                       nearest_min=quote["nearest_min"], promise_min=quote["promise_min"])
    fees = [d.visit_fee for d, _ in _nearby_doctors(db, patient)]
    visit = HomeVisit(doctor_id=None, patient_id=patient.id, status=VisitStatus.requested, on_demand=True,
                      reason=reason.strip(), scheduled_for=utcnow().replace(second=0, microsecond=0),
                      booking_ref=new_ref("BK"), address=(address.strip() or patient.address),
                      fee=max(fees) if fees else 800,
                      promise_min=quote["promise_min"] if quote["within_promise"] else None)
    db.add(visit)
    db.flush()
    perks.bill_visit(db, visit, cashless)
    dispatch.offer_on_demand_visit(db, visit)
    notify(db, users_for_patient(db, patient.id), "Finding your doctor",
           "We're asking the nearest available doctor. You'll see them on the map as soon as they accept."
           + (f" Our promise: a doctor at your door within {visit.promise_min} minutes." if visit.promise_min else ""),
           f"visit:{visit.id}")
    audit.record(db, user, "visit.book_now", "home_visit", visit.id)
    db.commit()
    return visit


def visit_to_dict(v: HomeVisit, patient: Patient | None = None) -> dict:
    km = _distance(v.doctor, patient) if patient and v.doctor else None
    return {
        "id": v.id, "booking_ref": v.booking_ref, "status": v.status.value, "reason": v.reason,
        "scheduled_for": v.scheduled_for.isoformat(), "address": v.address, "fee": v.fee, "on_demand": v.on_demand,
        "doctor": doctor_to_dict(v.doctor, km) if v.doctor else None,
        "follow_up_of": follow_up_info(v),
        "can_cancel": v.status in (VisitStatus.requested, VisitStatus.accepted),
        "notes": visit_notes.summary(v) if v.status == VisitStatus.completed else None,
        "bill": perks.bill_dict(v),
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
    perks.on_cancel(db, v)
    dispatch.close_offers_for_visit(db, v)
    dispatch.end_trips_for(db, visit_id=v.id)
    notify(db, users_for_doctor(db, v.doctor_id) if v.doctor_id else [], "Home visit cancelled",
           f"{v.patient.name} cancelled their visit.", f"visit:{v.id}")
    audit.record(db, user, "visit.cancel", "home_visit", v.id)
    db.commit()
    return v
