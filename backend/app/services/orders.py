"""Checkout, pharmacist review, clarifications, fulfilment, delivery and refunds."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..adapters.delivery import OPTION_INFO, SandboxDeliveryProvider
from ..adapters.geo import haversine_km
from ..adapters.payments import SUPPORTED_METHODS, SandboxPaymentGateway
from ..adapters.razorpay import RazorpayError, RazorpayGateway, configured as razorpay_configured
from ..adapters.pharmacy import MockPharmacyNetwork
from .india import SCHEDULE_X_NOTE, needs_h1_register, online_blocked, schedule_info
from ..errors import Conflict, Forbidden, NotFound, PaymentDeclined, Unprocessable
from ..models import (
    AirspaceZone,
    CartItem,
    CartItemStatus,
    DeliveryAssignment,
    DeliveryMission,
    DispensingRecord,
    OrderItem,
    OrderStatus,
    Patient,
    Payment,
    PaymentStatus,
    PharmacistApproval,
    Pharmacy,
    PharmacyOrder,
    Prescription,
    PrescriptionClarification,
    PrescriptionItem,
    QuantityStatus,
    Refund,
    Role,
    TrackingEvent,
    User,
)
from . import drones as drone_svc
from .carts import get_cart_for_patient
from . import dispatch
from .common import ensure_order_access, get_or_404, new_ref, notify, users_for_doctor, users_for_patient, users_for_pharmacy
from .dispensing_rules import achievable_quantities, evaluate_quantity_request, policy_for
from .matching import match_pharmacies
from .prescriptions import is_dispensable

_sandbox_gateway = SandboxPaymentGateway()
_razorpay_gateway = RazorpayGateway()


def get_gateway():
    """Razorpay when keys are configured (test or live), otherwise the built-in sandbox."""
    return _razorpay_gateway if razorpay_configured() else _sandbox_gateway
courier = SandboxDeliveryProvider()

STATUS_LABELS = {
    OrderStatus.prescription_received: "Prescription Received",
    OrderStatus.pharmacist_reviewing: "Pharmacist Reviewing",
    OrderStatus.awaiting_clarification: "Awaiting Prescriber Clarification",
    OrderStatus.order_accepted: "Order Accepted",
    OrderStatus.preparing: "Preparing Medicines",
    OrderStatus.ready_for_pickup: "Ready for Pickup",
    OrderStatus.out_for_delivery: "Out for Delivery",
    OrderStatus.delivered: "Delivered",
    OrderStatus.picked_up: "Collected",
    OrderStatus.rejected: "Rejected by Pharmacy",
    OrderStatus.cancelled: "Cancelled",
}

CHECKOUT_QTY_OK = (QuantityStatus.full, QuantityStatus.pending_pharmacist, QuantityStatus.approved)


def _event(db: Session, order: PharmacyOrder, status: OrderStatus, note: str = "") -> None:
    order.status = status
    db.add(TrackingEvent(order_id=order.id, status=status.value, note=note))


def _notify_patient(db: Session, order: PharmacyOrder, body: str) -> None:
    notify(db, users_for_patient(db, order.patient_id), f"Order {order.order_no}: {STATUS_LABELS[order.status]}", body,
           link=f"order:{order.id}")


def dispensed_so_far(db: Session, prescription_item_id: int) -> int:
    return db.scalar(
        select(func.coalesce(func.sum(DispensingRecord.quantity), 0)).where(
            DispensingRecord.prescription_item_id == prescription_item_id
        )
    )


def committed_in_open_orders(db: Session, prescription_item_id: int, exclude_order_id: int | None = None) -> int:
    """Quantity tied up in orders that are live but not yet dispensed."""
    q = (
        select(func.coalesce(func.sum(func.coalesce(OrderItem.approved_quantity, OrderItem.requested_quantity)), 0))
        .join(PharmacyOrder, PharmacyOrder.id == OrderItem.order_id)
        .where(
            OrderItem.prescription_item_id == prescription_item_id,
            PharmacyOrder.status.in_([
                OrderStatus.prescription_received, OrderStatus.pharmacist_reviewing,
                OrderStatus.awaiting_clarification, OrderStatus.order_accepted, OrderStatus.preparing,
            ]),
        )
    )
    if exclude_order_id:
        q = q.where(OrderItem.order_id != exclude_order_id)
    return db.scalar(q)


def max_dispensable(pi: PrescriptionItem) -> int:
    return pi.quantity * (1 + (pi.refills_allowed or 0))


# ---------------------------------------------------------------------- checkout
def checkout(
    db: Session,
    user: User,
    cart_id: int,
    *,
    pharmacy_id: int,
    fulfillment: str,
    delivery_option: str | None,
    scheduled_for: datetime | None,
    payment_method: str,
    payment_token: str,
    idempotency_key: str,
    expected_total: float | None = None,
) -> PharmacyOrder:
    existing = db.scalars(select(PharmacyOrder).where(PharmacyOrder.idempotency_key == idempotency_key)).first()
    if existing is not None:
        if existing.patient_id != user.patient_id:
            raise Conflict("idempotency_conflict", "Duplicate request key.")
        return existing

    cart = get_cart_for_patient(db, user, cart_id)
    rx = cart.prescription
    ok, why = is_dispensable(rx)
    if not ok:
        raise Unprocessable("prescription_not_dispensable", why)
    patient = db.get(Patient, cart.patient_id)
    pharmacy = db.get(Pharmacy, pharmacy_id)
    if pharmacy is None or pharmacy.jurisdiction != rx.jurisdiction or not pharmacy.license_verified:
        raise NotFound("pharmacy_not_found", "Pharmacy not available.")
    if payment_method not in SUPPORTED_METHODS:
        raise Unprocessable("bad_payment_method", "Choose a supported payment method.")

    items = [i for i in cart.items if i.status == CartItemStatus.in_cart]
    if not items:
        raise Unprocessable("empty_cart", "Your cart is empty.")
    for ci in items:
        if online_blocked(ci.prescription_item.medication, rx.jurisdiction):
            raise Unprocessable("schedule_x_online_sale", SCHEDULE_X_NOTE)
        if ci.quantity_status not in CHECKOUT_QTY_OK:
            raise Conflict("quantity_pending", f"{ci.prescription_item.medication.brand_name}: the requested quantity "
                           "is still waiting for authorisation. Wait for a response or buy the prescribed quantity.")
        pi = ci.prescription_item
        if dispensed_so_far(db, pi.id) + committed_in_open_orders(db, pi.id) + ci.requested_quantity > max_dispensable(pi):
            raise Conflict("duplicate_dispensing", f"{pi.medication.brand_name} has already been dispensed or ordered.")

    match = next((m for m in match_pharmacies(db, cart, patient) if m.pharmacy.id == pharmacy.id), None)
    if match is None or not match.eligible:
        raise Unprocessable("pharmacy_not_eligible", "This pharmacy can't fulfil your cart.",
                            reasons=match.reasons if match else [])

    if fulfillment == "delivery":
        codes = match.delivery_options
        if delivery_option not in codes:
            raise Unprocessable("delivery_option_unavailable", "That delivery option isn't available for this order.")
        if delivery_option == "scheduled" and not scheduled_for:
            raise Unprocessable("schedule_required", "Choose a delivery time.")
        delivery_fee = round(pharmacy.delivery_fee * OPTION_INFO[delivery_option]["fee_multiplier"], 2)
    elif fulfillment == "pickup":
        if not pharmacy.pickup_available:
            raise Unprocessable("pickup_unavailable", "This pharmacy doesn't offer pickup.")
        delivery_option, delivery_fee = None, 0.0
    else:
        raise Unprocessable("bad_fulfillment", "Choose delivery or pickup.")

    # Live re-check and reservation: inventory may have changed since the cart was viewed.
    network = MockPharmacyNetwork(db)
    reserved: list[tuple[int, int]] = []
    changed = []
    for ci in items:
        med_id = ci.prescription_item.medication_id
        if network.reserve(pharmacy, med_id, ci.requested_quantity):
            reserved.append((med_id, ci.requested_quantity))
        else:
            info = network.stock(pharmacy, med_id)
            changed.append({"cart_item_id": ci.id, "medicine": ci.prescription_item.medication.brand_name,
                            "requested": ci.requested_quantity, "available": info.units_in_stock or 0})
    if changed:
        for med_id, units in reserved:
            network.release(pharmacy, med_id, units)
        db.rollback()
        audit.record(db, user, "checkout.inventory_changed", "cart", cart.id, items=changed)
        db.commit()
        raise Conflict("inventory_changed", "Stock changed while you were checking out. Please review your cart.",
                       items=changed)

    policy = policy_for(rx.jurisdiction)
    lines = []
    subtotal = 0.0
    for ci in items:
        info = network.stock(pharmacy, ci.prescription_item.medication_id)
        line = round(info.unit_price * ci.requested_quantity, 2)
        subtotal += line
        lines.append((ci, info.unit_price))
    subtotal = round(subtotal, 2)
    tax = round(subtotal * policy.tax_rate, 2)
    total = round(subtotal + tax + delivery_fee, 2)
    if expected_total is not None and abs(expected_total - total) > 0.009:
        for med_id, units in reserved:
            network.release(pharmacy, med_id, units)
        db.rollback()
        raise Conflict("price_changed", "The total changed. Please review the updated price.", total=total)

    auth = get_gateway().authorize(payment_method, total, payment_token)
    if not auth.ok:
        for med_id, units in reserved:
            network.release(pharmacy, med_id, units)
        db.rollback()
        audit.record(db, user, "payment.authorization_failed", "cart", cart.id, method=payment_method, amount=total)
        db.commit()
        raise PaymentDeclined("payment_declined", auth.message)
    if db.scalars(select(Payment.id).where(Payment.provider_ref == auth.ref)).first():
        for med_id, units in reserved:
            network.release(pharmacy, med_id, units)
        db.rollback()
        raise PaymentDeclined("payment_reused", "This payment was already used for another order.")

    order = PharmacyOrder(
        order_no=new_ref("ORD"), idempotency_key=idempotency_key, cart_id=cart.id, prescription_id=rx.id,
        patient_id=cart.patient_id, pharmacy_id=pharmacy.id, fulfillment=fulfillment,
        delivery_option=delivery_option, scheduled_for=scheduled_for,
        subtotal=subtotal, delivery_fee=delivery_fee, tax=tax, discount=0.0, total=total,
    )
    db.add(order)
    db.flush()
    for ci, unit_price in lines:
        pi = ci.prescription_item
        db.add(OrderItem(order_id=order.id, cart_item_id=ci.id, prescription_item_id=pi.id,
                         medication_id=pi.medication_id, prescribed_quantity=pi.quantity,
                         requested_quantity=ci.requested_quantity, unit_price=unit_price))
        ci.status = CartItemStatus.ordered
    db.add(Payment(order_id=order.id, method=payment_method, provider_ref=auth.ref,
                   amount_authorized=total, status=PaymentStatus.authorized))
    _event(db, order, OrderStatus.prescription_received, "Payment authorised (not yet charged).")
    audit.record(db, user, "order.placed", "order", order.id, pharmacy_id=pharmacy.id, total=total,
                 payment="authorized")
    notify(db, users_for_pharmacy(db, pharmacy.id), "New prescription order",
           f"Order {order.order_no} needs pharmacist review.", link=f"order:{order.id}")
    db.commit()
    db.refresh(order)
    return order


# ------------------------------------------------------------- pharmacist review
def _pharmacist_order(db: Session, user: User, order_id: int) -> PharmacyOrder:
    order = get_or_404(db, PharmacyOrder, order_id, "Order")
    if user.role != Role.pharmacist or user.pharmacy_id != order.pharmacy_id:
        raise NotFound("not_found", "Order not found.")
    return order


def start_review(db: Session, user: User, order_id: int) -> PharmacyOrder:
    order = _pharmacist_order(db, user, order_id)
    if order.status != OrderStatus.prescription_received:
        raise Conflict("bad_state", "Order is not awaiting review.")
    _event(db, order, OrderStatus.pharmacist_reviewing, "A pharmacist is reviewing your prescription.")
    audit.record(db, user, "order.review_started", "order", order.id)
    _notify_patient(db, order, "A licensed pharmacist is reviewing your prescription.")
    db.commit()
    return order


def _release_and_void(db: Session, order: PharmacyOrder, reason: str) -> None:
    network = MockPharmacyNetwork(db)
    for it in order.items:
        network.release(order.pharmacy, it.medication_id, it.requested_quantity)
    pay = order.payment
    if pay.status == PaymentStatus.authorized:
        get_gateway().void(pay.provider_ref)
        pay.status = PaymentStatus.voided
    elif pay.status == PaymentStatus.captured:
        refund_amount = round(pay.amount_captured - pay.amount_refunded, 2)
        res = get_gateway().refund(pay.provider_ref, refund_amount)
        db.add(Refund(payment_id=pay.id, amount=refund_amount, reason=reason, provider_ref=res.ref))
        pay.amount_refunded = round(pay.amount_refunded + refund_amount, 2)
        pay.status = PaymentStatus.refunded
    for it in order.items:
        if it.cart_item_id is None:  # shop orders have no prescription cart
            continue
        ci = db.get(CartItem, it.cart_item_id)
        ci.status = CartItemStatus.in_cart  # patient may choose another pharmacy


def review(db: Session, user: User, order_id: int, decision: str, notes: str,
           adjustments: dict[int, int] | None = None, h1_register_confirmed: bool = False) -> PharmacyOrder:
    """Pharmacist approves, adjusts (downwards, within what the patient authorised) or rejects."""
    order = _pharmacist_order(db, user, order_id)
    if order.status not in (OrderStatus.pharmacist_reviewing, OrderStatus.prescription_received):
        raise Conflict("bad_state", "Order is not under review.")
    rx = db.get(Prescription, order.prescription_id)

    if decision == "reject":
        if not notes:
            raise Unprocessable("reason_required", "Give the patient a reason for rejection.")
        _release_and_void(db, order, f"Rejected by pharmacist: {notes}")
        db.add(PharmacistApproval(order_id=order.id, pharmacist_user_id=user.id, decision="reject", notes=notes))
        _event(db, order, OrderStatus.rejected, notes)
        audit.record(db, user, "order.rejected", "order", order.id, notes=notes)
        _notify_patient(db, order, f"The pharmacist could not dispense this order: {notes} "
                                   "Your payment hold has been released.")
        db.commit()
        return order

    ok, why = is_dispensable(rx)
    if not ok:
        raise Unprocessable("prescription_invalid", f"Cannot approve: {why} Reject the order or request clarification.")

    adjustments = {int(k): int(v) for k, v in (adjustments or {}).items()}
    if decision not in ("approve", "adjust"):
        raise Unprocessable("bad_decision", "Decision must be approve, adjust or reject.")
    if decision == "adjust" and not adjustments:
        raise Unprocessable("adjustments_required", "Provide the adjusted quantities.")
    h1_items = [it for it in order.items if needs_h1_register(it.medication, rx.jurisdiction)
                and adjustments.get(it.id, it.requested_quantity) > 0]
    if h1_items and not h1_register_confirmed:
        raise Unprocessable("h1_register_required",
                            "This order has Schedule H1 medicines. Record them in the Schedule H1 register "
                            "(patient, doctor, medicine, quantity) and confirm before approving.",
                            medicines=[it.medication.brand_name for it in h1_items])

    for it in order.items:
        qty = adjustments.get(it.id, it.requested_quantity)
        if qty < 0 or qty > it.requested_quantity:
            raise Unprocessable("bad_adjustment",
                                "Approved quantity must be between 0 and what the patient authorised.")
        if qty and qty < it.prescribed_quantity:
            qd = evaluate_quantity_request(med=it.medication, prescribed=it.prescribed_quantity, requested=qty,
                                           jurisdiction=rx.jurisdiction, pharmacy=order.pharmacy)
            if not qd.permitted:
                raise Unprocessable("partial_not_permitted", qd.explanation)
            ci = db.get(CartItem, it.cart_item_id)
            if ci.quantity_status == QuantityStatus.pending_prescriber or (
                qd.status == QuantityStatus.pending_prescriber and ci.quantity_status != QuantityStatus.approved
            ):
                raise Unprocessable("prescriber_auth_required", "Prescriber authorisation is required for this quantity.")
        pi = db.get(PrescriptionItem, it.prescription_item_id)
        if dispensed_so_far(db, pi.id) + committed_in_open_orders(db, pi.id, exclude_order_id=order.id) + qty > max_dispensable(pi):
            raise Conflict("duplicate_dispensing", f"{it.medication.brand_name} would exceed the prescribed quantity.")

    network = MockPharmacyNetwork(db)
    subtotal = 0.0
    for it in order.items:
        qty = adjustments.get(it.id, it.requested_quantity)
        if qty < it.requested_quantity:
            network.release(order.pharmacy, it.medication_id, it.requested_quantity - qty)
        it.approved_quantity = qty
        subtotal += qty * it.unit_price
        ci = db.get(CartItem, it.cart_item_id)
        if ci.quantity_status == QuantityStatus.pending_pharmacist:
            ci.quantity_status = QuantityStatus.approved
            ci.quantity_note = "Approved by the dispensing pharmacist."
    if not any(it.approved_quantity for it in order.items):
        raise Unprocessable("nothing_to_dispense", "Reject the order instead of approving zero items.")

    policy = policy_for(rx.jurisdiction)
    order.subtotal = round(subtotal, 2)
    order.tax = round(order.subtotal * policy.tax_rate, 2)
    order.total = round(order.subtotal + order.tax + order.delivery_fee - order.discount, 2)
    pay = order.payment
    capture_amount = min(order.total, pay.amount_authorized)
    get_gateway().capture(pay.provider_ref, capture_amount)
    pay.amount_captured = capture_amount
    pay.status = PaymentStatus.captured

    db.add(PharmacistApproval(order_id=order.id, pharmacist_user_id=user.id, decision=decision, notes=notes))
    _event(db, order, OrderStatus.order_accepted, notes or "Your pharmacist approved the order.")
    audit.record(db, user, f"order.{decision}d", "order", order.id,
                 approved={it.id: it.approved_quantity for it in order.items}, captured=capture_amount,
                 h1_register_entries=[{"medicine": it.medication.brand_name, "quantity": it.approved_quantity}
                                      for it in h1_items])
    msg = "Your order was accepted and payment captured."
    if decision == "adjust":
        msg = (f"The pharmacist adjusted your order ({notes}). You were charged {capture_amount:.2f} instead of "
               f"{pay.amount_authorized:.2f}; the rest of the hold is released.")
    _notify_patient(db, order, msg)
    db.commit()
    return order


# --------------------------------------------------------------- clarifications
CLARIFICATION_REASONS = {
    "quantity_not_dispensable": "Requested quantity cannot be dispensed",
    "medicine_unavailable": "Medicine is unavailable",
    "incomplete_prescription": "Prescription information is incomplete",
    "substitution_requires_authorization": "A substitution requires authorisation",
    "refill_authorization": "Refill authorisation is needed",
}


def request_clarification(db: Session, user: User, order_id: int, reason: str, message: str) -> PrescriptionClarification:
    order = _pharmacist_order(db, user, order_id)
    if reason not in CLARIFICATION_REASONS:
        raise Unprocessable("bad_reason", "Unknown clarification reason.")
    if order.status not in (OrderStatus.prescription_received, OrderStatus.pharmacist_reviewing):
        raise Conflict("bad_state", "Clarification can only be requested during review.")
    c = PrescriptionClarification(prescription_id=order.prescription_id, order_id=order.id,
                                  raised_by_user_id=user.id, reason=reason, message=message)
    db.add(c)
    _event(db, order, OrderStatus.awaiting_clarification, CLARIFICATION_REASONS[reason])
    rx = db.get(Prescription, order.prescription_id)
    notify(db, users_for_doctor(db, rx.doctor_id), "Pharmacist clarification request",
           f"{CLARIFICATION_REASONS[reason]} — {rx.reference_no}", link=f"rx:{rx.id}")
    _notify_patient(db, order, "The pharmacist has asked your doctor a question about your prescription.")
    audit.record(db, user, "clarification.requested", "order", order.id, reason=reason)
    db.commit()
    db.refresh(c)
    return c


def respond_clarification(db: Session, user: User, clarification_id: int, response: str, authorize: bool | None) -> PrescriptionClarification:
    """Prescriber answers. Content changes to the prescription happen only through
    a signed amendment (see prescriptions.amend)."""
    c = get_or_404(db, PrescriptionClarification, clarification_id, "Clarification")
    rx = db.get(Prescription, c.prescription_id)
    if user.role != Role.doctor or user.doctor_id != rx.doctor_id:
        raise NotFound("not_found", "Clarification not found.")
    if c.status != "open":
        raise Conflict("already_resolved", "This clarification is already resolved.")
    c.response = response
    c.responded_by_user_id = user.id
    c.status = "resolved"
    if c.reason == "partial_quantity_authorization":
        # Find the cart item awaiting the prescriber.
        for ci in db.scalars(select(CartItem).join(CartItem.cart).where(
                CartItem.quantity_status == QuantityStatus.pending_prescriber)):
            if ci.cart.prescription_id == rx.id:
                if authorize:
                    # Prescriber authorised; the dispensing pharmacist still makes the final call.
                    ci.quantity_status = QuantityStatus.approved
                    ci.quantity_note = "Your doctor authorised the smaller quantity. The pharmacist will confirm."
                else:
                    # Revert to the prescribed quantity; patient can still remove the item.
                    ci.requested_quantity = ci.prescription_item.quantity
                    ci.quantity_status = QuantityStatus.full
                    ci.quantity_note = f"Your doctor did not authorise a smaller quantity: {response}"
                notify(db, users_for_patient(db, rx.patient_id), "Your doctor responded", ci.quantity_note,
                       link=f"cart:{ci.cart_id}")
    if c.order_id:
        order = db.get(PharmacyOrder, c.order_id)
        if order.status == OrderStatus.awaiting_clarification:
            _event(db, order, OrderStatus.pharmacist_reviewing, "Prescriber responded; review resumed.")
        notify(db, users_for_pharmacy(db, order.pharmacy_id), "Prescriber responded",
               f"Clarification for {order.order_no} answered.", link=f"order:{order.id}")
    audit.record(db, user, "clarification.responded", "clarification", c.id, authorize=authorize)
    db.commit()
    return c


# ------------------------------------------------------------------ fulfilment
def _dispense(db: Session, user: User, order: PharmacyOrder) -> None:
    for it in order.items:
        if not it.approved_quantity or it.prescription_item_id is None:  # OTC shop items: no dispensing record
            continue
        pi = db.get(PrescriptionItem, it.prescription_item_id)
        exists = db.scalars(select(DispensingRecord).where(DispensingRecord.order_item_id == it.id)).first()
        if exists:
            raise Conflict("duplicate_dispensing", "This order item was already dispensed.")
        if dispensed_so_far(db, pi.id) + it.approved_quantity > max_dispensable(pi):
            raise Conflict("duplicate_dispensing", f"{it.medication.brand_name} would exceed the prescribed quantity.")
        db.add(DispensingRecord(order_item_id=it.id, prescription_item_id=pi.id, pharmacy_id=order.pharmacy_id,
                                pharmacist_user_id=user.id, quantity=it.approved_quantity))
        db.flush()


def pack_and_dispatch(db: Session, order: PharmacyOrder) -> str:
    """Order is packed: book the drone or offer the delivery to the nearest online rider."""
    if order.fulfillment == "delivery":
        patient = db.get(Patient, order.patient_id)
        dist = haversine_km(patient.lat, patient.lng, order.pharmacy.lat, order.pharmacy.lng)
        meds = [it.medication for it in order.items if it.approved_quantity]
        msg = "Your order is packed and waiting for the courier."
        mission = _book_drone(db, order, patient) if order.delivery_option == "drone" else None
        if mission is not None and mission.mode == "drone":
            provider, courier_name, ref = mission.provider, f"Drone {mission.vehicle['uin']}", mission.ref
            eta, code = mission.eta, mission.handover_code
            msg = "Your order is packed and loaded for drone delivery."
        else:
            if mission is not None:  # drone not possible on this route today: road fallback
                msg = _fallback_to_road(db, order, mission.fallback_reason)
                db.delete(mission)
            booking = courier.book(order.delivery_option, dist, 0, order.scheduled_for)
            provider, courier_name, ref = "triyana-dispatch", None, booking.tracking_ref
            eta, code = booking.eta, booking.handover_code
        db.add(DeliveryAssignment(
            order_id=order.id, provider=provider, option=order.delivery_option,
            courier_name=courier_name, tracking_ref=ref, eta=eta,
            handover_code=code,
            cold_chain=any(m.cold_chain for m in meds),
            id_check_required=any(m.id_check_required for m in meds),
            signature_required=True,
        ))
        if not (mission is not None and mission.mode == "drone"):
            db.flush()
            db.refresh(order)
            dispatch.offer_delivery(db, order)  # nearest online courier gets it first
            msg = ("Your order is packed. We're finding the nearest courier."
                   if msg == "Your order is packed and waiting for the courier." else f"{msg} We're finding the nearest courier.")
    else:
        msg = "Your order is ready to collect. Bring photo ID."
    return msg


def advance(db: Session, user: User, order_id: int, action: str) -> PharmacyOrder:
    order = get_or_404(db, PharmacyOrder, order_id, "Order")
    ensure_order_access(user, order)
    if user.role not in (Role.pharmacist, Role.courier):
        raise Forbidden("forbidden_role", "Only the pharmacy or its courier can update fulfilment.")
    transitions = {
        "prepare": (Role.pharmacist, OrderStatus.order_accepted, OrderStatus.preparing,
                    "Your medicines are being prepared."),
        "ready": (Role.pharmacist, OrderStatus.preparing, OrderStatus.ready_for_pickup,
                  "Your order is packed and ready."),
        "dispatch": (Role.courier, OrderStatus.ready_for_pickup, OrderStatus.out_for_delivery,
                     "Your medicines are on the way."),
    }
    if action not in transitions:
        raise Unprocessable("bad_action", "Unknown fulfilment action.")
    role, frm, to, msg = transitions[action]
    if user.role != role:
        raise Forbidden("forbidden_role", "Your role cannot perform this step.")
    if order.status != frm:
        raise Conflict("bad_state", f"Order is '{STATUS_LABELS[order.status]}'.")
    if action == "ready":
        _dispense(db, user, order)
        msg = pack_and_dispatch(db, order)
    if action == "dispatch" and order.fulfillment != "delivery":
        raise Conflict("not_delivery", "Pickup orders are not dispatched.")
    if action == "dispatch":
        mission = order_mission(db, order.id)
        if mission is not None:
            drone_svc.launch(mission)
            msg = "Your medicines are in the air. Keep your handover code ready."
        else:
            d = order.delivery
            if d.courier_user_id not in (None, user.id):
                raise Conflict("not_your_delivery", "Another courier is collecting this order.")
            d.courier_user_id, d.courier_name = user.id, user.name.split(" (")[0]
            dispatch.close_offers_for_order(db, order, user)
            p = db.get(Patient, order.patient_id)
            dispatch.start_trip(db, user, order_id=order.id, leg="to_patient", dest=(p.lat, p.lng),
                                dest_label=f"{p.name.split()[0]}'s home")
            msg = f"{d.courier_name} has your medicines and is on the way."
    _event(db, order, to, msg)
    audit.record(db, user, f"order.{action}", "order", order.id)
    _notify_patient(db, order, msg)
    db.commit()
    return order


def complete_handover(db: Session, user: User, order_id: int, code: str, recipient_name: str,
                      id_verified: bool) -> PharmacyOrder:
    """Courier (delivery) or pharmacist (pickup) records proof of delivery."""
    order = get_or_404(db, PharmacyOrder, order_id, "Order")
    ensure_order_access(user, order)
    if order.fulfillment == "delivery":
        if user.role != Role.courier or order.status != OrderStatus.out_for_delivery:
            raise Conflict("bad_state", "Order is not out for delivery.")
        d = order.delivery
        if code != d.handover_code:
            audit.record(db, user, "delivery.bad_code", "order", order.id)
            db.commit()
            raise Unprocessable("bad_handover_code", "Handover code doesn't match.")
        if d.id_check_required and not id_verified:
            raise Unprocessable("id_check_required", "This delivery requires an identity check.")
        if d.courier_user_id not in (None, user.id):
            raise Conflict("not_your_delivery", "This delivery belongs to another courier.")
        d.proof_of_delivery = {"recipient": recipient_name, "id_verified": id_verified, "code_matched": True}
        mission = order_mission(db, order.id)
        if mission is not None:
            drone_svc.confirm(mission, recipient_name or "Patient", temperature_ok=True)
        dispatch.end_trips_for(db, order_id=order.id)
        if mission is None:
            from .earnings import record_delivery
            record_delivery(db, order, user)
        _event(db, order, OrderStatus.delivered, f"Delivered to {recipient_name}.")
    else:
        if user.role != Role.pharmacist or order.status != OrderStatus.ready_for_pickup:
            raise Conflict("bad_state", "Order is not ready for pickup.")
        if not id_verified:
            raise Unprocessable("id_check_required", "Verify the patient's identity at pickup.")
        _event(db, order, OrderStatus.picked_up, f"Collected by {recipient_name}.")
    audit.record(db, user, "order.handed_over", "order", order.id, recipient=recipient_name, id_verified=id_verified)
    _notify_patient(db, order, "Your medicines have been delivered. Follow your doctor's instructions.")
    notify(db, users_for_pharmacy(db, order.pharmacy_id), "Delivery confirmed", f"{order.order_no} handed over.",
           link=f"order:{order.id}")
    db.commit()
    return order


def cancel(db: Session, user: User, order_id: int, reason: str) -> PharmacyOrder:
    order = get_or_404(db, PharmacyOrder, order_id, "Order")
    ensure_order_access(user, order)
    patient_cancellable = (OrderStatus.prescription_received, OrderStatus.pharmacist_reviewing,
                           OrderStatus.awaiting_clarification, OrderStatus.order_accepted)
    pharmacy_cancellable = patient_cancellable + (OrderStatus.preparing,)
    allowed = patient_cancellable if user.role == Role.patient else pharmacy_cancellable
    if user.role == Role.courier or order.status not in allowed:
        raise Conflict("not_cancellable", "This order can no longer be cancelled in the app. Contact the pharmacy.")
    _release_and_void(db, order, reason or "Cancelled")
    _event(db, order, OrderStatus.cancelled, reason or "Cancelled")
    audit.record(db, user, "order.cancelled", "order", order.id, reason=reason, payment=order.payment.status.value)
    _notify_patient(db, order, "Your order was cancelled. Any payment has been released or refunded.")
    db.commit()
    return order


# ------------------------------------------------------------------ drones
def order_mission(db: Session, order_id: int) -> DeliveryMission | None:
    return db.scalars(select(DeliveryMission).where(DeliveryMission.order_id == order_id)).first()


def _book_drone(db: Session, order: PharmacyOrder, patient: Patient) -> DeliveryMission:
    """Re-check the route at packing time (weather, airspace) and book the drone, or a road fallback."""
    payload = drone_svc.order_payload([(it.medication, it.approved_quantity) for it in order.items if it.approved_quantity])
    home = drone_svc.Place("Patient's home", patient.lat, patient.lng, "patient_home")
    return drone_svc.create_mission(db, drone_svc.pharmacy_place(order.pharmacy), home, payload,
                                    patient.jurisdiction, order_id=order.id)


def _fallback_to_road(db: Session, order: PharmacyOrder, reason: str | None) -> str:
    """Switch a drone order to priority road delivery and refund the fee difference."""
    new_fee = round(order.pharmacy.delivery_fee * OPTION_INFO["priority"]["fee_multiplier"], 2)
    diff = round(order.delivery_fee - new_fee, 2)
    order.delivery_option = "priority"
    if diff > 0:
        order.delivery_fee = new_fee
        order.total = round(order.total - diff, 2)
        pay = order.payment
        if pay.status in (PaymentStatus.captured, PaymentStatus.partially_refunded):
            res = get_gateway().refund(pay.provider_ref, diff)
            db.add(Refund(payment_id=pay.id, amount=diff, reason="Drone unavailable: switched to road",
                          provider_ref=res.ref))
            pay.amount_refunded = round(pay.amount_refunded + diff, 2)
            pay.status = PaymentStatus.partially_refunded
    audit.record(db, None, "order.drone_fallback", "order", order.id, reason=reason, refunded=max(diff, 0))
    return (f"Drone delivery isn't possible right now ({reason}) so a priority road courier will bring it. "
            + (f"The {diff:.2f} fee difference has been refunded." if diff > 0 else ""))


# --------------------------------------------------------------- serialization
def serialize_order(db: Session, order: PharmacyOrder, viewer: User) -> dict:
    juris = (db.get(Prescription, order.prescription_id).jurisdiction if order.prescription_id
             else db.get(Patient, order.patient_id).jurisdiction)
    d = order.delivery
    pay = order.payment
    data = {
        "id": order.id,
        "order_no": order.order_no,
        "prescription_id": order.prescription_id,
        "source": order.source or "prescription",
        "status": order.status.value,
        "status_label": STATUS_LABELS[order.status],
        "pharmacy": {"id": order.pharmacy.id, "name": order.pharmacy.name, "address": order.pharmacy.address},
        "fulfillment": order.fulfillment,
        "delivery_option": order.delivery_option,
        "items": [
            {
                "id": it.id,
                "medicine": f"{it.medication.brand_name} {it.medication.strength}",
                "prescribed_quantity": it.prescribed_quantity,
                "requested_quantity": it.requested_quantity,
                "approved_quantity": it.approved_quantity,
                "unit": it.medication.unit,
                "unit_price": it.unit_price,
                "india_schedule": schedule_info(it.medication, juris),
            }
            for it in order.items
        ],
        "price": {"subtotal": order.subtotal, "delivery_fee": order.delivery_fee, "tax": order.tax,
                  "discount": order.discount, "total": order.total},
        "payment": {"method": pay.method, "status": pay.status.value, "authorized": pay.amount_authorized,
                    "captured": pay.amount_captured, "refunded": pay.amount_refunded} if pay else None,
        "timeline": [{"status": e.status, "label": STATUS_LABELS.get(OrderStatus(e.status), e.status),
                      "note": e.note, "at": e.created_at.isoformat()} for e in order.events],
        "delivery": None,
        "created_at": order.created_at.isoformat(),
    }
    if d:
        data["delivery"] = {
            "provider": d.provider, "option": d.option, "courier": d.courier_name, "tracking_ref": d.tracking_ref,
            "eta": d.eta.isoformat() if d.eta else None, "cold_chain": d.cold_chain,
            "id_check_required": d.id_check_required, "signature_required": d.signature_required,
            "proof_of_delivery": d.proof_of_delivery,
        }
        if viewer.role == Role.patient:
            data["delivery"]["handover_code"] = d.handover_code  # patient shares it with the courier
    mission = order_mission(db, order.id)
    data["mission"] = drone_svc.serialize_mission(mission, list(db.scalars(select(AirspaceZone)))) if mission else None
    return data


# ------------------------------------------------------------- payment intent
def quote(db: Session, user: User, cart_id: int, *, pharmacy_id: int, fulfillment: str,
          delivery_option: str | None) -> dict:
    """Price the cart at a pharmacy without reserving stock (used to open the payment window)."""
    cart = get_cart_for_patient(db, user, cart_id)
    rx = cart.prescription
    patient = db.get(Patient, cart.patient_id)
    pharmacy = db.get(Pharmacy, pharmacy_id)
    if pharmacy is None or pharmacy.jurisdiction != rx.jurisdiction or not pharmacy.license_verified:
        raise NotFound("pharmacy_not_found", "Pharmacy not available.")
    items = [i for i in cart.items if i.status == CartItemStatus.in_cart]
    if not items:
        raise Unprocessable("empty_cart", "Your cart is empty.")
    match = next((m for m in match_pharmacies(db, cart, patient) if m.pharmacy.id == pharmacy.id), None)
    if match is None or not match.eligible:
        raise Unprocessable("pharmacy_not_eligible", "This pharmacy can't fulfil your cart.")
    if fulfillment == "delivery":
        if delivery_option not in match.delivery_options:
            raise Unprocessable("delivery_option_unavailable", "That delivery option isn't available for this order.")
        delivery_fee = round(pharmacy.delivery_fee * OPTION_INFO[delivery_option]["fee_multiplier"], 2)
    else:
        delivery_fee = 0.0
    network = MockPharmacyNetwork(db)
    subtotal = round(sum(network.stock(pharmacy, ci.prescription_item.medication_id).unit_price * ci.requested_quantity
                         for ci in items), 2)
    tax = round(subtotal * policy_for(rx.jurisdiction).tax_rate, 2)
    return {"cart": cart, "patient": patient, "total": round(subtotal + tax + delivery_fee, 2)}


def payment_intent(db: Session, user: User, cart_id: int, **kw) -> dict:
    q = quote(db, user, cart_id, **kw)
    gw = get_gateway()
    if not isinstance(gw, RazorpayGateway):
        return {"gateway": "sandbox", "amount": q["total"], "currency": "INR"}
    try:
        rzp = gw.create_order(q["total"], receipt=f"cart-{cart_id}", notes={"cart_id": str(cart_id)})
    except RazorpayError as e:
        raise PaymentDeclined("gateway_unavailable", str(e))
    audit.record(db, user, "payment.intent_created", "cart", cart_id, provider_order=rzp.get("id"), amount=q["total"])
    db.commit()
    return {"gateway": "razorpay", "key_id": gw.key_id, "test_mode": gw.test_mode, "order_id": rzp["id"],
            "amount": q["total"], "amount_paise": rzp["amount"], "currency": "INR",
            "prefill": {"name": q["patient"].name}}
