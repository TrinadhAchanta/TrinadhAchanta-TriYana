"""Pharmacy matching engine: finds and ranks licensed pharmacies for a cart."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters.delivery import OPTION_INFO, SandboxDeliveryProvider
from ..adapters.geo import haversine_km
from ..adapters.pharmacy import MockPharmacyNetwork
from ..models import CartItem, CartItemStatus, Patient, Pharmacy, SuggestedCart, utcnow
from .dispensing_rules import evaluate_quantity_request, policy_for
from .prescriptions import is_dispensable

SORTS = ("nearest", "price", "fastest", "rating", "pickup")


@dataclass
class ItemAvailability:
    cart_item_id: int
    medication: str
    quantity: int
    carried: bool
    in_stock: bool | None          # None => not verifiable
    stock_status: str              # confirmed | unconfirmed | out_of_stock | not_carried
    unit_price: float | None
    line_total: float | None
    quantity_allowed: bool
    quantity_note: str = ""


@dataclass
class PharmacyMatch:
    pharmacy: Pharmacy
    distance_km: float
    within_service_area: bool
    open_now: bool
    eligible: bool
    reasons: list[str]
    items: list[ItemAvailability]
    subtotal: float
    delivery_fee: float
    tax: float
    total: float
    eta_minutes: int | None
    delivery_options: list[str]
    all_stock_confirmed: bool
    recommended: bool = False
    score: float = 0.0
    extras: dict = field(default_factory=dict)


def is_open(pharmacy: Pharmacy, now: datetime | None = None) -> bool:
    hour = (now or utcnow()).hour
    if pharmacy.opens_at == 0 and pharmacy.closes_at == 24:
        return True
    return pharmacy.opens_at <= hour < pharmacy.closes_at


def active_items(cart: SuggestedCart) -> list[CartItem]:
    return [i for i in cart.items if i.status == CartItemStatus.in_cart]


def match_pharmacies(
    db: Session,
    cart: SuggestedCart,
    patient: Patient,
    sort: str = "nearest",
    now: datetime | None = None,
) -> list[PharmacyMatch]:
    network = MockPharmacyNetwork(db)
    courier = SandboxDeliveryProvider()
    rx = cart.prescription
    policy = policy_for(rx.jurisdiction)
    rx_ok, rx_reason = is_dispensable(rx)
    items = active_items(cart)
    results: list[PharmacyMatch] = []

    for ph in db.scalars(select(Pharmacy).where(Pharmacy.jurisdiction == rx.jurisdiction)):
        reasons: list[str] = []
        if not ph.license_verified:
            continue  # unlicensed / unverified pharmacies are never shown
        dist = round(haversine_km(patient.lat, patient.lng, ph.lat, ph.lng), 1)
        in_area = dist <= ph.service_radius_km
        open_now = is_open(ph, now)
        if not rx_ok:
            reasons.append(rx_reason)
        if not in_area and not ph.pickup_available:
            reasons.append("Outside this pharmacy's service area.")

        lines: list[ItemAvailability] = []
        subtotal = 0.0
        all_confirmed = True
        for ci in items:
            pi = ci.prescription_item
            med = pi.medication
            info = network.stock(ph, med.id)
            qty = ci.requested_quantity
            qd = evaluate_quantity_request(
                med=med, prescribed=pi.quantity, requested=qty, jurisdiction=rx.jurisdiction, pharmacy=ph
            )
            if not info.carried:
                status, in_stock = "not_carried", False
            elif not info.verified:
                status, in_stock = "unconfirmed", None
            elif info.units_in_stock >= qty:
                status, in_stock = "confirmed", True
            else:
                status, in_stock = "out_of_stock", False
            if status != "confirmed":
                all_confirmed = False
            line_total = round(info.unit_price * qty, 2) if info.unit_price is not None else None
            if line_total is not None:
                subtotal += line_total
            lines.append(ItemAvailability(
                cart_item_id=ci.id, medication=f"{med.brand_name} {med.strength}", quantity=qty,
                carried=info.carried, in_stock=in_stock, stock_status=status,
                unit_price=info.unit_price, line_total=line_total,
                quantity_allowed=qd.permitted, quantity_note="" if qd.permitted else qd.explanation,
            ))
            if status in ("not_carried", "out_of_stock"):
                reasons.append(f"{med.brand_name} is not available here.")
            if not qd.permitted:
                reasons.append(qd.explanation)

        options = [o for o in (ph.delivery_options or []) if o in OPTION_INFO]
        drone_note = None
        if "drone" in options:
            if not policy.drone_delivery_permitted:
                options = [o for o in options if o != "drone"]
            else:
                from . import drones as drone_svc  # local import: drones imports common helpers
                payload = drone_svc.order_payload([(ci.prescription_item.medication, ci.requested_quantity) for ci in items])
                home = drone_svc.Place("Your home", patient.lat, patient.lng, "patient_home")
                check = drone_svc.assess(db, drone_svc.pharmacy_place(ph), home, payload, rx.jurisdiction)
                if not check.eligible:
                    options = [o for o in options if o != "drone"]
                    drone_note = check.reason
                else:
                    drone_note = f"Drone can reach you in about {check.flight_minutes} min after packing."
        if not (ph.delivery_available and in_area):
            options = []
        if not options and not ph.pickup_available:
            reasons.append("No delivery or pickup available to your address.")
        eta = courier.eta_minutes(options[0], dist, ph.prep_minutes) if options else None
        fee = ph.delivery_fee if options else 0.0
        subtotal = round(subtotal, 2)
        tax = round(subtotal * policy.tax_rate, 2)
        results.append(PharmacyMatch(
            pharmacy=ph, distance_km=dist, within_service_area=in_area, open_now=open_now,
            eligible=not reasons and bool(items), reasons=reasons, items=lines,
            subtotal=subtotal, delivery_fee=fee, tax=tax, total=round(subtotal + fee + tax, 2),
            eta_minutes=eta, delivery_options=options, all_stock_confirmed=all_confirmed,
            extras={"drone_note": drone_note},
        ))

    eligible = [r for r in results if r.eligible]
    if eligible:
        # Balanced recommendation score: price, speed, distance, rating, confirmed stock.
        max_total = max(r.total for r in eligible) or 1
        max_eta = max((r.eta_minutes or 600) for r in eligible) or 1
        max_dist = max(r.distance_km for r in eligible) or 1
        for r in eligible:
            r.score = round(
                0.35 * (1 - r.total / max_total)
                + 0.25 * (1 - (r.eta_minutes or 600) / max_eta)
                + 0.15 * (1 - r.distance_km / max_dist)
                + 0.15 * (r.pharmacy.rating / 5)
                + 0.10 * (1 if r.all_stock_confirmed else 0)
                + (0.05 if r.open_now else 0),
                4,
            )
        max(eligible, key=lambda r: r.score).recommended = True

    keys = {
        "nearest": lambda r: r.distance_km,
        "price": lambda r: r.total,
        "fastest": lambda r: r.eta_minutes if r.eta_minutes is not None else 10**6,
        "rating": lambda r: -r.pharmacy.rating,
        "pickup": lambda r: (not r.pharmacy.pickup_available, r.distance_km),
    }
    key = keys.get(sort, keys["nearest"])
    results.sort(key=lambda r: (not r.eligible, key(r)))
    if sort == "pickup":
        results = [r for r in results if r.pharmacy.pickup_available]
    return results


def match_to_dict(m: PharmacyMatch) -> dict:
    ph = m.pharmacy
    return {
        "pharmacy_id": ph.id,
        "name": ph.name,
        "verified": {
            "license_no": ph.license_no,
            "license_verified": ph.license_verified,
            "business_reg_no": ph.business_reg_no,
        },
        "address": ph.address,
        "distance_km": m.distance_km,
        "within_service_area": m.within_service_area,
        "hours": f"{ph.opens_at:02d}:00–{ph.closes_at:02d}:00" if not (ph.opens_at == 0 and ph.closes_at == 24) else "Open 24 hours",
        "open_now": m.open_now,
        "rating": ph.rating,
        "rating_count": ph.rating_count,
        "pickup_available": ph.pickup_available,
        "delivery_available": bool(m.delivery_options),
        "delivery_options": [{"code": o, "label": OPTION_INFO[o]["label"]} for o in m.delivery_options],
        "eta_minutes": m.eta_minutes,
        "drone_note": m.extras.get("drone_note"),
        "items": [vars(i) for i in m.items],
        "all_stock_confirmed": m.all_stock_confirmed,
        "subtotal": m.subtotal,
        "delivery_fee": m.delivery_fee,
        "tax": m.tax,
        "total": m.total,
        "eligible": m.eligible,
        "reasons": m.reasons,
        "recommended": m.recommended,
        "score": m.score,
    }
