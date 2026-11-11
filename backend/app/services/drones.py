"""Drone delivery eligibility (India, Drone Rules 2021) and delivery missions.

Every leg is checked before a drone is booked. If any check fails the leg goes
by road courier instead, and the reason is shown to the people involved.

Rules modelled (simplified for a demo, NOT legal advice; a real launch needs
review against the current Drone Rules 2021, the DGCA airspace map on Digital
Sky, any BVLOS permissions and state health-department requirements):
  * Airspace zones: red = no-fly without central-government permission, so we
    never route through one; yellow = needs ATC / airport-operator permission,
    which the operator requests for registered drone pads only; green = up to
    120 m (400 ft) with no prior permission.
  * Drone must hold a UIN and be flown by a holder of a Remote Pilot
    Certificate; the operator must be authorised for this state.
  * Payload and range within the drone's type-certified limits.
  * Cold chain: an active 2–8 °C box that holds temperature for the whole flight.
  * Controlled (NDPS / narcotic-style) medicines are not flown; they go by road
    with an identity check.
  * Wind within the airframe's limit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters.drones import CRUISE_ALTITUDE_M, MAX_WIND_KMH, drone_provider, road_courier
from ..adapters.geo import haversine_km
from ..errors import Conflict, Unprocessable
from ..models import AirspaceZone, DeliveryMission, Hospital, Pharmacy, Shipment, utcnow
from .common import new_ref

ZONE_RANK = {"green": 0, "yellow": 1, "red": 2}

# Rough packed weights for medicine orders (kg per unit), plus packaging.
UNIT_WEIGHT_KG = {"tablet": 0.0015, "capsule": 0.0015, "pen": 0.035, "syrup": 0.0012, "injection": 0.02}
PACKAGING_KG = 0.25

CATEGORIES = {
    "medicines": "Medicines",
    "blood": "Blood units",
    "vaccines": "Vaccines",
    "lab_samples": "Lab samples",
    "antivenom": "Anti-snake venom",
}


@dataclass
class Place:
    name: str
    lat: float
    lng: float
    kind: str           # pharmacy | hospital | patient_home
    drone_pad: bool = False

    def as_dict(self) -> dict:
        return {"name": self.name, "lat": self.lat, "lng": self.lng, "kind": self.kind}


@dataclass
class Payload:
    weight_kg: float
    cold_chain: bool = False
    controlled: bool = False


@dataclass
class Check:
    code: str
    label: str
    ok: bool
    detail: str

    def as_dict(self) -> dict:
        return {"code": self.code, "label": self.label, "ok": self.ok, "detail": self.detail}


@dataclass
class Assessment:
    eligible: bool
    checks: list[Check]
    distance_km: float
    zone: str                          # worst zone on the route
    zones: list[dict] = field(default_factory=list)
    drone: object | None = None
    needs_permission: bool = False
    flight_minutes: int | None = None

    @property
    def reason(self) -> str | None:
        failed = [c for c in self.checks if not c.ok]
        return failed[0].detail if failed else None

    def as_dict(self) -> dict:
        return {
            "eligible": self.eligible, "distance_km": round(self.distance_km, 1), "zone": self.zone,
            "zones": self.zones, "needs_permission": self.needs_permission,
            "flight_minutes": self.flight_minutes, "reason": self.reason,
            "drone": {"model": self.drone.model, "uin": self.drone.uin} if self.drone else None,
            "checks": [c.as_dict() for c in self.checks],
        }


# ------------------------------------------------------------------ geometry
def zones_on_route(db: Session, a: Place, b: Place, samples: int = 40) -> list[AirspaceZone]:
    zones = list(db.scalars(select(AirspaceZone)))
    hit: dict[int, AirspaceZone] = {}
    for i in range(samples + 1):
        t = i / samples
        lat, lng = a.lat + (b.lat - a.lat) * t, a.lng + (b.lng - a.lng) * t
        for z in zones:
            if haversine_km(lat, lng, z.lat, z.lng) <= z.radius_km:
                hit[z.id] = z
    return sorted(hit.values(), key=lambda z: -ZONE_RANK[z.kind])


def zone_at(db: Session, lat: float, lng: float) -> str:
    worst = "green"
    for z in db.scalars(select(AirspaceZone)):
        if haversine_km(lat, lng, z.lat, z.lng) <= z.radius_km and ZONE_RANK[z.kind] > ZONE_RANK[worst]:
            worst = z.kind
    return worst


def order_payload(meds_and_qty: list[tuple]) -> Payload:
    weight = PACKAGING_KG + sum(UNIT_WEIGHT_KG.get(m.form, 0.01) * q for m, q in meds_and_qty)
    return Payload(
        weight_kg=round(weight, 2),
        cold_chain=any(m.cold_chain for m, _ in meds_and_qty),
        controlled=any(m.id_check_required or m.schedule.value == "controlled" for m, _ in meds_and_qty),
    )


# ---------------------------------------------------------------- eligibility
def assess(db: Session, origin: Place, dest: Place, payload: Payload, jurisdiction: str) -> Assessment:
    provider = drone_provider
    dist = haversine_km(origin.lat, origin.lng, dest.lat, dest.lng)
    route = zones_on_route(db, origin, dest)
    worst = route[0].kind if route else "green"
    checks: list[Check] = []

    covered = jurisdiction in provider.operating_jurisdictions
    checks.append(Check("operator", "Authorised drone operator", covered,
                        "A DGCA-authorised operator with a UIN-registered drone and certified remote pilot serves this area."
                        if covered else "No authorised drone operator serves this area yet."))

    reds = [z for z in route if z.kind == "red"]
    checks.append(Check("red_zone", "No red zones", not reds,
                        "Route stays clear of red (no-fly) zones." if not reds else
                        f"The route crosses a red zone ({reds[0].name}). Drones can't fly there."))

    yellows = [z for z in route if z.kind == "yellow"]
    needs_permission = bool(yellows)
    if yellows:
        pads = origin.drone_pad and dest.drone_pad and dest.kind != "patient_home"
        checks.append(Check("yellow_zone", "Yellow zone permission", pads,
                            f"Crosses a yellow zone ({yellows[0].name}). The operator requests ATC permission for this "
                            "pad-to-pad corridor, which adds about 15 minutes." if pads else
                            f"The address is in or behind a yellow zone ({yellows[0].name}). Only registered "
                            "pad-to-pad corridors get permission there, so this goes by road."))
    else:
        checks.append(Check("yellow_zone", "Green zone flight", True,
                            f"Whole route is in green zone. Cruise at {CRUISE_ALTITUDE_M} m, under the 120 m ceiling."))

    if dest.kind == "patient_home":
        landing_ok = origin.drone_pad
        landing_detail = ("Lowered by winch at the home's surveyed drop point." if landing_ok
                          else "The pharmacy has no drone launch pad.")
    else:
        landing_ok = origin.drone_pad and dest.drone_pad
        missing = [p.name for p in (origin, dest) if not p.drone_pad]
        landing_detail = ("Both sites have a registered drone pad." if landing_ok
                          else f"{missing[0]} has no registered drone pad.")
    checks.append(Check("landing", "Launch and landing site", landing_ok, landing_detail))

    if payload.controlled:
        checks.append(Check("controlled", "Medicine type", False,
                            "Controlled medicines need an identity check on hand-over, so they go by road."))
    else:
        checks.append(Check("controlled", "Medicine type", True, "No controlled medicines in this consignment."))

    drone = provider.pick_drone(dist, payload.weight_kg, payload.cold_chain)
    max_range = max(d.range_km for d in _fleet())
    checks.append(Check("range", "Distance", dist <= max_range,
                        f"{dist:.1f} km is within drone range ({max_range:.0f} km)." if dist <= max_range else
                        f"{dist:.1f} km is beyond drone range ({max_range:.0f} km)."))
    max_payload = max((d.cold_box_payload_kg if payload.cold_chain else d.max_payload_kg) for d in _fleet())
    pay_ok = payload.weight_kg <= max_payload
    checks.append(Check("payload", "Payload weight", pay_ok,
                        f"{payload.weight_kg:.2f} kg is within the {max_payload:.1f} kg limit"
                        f"{' with the cold box fitted' if payload.cold_chain else ''}." if pay_ok else
                        f"{payload.weight_kg:.2f} kg is over the {max_payload:.1f} kg limit"
                        f"{' with the cold box fitted' if payload.cold_chain else ''}."))

    flight = provider.flight_minutes(drone, dist) if drone else None
    if payload.cold_chain:
        hold = drone.cold_box_hold_minutes if drone else 0
        ok = bool(drone) and flight + 15 <= hold
        checks.append(Check("cold_chain", "Cold chain 2–8 °C", ok,
                            f"Active cold box holds 2–8 °C for {hold} min; flight is {flight} min." if ok else
                            "No drone can keep this consignment at 2–8 °C for the whole trip."))

    wind = provider.wind_kmh(origin.lat, origin.lng)
    checks.append(Check("weather", "Weather", wind <= MAX_WIND_KMH,
                        f"Wind {wind:.0f} km/h (limit {MAX_WIND_KMH:.0f})." if wind <= MAX_WIND_KMH else
                        f"Wind {wind:.0f} km/h is above the {MAX_WIND_KMH:.0f} km/h limit."))

    eligible = all(c.ok for c in checks) and drone is not None
    return Assessment(
        eligible=eligible, checks=checks, distance_km=dist, zone=worst,
        zones=[{"name": z.name, "kind": z.kind} for z in route], drone=drone if eligible else None,
        needs_permission=needs_permission and eligible, flight_minutes=flight if eligible else None,
    )


def _fleet():
    from ..adapters.drones import FLEET
    return FLEET


# ------------------------------------------------------------------- missions
def _log(m: DeliveryMission, status: str, note: str) -> None:
    m.events = [*(m.events or []), {"status": status, "note": note, "at": utcnow().isoformat()}]


def create_mission(db: Session, origin: Place, dest: Place, payload: Payload, jurisdiction: str,
                   urgency: str = "routine", want_drone: bool = True, shipment: Shipment | None = None,
                   order_id: int | None = None) -> DeliveryMission:
    a = assess(db, origin, dest, payload, jurisdiction)
    corridor = f"{origin.name}->{dest.name}"
    m = DeliveryMission(ref=new_ref("MSN"), shipment_id=shipment.id if shipment else None, order_id=order_id,
                        origin=origin.as_dict(), destination=dest.as_dict(), distance_km=round(a.distance_km, 1),
                        cold_chain=payload.cold_chain, checks=[c.as_dict() for c in a.checks], events=[],
                        temperature_log=[])
    if want_drone and a.eligible:
        b = drone_provider.book(a.drone, a.distance_km, a.needs_permission, corridor)
        m.mode, m.provider, m.status = "drone", drone_provider.name, "scheduled"
        m.duration_minutes, m.eta, m.handover_code = b.duration_minutes, b.eta, b.handover_code
        m.vehicle = {"type": "drone", "model": b.drone.model, "uin": b.drone.uin, "category": b.drone.category,
                     "provider_ref": b.provider_ref}
        m.compliance = {"remote_pilot": b.remote_pilot, "max_altitude_m": CRUISE_ALTITUDE_M,
                        "zone": a.zone, "permission_ref": b.permission_ref,
                        "rules": "Drone Rules 2021 (India)", "bvlos": True}
        _log(m, "scheduled", f"Drone {b.drone.uin} booked. Pre-flight checks under way."
             + (f" ATC permission {b.permission_ref} requested for the yellow zone." if b.permission_ref else ""))
    else:
        reason = a.reason if want_drone else "Road delivery chosen."
        _book_road(m, a.distance_km, payload.cold_chain, urgency, reason)
    db.add(m)
    db.flush()
    return m


def _book_road(m: DeliveryMission, distance_km: float, cold_chain: bool, urgency: str, reason: str | None) -> None:
    b = road_courier.book(distance_km, cold_chain, urgency)
    m.mode, m.provider, m.status = "road", road_courier.name, "scheduled"
    m.duration_minutes, m.eta = b.duration_minutes, b.eta
    if not m.handover_code:
        m.handover_code = b.handover_code
    m.vehicle = {"type": "road", "courier": b.courier, "vehicle": b.vehicle, "provider_ref": b.provider_ref}
    m.compliance = {}
    m.fallback_reason = reason
    _log(m, "scheduled", f"Road courier {b.courier} assigned ({b.vehicle})."
         + (f" Drone not used: {reason}" if reason and reason != "Road delivery chosen." else ""))


def launch(m: DeliveryMission) -> None:
    if m.status != "scheduled":
        raise Conflict("bad_state", "This delivery has already left.")
    m.status = "in_flight" if m.mode == "drone" else "in_transit"
    m.launched_at = utcnow()
    m.eta = m.launched_at + timedelta(minutes=m.duration_minutes)
    if m.cold_chain:
        m.temperature_log = [*(m.temperature_log or []), {"at": utcnow().isoformat(), "celsius": 4.6}]
    _log(m, m.status, "Drone took off." if m.mode == "drone" else "Courier picked up the consignment.")


def arrive(m: DeliveryMission) -> None:
    if m.status not in ("in_flight", "in_transit"):
        raise Conflict("bad_state", "This delivery isn't on its way.")
    m.status = "arrived"
    if m.cold_chain:
        m.temperature_log = [*(m.temperature_log or []), {"at": utcnow().isoformat(), "celsius": 5.2}]
    _log(m, "arrived", "Drone landed on the pad." if m.mode == "drone" and m.destination.get("kind") != "patient_home"
         else "Lowered at the drop point." if m.mode == "drone" else "Courier has arrived.")


def divert_to_road(m: DeliveryMission, reason: str, urgency: str = "routine") -> None:
    """Pre-flight abort (e.g. weather hold): hand the consignment to a road courier."""
    if m.mode != "drone" or m.status != "scheduled":
        raise Conflict("bad_state", "Only a drone delivery that hasn't taken off can be switched to road.")
    _book_road(m, m.distance_km, m.cold_chain, urgency, reason)


def confirm(m: DeliveryMission, received_by: str, temperature_ok: bool | None = None) -> None:
    if m.status not in ("arrived", "in_flight", "in_transit"):
        raise Conflict("bad_state", "This delivery hasn't arrived yet.")
    if m.cold_chain and not temperature_ok:
        raise Unprocessable("temperature_check", "Confirm the cold-chain indicator shows 2–8 °C before accepting.")
    if not received_by.strip():
        raise Unprocessable("receiver_required", "Enter who received it.")
    m.status = "delivered"
    m.received_by = received_by.strip()[:120]
    m.delivered_at = utcnow()
    _log(m, "delivered", f"Received by {m.received_by}.")


def progress(m: DeliveryMission) -> float:
    if m.status in ("arrived", "delivered"):
        return 1.0
    if m.status in ("in_flight", "in_transit") and m.launched_at:
        elapsed = (utcnow() - m.launched_at).total_seconds() / 60
        return round(min(0.95, max(0.02, elapsed / max(1, m.duration_minutes))), 3)
    return 0.0


STATUS_LABEL = {
    "scheduled": "Preparing for take-off", "in_flight": "In the air", "in_transit": "On the road",
    "arrived": "Arrived", "delivered": "Delivered", "cancelled": "Cancelled",
}


def serialize_mission(m: DeliveryMission, zones: list[AirspaceZone] | None = None) -> dict:
    p = progress(m)
    o, d = m.origin, m.destination
    label = STATUS_LABEL.get(m.status, m.status)
    if m.mode == "road" and m.status == "scheduled":
        label = "Courier on the way to pick up"
    return {
        "id": m.id, "ref": m.ref, "mode": m.mode, "provider": m.provider, "status": m.status, "status_label": label,
        "origin": o, "destination": d, "distance_km": m.distance_km, "duration_minutes": m.duration_minutes,
        "eta": m.eta.isoformat() if m.eta else None, "progress": p,
        "position": {"lat": o["lat"] + (d["lat"] - o["lat"]) * p, "lng": o["lng"] + (d["lng"] - o["lng"]) * p},
        "vehicle": m.vehicle, "compliance": m.compliance, "checks": m.checks, "fallback_reason": m.fallback_reason,
        "cold_chain": m.cold_chain, "temperature_log": m.temperature_log, "received_by": m.received_by,
        "events": m.events, "launched_at": m.launched_at.isoformat() if m.launched_at else None,
        "delivered_at": m.delivered_at.isoformat() if m.delivered_at else None,
        "zones": [{"name": z.name, "kind": z.kind, "lat": z.lat, "lng": z.lng, "radius_km": z.radius_km}
                  for z in (zones or [])],
    }


# ------------------------------------------------------------------ places
def hospital_place(h: Hospital) -> Place:
    return Place(h.name, h.lat, h.lng, "hospital", h.drone_pad)


def pharmacy_place(p: Pharmacy) -> Place:
    return Place(p.name, p.lat, p.lng, "pharmacy", p.drone_pad)
