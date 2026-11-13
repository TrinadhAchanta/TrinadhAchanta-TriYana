"""Dispatch and live trips, DoorDash/Dasher style.

* Providers (doctors, couriers) "Go online" in the Provider app.
* A job is offered to ONE provider at a time, nearest first. They accept or decline;
  an unanswered on-demand offer times out and moves to the next nearest provider.
* After acceptance a Trip starts. Its position is simulated along the route (demo GPS),
  or taken from real GPS when the provider app sends it. The patient app shows the
  provider moving on a map with an ETA; the provider app shows turn-by-turn steps.

Routes start as a simple synthetic street path so the backend never needs the network.
The provider app may replace it with a real road route (OSRM) via ``set_route``.
"""
from __future__ import annotations

import math
import os
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..adapters.geo import haversine_km
from ..errors import Conflict, Forbidden, NotFound, Unprocessable
from ..models import (
    DeliveryAssignment,
    Doctor,
    DispatchOffer,
    HomeVisit,
    OrderStatus,
    Patient,
    Pharmacy,
    PharmacyOrder,
    Role,
    Trip,
    User,
    VisitStatus,
    utcnow,
)
from . import face_verification as face
from .common import notify, users_for_patient

OFFER_SECONDS = int(os.environ.get("TRIYANA_OFFER_SECONDS", "45"))
SIM_SPEEDUP = float(os.environ.get("TRIYANA_SIM_SPEEDUP", "8"))  # demo time runs this many times faster
DOCTOR_RADIUS_KM = 15.0
COURIER_RADIUS_KM = 12.0
LAB_RADIUS_KM = 15.0
ROLE_FOR = {"visit": Role.doctor, "delivery": Role.courier, "lab": Role.phlebotomist}
RADIUS_FOR = {"visit": DOCTOR_RADIUS_KM, "delivery": COURIER_RADIUS_KM, "lab": LAB_RADIUS_KM}
CITY_KMH = 22.0  # average city speed used for ETAs on synthetic routes
GPS_FRESH = timedelta(seconds=30)
# Triyana's promise: a doctor at your door in 10 minutes. A doctor counts as "in the 10-minute zone" when
# the time to accept and pass the live face check plus the drive fits inside the promise.
PROMISE_MIN = int(os.environ.get("TRIYANA_PROMISE_MIN", "10"))
HANDOFF_MIN = 2  # accept the request + live face check before setting off


def drive_minutes(km: float) -> int:
    """Rough city drive time for a straight-line distance (roads are ~1.3x longer)."""
    return math.ceil(km * 1.3 / CITY_KMH * 60 + 1)


def doorstep_minutes(km: float) -> int:
    """From tapping "Doctor now" to the doctor at the door."""
    return drive_minutes(km) + HANDOFF_MIN


# ------------------------------------------------------------------ geometry
def _bearing(a, b) -> float:
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dl = math.radians(b[1] - a[1])
    x = math.sin(dl) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _cardinal(deg: float) -> str:
    return ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"][int((deg + 22.5) // 45) % 8]


def _seg_m(a, b) -> float:
    return haversine_km(a[0], a[1], b[0], b[1]) * 1000


def synthetic_route(origin: tuple[float, float], dest: tuple[float, float], dest_label: str) -> dict:
    """A plausible street-grid path (two turns) with turn-by-turn steps. No network needed."""
    o, d = list(origin), list(dest)
    corner1 = [o[0], o[1] + 0.6 * (d[1] - o[1])]
    corner2 = [d[0], corner1[1]]
    pts = [o, corner1, corner2, d]
    pts = [p for i, p in enumerate(pts) if i == 0 or _seg_m(pts[i - 1], p) > 15]
    if len(pts) == 1:
        pts.append(d)
    route, along, steps = [], 0.0, []
    for i, p in enumerate(pts):
        if i:
            along += _seg_m(pts[i - 1], p)
        route.append([round(p[0], 6), round(p[1], 6)])
        if i == 0:
            nxt = pts[1]
            steps.append({"text": f"Head {_cardinal(_bearing(p, nxt))}", "along_m": 0, "type": "depart", "modifier": "straight"})
        elif i < len(pts) - 1:
            delta = (_bearing(p, pts[i + 1]) - _bearing(pts[i - 1], p) + 540) % 360 - 180
            mod = "straight" if abs(delta) < 20 else ("right" if delta > 0 else "left")
            text = "Continue straight" if mod == "straight" else f"Turn {mod}"
            steps.append({"text": text, "along_m": round(along), "type": "turn", "modifier": mod})
        else:
            steps.append({"text": f"Arrive at {dest_label}", "along_m": round(along), "type": "arrive", "modifier": "straight"})
    duration = along / (CITY_KMH * 1000 / 3600) + 60
    return {"route": route, "steps": steps, "distance_m": round(along), "duration_s": round(duration), "source": "synthetic"}


def _point_along(route: list, target_m: float) -> tuple[list, float]:
    """Position and heading at ``target_m`` metres along the polyline."""
    if len(route) < 2:
        return route[0] if route else [0, 0], 0.0
    done = 0.0
    for i in range(1, len(route)):
        a, b = route[i - 1], route[i]
        seg = _seg_m(a, b)
        if done + seg >= target_m and seg > 0:
            f = (target_m - done) / seg
            return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f], _bearing(a, b)
        done += seg
    return route[-1], _bearing(route[-2], route[-1])


# ------------------------------------------------------------------ locations
def provider_point(db: Session, user: User) -> tuple[float, float]:
    if user.lat is not None and user.lng is not None:
        return user.lat, user.lng
    if user.doctor_id:
        doc = db.get(Doctor, user.doctor_id)
        return doc.lat, doc.lng
    if user.pharmacy_id:
        ph = db.get(Pharmacy, user.pharmacy_id)
        return ph.lat, ph.lng
    if user.physio_id:
        from .physio import physio_point
        return physio_point(db, user)
    return 17.44, 78.35


def active_trip(db: Session, user_id: int) -> Trip | None:
    return db.scalars(select(Trip).where(Trip.user_id == user_id, Trip.ended_at.is_(None)).order_by(Trip.id.desc())).first()


def _busy(db: Session, user: User) -> bool:
    if active_trip(db, user.id):
        return True
    if user.doctor_id and db.scalars(select(HomeVisit.id).where(  # accepted "Doctor now", still verifying
            HomeVisit.doctor_id == user.doctor_id, HomeVisit.on_demand.is_(True),
            HomeVisit.status == VisitStatus.accepted)).first() is not None:
        return True
    return db.scalars(select(DispatchOffer.id).where(DispatchOffer.user_id == user.id, DispatchOffer.status == "offered",
                                                     DispatchOffer.expires_at.isnot(None))).first() is not None


# ------------------------------------------------------------------ candidates
def _target_point(db: Session, offer_kind: str, target) -> tuple[float, float]:
    if offer_kind == "visit":
        p = db.get(Patient, target.patient_id)
        return p.lat, p.lng
    ph = db.get(Pharmacy, target.pharmacy_id)  # couriers are matched to the pickup point
    return ph.lat, ph.lng


def _already_asked(db: Session, kind: str, target_id: int, *, retry_missed: bool = False) -> set[int]:
    col = DispatchOffer.visit_id if kind == "visit" else DispatchOffer.order_id
    q = select(DispatchOffer.user_id).where(col == target_id)
    if retry_missed:  # providers who let an offer time out may be asked again; decliners are not
        q = q.where(DispatchOffer.status != "expired")
    return set(db.scalars(q))


def candidates(db: Session, kind: str, target, *, online_only: bool = True,
               retry_missed: bool = False) -> list[tuple[User, float]]:
    lat, lng = _target_point(db, kind, target)
    asked = _already_asked(db, kind, target.id, retry_missed=retry_missed)
    role = Role.doctor if kind == "visit" else Role.courier
    radius = DOCTOR_RADIUS_KM if kind == "visit" else COURIER_RADIUS_KM
    out = []
    for u in db.scalars(select(User).where(User.role == role)):
        if u.id in asked or (online_only and not u.on_duty) or not u.is_verified:
            continue
        if kind == "visit":
            doc = db.get(Doctor, u.doctor_id)
            patient = db.get(Patient, target.patient_id)
            if not doc or not doc.license_verified or doc.jurisdiction != patient.jurisdiction:
                continue
        if online_only and _busy(db, u):
            continue
        plat, plng = provider_point(db, u)
        km = round(haversine_km(lat, lng, plat, plng), 1)
        if km <= radius:
            out.append((u, km))
    return sorted(out, key=lambda r: r[1])


def online_count(db: Session, kind: str, lat: float, lng: float) -> int:
    role, radius = ROLE_FOR[kind], RADIUS_FOR[kind]
    n = 0
    for u in db.scalars(select(User).where(User.role == role, User.on_duty.is_(True))):
        plat, plng = provider_point(db, u)
        if haversine_km(lat, lng, plat, plng) <= radius and not _busy(db, u):
            if kind == "visit" and not db.get(Doctor, u.doctor_id).license_verified:
                continue
            n += 1
    return n


def doctor_quote(db: Session, patient: Patient) -> dict:
    """What "Doctor now" can promise this patient right now."""
    cands = candidates(db, "visit", HomeVisit(id=0, patient_id=patient.id))
    etas = [doorstep_minutes(km) for _, km in cands]
    in_zone = sum(1 for e in etas if e <= PROMISE_MIN)
    return {"promise_min": PROMISE_MIN, "available": len(cands), "in_promise": in_zone,
            "within_promise": in_zone > 0, "nearest_min": etas[0] if etas else None,
            "nearest_km": cands[0][1] if cands else None}


# ------------------------------------------------------------------ offers
def _make_offer(db: Session, kind: str, target, user: User, km: float, timed: bool) -> DispatchOffer:
    offer = DispatchOffer(kind=kind, user_id=user.id, distance_km=km,
                          visit_id=target.id if kind == "visit" else None,
                          order_id=target.id if kind == "delivery" else None,
                          expires_at=utcnow() + timedelta(seconds=OFFER_SECONDS) if timed else None)
    db.add(offer)
    db.flush()
    if kind == "visit":
        title = "New visit request near you" if target.on_demand else "New home visit booking"
        body = f"{km} km away · {target.reason}"
        if target.on_demand and target.promise_min:
            title = f"{target.promise_min}-minute visit near you"
            body = f"Patient promised a doctor in {target.promise_min} min · {body}"
    else:
        title = "New delivery near you"
        body = f"Pickup {km} km away at {target.pharmacy.name}"
    notify(db, [user], title, body, f"offer:{offer.id}")
    return offer


def offer_on_demand_visit(db: Session, visit: HomeVisit) -> DispatchOffer | None:
    """Offer an on-demand visit to the nearest online doctor not yet asked. None if nobody is left."""
    cands = candidates(db, "visit", visit)
    if not cands:
        return None
    return _make_offer(db, "visit", visit, cands[0][0], cands[0][1], timed=True)


def offer_booked_visit(db: Session, visit: HomeVisit) -> DispatchOffer | None:
    """A booked time goes to the assigned doctor and waits for their answer."""
    user = db.scalars(select(User).where(User.doctor_id == visit.doctor_id)).first()
    if not user:
        return None
    patient = db.get(Patient, visit.patient_id)
    plat, plng = provider_point(db, user)
    return _make_offer(db, "visit", visit, user, round(haversine_km(patient.lat, patient.lng, plat, plng), 1), timed=False)


def offer_delivery(db: Session, order: PharmacyOrder) -> DispatchOffer | None:
    cands = candidates(db, "delivery", order) or candidates(db, "delivery", order, retry_missed=True)
    if not cands:
        return None
    return _make_offer(db, "delivery", order, cands[0][0], cands[0][1], timed=True)


def _redispatch(db: Session, offer: DispatchOffer) -> None:
    """After a decline or timeout, move to the next nearest provider."""
    if offer.kind == "physio":
        from .physio import redispatch
        return redispatch(db, offer)
    if offer.kind == "visit":
        v = offer.visit
        if v.status != VisitStatus.requested:
            return
        if v.on_demand:
            nxt = offer_on_demand_visit(db, v)
            if nxt is None:
                v.status = VisitStatus.cancelled
                notify(db, users_for_patient(db, v.patient_id), "No doctor available right now",
                       "All nearby doctors are busy. Please try again in a few minutes or book a time.", f"visit:{v.id}")
            elif (v.promise_min and doorstep_minutes(offer.distance_km) <= v.promise_min
                  < doorstep_minutes(nxt.distance_km)):
                # The 10-minute zone ran out. Keep the patient's care going, and say so honestly.
                notify(db, users_for_patient(db, v.patient_id), "Your doctor may take a little longer",
                       f"No doctor within {v.promise_min} minutes could come, so we've asked the next nearest, "
                       f"about {doorstep_minutes(nxt.distance_km)} minutes away.", f"visit:{v.id}")
            return
        # Booked time: the next nearest verified doctor who is free at that time.
        from .visits import free_slots  # local import avoids a cycle
        for u, _km in candidates(db, "visit", v, online_only=False):
            if v.scheduled_for in free_slots(db, u.doctor_id):
                v.doctor_id = u.doctor_id
                db.flush()
                offer_booked_visit(db, v)
                notify(db, users_for_patient(db, v.patient_id), "We found you another doctor",
                       f"Your first doctor couldn't make it, so we sent your request to {db.get(Doctor, u.doctor_id).name}.",
                       f"visit:{v.id}")
                return
        v.status = VisitStatus.cancelled
        notify(db, users_for_patient(db, v.patient_id), "No doctor free at that time",
               "We couldn't find another doctor for your booking. Please pick a new time.", f"visit:{v.id}")
    elif offer.kind == "lab":
        from . import labs  # local import avoids a cycle
        labs.redispatch(db, offer)
    else:
        order = offer.order
        if order.delivery and order.delivery.courier_user_id is None:
            offer_delivery(db, order)  # if nobody is online, the pharmacy's own courier can still collect


def sweep(db: Session) -> None:
    """Expire unanswered on-demand offers and move them on. Called on every live read."""
    now = utcnow()
    stale = db.scalars(select(DispatchOffer).where(DispatchOffer.status == "offered", DispatchOffer.expires_at.isnot(None),
                                                   DispatchOffer.expires_at < now)).all()
    for o in stale:
        o.status, o.responded_at = "expired", now
        db.flush()
        _redispatch(db, o)
    if stale:
        db.commit()
    from . import labs  # reports that are ready, and collectors for booked lab slots
    labs.sweep(db)
    from .shop import autopack  # shop orders the pharmacy has packed are offered to riders here
    autopack(db)
    _offer_waiting_deliveries(db)


def _offer_waiting_deliveries(db: Session) -> None:
    """Packed road deliveries with no rider yet go to whoever is online now (e.g. a rider who just came online)."""
    waiting = db.scalars(select(PharmacyOrder).join(DeliveryAssignment, DeliveryAssignment.order_id == PharmacyOrder.id)
                         .where(PharmacyOrder.status == OrderStatus.ready_for_pickup,
                                PharmacyOrder.fulfillment == "delivery",
                                DeliveryAssignment.provider == "triyana-dispatch",
                                DeliveryAssignment.courier_user_id.is_(None))).all()
    made = False
    for order in waiting:
        open_offer = db.scalars(select(DispatchOffer.id).where(DispatchOffer.order_id == order.id,
                                                               DispatchOffer.status == "offered")).first()
        if open_offer is None and offer_delivery(db, order) is not None:
            made = True
    if made:
        db.commit()


def _my_offer(db: Session, user: User, offer_id: int) -> DispatchOffer:
    o = db.get(DispatchOffer, offer_id)
    if o is None or o.user_id != user.id:
        raise NotFound("not_found", "Request not found.")
    if o.status != "offered":
        raise Conflict("offer_closed", "This request is no longer available." if o.status in ("expired", "withdrawn")
                       else f"You already {o.status} this request.")
    return o


def accept(db: Session, user: User, offer_id: int) -> DispatchOffer:
    sweep(db)
    o = _my_offer(db, user, offer_id)
    o.status, o.responded_at = "accepted", utcnow()
    if o.kind == "physio":
        from .physio import on_accept
        on_accept(db, user, o)
    elif o.kind == "visit":
        v = o.visit
        if v.status != VisitStatus.requested:
            raise Conflict("bad_visit_state", "This visit is no longer waiting for a doctor.")
        face.require_enrolled(db, user)
        v.doctor_id = user.doctor_id
        v.status = VisitStatus.accepted
        doc = db.get(Doctor, user.doctor_id)
        if v.on_demand:
            # No trip yet: the doctor must pass a live face check for this visit before Start journey.
            notify(db, users_for_patient(db, v.patient_id), "Doctor accepted your request",
                   f"{doc.name} accepted. They're completing Triyana's live identity check before they set off.",
                   f"visit:{v.id}")
        else:
            notify(db, users_for_patient(db, v.patient_id), "Doctor confirmed your visit",
                   f"{doc.name} confirmed your home visit.", f"visit:{v.id}")
        audit.record(db, user, "visit.accept", "home_visit", v.id, via="dispatch", on_demand=v.on_demand)
    elif o.kind == "lab":
        from . import labs
        labs.on_accept(db, user, o)
    else:
        order = o.order
        d = order.delivery
        if d is None or d.courier_user_id not in (None, user.id):
            raise Conflict("offer_closed", "Another courier already took this delivery.")
        d.courier_user_id, d.courier_name = user.id, user.name.split(" (")[0]
        start_trip(db, user, order_id=order.id, leg="to_pharmacy", dest=(order.pharmacy.lat, order.pharmacy.lng),
                   dest_label=order.pharmacy.name)
        notify(db, users_for_patient(db, order.patient_id), "Courier assigned",
               f"{d.courier_name} is heading to {order.pharmacy.name} to collect your medicines.", f"order:{order.id}")
        audit.record(db, user, "delivery.accept", "order", order.id)
    db.commit()
    return o


def decline(db: Session, user: User, offer_id: int) -> DispatchOffer:
    sweep(db)
    o = db.get(DispatchOffer, offer_id)
    if o is not None and o.user_id == user.id and o.status in ("declined", "expired", "withdrawn"):
        return o  # already off their list (double tap, or it timed out a moment ago): nothing to undo
    o = _my_offer(db, user, offer_id)
    o.status, o.responded_at = "declined", utcnow()
    db.flush()
    _redispatch(db, o)
    audit.record(db, user, f"{o.kind}.decline", "offer", o.id)
    db.commit()
    return o


def close_offers_for_visit(db: Session, visit: HomeVisit, accepted_by: User | None = None) -> None:
    for o in db.scalars(select(DispatchOffer).where(DispatchOffer.visit_id == visit.id, DispatchOffer.status == "offered")):
        o.status = "accepted" if accepted_by and o.user_id == accepted_by.id else "withdrawn"
        o.responded_at = utcnow()


def close_offers_for_order(db: Session, order: PharmacyOrder, taken_by: User) -> None:
    for o in db.scalars(select(DispatchOffer).where(DispatchOffer.order_id == order.id, DispatchOffer.status == "offered")):
        o.status = "accepted" if o.user_id == taken_by.id else "withdrawn"
        o.responded_at = utcnow()


def has_open_offer(db: Session, user: User, order_id: int) -> bool:
    return db.scalars(select(DispatchOffer.id).where(DispatchOffer.order_id == order_id, DispatchOffer.user_id == user.id,
                                                     DispatchOffer.status.in_(("offered", "accepted")))).first() is not None


# ------------------------------------------------------------------ trips
def start_trip(db: Session, user: User, *, leg: str, dest: tuple[float, float], dest_label: str,
               visit_id: int | None = None, order_id: int | None = None, lab_booking_id: int | None = None) -> Trip:
    for t in db.scalars(select(Trip).where(Trip.user_id == user.id, Trip.ended_at.is_(None))):
        end_trip(db, t)
    origin = provider_point(db, user)
    r = synthetic_route(origin, dest, dest_label)
    trip = Trip(user_id=user.id, visit_id=visit_id, order_id=order_id, lab_booking_id=lab_booking_id, leg=leg, dest_label=dest_label,
                speedup=SIM_SPEEDUP, started_at=utcnow(), **r)
    db.add(trip)
    db.flush()
    return trip


def start_trip_to_patient(db: Session, user: User, visit: HomeVisit) -> Trip:
    p = db.get(Patient, visit.patient_id)
    return start_trip(db, user, leg="to_patient", dest=(p.lat, p.lng), dest_label=f"{p.name.split()[0]}'s home",
                      visit_id=visit.id)


def depart(db: Session, user: User, visit_id: int) -> Trip:
    """Doctor starts driving to a booked (accepted) visit."""
    v = db.get(HomeVisit, visit_id)
    if v is None or v.doctor_id != user.doctor_id:
        raise NotFound("not_found", "Visit not found.")
    if v.status != VisitStatus.accepted:
        raise Conflict("bad_visit_state", "Accept the visit before you set off.")
    t = active_trip(db, user.id)
    if t and t.visit_id == v.id:
        return t
    face.require_for_journey(db, user, v)  # mandatory live face check for THIS visit, enforced here
    trip = start_trip_to_patient(db, user, v)
    notify(db, users_for_patient(db, v.patient_id), "Your doctor is on the way",
           f"{db.get(Doctor, user.doctor_id).name} is heading to you. Follow them live on the map.", f"visit:{v.id}")
    audit.record(db, user, "visit.depart", "home_visit", v.id)
    db.commit()
    return trip


def end_trip(db: Session, trip: Trip) -> None:
    if trip.ended_at:
        return
    now = utcnow()
    trip.arrived_at = trip.arrived_at or now
    trip.ended_at = now
    if trip.route:
        u = db.get(User, trip.user_id)
        u.lat, u.lng, u.loc_updated_at = trip.route[-1][0], trip.route[-1][1], now


def end_trips_for(db: Session, *, visit_id: int | None = None, order_id: int | None = None,
                  lab_booking_id: int | None = None) -> None:
    q = select(Trip).where(Trip.ended_at.is_(None))
    if lab_booking_id:
        q = q.where(Trip.lab_booking_id == lab_booking_id)
    else:
        q = q.where(Trip.visit_id == visit_id) if visit_id else q.where(Trip.order_id == order_id)
    for t in db.scalars(q):
        end_trip(db, t)


def set_route(db: Session, user: User, trip_id: int, route: list, steps: list, distance_m: float, duration_s: float,
              source: str) -> Trip:
    trip = db.get(Trip, trip_id)
    if trip is None or trip.user_id != user.id or trip.ended_at:
        raise NotFound("not_found", "Trip not found.")
    if len(route) < 2 or distance_m <= 0 or duration_s <= 0:
        raise Unprocessable("bad_route", "Route needs at least two points.")
    frac = progress(trip)["fraction"]
    trip.route = [[float(a), float(b)] for a, b in route][:5000]
    trip.steps = steps[:200]
    trip.distance_m, trip.duration_s, trip.source = float(distance_m), float(duration_s), source[:16]
    # Keep the same progress on the new route.
    trip.started_at = utcnow() - timedelta(seconds=frac * trip.duration_s / trip.speedup)
    db.commit()
    return trip


def update_location(db: Session, user: User, lat: float, lng: float) -> None:
    now = utcnow()
    user.lat, user.lng, user.loc_updated_at = lat, lng, now
    t = active_trip(db, user.id)
    if t:
        t.gps_lat, t.gps_lng, t.gps_at = lat, lng, now
    db.commit()


def set_duty(db: Session, user: User, online: bool) -> None:
    if user.role not in (Role.doctor, Role.courier, Role.phlebotomist, Role.physio):
        raise Forbidden("forbidden_role", "Only doctors, physiotherapists, couriers and sample collectors go online.")
    if online and not user.is_verified:
        raise Forbidden("not_verified", "Your account is still being verified. You can go online once Triyana approves it.")
    if user.role == Role.physio:
        from .physio import ensure_physio_verified
        ensure_physio_verified(db, user)
    if user.role == Role.doctor and not db.get(Doctor, user.doctor_id).license_verified:
        raise Forbidden("licence_not_verified", "Your licence must be verified before you can take visits.")
    if online:
        face.require_enrolled(db, user)
    user.on_duty = online
    if not online:
        for o in db.scalars(select(DispatchOffer).where(DispatchOffer.user_id == user.id, DispatchOffer.status == "offered",
                                                        DispatchOffer.expires_at.isnot(None))):
            o.status, o.responded_at = "withdrawn", utcnow()
            db.flush()
            _redispatch(db, o)
    audit.record(db, user, "provider.online" if online else "provider.offline", "user", user.id)
    db.commit()


def progress(trip: Trip) -> dict:
    now = utcnow()
    total = max(trip.distance_m, 1.0)
    if trip.ended_at or trip.arrived_at:
        traveled = total
    else:
        speed = total / max(trip.duration_s, 1.0) * trip.speedup
        traveled = min(total, (now - trip.started_at).total_seconds() * speed)
    pos, heading = _point_along(trip.route, traveled)
    remaining_m = total - traveled
    remaining_s = trip.duration_s * remaining_m / total
    if trip.gps_at and now - trip.gps_at < GPS_FRESH and not trip.arrived_at:  # real GPS wins
        pos = [trip.gps_lat, trip.gps_lng]
        remaining_m = _seg_m(pos, trip.route[-1]) * 1.3
        remaining_s = remaining_m / (CITY_KMH * 1000 / 3600)
    nxt = next((s for s in trip.steps if s["along_m"] > traveled + 5), trip.steps[-1] if trip.steps else None)
    return {"fraction": traveled / total, "traveled_m": round(traveled), "remaining_m": round(max(remaining_m, 0)),
            "remaining_s": round(max(remaining_s, 0)), "position": [round(pos[0], 6), round(pos[1], 6)],
            "heading": round(heading), "next_step": nxt,
            "next_step_in_m": round(max(nxt["along_m"] - traveled, 0)) if nxt else 0}


def tick(db: Session, trip: Trip) -> dict:
    """Progress, plus one-time arrival handling."""
    p = progress(trip)
    if p["remaining_m"] <= 0 and not trip.arrived_at:
        trip.arrived_at = utcnow()
        u = db.get(User, trip.user_id)
        u.lat, u.lng, u.loc_updated_at = p["position"][0], p["position"][1], utcnow()
        if trip.visit_id:
            v = db.get(HomeVisit, trip.visit_id)
            notify(db, users_for_patient(db, v.patient_id), "Your doctor has arrived",
                   f"{db.get(Doctor, v.doctor_id).name} is at your door.", f"visit:{v.id}")
        elif trip.lab_booking_id:
            from . import labs
            labs.arrival_notice(db, trip)
        elif trip.physio_session_id:
            from .physio import notify_arrival
            notify_arrival(db, trip)
        elif trip.order_id and trip.leg == "to_patient":
            o = db.get(PharmacyOrder, trip.order_id)
            notify(db, users_for_patient(db, o.patient_id), "Your courier has arrived",
                   "Your medicines are at your door. Have your handover code ready.", f"order:{o.id}")
        db.commit()
        p = progress(trip)
    return p


def trip_to_dict(db: Session, trip: Trip, *, with_route: bool = True) -> dict:
    p = tick(db, trip)
    out = {"id": trip.id, "leg": trip.leg, "visit_id": trip.visit_id, "order_id": trip.order_id,
           "lab_booking_id": trip.lab_booking_id,
           "physio_session_id": trip.physio_session_id,
           "dest_label": trip.dest_label, "origin": trip.route[0] if trip.route else None,
           "destination": trip.route[-1] if trip.route else None, "distance_m": round(trip.distance_m),
           "duration_s": round(trip.duration_s), "source": trip.source, "speedup": trip.speedup,
           "started_at": trip.started_at.isoformat(), "arrived": trip.arrived_at is not None,
           "ended": trip.ended_at is not None, "eta_min": math.ceil(p["remaining_s"] / 60), **p}
    if with_route:
        out["route"], out["steps"] = trip.route, trip.steps
    return out


# ------------------------------------------------------------------ views
def offer_to_dict(db: Session, o: DispatchOffer) -> dict:
    now = utcnow()
    base = {"id": o.id, "kind": o.kind, "status": o.status, "distance_km": o.distance_km,
            "expires_at": o.expires_at.isoformat() if o.expires_at else None,
            "seconds_left": max(0, int((o.expires_at - now).total_seconds())) if o.expires_at else None,
            "offer_seconds": OFFER_SECONDS}
    if o.kind == "physio":
        from .physio import offer_dict
        base.update(offer_dict(db, o))
    elif o.kind == "visit":
        v = o.visit
        p = db.get(Patient, v.patient_id)
        base.update({"title": "Home visit now" if v.on_demand else "Home visit booking", "on_demand": v.on_demand,
                     "visit_id": v.id,
                     "patient": p.name, "reason": v.reason, "scheduled_for": v.scheduled_for.isoformat(),
                     "address": v.address or p.address, "earning": v.fee,
                     "dropoff": {"lat": p.lat, "lng": p.lng, "label": p.name},
                     "drive_min": drive_minutes(o.distance_km)})
    elif o.kind == "lab":
        from . import labs
        base.update(labs.offer_fields(db, o))
    else:
        order = o.order
        p = db.get(Patient, order.patient_id)
        drop_km = round(haversine_km(order.pharmacy.lat, order.pharmacy.lng, p.lat, p.lng), 1)
        base.update({"title": "Medicine delivery", "on_demand": True, "patient": p.name, "order_no": order.order_no,
                     "earning": round(max(order.delivery_fee, 30) * 0.8, 2),
                     "pickup": {"lat": order.pharmacy.lat, "lng": order.pharmacy.lng, "label": order.pharmacy.name},
                     "dropoff": {"lat": p.lat, "lng": p.lng, "label": p.name}, "dropoff_km": drop_km,
                     "cold_chain": bool(order.delivery and order.delivery.cold_chain),
                     "drive_min": math.ceil((o.distance_km + drop_km) * 1.3 / CITY_KMH * 60 + 2)})
    return base


def provider_status(db: Session, user: User) -> dict:
    sweep(db)
    offers = db.scalars(select(DispatchOffer).where(DispatchOffer.user_id == user.id, DispatchOffer.status == "offered")
                        .order_by(DispatchOffer.id.desc())).all()
    trip = active_trip(db, user.id)
    lat, lng = provider_point(db, user)
    return {"name": user.name, "role": user.role.value, "online": user.on_duty, "location": [lat, lng],
            "can_go_online": user.role in (Role.doctor, Role.courier, Role.phlebotomist, Role.physio),
            "verification_status": user.verification_status or "verified",
            "offers": [offer_to_dict(db, o) for o in offers],
            "active_trip": trip_to_dict(db, trip, with_route=False) if trip else None,
            "sim_speedup": SIM_SPEEDUP}


def _provider_card(db: Session, user: User | None) -> dict | None:
    if not user:
        return None
    card = {"name": user.name.split(" (")[0], "role": user.role.value, "vehicle": user.vehicle}
    if user.doctor_id:
        d = db.get(Doctor, user.doctor_id)
        card.update({"name": d.name, "specialty": d.specialty, "rating": d.rating, "license_no": d.license_no})
    if user.physio_id:
        from ..models import Physiotherapist
        ph = db.get(Physiotherapist, user.physio_id)
        card.update({"name": ph.name, "specialty": f"Physiotherapist · {ph.qualification}", "rating": ph.rating,
                     "license_no": ph.registration_no})
    return card


def visit_live(db: Session, patient_user: User, visit_id: int) -> dict:
    sweep(db)
    v = db.get(HomeVisit, visit_id)
    if v is None or v.patient_id != patient_user.patient_id:
        raise NotFound("not_found", "Visit not found.")
    p = db.get(Patient, v.patient_id)
    trip = db.scalars(select(Trip).where(Trip.visit_id == v.id).order_by(Trip.id.desc())).first()
    doc_user = db.scalars(select(User).where(User.doctor_id == v.doctor_id)).first() if v.doctor_id else None
    asked = len(_already_asked(db, "visit", v.id))
    if v.status == VisitStatus.cancelled:
        phase = "cancelled"
    elif v.status == VisitStatus.completed:
        phase = "done"
    elif v.status == VisitStatus.in_progress:
        phase = "with_you"
    elif v.status == VisitStatus.requested:
        phase = "searching" if v.on_demand else "waiting"
    elif trip and not trip.ended_at:
        phase = "on_the_way"
    elif v.on_demand and doc_user and not face.ever_passed(db, doc_user.id, v.id):
        phase = "verifying"
    else:
        phase = "confirmed"
    t = trip_to_dict(db, trip) if trip and not trip.ended_at else None
    if t and t["arrived"]:
        phase = "arrived"
    identity = face.patient_view(db, v, doc_user) if doc_user else None
    promise = None
    if v.on_demand and v.promise_min:
        left = (v.created_at + timedelta(minutes=v.promise_min) - utcnow()).total_seconds()
        promise = {"minutes": v.promise_min, "seconds_left": round(left)}
    arrived_in_s = (round((trip.arrived_at - v.created_at).total_seconds())
                    if v.on_demand and trip and trip.arrived_at else None)
    return {"kind": "visit", "promise": promise, "arrived_in_s": arrived_in_s, "id": v.id, "booking_ref": v.booking_ref, "status": v.status.value, "phase": phase,
            "on_demand": v.on_demand, "reason": v.reason, "scheduled_for": v.scheduled_for.isoformat(),
            "home": {"lat": p.lat, "lng": p.lng, "label": "Home", "address": v.address or p.address},
            "provider": _provider_card(db, doc_user), "trip": t, "providers_asked": asked, "identity": identity,
            "online_nearby": online_count(db, "visit", p.lat, p.lng),
            "provider_location": t["position"] if t else (list(provider_point(db, doc_user)) if doc_user else None)}


def order_live(db: Session, user: User, order_id: int) -> dict:
    sweep(db)
    order = db.get(PharmacyOrder, order_id)
    if order is None or user.role != Role.patient or order.patient_id != user.patient_id:
        raise NotFound("not_found", "Order not found.")
    p = db.get(Patient, order.patient_id)
    d = order.delivery
    courier = db.get(User, d.courier_user_id) if d and d.courier_user_id else None
    trip = db.scalars(select(Trip).where(Trip.order_id == order.id).order_by(Trip.id.desc())).first()
    t = trip_to_dict(db, trip) if trip and not trip.ended_at else None
    if order.status.value in ("delivered", "picked_up"):
        phase = "done"
    elif order.status.value in ("cancelled", "rejected"):
        phase = "cancelled"
    elif d is None:
        phase = "preparing"
    elif courier is None:
        phase = "searching"
    elif t and t["leg"] == "to_pharmacy":
        phase = "to_pharmacy"
    elif t and t["arrived"]:
        phase = "arrived"
    elif t:
        phase = "on_the_way"
    else:
        phase = "assigned"
    return {"kind": "delivery", "id": order.id, "order_no": order.order_no, "status": order.status.value,
            "phase": phase, "home": {"lat": p.lat, "lng": p.lng, "label": "Home", "address": p.address},
            "pharmacy": {"lat": order.pharmacy.lat, "lng": order.pharmacy.lng, "label": order.pharmacy.name},
            "provider": _provider_card(db, courier), "trip": t,
            "provider_location": t["position"] if t else (list(provider_point(db, courier)) if courier else None),
            "online_nearby": online_count(db, "delivery", order.pharmacy.lat, order.pharmacy.lng)}


def provider_jobs(db: Session, user: User) -> list[dict]:
    """Accepted jobs for the provider app (visits for doctors, deliveries for couriers)."""
    out = []
    if user.role == Role.physio:
        from .physio import provider_jobs as physio_jobs
        return physio_jobs(db, user)
    if user.role == Role.doctor:
        for v in db.scalars(select(HomeVisit).where(HomeVisit.doctor_id == user.doctor_id,
                                                    HomeVisit.status.in_((VisitStatus.accepted, VisitStatus.in_progress)))
                            .order_by(HomeVisit.scheduled_for)):
            p = db.get(Patient, v.patient_id)
            trip = db.scalars(select(Trip).where(Trip.visit_id == v.id, Trip.ended_at.is_(None))).first()
            out.append({"kind": "visit", "id": v.id, "status": v.status.value, "patient": p.name, "reason": v.reason,
                        "identity_verified": face.visit_pass(db, user, v.id) is not None,
                        "arrival_confirmed": v.arrival_confirmed_at is not None,
                        "address": v.address or p.address, "scheduled_for": v.scheduled_for.isoformat(),
                        "on_demand": v.on_demand, "earning": v.fee, "trip_id": trip.id if trip else None,
                        "dropoff": {"lat": p.lat, "lng": p.lng, "label": p.name}})
    elif user.role == Role.courier:
        q = select(PharmacyOrder).join(DeliveryAssignment, DeliveryAssignment.order_id == PharmacyOrder.id).where(
            DeliveryAssignment.courier_user_id == user.id)
        for o in db.scalars(q.order_by(PharmacyOrder.id.desc())):
            p = db.get(Patient, o.patient_id)
            trip = db.scalars(select(Trip).where(Trip.order_id == o.id, Trip.ended_at.is_(None))).first()
            out.append({"kind": "delivery", "id": o.id, "status": o.status.value, "patient": p.name,
                        "order_no": o.order_no, "address": p.address, "trip_id": trip.id if trip else None,
                        "pickup": {"lat": o.pharmacy.lat, "lng": o.pharmacy.lng, "label": o.pharmacy.name},
                        "dropoff": {"lat": p.lat, "lng": p.lng, "label": p.name},
                        "cold_chain": o.delivery.cold_chain, "id_check_required": o.delivery.id_check_required})
    elif user.role == Role.phlebotomist:
        from . import labs
        out = labs.provider_jobs(db, user)
    return out
