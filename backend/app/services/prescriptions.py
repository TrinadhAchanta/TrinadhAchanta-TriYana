"""Home visits and digital prescriptions (create, review, sign, amend)."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import Conflict, Forbidden, NotFound, Unprocessable
from ..models import (
    CartItemStatus,
    CartItem,
    HomeVisit,
    Medication,
    PrescriberSignature,
    Prescription,
    PrescriptionItem,
    QuantityStatus,
    RxStatus,
    SuggestedCart,
    User,
    VisitStatus,
    utcnow,
)
from ..security import canonical_hash, sign_prescription, verify_prescription_signature
from .common import ensure_visit_doctor, get_or_404, new_ref, notify, users_for_patient
from .dispensing_rules import policy_for
from .india import SCHEDULE_X_NOTE, online_blocked

# ------------------------------------------------------------------- visits
VISIT_FLOW = {
    "accept": (VisitStatus.requested, VisitStatus.accepted),
    "start": (VisitStatus.accepted, VisitStatus.in_progress),
    "complete": (VisitStatus.in_progress, VisitStatus.completed),
}


def advance_visit(db: Session, user: User, visit_id: int, action: str) -> HomeVisit:
    visit = get_or_404(db, HomeVisit, visit_id, "Visit")
    ensure_visit_doctor(user, visit)
    if action not in VISIT_FLOW:
        raise Unprocessable("bad_action", "Unknown visit action.")
    frm, to = VISIT_FLOW[action]
    if visit.status != frm:
        raise Conflict("bad_visit_state", f"Visit is '{visit.status.value}', cannot {action}.")
    visit.status = to
    if to == VisitStatus.completed:
        visit.completed_at = utcnow()
    if action == "accept":
        notify(db, users_for_patient(db, visit.patient_id), "Doctor confirmed your visit",
               f"{visit.doctor.name} confirmed your home visit.", f"visit:{visit.id}")
    elif action == "start":
        notify(db, users_for_patient(db, visit.patient_id), "Your doctor has arrived",
               f"{visit.doctor.name} has started your home visit.", f"visit:{visit.id}")
    audit.record(db, user, f"visit.{action}", "home_visit", visit.id)
    db.commit()
    return visit


# ------------------------------------------------------------ prescriptions
EDITABLE_ITEM_FIELDS = (
    "medication_id", "dosage", "frequency", "duration_days", "quantity", "route", "instructions", "refills_allowed",
)


def _validate_items(db: Session, items: list[dict], jurisdiction: str) -> None:
    if not items:
        raise Unprocessable("no_items", "A prescription needs at least one medicine.")
    for it in items:
        med = db.get(Medication, it["medication_id"])
        if med is None:
            raise Unprocessable("unknown_medication", f"Medication {it['medication_id']} is not in the catalogue.")
        if it["quantity"] < 1 or it["duration_days"] < 1:
            raise Unprocessable("bad_quantity", "Quantity and duration must be positive.")
        if it.get("refills_allowed", 0) and med.schedule.value == "controlled":
            raise Unprocessable("refill_not_permitted", f"Refills are not permitted for {med.brand_name}.")


def create_draft(db: Session, doctor_user: User, visit_id: int, diagnosis_note: str, items: list[dict]) -> Prescription:
    visit = get_or_404(db, HomeVisit, visit_id, "Visit")
    ensure_visit_doctor(doctor_user, visit)
    doctor = visit.doctor
    if not doctor.license_verified:
        raise Forbidden("doctor_not_verified", "Only verified doctors can prescribe.")
    if visit.status not in (VisitStatus.in_progress, VisitStatus.completed):
        raise Conflict("visit_not_started", "Start or complete the consultation before prescribing.")
    jurisdiction = visit.patient.jurisdiction
    _validate_items(db, items, jurisdiction)
    rx = Prescription(
        reference_no=new_ref("RX"),
        visit_id=visit.id,
        doctor_id=doctor.id,
        patient_id=visit.patient_id,
        jurisdiction=jurisdiction,
        status=RxStatus.draft,
        consultation_date=visit.completed_at or utcnow(),
        diagnosis_note=diagnosis_note or "",
    )
    db.add(rx)
    db.flush()
    for it in items:
        db.add(PrescriptionItem(prescription_id=rx.id, **{k: it.get(k, "" if k == "instructions" else 0) for k in EDITABLE_ITEM_FIELDS}))
    audit.record(db, doctor_user, "prescription.draft_created", "prescription", rx.id, items=len(items))
    db.commit()
    db.refresh(rx)
    return rx


def update_draft(db: Session, doctor_user: User, rx_id: int, diagnosis_note: str | None, items: list[dict] | None) -> Prescription:
    rx = get_or_404(db, Prescription, rx_id, "Prescription")
    if doctor_user.doctor_id != rx.doctor_id:
        raise NotFound("not_found", "Prescription not found.")
    if rx.status != RxStatus.draft:
        raise Conflict("prescription_locked", "Signed prescriptions cannot be edited. Create an amendment instead.")
    if diagnosis_note is not None:
        rx.diagnosis_note = diagnosis_note
    if items is not None:
        _validate_items(db, items, rx.jurisdiction)
        for old in list(rx.items):
            db.delete(old)
        db.flush()
        for it in items:
            db.add(PrescriptionItem(prescription_id=rx.id, **{k: it.get(k, "" if k == "instructions" else 0) for k in EDITABLE_ITEM_FIELDS}))
    audit.record(db, doctor_user, "prescription.draft_updated", "prescription", rx.id)
    db.commit()
    db.refresh(rx)
    return rx


def content_payload(rx: Prescription) -> dict:
    """Everything the signature covers. Any change to these fields breaks it."""
    return {
        "reference_no": rx.reference_no,
        "doctor_id": rx.doctor_id,
        "patient_id": rx.patient_id,
        "jurisdiction": rx.jurisdiction,
        "consultation_date": rx.consultation_date.isoformat(),
        "valid_until": rx.valid_until.isoformat() if rx.valid_until else None,
        "items": [
            {
                "medication_id": i.medication_id,
                "dosage": i.dosage,
                "frequency": i.frequency,
                "duration_days": i.duration_days,
                "quantity": i.quantity,
                "route": i.route,
                "instructions": i.instructions,
                "refills_allowed": i.refills_allowed,
            }
            for i in rx.items
        ],
    }


def verify_integrity(rx: Prescription) -> bool:
    if rx.signature is None or rx.status not in (RxStatus.signed,):
        return False
    current = canonical_hash(content_payload(rx))
    return current == rx.content_hash == rx.signature.content_hash and verify_prescription_signature(
        rx.doctor.license_no, current, rx.signature.signature
    )


def is_dispensable(rx: Prescription) -> tuple[bool, str]:
    if rx.status != RxStatus.signed or rx.signature is None:
        return False, "Prescription is not signed by the prescriber."
    if not rx.doctor.license_verified:
        return False, "Prescriber licence is not verified."
    if rx.valid_until and utcnow() > rx.valid_until:
        return False, "Prescription has expired."
    if not verify_integrity(rx):
        return False, "Prescription content does not match the prescriber's signature."
    return True, ""


def sign(db: Session, doctor_user: User, rx_id: int, confirm_reviewed: bool) -> Prescription:
    rx = get_or_404(db, Prescription, rx_id, "Prescription")
    if doctor_user.doctor_id != rx.doctor_id:
        raise NotFound("not_found", "Prescription not found.")
    if not confirm_reviewed:
        raise Unprocessable("review_required", "Please confirm you have reviewed the prescription before signing.")
    if rx.status != RxStatus.draft:
        raise Conflict("already_signed", "This prescription has already been signed.")
    if not rx.doctor.license_verified:
        raise Forbidden("doctor_not_verified", "Only verified doctors can sign prescriptions.")
    if not rx.items:
        raise Unprocessable("no_items", "A prescription needs at least one medicine.")
    rx.valid_until = rx.consultation_date + timedelta(days=policy_for(rx.jurisdiction).prescription_validity_days)
    content_hash = canonical_hash(content_payload(rx))
    rx.content_hash = content_hash
    rx.status = RxStatus.signed
    rx.signed_at = utcnow()
    db.add(PrescriberSignature(
        prescription_id=rx.id,
        doctor_id=rx.doctor_id,
        content_hash=content_hash,
        signature=sign_prescription(rx.doctor.license_no, content_hash),
    ))
    db.flush()
    audit.record(db, doctor_user, "prescription.signed", "prescription", rx.id, content_hash=content_hash)
    if rx.supersedes_id:
        old = db.get(Prescription, rx.supersedes_id)
        if old is not None and old.status == RxStatus.signed:
            old.status = RxStatus.superseded
            audit.record(db, doctor_user, "prescription.superseded", "prescription", old.id, by=rx.id)
    cart = build_suggested_cart(db, rx)
    notify(
        db, users_for_patient(db, rx.patient_id),
        "Your prescription is ready",
        "Your prescription is ready. Review your medicines and choose what you would like to order.",
        link=f"cart:{cart.id}",
    )
    db.commit()
    db.refresh(rx)
    return rx


def build_suggested_cart(db: Session, rx: Prescription) -> SuggestedCart:
    """Creates the Suggested Medicine Cart. Nothing is ordered or charged."""
    cart = SuggestedCart(prescription_id=rx.id, patient_id=rx.patient_id)
    db.add(cart)
    db.flush()
    for item in rx.items:
        blocked = online_blocked(item.medication, rx.jurisdiction)
        db.add(CartItem(
            cart_id=cart.id,
            prescription_item_id=item.id,
            requested_quantity=item.quantity,
            quantity_status=QuantityStatus.not_permitted if blocked else QuantityStatus.full,
            quantity_note=SCHEDULE_X_NOTE if blocked else "",
            status=CartItemStatus.removed if blocked else CartItemStatus.in_cart,
        ))
    audit.record(db, None, "cart.suggested_created", "cart", cart.id, prescription_id=rx.id)
    db.flush()
    return cart


def amend(db: Session, doctor_user: User, rx_id: int, reason: str, items: list[dict]) -> Prescription:
    """Only the prescriber can change a signed prescription. Creates a new draft
    version; the original is superseded once the new version is signed."""
    old = get_or_404(db, Prescription, rx_id, "Prescription")
    if doctor_user.doctor_id != old.doctor_id:
        raise NotFound("not_found", "Prescription not found.")
    if old.status != RxStatus.signed:
        raise Conflict("not_signed", "Only signed prescriptions can be amended.")
    if not reason:
        raise Unprocessable("reason_required", "An amendment needs a reason.")
    _validate_items(db, items, old.jurisdiction)
    new = Prescription(
        reference_no=new_ref("RX"),
        visit_id=old.visit_id,
        doctor_id=old.doctor_id,
        patient_id=old.patient_id,
        jurisdiction=old.jurisdiction,
        status=RxStatus.draft,
        consultation_date=old.consultation_date,
        diagnosis_note=old.diagnosis_note,
        supersedes_id=old.id,
    )
    db.add(new)
    db.flush()
    for it in items:
        db.add(PrescriptionItem(prescription_id=new.id, **{k: it.get(k, "" if k == "instructions" else 0) for k in EDITABLE_ITEM_FIELDS}))
    audit.record(db, doctor_user, "prescription.amendment_drafted", "prescription", new.id, supersedes=old.id, reason=reason)
    db.commit()
    db.refresh(new)
    return new


def list_for_patient(db: Session, patient_id: int) -> list[Prescription]:
    return list(db.scalars(
        select(Prescription)
        .where(Prescription.patient_id == patient_id, Prescription.status.in_([RxStatus.signed, RxStatus.superseded]))
        .order_by(Prescription.id.desc())
    ))


def list_for_doctor(db: Session, doctor_id: int) -> list[Prescription]:
    return list(db.scalars(select(Prescription).where(Prescription.doctor_id == doctor_id).order_by(Prescription.id.desc())))
