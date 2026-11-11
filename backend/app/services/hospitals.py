"""Hospital accounts: drone (or road) consignments to and between hospitals."""
from __future__ import annotations

from sqlalchemy import or_, and_, select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import Forbidden, NotFound, Unprocessable
from ..models import AirspaceZone, DeliveryMission, Hospital, PharmacyOrder, Pharmacy, Role, Shipment, User
from . import drones as drone_svc
from .common import get_or_404, new_ref, notify

ALWAYS_COLD = {"blood", "vaccines"}
URGENCY = ("routine", "urgent", "emergency")
COVERAGE_PAYLOAD = drone_svc.Payload(weight_kg=2.0)  # a typical medicines box for the coverage view


def my_hospital(db: Session, user: User) -> Hospital:
    if user.role != Role.hospital or not user.hospital_id:
        raise Forbidden("forbidden_role", "Only hospital accounts can do this.")
    return db.get(Hospital, user.hospital_id)


def hospital_to_dict(h: Hospital) -> dict:
    return {"id": h.id, "name": h.name, "kind": h.kind, "registration_no": h.registration_no, "verified": h.verified,
            "address": h.address, "lat": h.lat, "lng": h.lng, "drone_pad": h.drone_pad, "cold_storage": h.cold_storage}


def _origin(db: Session, kind: str, origin_id: int) -> tuple[drone_svc.Place, str]:
    if kind == "pharmacy":
        ph = db.get(Pharmacy, origin_id)
        if not ph or not ph.license_verified:
            raise NotFound("not_found", "Pharmacy not found.")
        return drone_svc.pharmacy_place(ph), ph.jurisdiction
    if kind == "hospital":
        h = db.get(Hospital, origin_id)
        if not h or not h.verified:
            raise NotFound("not_found", "Hospital not found.")
        return drone_svc.hospital_place(h), h.jurisdiction
    raise Unprocessable("bad_origin", "Origin must be a pharmacy or a hospital.")


def network(db: Session, user: User) -> dict:
    """Every verified hospital and pharmacy, with whether a drone can serve it from this hospital."""
    me = my_hospital(db, user)
    here = drone_svc.hospital_place(me)
    rows = []
    for h in db.scalars(select(Hospital).where(Hospital.verified.is_(True), Hospital.id != me.id).order_by(Hospital.name)):
        a = drone_svc.assess(db, here, drone_svc.hospital_place(h), COVERAGE_PAYLOAD, me.jurisdiction)
        rows.append({**hospital_to_dict(h), "type": "hospital", "coverage": _coverage(a)})
    pharmacies = []
    for p in db.scalars(select(Pharmacy).where(Pharmacy.license_verified.is_(True)).order_by(Pharmacy.name)):
        a = drone_svc.assess(db, drone_svc.pharmacy_place(p), here, COVERAGE_PAYLOAD, me.jurisdiction)
        pharmacies.append({"id": p.id, "name": p.name, "address": p.address, "lat": p.lat, "lng": p.lng,
                           "drone_pad": p.drone_pad, "type": "pharmacy", "coverage": _coverage(a)})
    zones = [{"name": z.name, "kind": z.kind, "lat": z.lat, "lng": z.lng, "radius_km": z.radius_km,
              "authority": z.authority} for z in db.scalars(select(AirspaceZone))]
    by_drone = sum(1 for r in rows + pharmacies if r["coverage"]["drone"])
    return {"hospital": hospital_to_dict(me), "hospitals": rows, "pharmacies": pharmacies, "zones": zones,
            "summary": {"total": len(rows) + len(pharmacies), "drone": by_drone,
                        "road_only": len(rows) + len(pharmacies) - by_drone}}


def _coverage(a: drone_svc.Assessment) -> dict:
    return {"drone": a.eligible, "distance_km": round(a.distance_km, 1), "zone": a.zone,
            "needs_permission": a.needs_permission, "flight_minutes": a.flight_minutes,
            "road_minutes": drone_svc.road_courier.duration_minutes(a.distance_km),
            "reason": a.reason}


def _validate(db: Session, user: User, body: dict):
    me = my_hospital(db, user)
    origin_kind, origin_id, dest_id = body["origin_kind"], int(body["origin_id"]), int(body["dest_hospital_id"])
    origin, jurisdiction = _origin(db, origin_kind, origin_id)
    dest = db.get(Hospital, dest_id)
    if not dest or not dest.verified:
        raise NotFound("not_found", "Destination hospital not found.")
    if origin_kind == "hospital" and origin_id == dest_id:
        raise Unprocessable("same_site", "Origin and destination are the same hospital.")
    if dest.id != me.id and not (origin_kind == "hospital" and origin_id == me.id):
        raise Forbidden("not_your_hospital", "You can only send from or receive at your own hospital.")
    category = body.get("category", "medicines")
    if category not in drone_svc.CATEGORIES:
        raise Unprocessable("bad_category", "Unknown consignment type.")
    urgency = body.get("urgency", "routine")
    if urgency not in URGENCY:
        raise Unprocessable("bad_urgency", "Urgency must be routine, urgent or emergency.")
    weight = float(body.get("weight_kg") or 0)
    if not 0.05 <= weight <= 50:
        raise Unprocessable("bad_weight", "Weight must be between 0.05 and 50 kg.")
    payload = drone_svc.Payload(weight_kg=weight, cold_chain=bool(body.get("cold_chain")) or category in ALWAYS_COLD,
                                controlled=bool(body.get("controlled")))
    return me, origin, dest, jurisdiction, category, urgency, payload


def quote(db: Session, user: User, body: dict) -> dict:
    _, origin, dest, jurisdiction, _, urgency, payload = _validate(db, user, body)
    a = drone_svc.assess(db, origin, drone_svc.hospital_place(dest), payload, jurisdiction)
    return {**a.as_dict(), "road_minutes": drone_svc.road_courier.duration_minutes(a.distance_km, urgency),
            "cold_chain": payload.cold_chain}


def create(db: Session, user: User, body: dict) -> Shipment:
    me, origin, dest, jurisdiction, category, urgency, payload = _validate(db, user, body)
    contents = (body.get("contents") or "").strip()
    if not contents:
        raise Unprocessable("contents_required", "Describe what is being sent.")
    s = Shipment(ref=new_ref("SHP"), requested_by_user_id=user.id, origin_kind=body["origin_kind"],
                 origin_id=int(body["origin_id"]), dest_hospital_id=dest.id, category=category,
                 contents=contents[:300], weight_kg=payload.weight_kg, cold_chain=payload.cold_chain,
                 controlled=payload.controlled, urgency=urgency)
    db.add(s)
    db.flush()
    drone_svc.create_mission(db, origin, drone_svc.hospital_place(dest), payload, jurisdiction, urgency,
                             want_drone=body.get("mode", "auto") != "road", shipment=s)
    audit.record(db, user, "shipment.created", "shipment", s.id, mode=s.mission.mode, urgency=urgency,
                 fallback=s.mission.fallback_reason)
    _notify_parties(db, s, f"{drone_svc.CATEGORIES[category]} {s.ref} booked by "
                           f"{'drone' if s.mission.mode == 'drone' else 'road courier'}.", exclude=user)
    db.commit()
    return s


def _parties(db: Session, s: Shipment) -> list[User]:
    conds = [User.hospital_id == s.dest_hospital_id]
    if s.origin_kind == "hospital":
        conds.append(User.hospital_id == s.origin_id)
    else:
        conds.append(and_(User.pharmacy_id == s.origin_id, User.role == Role.pharmacist))
    return list(db.scalars(select(User).where(or_(*conds))))


def _notify_parties(db: Session, s: Shipment, body: str, exclude: User | None = None) -> None:
    users = [u for u in _parties(db, s) if not exclude or u.id != exclude.id]
    notify(db, users, f"Shipment {s.ref}", body, link=f"shipment:{s.id}")


def is_party(db: Session, user: User, s: Shipment) -> bool:
    return any(u.id == user.id for u in _parties(db, s))


def list_for(db: Session, user: User) -> list[Shipment]:
    if user.role == Role.hospital:
        q = or_(Shipment.dest_hospital_id == user.hospital_id,
                and_(Shipment.origin_kind == "hospital", Shipment.origin_id == user.hospital_id))
    elif user.role == Role.pharmacist:
        q = and_(Shipment.origin_kind == "pharmacy", Shipment.origin_id == user.pharmacy_id)
    else:
        return []
    return list(db.scalars(select(Shipment).where(q).order_by(Shipment.id.desc())))


def shipment_to_dict(db: Session, s: Shipment, zones: list | None = None) -> dict:
    origin_name = (db.get(Pharmacy, s.origin_id) if s.origin_kind == "pharmacy" else db.get(Hospital, s.origin_id)).name
    return {"id": s.id, "ref": s.ref, "origin_kind": s.origin_kind, "origin_name": origin_name,
            "route": "pharmacy_to_hospital" if s.origin_kind == "pharmacy" else "hospital_to_hospital",
            "destination": s.dest_hospital.name, "dest_hospital_id": s.dest_hospital_id, "category": s.category,
            "category_label": drone_svc.CATEGORIES[s.category], "contents": s.contents, "weight_kg": s.weight_kg,
            "cold_chain": s.cold_chain, "controlled": s.controlled, "urgency": s.urgency,
            "created_at": s.created_at.isoformat(),
            "mission": drone_svc.serialize_mission(s.mission, zones) if s.mission else None}


# ------------------------------------------------------------ mission access
def mission_for_user(db: Session, user: User, mission_id: int) -> DeliveryMission:
    m = get_or_404(db, DeliveryMission, mission_id, "Delivery")
    if m.shipment_id:
        if is_party(db, user, m.shipment):
            return m
    elif m.order_id:
        order = db.get(PharmacyOrder, m.order_id)
        if (user.role == Role.patient and user.patient_id == order.patient_id) or (
                user.role in (Role.pharmacist, Role.courier) and user.pharmacy_id == order.pharmacy_id):
            return m
    raise NotFound("not_found", "Delivery not found.")


def mission_action(db: Session, user: User, mission_id: int, action: str, body: dict) -> DeliveryMission:
    m = mission_for_user(db, user, mission_id)
    if not m.shipment_id:
        raise Forbidden("use_order_flow", "Patient deliveries are updated from the courier's delivery screen.")
    s = m.shipment
    if action == "launch":
        drone_svc.launch(m)
        _notify_parties(db, s, "Your consignment is in the air." if m.mode == "drone" else "Courier has picked it up.", user)
    elif action == "arrive":
        drone_svc.arrive(m)
        _notify_parties(db, s, "Your consignment has arrived. Please receive it.", user)
    elif action == "divert":
        drone_svc.divert_to_road(m, (body.get("reason") or "Weather hold before take-off.")[:200], s.urgency)
        _notify_parties(db, s, f"Switched to road courier: {m.fallback_reason}", user)
    elif action == "confirm":
        if user.role != Role.hospital or user.hospital_id != s.dest_hospital_id:
            raise Forbidden("receiver_only", "Only the receiving hospital can confirm receipt.")
        drone_svc.confirm(m, body.get("received_by") or "", body.get("temperature_ok"))
        _notify_parties(db, s, f"Received by {m.received_by}.", user)
    else:
        raise Unprocessable("bad_action", "Unknown action.")
    audit.record(db, user, f"mission.{action}", "mission", m.id, mode=m.mode)
    db.commit()
    return m

