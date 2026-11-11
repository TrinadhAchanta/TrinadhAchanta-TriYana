"""Yana AI prescription assistant.

Yana helps with the cart, pharmacy discovery, tracking and messaging. It is
deliberately restricted: it can never alter prescriptions, suggest stopping a
medicine, authorise substitutions or change treatment instructions. Every cart
change goes through the same service functions (and rules) as the app UI.

Intent detection here is rule-based so it is deterministic and testable; an
LLM front-end can map free text onto these same intents.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..models import CartItemStatus, Patient, PharmacyOrder, User
from . import carts as cart_svc
from .matching import match_pharmacies
from .orders import STATUS_LABELS
from .prescriptions import list_for_patient

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30,
}

REFUSAL = (
    "I can't change your prescription, dosage or treatment, recommend stopping a medicine, or approve a "
    "substitution. Only your doctor can do that. I can help you message your doctor or pharmacist."
)

BLOCKED_PATTERNS = [
    r"\b(stop|quit|discontinue)\b.*\b(taking|medicine|medication|tablet|treatment)",
    r"\b(change|increase|double|reduce|lower|raise)\b.*\b(dose|dosage|strength|frequency|duration)\b",
    r"\bsubstitut|\bswap\b|\breplace\b.*\b(medicine|with)\b|\bgeneric instead\b",
    r"\b(edit|modify|change|alter)\b.*\bprescription\b",
    r"\bmore (tablets|capsules|pills)\b.*\bthan\b|\b(increase|more)\b.*\bquantity\b",
    r"\bdo i (really )?need\b|\bis it (necessary|safe) to skip\b",
]


def _numbers(text: str) -> list[int]:
    out = [int(n) for n in re.findall(r"\b\d+\b", text)]
    for w, n in NUMBER_WORDS.items():
        for _ in re.finditer(rf"\b{w}\b", text):
            out.append(n)
    # keep order of appearance
    positions = []
    for m in re.finditer(r"\b\d+\b|\b(" + "|".join(NUMBER_WORDS) + r")\b", text):
        tok = m.group(0)
        positions.append(int(tok) if tok.isdigit() else NUMBER_WORDS[tok])
    return positions or out


def _find_item(cart, text: str):
    items = [i for i in cart.items if i.status != CartItemStatus.ordered]
    for ci in items:
        med = ci.prescription_item.medication
        names = {med.brand_name.lower(), med.generic_name.lower(), med.brand_name.lower().split()[0]}
        if any(n and n in text for n in names):
            return ci
    in_cart = [i for i in items if i.status == CartItemStatus.in_cart]
    return in_cart[0] if len(in_cart) == 1 else None


def handle(db: Session, user: User, message: str) -> dict:
    text = message.lower().strip()
    audit.record(db, user, "yana.request", "patient", user.patient_id, chars=len(message))
    db.commit()

    for pat in BLOCKED_PATTERNS:
        if re.search(pat, text):
            return {"intent": "refused", "reply": REFUSAL, "actions": ["contact_doctor", "ask_pharmacist"]}

    cart = cart_svc.latest_cart(db, user.patient_id)
    patient = db.get(Patient, user.patient_id)

    if re.search(r"\b(prescri|my medicines|what did .* doctor)", text) and not re.search(r"\b(remove|only|instead)\b", text):
        rxs = list_for_patient(db, user.patient_id)
        if not rxs:
            return {"intent": "show_prescriptions", "reply": "You don't have any prescriptions yet."}
        rx = rxs[0]
        lines = [f"{i.medication.brand_name} {i.medication.strength}: {i.quantity} {i.medication.unit}, "
                 f"{i.dosage}, {i.frequency} for {i.duration_days} days" for i in rx.items]
        return {"intent": "show_prescriptions",
                "reply": f"Dr. {rx.doctor.name.replace('Dr. ', '')} prescribed ({rx.reference_no}):\n- " + "\n- ".join(lines),
                "prescription_id": rx.id}

    if re.search(r"\bwhen\b.*\b(arrive|deliver|come)|\btrack|\bwhere is my (order|medicine)", text):
        order = db.scalars(select(PharmacyOrder).where(PharmacyOrder.patient_id == user.patient_id)
                           .order_by(PharmacyOrder.id.desc())).first()
        if not order:
            return {"intent": "track_order", "reply": "You don't have any medicine orders yet."}
        eta = order.delivery.eta.strftime("%H:%M UTC") if order.delivery and order.delivery.eta else None
        reply = f"Order {order.order_no} is {STATUS_LABELS[order.status]}."
        if eta and order.status.value not in ("delivered", "cancelled", "rejected"):
            reply += f" Estimated arrival around {eta}."
        return {"intent": "track_order", "reply": reply, "order_id": order.id}

    if cart is None:
        return {"intent": "unknown", "reply": "You don't have a medicine cart yet. It appears after your doctor signs a prescription."}

    if re.search(r"\b(cheapest|lowest price|least expensive)\b", text):
        matches = [m for m in match_pharmacies(db, cart, patient, sort="price") if m.eligible]
        if not matches:
            return {"intent": "cheapest_pharmacy", "reply": "No eligible pharmacy can fulfil your cart right now."}
        m = matches[0]
        return {"intent": "cheapest_pharmacy",
                "reply": f"{m.pharmacy.name} is the lowest total at {m.total:.2f} including delivery and tax "
                         f"({m.distance_km} km away).", "pharmacy_id": m.pharmacy.id}

    if re.search(r"\b(pharmac|chemist|near)", text) and not re.search(r"\b(remove|only)\b", text):
        matches = [m for m in match_pharmacies(db, cart, patient, sort="nearest") if m.eligible]
        if not matches:
            return {"intent": "find_pharmacy", "reply": "No eligible pharmacy serves your address for this cart right now."}
        top = matches[:3]
        return {"intent": "find_pharmacy",
                "reply": "Nearest eligible pharmacies: " + "; ".join(
                    f"{m.pharmacy.name} ({m.distance_km} km, {m.total:.2f})" for m in top),
                "pharmacy_ids": [m.pharmacy.id for m in top]}

    if re.search(r"\b(remove|delete|don'?t want|skip)\b", text):
        ci = _find_item(cart, text)
        if not ci:
            return {"intent": "remove_item", "reply": "Which medicine would you like to remove from your cart?"}
        res = cart_svc.set_status(db, user, ci.id, "remove")
        return {"intent": "remove_item",
                "reply": f"I removed {ci.prescription_item.medication.brand_name} from your shopping cart. "
                         + res["message"], "cart_item_id": ci.id}

    if re.search(r"\b(only|instead|fewer|less|just)\b", text) and _numbers(text):
        ci = _find_item(cart, text)
        if not ci:
            return {"intent": "change_quantity", "reply": "Which medicine do you want to change the quantity for?"}
        nums = _numbers(text)
        requested = nums[0]
        res = cart_svc.request_quantity(db, user, ci.id, requested)
        return {"intent": "change_quantity", "reply": res["explanation"], "result": res}

    return {"intent": "unknown",
            "reply": "I can show your prescription, find pharmacies, change how many tablets you buy, "
                     "remove items from your cart, and track deliveries."}
