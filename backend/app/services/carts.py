"""Suggested Medicine Cart: patient choices that never touch the official prescription."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import Conflict, NotFound, Unprocessable
from ..models import (
    CartItem,
    CartItemStatus,
    PartialDispenseRequest,
    PatientMessage,
    Patient,
    PrescriptionClarification,
    QuantityStatus,
    SuggestedCart,
    User,
)
from .common import notify, users_for_doctor
from .dispensing_rules import COURSE_WARNING, achievable_quantities, evaluate_quantity_request, policy_for
from .matching import match_pharmacies

DECLINE_MESSAGE = (
    "You don't have to buy this medicine through Triyana, and it stays on your prescription. "
    "Before changing or stopping any treatment, please check with your doctor or pharmacist."
)


def get_cart_for_patient(db: Session, user: User, cart_id: int) -> SuggestedCart:
    cart = db.get(SuggestedCart, cart_id)
    if cart is None or user.patient_id != cart.patient_id:
        raise NotFound("not_found", "Cart not found.")
    return cart


def get_item(db: Session, user: User, item_id: int) -> CartItem:
    item = db.get(CartItem, item_id)
    if item is None or item.cart.patient_id != user.patient_id:
        raise NotFound("not_found", "Cart item not found.")
    if item.status == CartItemStatus.ordered:
        raise Conflict("already_ordered", "This medicine has already been ordered.")
    return item


def latest_cart(db: Session, patient_id: int) -> SuggestedCart | None:
    return db.scalars(
        select(SuggestedCart).where(SuggestedCart.patient_id == patient_id).order_by(SuggestedCart.id.desc())
    ).first()


def serialize_cart(db: Session, cart: SuggestedCart) -> dict:
    rx = cart.prescription
    policy = policy_for(rx.jurisdiction)
    patient = db.get(Patient, cart.patient_id)
    matches = match_pharmacies(db, cart, patient, sort="price")
    best = next((m for m in matches if m.eligible), None)
    best_prices = {}
    for m in matches:
        for line in m.items:
            if line.unit_price is not None:
                best_prices[line.cart_item_id] = min(best_prices.get(line.cart_item_id, 1e9), line.unit_price)
    items = []
    for ci in cart.items:
        pi = ci.prescription_item
        med = pi.medication
        unit = best_prices.get(ci.id, med.reference_unit_price)
        available_at = sum(1 for m in matches for line in m.items if line.cart_item_id == ci.id and line.stock_status in ("confirmed", "unconfirmed"))
        items.append({
            "id": ci.id,
            "status": ci.status.value,
            "medicine": med.brand_name,
            "generic_name": med.generic_name,
            "strength": med.strength,
            "form": med.form,
            "unit": med.unit,
            "schedule": med.schedule.value,
            "prescribed": {
                "quantity": pi.quantity,
                "dosage": pi.dosage,
                "frequency": pi.frequency,
                "duration_days": pi.duration_days,
                "route": pi.route,
                "instructions": pi.instructions,
                "refills_allowed": pi.refills_allowed,
            },
            "requested_quantity": ci.requested_quantity,
            "quantity_status": ci.quantity_status.value,
            "quantity_note": ci.quantity_note,
            "pack_sizes": med.pack_sizes,
            "allowed_quantities": achievable_quantities(med, pi.quantity),
            "estimated_unit_price": unit,
            "estimated_line_total": round(unit * ci.requested_quantity, 2),
            "pharmacies_with_stock": available_at,
            "cold_chain": med.cold_chain,
            "id_check_required": med.id_check_required,
        })
    in_cart = [i for i in items if i["status"] == "in_cart"]
    est_subtotal = round(sum(i["estimated_line_total"] for i in in_cart), 2)
    return {
        "id": cart.id,
        "prescription": {
            "id": rx.id,
            "reference_no": rx.reference_no,
            "status": rx.status.value,
            "doctor": rx.doctor.name,
            "consultation_date": rx.consultation_date.isoformat(),
            "valid_until": rx.valid_until.isoformat() if rx.valid_until else None,
        },
        "currency": policy.currency,
        "items": items,
        "estimate": {
            "subtotal": est_subtotal,
            "delivery_fee": best.delivery_fee if best else None,
            "tax": round(est_subtotal * policy.tax_rate, 2),
            "total": round(est_subtotal * (1 + policy.tax_rate) + (best.delivery_fee if best else 0), 2),
            "fastest_eta_minutes": min((m.eta_minutes for m in matches if m.eligible and m.eta_minutes), default=None),
            "note": "Estimate only. Final prices and stock are confirmed by the pharmacy.",
        },
        "disclaimer": "Nothing is ordered or charged until you review and authorise payment.",
    }


def set_status(db: Session, user: User, item_id: int, action: str) -> dict:
    item = get_item(db, user, item_id)
    mapping = {
        "add": CartItemStatus.in_cart,
        "remove": CartItemStatus.removed,
        "buy_later": CartItemStatus.buy_later,
    }
    if action not in mapping:
        raise Unprocessable("bad_action", "Unknown cart action.")
    item.status = mapping[action]
    audit.record(db, user, f"cart.item_{action}", "cart_item", item.id,
                 prescription_item_id=item.prescription_item_id)
    db.commit()
    message = DECLINE_MESSAGE if action in ("remove", "buy_later") else "Added to your cart."
    return {"item_id": item.id, "status": item.status.value, "message": message}


def request_quantity(db: Session, user: User, item_id: int, requested: int) -> dict:
    item = get_item(db, user, item_id)
    pi = item.prescription_item
    rx = item.cart.prescription
    decision = evaluate_quantity_request(
        med=pi.medication, prescribed=pi.quantity, requested=requested, jurisdiction=rx.jurisdiction
    )
    db.add(PartialDispenseRequest(
        cart_item_id=item.id,
        prescribed_quantity=pi.quantity,
        requested_quantity=requested,
        status=decision.status,
        rule_code=decision.rule_code,
        explanation=decision.explanation,
        decided_by_user_id=None,
    ))
    if decision.permitted:
        item.requested_quantity = requested
        item.quantity_status = decision.status
        item.quantity_note = decision.explanation
        if item.status != CartItemStatus.in_cart:
            item.status = CartItemStatus.in_cart
        if decision.status == QuantityStatus.pending_prescriber:
            db.add(PrescriptionClarification(
                prescription_id=rx.id,
                raised_by_user_id=user.id,
                reason="partial_quantity_authorization",
                message=f"Patient requests to purchase {requested} of {pi.quantity} {pi.medication.unit} "
                        f"of {pi.medication.brand_name} (cart item {item.id}).",
            ))
            notify(db, users_for_doctor(db, rx.doctor_id), "Quantity authorisation requested",
                   f"A patient asked to buy a smaller quantity of {pi.medication.brand_name}.", link=f"rx:{rx.id}")
    audit.record(db, user, "cart.quantity_requested", "cart_item", item.id,
                 prescribed=pi.quantity, requested=requested, outcome=decision.status.value, rule=decision.rule_code)
    db.commit()
    return {
        "item_id": item.id,
        "prescribed_quantity": pi.quantity,
        "requested_quantity": requested,
        "current_purchase_quantity": item.requested_quantity,
        "status": decision.status.value,
        "rule": decision.rule_code,
        "explanation": decision.explanation,
        "allowed_quantities": decision.allowed_quantities,
        "course_warning": COURSE_WARNING if requested < pi.quantity else "",
        "contact_options": [] if decision.permitted else ["ask_pharmacist", "contact_doctor"],
        "official_prescription_unchanged": True,
    }


def send_message(db: Session, user: User, item_id: int, recipient: str, body: str) -> dict:
    item = db.get(CartItem, item_id)
    if item is None or item.cart.patient_id != user.patient_id:
        raise NotFound("not_found", "Cart item not found.")
    if recipient not in ("pharmacist", "doctor"):
        raise Unprocessable("bad_recipient", "Choose pharmacist or doctor.")
    if not body.strip():
        raise Unprocessable("empty_message", "Please write a message.")
    msg = PatientMessage(patient_id=user.patient_id, prescription_item_id=item.prescription_item_id,
                         recipient=recipient, sender_user_id=user.id, body=body.strip())
    db.add(msg)
    if recipient == "doctor":
        notify(db, users_for_doctor(db, item.cart.prescription.doctor_id), "New patient message",
               "A patient has a question about their prescription.", link=f"rx:{item.cart.prescription_id}")
    audit.record(db, user, f"message.to_{recipient}", "cart_item", item.id)
    db.commit()
    return {"id": msg.id, "sent": True, "recipient": recipient}
