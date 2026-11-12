"""Online medicine shop: browse, add to basket, pay, and a rider delivers to the door.

* Over-the-counter (OTC) products are sold freely.
* Prescription medicines are never sold from the shop basket. They are bought only against a
  valid, signed Triyana prescription, through that prescription's medicine cart (pharmacist
  review included). The shop links the patient straight to that cart when they have one.
* Schedule X medicines are never sold online.

A shop order goes to the nearest licensed pharmacy that has the whole basket in stock. The
pharmacy accepts it straight away (no prescription to check), packs it, and the delivery is
offered to the nearest online rider in Triyana Partner, with live map tracking for the patient.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..adapters.delivery import OPTION_INFO
from ..adapters.geo import haversine_km
from ..adapters.pharmacy import MockPharmacyNetwork
from ..adapters.razorpay import RazorpayError, RazorpayGateway
from ..errors import Conflict, NotFound, PaymentDeclined, Unprocessable
from ..models import (
    CartItemStatus,
    Medication,
    MedSchedule,
    OrderItem,
    OrderStatus,
    Patient,
    Payment,
    PaymentStatus,
    Pharmacy,
    PharmacyOrder,
    TrackingEvent,
    User,
    utcnow,
)
from . import orders as order_svc
from .carts import latest_cart
from .common import new_ref, notify, users_for_pharmacy
from .dispensing_rules import policy_for
from .india import SCHEDULE_X_NOTE, applies as india_applies, schedule_info
from .matching import is_open
from .prescriptions import is_dispensable

MAX_PACKS = 10
MAX_LINES = 20
SHOP_OPTIONS = ("priority", "same_day", "standard")  # rider delivery speeds, fastest first
# Demo stand-in for the pharmacy's own system confirming and packing the order.
ACCEPT_TO_PACKING_S = int(os.environ.get("TRIYANA_SHOP_PACKING_SECONDS", "8"))
PACKED_AFTER_S = int(os.environ.get("TRIYANA_SHOP_PACKED_SECONDS", "30"))

RX_NOTE = "Prescription medicine. You can buy it only with a valid prescription from a registered doctor."


# ------------------------------------------------------------------ rules
def kind_of(med: Medication, jurisdiction: str) -> str:
    """'otc' (sold freely), 'rx' (only against a prescription) or 'blocked' (never online)."""
    if india_applies(jurisdiction):
        code = med.india_schedule or "H"
        if code == "X":
            return "blocked"
        return "otc" if code == "OTC" and med.schedule == MedSchedule.otc else "rx"
    return "otc" if med.schedule == MedSchedule.otc else "rx"


def pack_size(med: Medication) -> int:
    return max(med.pack_sizes or [1])


def pack_label(med: Medication) -> str:
    n = pack_size(med)
    if n == 1:
        return "1 device" if med.form == "device" else f"{med.strength} {med.unit.rstrip('s')}"
    return f"Pack of {n} {med.unit}"


def _patient(db: Session, user: User) -> Patient:
    return db.get(Patient, user.patient_id)


def _nearby_pharmacies(db: Session, patient: Patient) -> list[tuple[Pharmacy, float]]:
    out = []
    for ph in db.scalars(select(Pharmacy).where(Pharmacy.jurisdiction == patient.jurisdiction,
                                                Pharmacy.license_verified.is_(True),
                                                Pharmacy.delivery_available.is_(True))):
        km = round(haversine_km(patient.lat, patient.lng, ph.lat, ph.lng), 1)
        if km <= ph.service_radius_km and is_open(ph):
            out.append((ph, km))
    return sorted(out, key=lambda r: r[1])


def _rx_carts(db: Session, patient_id: int) -> dict[int, dict]:
    """medication_id -> the patient's prescription cart that can still buy it."""
    from ..models import SuggestedCart
    out: dict[int, dict] = {}
    for cart in db.scalars(select(SuggestedCart).where(SuggestedCart.patient_id == patient_id)
                           .order_by(SuggestedCart.id.desc())):
        ok, _ = is_dispensable(cart.prescription)
        if not ok:
            continue
        for ci in cart.items:
            med_id = ci.prescription_item.medication_id
            if ci.status != CartItemStatus.ordered and med_id not in out:
                out[med_id] = {"cart_id": cart.id, "cart_item_id": ci.id,
                               "prescription": cart.prescription.reference_no,
                               "doctor": cart.prescription.doctor.name}
    return out


# ------------------------------------------------------------------ catalog
def catalog(db: Session, user: User, q: str = "", category: str = "") -> dict:
    patient = _patient(db, user)
    juris = patient.jurisdiction
    nearby = _nearby_pharmacies(db, patient)
    network = MockPharmacyNetwork(db)
    rx_carts = _rx_carts(db, patient.id)
    products = []
    categories: dict[str, int] = {}
    otc_aisles: set[str] = set()
    needle = q.strip().lower()
    for med in db.scalars(select(Medication).order_by(Medication.brand_name)):
        kind = kind_of(med, juris)
        cat = med.category or ("Everyday care" if kind == "otc" else "Prescription medicines")
        if needle and needle not in f"{med.brand_name} {med.generic_name} {cat}".lower():
            continue
        categories[cat] = categories.get(cat, 0) + 1
        if kind == "otc":
            otc_aisles.add(cat)
        if category and cat != category:
            continue
        n = pack_size(med)
        prices, stocked = [], 0
        for ph, _ in nearby:
            info = network.stock(ph, med.id)
            if info.carried and info.unit_price is not None and (info.units_in_stock or 0) >= n:
                prices.append(info.unit_price)
                stocked += 1
        price = round(min(prices) * n, 2) if prices else round(med.reference_unit_price * n, 2)
        item = {
            "id": med.id, "name": med.brand_name, "generic_name": med.generic_name, "strength": med.strength,
            "form": med.form, "unit": med.unit, "pack_size": n, "pack_label": pack_label(med),
            "category": cat, "description": med.description, "kind": kind,
            "india_schedule": schedule_info(med, juris), "cold_chain": med.cold_chain,
            "price": price, "mrp": round(med.reference_unit_price * n * 1.15, 2),
            "in_stock": stocked > 0, "pharmacies_in_stock": stocked, "max_packs": MAX_PACKS,
        }
        if kind == "rx":
            item["note"] = RX_NOTE
            item["rx_cart"] = rx_carts.get(med.id)
        elif kind == "blocked":
            item["note"] = SCHEDULE_X_NOTE
        products.append(item)
    products.sort(key=lambda p: ({"otc": 0, "rx": 1, "blocked": 2}[p["kind"]], not p["in_stock"], p["name"]))
    return {
        "currency": policy_for(juris).currency,
        "categories": [{"name": k, "count": v} for k, v in
                       sorted(categories.items(), key=lambda kv: (kv[0] not in otc_aisles, kv[0]))],
        "products": products,
        "pharmacies_nearby": len(nearby),
        "rule": "Over-the-counter products ship without a prescription. Prescription medicines are sold only "
                "against a valid prescription from a registered doctor, after a pharmacist checks it.",
    }


# ------------------------------------------------------------------ basket pricing
@dataclass
class Line:
    med: Medication
    packs: int

    @property
    def units(self) -> int:
        return self.packs * pack_size(self.med)


def _lines(db: Session, patient: Patient, items: list[dict]) -> list[Line]:
    if not items:
        raise Unprocessable("empty_basket", "Your basket is empty.")
    if len(items) > MAX_LINES:
        raise Unprocessable("basket_too_large", f"A basket can hold up to {MAX_LINES} different products.")
    seen, out = set(), []
    rx_carts = None
    for it in items:
        med_id, packs = int(it.get("medication_id", 0)), int(it.get("packs", 0))
        if med_id in seen:
            raise Unprocessable("duplicate_line", "Each product should appear once in the basket.")
        seen.add(med_id)
        med = db.get(Medication, med_id)
        if med is None:
            raise NotFound("product_not_found", "That product isn't available.")
        kind = kind_of(med, patient.jurisdiction)
        if kind == "blocked":
            raise Unprocessable("schedule_x_online_sale", SCHEDULE_X_NOTE, medicine=med.brand_name)
        if kind == "rx":
            rx_carts = rx_carts if rx_carts is not None else _rx_carts(db, patient.id)
            raise Unprocessable("prescription_required",
                                f"{med.brand_name} is a prescription medicine. Buy it from your prescription "
                                "so a pharmacist can check it." if med.id in rx_carts else
                                f"{med.brand_name} needs a prescription from a registered doctor.",
                                medicine=med.brand_name, rx_cart=rx_carts.get(med.id))
        if not 1 <= packs <= MAX_PACKS:
            raise Unprocessable("bad_quantity", f"Choose between 1 and {MAX_PACKS} packs of {med.brand_name}.")
        out.append(Line(med, packs))
    return out


def _price_at(db: Session, ph: Pharmacy, lines: list[Line]) -> tuple[float | None, list[str]]:
    network = MockPharmacyNetwork(db)
    subtotal, missing = 0.0, []
    for ln in lines:
        info = network.stock(ph, ln.med.id)
        if not info.carried or info.unit_price is None or (info.units_in_stock or 0) < ln.units:
            missing.append(ln.med.brand_name)
        else:
            subtotal += info.unit_price * ln.units
    return (None if missing else round(subtotal, 2)), missing


def _options(ph: Pharmacy, km: float) -> list[dict]:
    from ..adapters.delivery import SandboxDeliveryProvider
    eta = SandboxDeliveryProvider()
    return [{"code": c, "label": OPTION_INFO[c]["label"],
             "fee": round(ph.delivery_fee * OPTION_INFO[c]["fee_multiplier"], 2),
             "eta_minutes": eta.eta_minutes(c, km, ph.prep_minutes)}
            for c in SHOP_OPTIONS if c in (ph.delivery_options or [])]


def quote(db: Session, user: User, items: list[dict]) -> dict:
    patient = _patient(db, user)
    lines = _lines(db, patient, items)
    tax_rate = policy_for(patient.jurisdiction).tax_rate
    offers, unavailable = [], []
    for ph, km in _nearby_pharmacies(db, patient):
        subtotal, missing = _price_at(db, ph, lines)
        opts = _options(ph, km)
        if subtotal is None or not opts:
            unavailable.append({"pharmacy": ph.name, "missing": missing or ["delivery"]})
            continue
        offers.append({"pharmacy_id": ph.id, "name": ph.name, "address": ph.address, "distance_km": km,
                       "rating": ph.rating, "subtotal": subtotal, "tax": round(subtotal * tax_rate, 2),
                       "delivery_options": opts})
    offers.sort(key=lambda o: (o["delivery_options"][0]["eta_minutes"], o["subtotal"]))
    return {
        "lines": [{"medication_id": ln.med.id, "name": ln.med.brand_name, "pack_label": pack_label(ln.med),
                   "packs": ln.packs, "units": ln.units} for ln in lines],
        "offers": offers,
        "unavailable": unavailable,
        "note": None if offers else "No pharmacy near you has everything in stock right now. "
                                    "Try removing an item or fewer packs.",
    }


def _priced(db: Session, user: User, items: list[dict], pharmacy_id: int, delivery_option: str):
    patient = _patient(db, user)
    lines = _lines(db, patient, items)
    match = next(((ph, km) for ph, km in _nearby_pharmacies(db, patient) if ph.id == pharmacy_id), None)
    if match is None:
        raise Unprocessable("pharmacy_not_eligible", "This pharmacy can't deliver to you right now.")
    ph, km = match
    opt = next((o for o in _options(ph, km) if o["code"] == delivery_option), None)
    if opt is None:
        raise Unprocessable("delivery_option_unavailable", "That delivery option isn't available from this pharmacy.")
    subtotal, missing = _price_at(db, ph, lines)
    if subtotal is None:
        raise Conflict("out_of_stock", f"Out of stock now: {', '.join(missing)}.", missing=missing)
    tax = round(subtotal * policy_for(patient.jurisdiction).tax_rate, 2)
    total = round(subtotal + tax + opt["fee"], 2)
    return patient, lines, ph, opt, subtotal, tax, total


def payment_intent(db: Session, user: User, items: list[dict], pharmacy_id: int, delivery_option: str) -> dict:
    patient, _, _, _, _, _, total = _priced(db, user, items, pharmacy_id, delivery_option)
    gw = order_svc.get_gateway()
    if not isinstance(gw, RazorpayGateway):
        return {"gateway": "sandbox", "amount": total, "currency": "INR"}
    try:
        rzp = gw.create_order(total, receipt=f"shop-{patient.id}", notes={"kind": "shop"})
    except RazorpayError as e:
        raise PaymentDeclined("gateway_unavailable", str(e))
    audit.record(db, user, "payment.intent_created", "shop", patient.id, provider_order=rzp.get("id"), amount=total)
    db.commit()
    return {"gateway": "razorpay", "key_id": gw.key_id, "test_mode": gw.test_mode, "order_id": rzp["id"],
            "amount": total, "amount_paise": rzp["amount"], "currency": "INR", "prefill": {"name": patient.name}}


# ------------------------------------------------------------------ checkout
def checkout(db: Session, user: User, *, items: list[dict], pharmacy_id: int, delivery_option: str,
             payment_method: str, payment_token: str, idempotency_key: str,
             expected_total: float | None = None) -> PharmacyOrder:
    from ..adapters.payments import SUPPORTED_METHODS
    existing = db.scalars(select(PharmacyOrder).where(PharmacyOrder.idempotency_key == idempotency_key)).first()
    if existing is not None:
        if existing.patient_id != user.patient_id:
            raise Conflict("idempotency_conflict", "Duplicate request key.")
        return existing
    if payment_method not in SUPPORTED_METHODS:
        raise Unprocessable("bad_payment_method", "Choose a supported payment method.")
    patient, lines, ph, opt, subtotal, tax, total = _priced(db, user, items, pharmacy_id, delivery_option)
    if expected_total is not None and abs(expected_total - total) > 0.009:
        raise Conflict("price_changed", "The total changed. Please review the updated price.", total=total)

    network = MockPharmacyNetwork(db)
    for ln in lines:
        if not network.reserve(ph, ln.med.id, ln.units):
            db.rollback()
            raise Conflict("out_of_stock", f"{ln.med.brand_name} just went out of stock. Please review your basket.")

    gw = order_svc.get_gateway()
    auth = gw.authorize(payment_method, total, payment_token)
    if not auth.ok:
        db.rollback()
        audit.record(db, user, "payment.authorization_failed", "shop", patient.id, method=payment_method, amount=total)
        db.commit()
        raise PaymentDeclined("payment_declined", auth.message)
    if db.scalars(select(Payment.id).where(Payment.provider_ref == auth.ref)).first():
        db.rollback()
        raise PaymentDeclined("payment_reused", "This payment was already used for another order.")

    order = PharmacyOrder(
        order_no=new_ref("ORD"), idempotency_key=idempotency_key, source="shop", cart_id=None, prescription_id=None,
        patient_id=patient.id, pharmacy_id=ph.id, fulfillment="delivery", delivery_option=delivery_option,
        subtotal=subtotal, delivery_fee=opt["fee"], tax=tax, discount=0.0, total=total,
    )
    db.add(order)
    db.flush()
    for ln in lines:
        unit_price = network.stock(ph, ln.med.id).unit_price
        db.add(OrderItem(order_id=order.id, cart_item_id=None, prescription_item_id=None, medication_id=ln.med.id,
                         prescribed_quantity=ln.units, requested_quantity=ln.units, approved_quantity=ln.units,
                         unit_price=unit_price))
    # No prescription to review: the pharmacy accepts in-stock OTC orders straight away and payment is captured.
    gw.capture(auth.ref, total)
    db.add(Payment(order_id=order.id, method=payment_method, provider_ref=auth.ref, amount_authorized=total,
                   amount_captured=total, status=PaymentStatus.captured))
    order.status = OrderStatus.order_accepted
    db.add(TrackingEvent(order_id=order.id, status=OrderStatus.order_accepted.value,
                         note=f"{ph.name.replace(' (Demo)', '')} accepted your order. Payment received."))
    audit.record(db, user, "order.placed", "order", order.id, source="shop", pharmacy_id=ph.id, total=total,
                 payment="captured", items={ln.med.brand_name: ln.units for ln in lines})
    notify(db, users_for_pharmacy(db, ph.id), "New shop order",
           f"Order {order.order_no}: {len(lines)} over-the-counter item(s) to pack for rider delivery.",
           link=f"order:{order.id}")
    db.commit()
    db.refresh(order)
    return order


def list_orders(db: Session, user: User) -> list[PharmacyOrder]:
    return list(db.scalars(select(PharmacyOrder).where(PharmacyOrder.patient_id == user.patient_id,
                                                       PharmacyOrder.source == "shop")
                           .order_by(PharmacyOrder.id.desc())))


# ------------------------------------------------------------------ demo pharmacy automation
def autopack(db: Session) -> None:
    """Stand-in for the pharmacy's own system: start packing shop orders and hand them to riders.

    A pharmacist in Triyana Partner can do the same steps sooner by hand."""
    now = utcnow()
    changed = False
    for o in db.scalars(select(PharmacyOrder).where(
            PharmacyOrder.source == "shop",
            PharmacyOrder.status.in_([OrderStatus.order_accepted, OrderStatus.preparing]))):
        age = now - o.created_at
        if o.status == OrderStatus.order_accepted and age >= timedelta(seconds=ACCEPT_TO_PACKING_S):
            o.status = OrderStatus.preparing
            db.add(TrackingEvent(order_id=o.id, status=o.status.value, note="The pharmacy is packing your order."))
            changed = True
        if o.status == OrderStatus.preparing and age >= timedelta(seconds=PACKED_AFTER_S):
            msg = order_svc.pack_and_dispatch(db, o)
            o.status = OrderStatus.ready_for_pickup
            db.add(TrackingEvent(order_id=o.id, status=o.status.value, note=msg))
            audit.record(db, None, "order.ready", "order", o.id, by="pharmacy-system")
            order_svc._notify_patient(db, o, msg)
            changed = True
    if changed:
        db.commit()
