"""Physiotherapy at home: book a session or a package, nearest physiotherapist gets it (Dasher style),
live map while they travel, and session notes the patient can read afterwards.

* "As soon as possible" goes to the nearest ONLINE verified physiotherapist, who has a short time to
  accept; a decline or timeout moves it to the next nearest (same rules as "Doctor now").
* A booked time goes to the nearest verified physiotherapist who is free then, online or not, and waits
  for their answer; a decline moves it on.
* The physiotherapist who accepts session 1 keeps the whole package, so the patient sees the same person.
  Package sessions are set every other day at the same time; the patient can move any upcoming one.
* Every session ends with notes: pain before/after (0-10), exercises done, a home exercise plan and the
  focus for next time. Notes are encrypted at rest and visible only to the patient and their physio.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..adapters.geo import haversine_km
from ..errors import Conflict, Forbidden, NotFound, Unprocessable
from ..models import (
    DispatchOffer,
    Patient,
    PhysioBooking,
    PhysioSession,
    Physiotherapist,
    Role,
    Trip,
    User,
    utcnow,
)
from .common import new_ref, notify, users_for_patient

RADIUS_KM = 12.0
SESSION_FEE = 699.0  # per 45-minute home session (demo price, INR)
SESSION_MINUTES = 45
LOCAL_TZ = timezone(timedelta(hours=5, minutes=30))
HOURS = list(range(7, 21))  # 7 AM to 8 PM starts, IST
BOOKING_DAYS = 7
MIN_LEAD = timedelta(minutes=60)
PACKAGE_GAP_DAYS = 2  # package sessions every other day

PLANS = {
    "single": {"label": "Single session", "sessions": 1, "discount": 0.0, "blurb": "One 45-minute assessment and treatment"},
    "pack5": {"label": "5-session package", "sessions": 5, "discount": 0.10, "blurb": "Most chosen for pain and sprains"},
    "pack10": {"label": "10-session package", "sessions": 10, "discount": 0.15, "blurb": "For rehab after surgery or a stroke"},
}

CONDITIONS = {
    "back_neck": {"label": "Back or neck pain", "icon": "user",
                  "exercises": ["Cat-cow stretch", "Chin tucks", "Pelvic tilts", "Bird-dog", "Hamstring stretch", "Heat therapy"]},
    "knee_joint": {"label": "Knee or joint pain", "icon": "pin",
                   "exercises": ["Quad sets", "Straight leg raises", "Heel slides", "Mini squats", "Step-ups", "Ice therapy"]},
    "post_surgery": {"label": "After surgery (knee, hip, spine)", "icon": "shield",
                     "exercises": ["Ankle pumps", "Gait training with walker", "Range-of-motion work", "Bed-to-chair transfers", "Scar mobilisation"]},
    "stroke_neuro": {"label": "Stroke or neuro rehab", "icon": "heart",
                     "exercises": ["Assisted arm reaching", "Sit-to-stand practice", "Balance training", "Fine motor (grip) work", "Assisted walking"]},
    "sports": {"label": "Sports injury or sprain", "icon": "bolt",
               "exercises": ["Ankle alphabet", "Resistance band work", "Balance board", "Calf raises", "Kinesio taping"]},
    "elderly": {"label": "Elderly mobility and falls", "icon": "calendar",
                "exercises": ["Chair sit-to-stand", "Heel-to-toe walk", "Side leg raises", "Seated marching", "Fall-safe home check"]},
}

OPEN_SESSION = ("requested", "scheduled", "in_progress")


# ------------------------------------------------------------------ helpers
def _patient(db: Session, user: User) -> Patient:
    return db.get(Patient, user.patient_id)


def _km(a_lat, a_lng, b_lat, b_lng) -> float:
    return round(haversine_km(a_lat, a_lng, b_lat, b_lng), 1)


def physio_point(db: Session, user: User) -> tuple[float, float]:
    if user.lat is not None and user.lng is not None:
        return user.lat, user.lng
    ph = db.get(Physiotherapist, user.physio_id)
    return ph.lat, ph.lng


def price(plan: str) -> dict:
    p = PLANS[plan]
    full = SESSION_FEE * p["sessions"]
    total = round(full * (1 - p["discount"]))
    return {"key": plan, **p, "session_fee": SESSION_FEE, "full_price": full, "price": float(total),
            "per_session": round(total / p["sessions"]), "saving": round(full - total)}


def _local_days(now: datetime):
    local = now.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)
    return [(local + timedelta(days=d)).date() for d in range(BOOKING_DAYS)]


def _to_utc(day, hour: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=LOCAL_TZ).astimezone(timezone.utc).replace(tzinfo=None)


def slots(now: datetime | None = None) -> list[datetime]:
    now = now or utcnow()
    return [s for d in _local_days(now) for h in HOURS if (s := _to_utc(d, h)) >= now + MIN_LEAD]


def _taken(db: Session, physio_id: int) -> set[datetime]:
    q = select(PhysioSession.scheduled_for).join(PhysioBooking).where(
        PhysioBooking.physio_id == physio_id, PhysioSession.status.in_(("scheduled", "in_progress")))
    return set(db.scalars(q))


def _is_free(db: Session, physio_id: int, when: datetime) -> bool:
    return all(abs((t - when).total_seconds()) >= 3600 for t in _taken(db, physio_id))


def physio_to_dict(ph: Physiotherapist, km: float | None = None, online: bool | None = None) -> dict:
    return {"id": ph.id, "name": ph.name, "qualification": ph.qualification, "registration_no": ph.registration_no,
            "council": ph.council, "verified": ph.verified, "rating": ph.rating, "rating_count": ph.rating_count,
            "experience_years": ph.experience_years, "languages": ph.languages, "gender": ph.gender,
            "about": ph.about, "area": ph.area, "focus": [CONDITIONS[f]["label"] for f in ph.focus if f in CONDITIONS],
            "distance_km": km, "online": online}


# ------------------------------------------------------------------ catalogue
def catalogue(db: Session, user: User) -> dict:
    p = _patient(db, user)
    from .dispatch import _busy  # local import avoids a cycle
    near = []
    for u in db.scalars(select(User).where(User.role == Role.physio)):
        ph = db.get(Physiotherapist, u.physio_id)
        if not ph or not ph.verified or ph.jurisdiction != p.jurisdiction:
            continue
        km = _km(p.lat, p.lng, *physio_point(db, u))
        if km <= RADIUS_KM:
            near.append(physio_to_dict(ph, km, bool(u.on_duty and not _busy(db, u))))
    near.sort(key=lambda r: (not r["online"], r["distance_km"]))
    return {"conditions": [{"key": k, "label": v["label"], "icon": v["icon"]} for k, v in CONDITIONS.items()],
            "plans": [price(k) for k in PLANS], "session_minutes": SESSION_MINUTES,
            "physios": near, "online_nearby": sum(1 for r in near if r["online"]),
            "slots": [s.isoformat() for s in slots()], "address": p.address, "home": [p.lat, p.lng]}


# ------------------------------------------------------------------ dispatch
def _asked(db: Session, session_id: int) -> set[int]:
    return set(db.scalars(select(DispatchOffer.user_id).where(DispatchOffer.physio_session_id == session_id)))


def candidates(db: Session, s: PhysioSession, *, online_only: bool) -> list[tuple[User, float]]:
    from .dispatch import _busy
    b = s.booking
    p = db.get(Patient, b.patient_id)
    asked = _asked(db, s.id)
    out = []
    for u in db.scalars(select(User).where(User.role == Role.physio)):
        if u.id in asked or (online_only and not u.on_duty):
            continue
        ph = db.get(Physiotherapist, u.physio_id)
        if not ph or not ph.verified or ph.jurisdiction != p.jurisdiction:
            continue
        if online_only and _busy(db, u):
            continue
        if not b.on_demand and not _is_free(db, ph.id, s.scheduled_for):
            continue
        km = _km(p.lat, p.lng, *physio_point(db, u))
        if km <= RADIUS_KM:
            out.append((u, km))
    return sorted(out, key=lambda r: r[1])


def offer_next(db: Session, s: PhysioSession) -> DispatchOffer | None:
    """Offer session 1 to the nearest suitable physiotherapist not yet asked."""
    from .dispatch import OFFER_SECONDS
    b = s.booking
    cands = candidates(db, s, online_only=b.on_demand)
    if not cands:
        return None
    u, km = cands[0]
    o = DispatchOffer(kind="physio", physio_session_id=s.id, user_id=u.id, distance_km=km,
                      expires_at=utcnow() + timedelta(seconds=OFFER_SECONDS) if b.on_demand else None)
    db.add(o)
    db.flush()
    cond = CONDITIONS[b.condition]["label"]
    notify(db, [u], "New physio session near you" if b.on_demand else "New physio booking",
           f"{km} km away · {cond} · {PLANS[b.plan]['label']}", f"offer:{o.id}")
    return o


def redispatch(db: Session, offer: DispatchOffer) -> None:
    s = db.get(PhysioSession, offer.physio_session_id)
    b = s.booking
    if b.status != "searching":
        return
    if offer_next(db, s) is None:
        _cancel(db, b)
        msg = ("All nearby physiotherapists are busy. Please try again shortly or book a time." if b.on_demand
               else "No physiotherapist is free at that time. Please pick another time.")
        notify(db, users_for_patient(db, b.patient_id), "No physiotherapist available", msg, f"physio:{b.id}")


def on_accept(db: Session, user: User, offer: DispatchOffer) -> None:
    from .dispatch import start_trip
    s = db.get(PhysioSession, offer.physio_session_id)
    b = s.booking
    if b.status != "searching":
        raise Conflict("bad_booking_state", "This booking is no longer waiting for a physiotherapist.")
    ph = db.get(Physiotherapist, user.physio_id)
    b.physio_id, b.status = ph.id, "active"
    for x in b.sessions:
        if x.status == "requested":
            x.status = "scheduled"
    if b.on_demand:
        p = db.get(Patient, b.patient_id)
        trip = start_trip(db, user, leg="to_patient", dest=(p.lat, p.lng), dest_label=f"{p.name.split()[0]}'s home")
        trip.physio_session_id = s.id
        notify(db, users_for_patient(db, b.patient_id), "Your physiotherapist is on the way",
               f"{ph.name} accepted and is heading to you. Arriving in about {math.ceil(trip.duration_s / 60)} min.",
               f"physio:{b.id}")
    else:
        notify(db, users_for_patient(db, b.patient_id), "Physiotherapist confirmed",
               f"{ph.name} confirmed your {PLANS[b.plan]['label'].lower()}.", f"physio:{b.id}")
    audit.record(db, user, "physio.accept", "physio_booking", b.id, on_demand=b.on_demand)


def offer_dict(db: Session, o: DispatchOffer) -> dict:
    from .dispatch import CITY_KMH
    from .earnings import ON_DEMAND_BONUS, physio_pay
    s = db.get(PhysioSession, o.physio_session_id)
    b = s.booking
    p = db.get(Patient, b.patient_id)
    pr = price(b.plan)
    return {"title": "Physio session now" if b.on_demand else "Physio booking", "on_demand": b.on_demand,
            "patient": p.name, "reason": " · ".join(x for x in (CONDITIONS[b.condition]["label"], b.details) if x),
            "scheduled_for": s.scheduled_for.isoformat(), "address": b.address or p.address,
            "earning": physio_pay(b.session_fee) + (ON_DEMAND_BONUS if b.on_demand else 0), "plan": pr["label"],
            "sessions_total": b.sessions_total, "package_earning": physio_pay(b.session_fee) * b.sessions_total,
            "dropoff": {"lat": p.lat, "lng": p.lng, "label": p.name},
            "drive_min": math.ceil(o.distance_km * 1.3 / CITY_KMH * 60 + 1)}


# ------------------------------------------------------------------ patient actions
def book(db: Session, user: User, *, condition: str, plan: str, when: str | datetime, details: str = "",
         address: str = "") -> PhysioBooking:
    if condition not in CONDITIONS:
        raise Unprocessable("bad_condition", "Pick what you need help with.")
    if plan not in PLANS:
        raise Unprocessable("bad_plan", "Pick a single session or a package.")
    p = _patient(db, user)
    on_demand = when == "now"
    if on_demand:
        start = utcnow().replace(second=0, microsecond=0)
    else:
        start = when if isinstance(when, datetime) else None
        if start is not None and start.tzinfo:
            start = start.astimezone(timezone.utc).replace(tzinfo=None)
        if start not in slots():
            raise Unprocessable("bad_slot", "Pick one of the available times.")
    open_ = db.scalars(select(PhysioBooking.id).where(PhysioBooking.patient_id == p.id,
                                                      PhysioBooking.status == "searching")).first()
    if open_:
        raise Conflict("already_searching", "We're still finding a physiotherapist for your last request.")
    pr = price(plan)
    b = PhysioBooking(ref=new_ref("PT"), patient_id=p.id, condition=condition, details=details.strip()[:300],
                      plan=plan, sessions_total=pr["sessions"], session_fee=pr["per_session"], price_total=pr["price"],
                      address=(address.strip() or p.address), status="searching", on_demand=on_demand)
    db.add(b)
    db.flush()
    for i in range(pr["sessions"]):
        at = start + timedelta(days=PACKAGE_GAP_DAYS * i)
        if i and on_demand:  # later package sessions start on the next full local hour
            local = (at + timedelta(hours=1)).replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ).replace(minute=0)
            at = local.astimezone(timezone.utc).replace(tzinfo=None)
        db.add(PhysioSession(booking_id=b.id, number=i + 1, scheduled_for=at,
                             status="requested" if i == 0 else "scheduled"))
    db.flush()
    db.refresh(b)
    first = b.sessions[0]
    if offer_next(db, first) is None:
        db.rollback()
        if on_demand:
            raise Conflict("no_physio_online", "No physiotherapists are online near you right now. Please book a time instead.")
        raise Conflict("no_physio_free", "No physiotherapist near you is free at that time. Please pick another time.")
    notify(db, users_for_patient(db, p.id), "Finding your physiotherapist",
           "We're asking the nearest available physiotherapist. You'll see them on the map once they accept."
           if on_demand else "We've sent your booking to the nearest physiotherapist free at that time.", f"physio:{b.id}")
    audit.record(db, user, "physio.book", "physio_booking", b.id, plan=plan, on_demand=on_demand)
    db.commit()
    return b


def _my_booking(db: Session, user: User, booking_id: int) -> PhysioBooking:
    b = db.get(PhysioBooking, booking_id)
    if b is None or user.role != Role.patient or b.patient_id != user.patient_id:
        raise NotFound("not_found", "Booking not found.")
    return b


def _cancel(db: Session, b: PhysioBooking) -> None:
    from .dispatch import end_trip
    b.status = "cancelled"
    ids = [s.id for s in b.sessions]
    for s in b.sessions:
        if s.status in ("requested", "scheduled"):
            s.status = "cancelled"
    for o in db.scalars(select(DispatchOffer).where(DispatchOffer.physio_session_id.in_(ids), DispatchOffer.status == "offered")):
        o.status, o.responded_at = "withdrawn", utcnow()
    for t in db.scalars(select(Trip).where(Trip.physio_session_id.in_(ids), Trip.ended_at.is_(None))):
        end_trip(db, t)


def cancel(db: Session, user: User, booking_id: int) -> PhysioBooking:
    b = _my_booking(db, user, booking_id)
    if b.status not in ("searching", "active"):
        raise Conflict("bad_booking_state", "This booking can't be cancelled.")
    if any(s.status == "in_progress" for s in b.sessions):
        raise Conflict("session_in_progress", "A session is in progress. Cancel after it ends.")
    done = sum(1 for s in b.sessions if s.status == "completed")
    _cancel(db, b)
    if done:  # keep the history: a package with completed sessions ends as completed
        b.status = "completed"
    if b.physio_id:
        notify(db, list(db.scalars(select(User).where(User.physio_id == b.physio_id))), "Booking cancelled",
               f"{db.get(Patient, b.patient_id).name} cancelled the remaining sessions ({b.ref}).", f"physio:{b.id}")
    audit.record(db, user, "physio.cancel", "physio_booking", b.id)
    db.commit()
    return b


def reschedule(db: Session, user: User, session_id: int, when: datetime) -> PhysioSession:
    s = db.get(PhysioSession, session_id)
    if s is None:
        raise NotFound("not_found", "Session not found.")
    b = _my_booking(db, user, s.booking_id)
    if s.status != "scheduled" or b.status != "active":
        raise Conflict("bad_session_state", "Only upcoming sessions can be moved.")
    if when.tzinfo:
        when = when.astimezone(timezone.utc).replace(tzinfo=None)
    if when not in slots():
        raise Unprocessable("bad_slot", "Pick one of the available times.")
    if db.scalars(select(Trip.id).where(Trip.physio_session_id == s.id, Trip.ended_at.is_(None))).first():
        raise Conflict("on_the_way", "Your physiotherapist is already on the way.")
    others = db.scalars(select(PhysioSession.scheduled_for).join(PhysioBooking).where(
        PhysioBooking.physio_id == b.physio_id, PhysioSession.id != s.id,
        PhysioSession.status.in_(("scheduled", "in_progress"))))
    if any(abs((t - when).total_seconds()) < 3600 for t in others):
        raise Conflict("physio_busy", "Your physiotherapist is busy then. Please pick another time.")
    s.scheduled_for = when
    ph = db.get(Physiotherapist, b.physio_id)
    notify(db, list(db.scalars(select(User).where(User.physio_id == ph.id))), "Session moved",
           f"{db.get(Patient, b.patient_id).name} moved session {s.number} ({b.ref}).", f"physio:{b.id}")
    audit.record(db, user, "physio.reschedule", "physio_session", s.id)
    db.commit()
    return s


# ------------------------------------------------------------------ physiotherapist actions
def _my_session(db: Session, user: User, session_id: int) -> PhysioSession:
    s = db.get(PhysioSession, session_id)
    if s is None or user.role != Role.physio or s.booking.physio_id != user.physio_id:
        raise NotFound("not_found", "Session not found.")
    return s


def depart(db: Session, user: User, session_id: int) -> Trip:
    from .dispatch import active_trip, start_trip
    s = _my_session(db, user, session_id)
    if s.status != "scheduled" or s.booking.status != "active":
        raise Conflict("bad_session_state", "This session isn't waiting for you.")
    t = active_trip(db, user.id)
    if t and t.physio_session_id == s.id:
        return t
    p = db.get(Patient, s.booking.patient_id)
    trip = start_trip(db, user, leg="to_patient", dest=(p.lat, p.lng), dest_label=f"{p.name.split()[0]}'s home")
    trip.physio_session_id = s.id
    notify(db, users_for_patient(db, p.id), "Your physiotherapist is on the way",
           f"{db.get(Physiotherapist, user.physio_id).name} is heading to you for session {s.number}. Follow them live on the map.",
           f"physio:{s.booking_id}")
    audit.record(db, user, "physio.depart", "physio_session", s.id)
    db.commit()
    return trip


def start(db: Session, user: User, session_id: int) -> PhysioSession:
    from .dispatch import end_trip
    s = _my_session(db, user, session_id)
    if s.status != "scheduled" or s.booking.status != "active":
        raise Conflict("bad_session_state", "This session can't be started.")
    if any(x.status == "in_progress" for x in s.booking.sessions):
        raise Conflict("bad_session_state", "Finish the session in progress first.")
    s.status, s.started_at = "in_progress", utcnow()
    for t in db.scalars(select(Trip).where(Trip.physio_session_id == s.id, Trip.ended_at.is_(None))):
        end_trip(db, t)
    notify(db, users_for_patient(db, s.booking.patient_id), "Your session has started",
           f"Session {s.number} of {s.booking.sessions_total} with {s.booking.physio.name}.", f"physio:{s.booking_id}")
    audit.record(db, user, "physio.start", "physio_session", s.id)
    db.commit()
    return s


def complete(db: Session, user: User, session_id: int, *, pain_before: int, pain_after: int, exercises: list[str],
             notes: str, home_plan: str = "", next_focus: str = "") -> PhysioSession:
    s = _my_session(db, user, session_id)
    if s.status != "in_progress":
        raise Conflict("bad_session_state", "Start the session before writing its notes.")
    if not exercises and not notes.strip():
        raise Unprocessable("notes_required", "Add the exercises you did or a short note.")
    s.pain_before, s.pain_after = pain_before, pain_after
    s.exercises = [e.strip()[:80] for e in exercises if e.strip()][:20]
    s.notes, s.home_plan, s.next_focus = notes.strip()[:2000], home_plan.strip()[:1000], next_focus.strip()[:300]
    s.status, s.completed_at = "completed", utcnow()
    from .earnings import record_physio
    record_physio(db, s, user)
    b = s.booking
    done = sum(1 for x in b.sessions if x.status == "completed")
    if done >= b.sessions_total or not any(x.status == "scheduled" for x in b.sessions):
        b.status = "completed"
    trend = f"Pain {pain_before}/10 → {pain_after}/10. " if pain_before is not None and pain_after is not None else ""
    notify(db, users_for_patient(db, b.patient_id), f"Session {s.number} notes are ready",
           f"{trend}{b.physio.name} added your exercises and home plan.", f"physio:{b.id}")
    audit.record(db, user, "physio.complete", "physio_session", s.id)
    db.commit()
    return s


def notify_arrival(db: Session, trip: Trip) -> None:
    s = db.get(PhysioSession, trip.physio_session_id)
    notify(db, users_for_patient(db, s.booking.patient_id), "Your physiotherapist has arrived",
           f"{s.booking.physio.name} is at your door.", f"physio:{s.booking_id}")


# ------------------------------------------------------------------ views
def session_to_dict(s: PhysioSession, *, with_notes: bool = True) -> dict:
    out = {"id": s.id, "number": s.number, "status": s.status, "scheduled_for": s.scheduled_for.isoformat(),
           "started_at": s.started_at.isoformat() if s.started_at else None,
           "completed_at": s.completed_at.isoformat() if s.completed_at else None}
    if with_notes and s.status == "completed":
        out["notes"] = {"pain_before": s.pain_before, "pain_after": s.pain_after, "exercises": s.exercises or [],
                        "notes": s.notes, "home_plan": s.home_plan, "next_focus": s.next_focus}
    return out


def booking_to_dict(db: Session, b: PhysioBooking) -> dict:
    p = db.get(Patient, b.patient_id)
    done = sum(1 for s in b.sessions if s.status == "completed")
    nxt = next((s for s in b.sessions if s.status in OPEN_SESSION), None)
    return {"id": b.id, "ref": b.ref, "status": b.status, "on_demand": b.on_demand, "condition": b.condition,
            "condition_label": CONDITIONS[b.condition]["label"], "details": b.details, "plan": b.plan,
            "plan_label": PLANS[b.plan]["label"], "sessions_total": b.sessions_total, "sessions_done": done,
            "price_total": b.price_total, "session_fee": b.session_fee, "address": b.address,
            "created_at": b.created_at.isoformat(),
            "physio": physio_to_dict(b.physio, _km(p.lat, p.lng, b.physio.lat, b.physio.lng)) if b.physio else None,
            "next_session": session_to_dict(nxt, with_notes=False) if nxt else None,
            "sessions": [session_to_dict(s) for s in b.sessions],
            "can_cancel": b.status in ("searching", "active") and not any(s.status == "in_progress" for s in b.sessions)}


def list_for_patient(db: Session, user: User) -> list[dict]:
    rows = db.scalars(select(PhysioBooking).where(PhysioBooking.patient_id == user.patient_id)
                      .order_by(PhysioBooking.id.desc())).all()
    return [booking_to_dict(db, b) for b in rows]


def get_for_patient(db: Session, user: User, booking_id: int) -> dict:
    return booking_to_dict(db, _my_booking(db, user, booking_id))


def live(db: Session, user: User, session_id: int) -> dict:
    from .dispatch import _provider_card, provider_point, sweep, trip_to_dict
    sweep(db)
    s = db.get(PhysioSession, session_id)
    if s is None:
        raise NotFound("not_found", "Session not found.")
    b = _my_booking(db, user, s.booking_id)
    p = db.get(Patient, b.patient_id)
    trip = db.scalars(select(Trip).where(Trip.physio_session_id == s.id).order_by(Trip.id.desc())).first()
    pu = db.scalars(select(User).where(User.physio_id == b.physio_id)).first() if b.physio_id else None
    t = trip_to_dict(db, trip) if trip and not trip.ended_at else None
    if s.status == "cancelled" or b.status == "cancelled" and s.status != "completed":
        phase = "cancelled"
    elif s.status == "completed":
        phase = "done"
    elif s.status == "in_progress":
        phase = "with_you"
    elif b.status == "searching":
        phase = "searching" if b.on_demand else "waiting"
    elif t:
        phase = "arrived" if t["arrived"] else "on_the_way"
    else:
        phase = "confirmed"
    from .dispatch import _busy
    online = 0
    for u in db.scalars(select(User).where(User.role == Role.physio, User.on_duty.is_(True))):
        ph = db.get(Physiotherapist, u.physio_id)
        if ph and ph.verified and _km(p.lat, p.lng, *physio_point(db, u)) <= RADIUS_KM and not _busy(db, u):
            online += 1
    return {"kind": "physio", "id": s.id, "booking_id": b.id, "booking_ref": b.ref, "status": s.status, "phase": phase,
            "on_demand": b.on_demand, "reason": CONDITIONS[b.condition]["label"], "number": s.number,
            "sessions_total": b.sessions_total, "scheduled_for": s.scheduled_for.isoformat(),
            "home": {"lat": p.lat, "lng": p.lng, "label": "Home", "address": b.address or p.address},
            "provider": _provider_card(db, pu), "trip": t, "providers_asked": len(_asked(db, s.id)),
            "online_nearby": online,
            "provider_location": t["position"] if t else (list(provider_point(db, pu)) if pu else None)}


def _pay(fee: float) -> float:
    from .earnings import physio_pay
    return physio_pay(fee)


def provider_jobs(db: Session, user: User) -> list[dict]:
    out = []
    q = (select(PhysioSession).join(PhysioBooking).where(PhysioBooking.physio_id == user.physio_id,
                                                          PhysioBooking.status == "active",
                                                          PhysioSession.status.in_(("scheduled", "in_progress")))
         .order_by(PhysioSession.scheduled_for))
    for s in db.scalars(q):
        b = s.booking
        p = db.get(Patient, b.patient_id)
        trip = db.scalars(select(Trip).where(Trip.physio_session_id == s.id, Trip.ended_at.is_(None))).first()
        out.append({"kind": "physio", "id": s.id, "booking_id": b.id, "status": s.status, "patient": p.name,
                    "reason": CONDITIONS[b.condition]["label"] + (f" · {b.details}" if b.details else ""),
                    "address": b.address or p.address, "scheduled_for": s.scheduled_for.isoformat(),
                    "on_demand": b.on_demand and s.number == 1, "number": s.number, "sessions_total": b.sessions_total,
                    "earning": _pay(b.session_fee), "trip_id": trip.id if trip else None,
                    "dropoff": {"lat": p.lat, "lng": p.lng, "label": p.name}})
    return out


def physio_bookings(db: Session, user: User) -> list[dict]:
    """The physiotherapist's patients: every package, with past session notes for continuity."""
    rows = db.scalars(select(PhysioBooking).where(PhysioBooking.physio_id == user.physio_id)
                      .order_by(PhysioBooking.id.desc())).all()
    out = []
    for b in rows:
        d = booking_to_dict(db, b)
        p = db.get(Patient, b.patient_id)
        d["patient"] = {"name": p.name, "patient_ref": p.patient_ref}
        d["suggested_exercises"] = CONDITIONS[b.condition]["exercises"]
        d.pop("physio", None)
        out.append(d)
    return out


def ensure_physio_verified(db: Session, user: User) -> None:
    ph = db.get(Physiotherapist, user.physio_id)
    if not ph or not ph.verified:
        raise Forbidden("licence_not_verified", "Your registration must be verified before you can take sessions.")
