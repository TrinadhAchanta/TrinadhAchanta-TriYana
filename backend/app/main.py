"""Triyana API: Digital Prescription -> Suggested Cart -> Pharmacy -> Delivery."""
from __future__ import annotations

import mimetypes
import os
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import audit
from .adapters.payments import INDIA_METHODS, SUPPORTED_METHODS
from .db import Base, engine, get_db, SessionLocal
from .deps import current_user, require
from .routers.auth import router as auth_router
from .routers.labs import router as labs_router
from .routers.live import router as live_router
from .routers.visit_notes import router as visit_notes_router
from .routers.shop import router as shop_router
from .routers.physio import router as physio_router
from .routers.face import router as face_router
from .routers.perks import router as perks_router
from .routers.care import router as care_router
from .routers.family import router as family_router
from .errors import DomainError, Forbidden, NotFound
from .models import (
    AuditLog,
    DispensingRecord,
    HomeVisit,
    Medication,
    Notification,
    OrderItem,
    OrderStatus,
    Patient,
    PatientMessage,
    Pharmacy,
    PharmacyOrder,
    Prescription,
    PrescriptionClarification,
    Role,
    RxStatus,
    SuggestedCart,
    User,
    utcnow,
)
from .services import carts as cart_svc
from .services import hospitals as hospital_svc
from .services import orders as order_svc
from .services import prescriptions as rx_svc
from .services import privacy as privacy_svc
from .services import visits as visit_svc
from .services import visit_notes as notes_svc
from .services import yana as yana_svc
from .services.common import ensure_order_access, ensure_prescription_access, get_or_404
from .services.dispensing_rules import policy_for
from .services.india import schedule_info
from .services.matching import SORTS, match_pharmacies, match_to_dict

# Windows can map .js to text/plain in its registry; with nosniff the browser would then refuse
# to run the app's scripts and both apps would show a blank or dead page.
for _ext, _type in ((".js", "text/javascript"), (".css", "text/css"), (".svg", "image/svg+xml"),
                    (".webmanifest", "application/manifest+json")):
    mimetypes.add_type(_type, _ext)

app = FastAPI(title="Triyana Home — Prescriptions to Delivery", version="1.0.0")


@app.exception_handler(DomainError)
async def domain_error_handler(_: Request, exc: DomainError):
    return JSONResponse(status_code=exc.status_code,
                        content={"detail": {"code": exc.code, "message": exc.message, **exc.extra}})


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


# ------------------------------------------------------------------- schemas
class RxItemIn(BaseModel):
    medication_id: int
    dosage: str = Field(min_length=1, max_length=80)
    frequency: str = Field(min_length=1, max_length=80)
    duration_days: int = Field(ge=1, le=365)
    quantity: int = Field(ge=1, le=1000)
    route: str = Field(default="oral", max_length=40)
    instructions: str = Field(default="", max_length=500)
    refills_allowed: int = Field(default=0, ge=0, le=12)


class RxCreate(BaseModel):
    visit_id: int
    diagnosis_note: str = ""
    items: list[RxItemIn]


class RxUpdate(BaseModel):
    diagnosis_note: str | None = None
    items: list[RxItemIn] | None = None


class RxSign(BaseModel):
    confirm_reviewed: bool


class RxAmend(BaseModel):
    reason: str
    items: list[RxItemIn]


class QuantityIn(BaseModel):
    requested_quantity: int


class MessageIn(BaseModel):
    recipient: str
    body: str = Field(max_length=1000)


class CheckoutIn(BaseModel):
    pharmacy_id: int
    fulfillment: str
    delivery_option: str | None = None
    scheduled_for: datetime | None = None
    payment_method: str
    payment_token: str = "sandbox-ok"
    idempotency_key: str = Field(min_length=8, max_length=80)
    expected_total: float | None = None


class ReviewIn(BaseModel):
    decision: str
    notes: str = ""
    adjustments: dict[int, int] | None = None
    h1_register_confirmed: bool = False


class ClarifyIn(BaseModel):
    reason: str
    message: str


class ClarifyResponseIn(BaseModel):
    response: str
    authorize: bool | None = None


class HandoverIn(BaseModel):
    code: str = ""
    recipient_name: str
    id_verified: bool = False


class CancelIn(BaseModel):
    reason: str = ""


class YanaIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)


# -------------------------------------------------------------- serializers
def rx_to_dict(rx: Prescription, include_integrity: bool = True) -> dict:
    d = rx.doctor
    out = {
        "id": rx.id,
        "reference_no": rx.reference_no,
        "status": rx.status.value,
        "patient": {"name": rx.patient.name, "patient_ref": rx.patient.patient_ref,
                    "date_of_birth": rx.patient.date_of_birth},
        "doctor": {"name": d.name, "specialty": d.specialty, "license_no": d.license_no,
                   "license_verified": d.license_verified, "medical_council": d.medical_council,
                   "qualification": d.qualification, "registration_year": d.registration_year},
        "jurisdiction": rx.jurisdiction,
        "consultation_date": rx.consultation_date.isoformat(),
        "valid_until": rx.valid_until.isoformat() if rx.valid_until else None,
        "signed_at": rx.signed_at.isoformat() if rx.signed_at else None,
        "supersedes_id": rx.supersedes_id,
        "diagnosis_note": rx.diagnosis_note,
        "items": [
            {
                "id": i.id,
                "medication_id": i.medication_id,
                "medicine": i.medication.brand_name,
                "generic_name": i.medication.generic_name,
                "strength": i.medication.strength,
                "form": i.medication.form,
                "unit": i.medication.unit,
                "india_schedule": schedule_info(i.medication, rx.jurisdiction),
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
    if rx.signature is not None:
        out["signature"] = {"method": rx.signature.method, "signed_at": rx.signature.signed_at.isoformat(),
                            "content_hash": rx.signature.content_hash[:16] + "…"}
    if include_integrity:
        out["integrity_verified"] = rx_svc.verify_integrity(rx) if rx.status == RxStatus.signed else None
    return out


# -------------------------------------------------------------------- meta
@app.get("/api/health")
def health():
    return {"ok": True, "mode": "demo" if os.environ.get("TRIYANA_DEMO", "1") == "1" else "live"}


@app.get("/api/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    unread = db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.read.is_(False))).all()
    return {"id": user.id, "name": user.name, "role": user.role.value, "unread_notifications": len(unread),
            "hospital_id": user.hospital_id, "pharmacy_id": user.pharmacy_id,
            "email": user.email, "demo": user.email is None,
            "verification_status": user.verification_status or "verified"}


@app.get("/api/notifications")
def notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Notification).where(Notification.user_id == user.id).order_by(Notification.id.desc())).all()
    return [{"id": n.id, "title": n.title, "body": n.body, "link": n.link, "read": n.read,
             "at": n.created_at.isoformat()} for n in rows]


@app.post("/api/notifications/{nid}/read")
def read_notification(nid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    n = db.get(Notification, nid)
    if n and n.user_id == user.id:
        n.read = True
        db.commit()
    return {"ok": True}


@app.get("/api/catalog/medications")
def medications(user: User = Depends(require(Role.doctor, Role.pharmacist)), db: Session = Depends(get_db)):
    return [{"id": m.id, "brand_name": m.brand_name, "generic_name": m.generic_name, "strength": m.strength,
             "form": m.form, "unit": m.unit, "schedule": m.schedule.value, "pack_sizes": m.pack_sizes,
             "india_schedule": m.india_schedule}
            for m in db.scalars(select(Medication).order_by(Medication.brand_name))]


@app.get("/api/payment-methods")
def payment_methods():
    return [{"code": k, "label": SUPPORTED_METHODS[k]} for k in INDIA_METHODS]


@app.get("/api/payment-config")
def payment_config():
    gw = order_svc.get_gateway()
    return {"gateway": gw.name, "test_mode": getattr(gw, "test_mode", True),
            "key_id": getattr(gw, "key_id", None)}


class IntentIn(BaseModel):
    pharmacy_id: int
    fulfillment: str
    delivery_option: str | None = None


@app.post("/api/carts/{cart_id}/payment-intent")
def payment_intent(cart_id: int, body: IntentIn, user: User = Depends(require(Role.patient)), db: Session = Depends(get_db)):
    privacy_svc.require_care(db, user)
    return order_svc.payment_intent(db, user, cart_id, pharmacy_id=body.pharmacy_id, fulfillment=body.fulfillment,
                                    delivery_option=body.delivery_option)


# ------------------------------------------------------------------ privacy (DPDP Act 2023)
class ConsentIn(BaseModel):
    purpose: str
    granted: bool
    language: str = "en"


class DataRequestIn(BaseModel):
    kind: Literal["erasure", "correction"]
    details: str = Field(default="", max_length=1000)


@app.get("/api/privacy/notice")
def privacy_notice():
    return {**privacy_svc.NOTICE, "purposes": privacy_svc.PURPOSES}


@app.get("/api/consents")
def get_consents(user: User = Depends(require(Role.patient)), db: Session = Depends(get_db)):
    return {"notice_version": privacy_svc.NOTICE_VERSION, "consents": privacy_svc.current(db, user),
            "history": privacy_svc.history(db, user)}


@app.post("/api/consents")
def set_consent(body: ConsentIn, user: User = Depends(require(Role.patient)), db: Session = Depends(get_db)):
    return {"consents": privacy_svc.record(db, user, body.purpose, body.granted, body.language)}


@app.get("/api/patient/my-data")
def my_data(user: User = Depends(require(Role.patient)), db: Session = Depends(get_db)):
    """DPDP right to access: a copy of the patient's own data."""
    patient = db.get(Patient, user.patient_id)
    audit.record(db, user, "privacy.data_exported", "patient", patient.id)
    db.commit()
    return {
        "profile": {"name": patient.name, "patient_ref": patient.patient_ref, "date_of_birth": patient.date_of_birth,
                    "address": patient.address},
        "visits": visit_svc.list_for_patient(db, user),
        "visit_notes": [n for n in (notes_svc.get_for_patient(db, user, v["id"]) for v in visit_svc.list_for_patient(db, user)) if n],
        "prescriptions": [rx_to_dict(rx, include_integrity=False) for rx in rx_svc.list_for_patient(db, user.patient_id)],
        "orders": [order_svc.serialize_order(db, o, user) for o in db.scalars(
            select(PharmacyOrder).where(PharmacyOrder.patient_id == patient.id).order_by(PharmacyOrder.id))],
        "consents": privacy_svc.history(db, user),
    }


@app.post("/api/patient/data-requests", status_code=201)
def data_request(body: DataRequestIn, user: User = Depends(require(Role.patient)), db: Session = Depends(get_db)):
    req = privacy_svc.data_request(db, user, body.kind, body.details)
    return {"reference": req.reference, "kind": req.kind, "status": req.status,
            "respond_within_days": privacy_svc.NOTICE["grievance_officer"]["respond_within_days"]}


# ------------------------------------------------------------------ patient booking
class BookingIn(BaseModel):
    doctor_id: int | None = None  # None = nearest available doctor
    scheduled_for: str = Field(default="", max_length=40)  # not needed when asap is true
    reason: str = Field(min_length=2, max_length=300)
    address: str = Field(default="", max_length=300)
    asap: bool = False  # whoever is available soonest
    follow_up_of: int | None = None  # the completed visit this one follows up
    cashless: bool = False  # bill the visit to the patient's health insurer
    member_id: int | None = None  # family booking: the family member this visit is for


class AvailabilityIn(BaseModel):
    date: str = Field(min_length=10, max_length=10)
    hours: list[int] = Field(default_factory=list, max_length=24)


@app.get("/api/doctors")
def nearby_doctors(member: int | None = None, user: User = Depends(require(Role.patient)), db: Session = Depends(get_db)):
    from .services.family import patient_for
    patient = patient_for(db, user, member)
    return {"address": patient.address, "radius_km": visit_svc.SERVICE_RADIUS_KM,
            "doctors": visit_svc.list_doctors(db, patient), "soonest": visit_svc.soonest_to_dict(db, patient)}


@app.get("/api/patient/follow-up")
def follow_up(user: User = Depends(require(Role.patient)), db: Session = Depends(get_db)):
    return visit_svc.follow_up(db, user)


@app.get("/api/visit-slots")
def visit_slots(doctor_id: int | None = None, member: int | None = None, user: User = Depends(require(Role.patient)),
                db: Session = Depends(get_db)):
    from .services.family import patient_for
    return visit_svc.slots_for(db, patient_for(db, user, member), doctor_id)


@app.get("/api/patient/visits")
def patient_visits(user: User = Depends(require(Role.patient)), db: Session = Depends(get_db)):
    return visit_svc.list_for_patient(db, user)


@app.post("/api/patient/visits", status_code=201)
def book_visit(body: BookingIn, user: User = Depends(require(Role.patient)), db: Session = Depends(get_db)):
    privacy_svc.require_care(db, user)
    v = visit_svc.book(db, user, body.doctor_id, body.scheduled_for, body.reason, body.address,
                       asap=body.asap, follow_up_of=body.follow_up_of, cashless=body.cashless,
                       member_id=body.member_id)
    return visit_svc.visit_to_dict(v, v.patient)


@app.post("/api/patient/visits/{visit_id}/cancel")
def cancel_visit(visit_id: int, user: User = Depends(require(Role.patient)), db: Session = Depends(get_db)):
    v = visit_svc.cancel(db, user, visit_id)
    return {"id": v.id, "status": v.status.value}


# ------------------------------------------------------------------ doctor
@app.get("/api/doctor/visits")
def doctor_visits(user: User = Depends(require(Role.doctor)), db: Session = Depends(get_db)):
    rows = db.scalars(select(HomeVisit).where(HomeVisit.doctor_id == user.doctor_id).order_by(HomeVisit.id)).all()
    return [{"id": v.id, "status": v.status.value, "patient": {"id": v.patient_id, "name": v.patient.name,
             "patient_ref": v.patient.patient_ref}, "reason": v.reason, "address": v.address or v.patient.address,
             "booking_ref": v.booking_ref, "fee": v.fee, "on_demand": v.on_demand, "follow_up_of": visit_svc.follow_up_info(v),
             "has_notes": v.note is not None, "scheduled_for": v.scheduled_for.isoformat()} for v in rows]


@app.get("/api/doctor/availability")
def doctor_availability(user: User = Depends(require(Role.doctor)), db: Session = Depends(get_db)):
    return visit_svc.availability(db, user.doctor_id)


@app.put("/api/doctor/availability")
def set_doctor_availability(body: AvailabilityIn, user: User = Depends(require(Role.doctor)),
                            db: Session = Depends(get_db)):
    return visit_svc.set_availability(db, user, body.date, body.hours)


class VisitActionIn(BaseModel):
    arrival_code: str | None = Field(None, max_length=8)


@app.post("/api/doctor/visits/{visit_id}/{action}")
def visit_action(visit_id: int, action: Literal["accept", "start", "complete"], body: VisitActionIn | None = None,
                 user: User = Depends(require(Role.doctor)), db: Session = Depends(get_db)):
    v = rx_svc.advance_visit(db, user, visit_id, action, body.arrival_code if body else None)
    return {"id": v.id, "status": v.status.value}


@app.get("/api/doctor/prescriptions")
def doctor_prescriptions(user: User = Depends(require(Role.doctor)), db: Session = Depends(get_db)):
    return [rx_to_dict(rx, include_integrity=False) for rx in rx_svc.list_for_doctor(db, user.doctor_id)]


@app.post("/api/prescriptions", status_code=201)
def create_prescription(body: RxCreate, user: User = Depends(require(Role.doctor)), db: Session = Depends(get_db)):
    rx = rx_svc.create_draft(db, user, body.visit_id, body.diagnosis_note, [i.model_dump() for i in body.items])
    return rx_to_dict(rx)


@app.patch("/api/prescriptions/{rx_id}")
def update_prescription(rx_id: int, body: RxUpdate, user: User = Depends(require(Role.doctor)), db: Session = Depends(get_db)):
    rx = rx_svc.update_draft(db, user, rx_id, body.diagnosis_note,
                             [i.model_dump() for i in body.items] if body.items is not None else None)
    return rx_to_dict(rx)


@app.post("/api/prescriptions/{rx_id}/sign")
def sign_prescription(rx_id: int, body: RxSign, user: User = Depends(require(Role.doctor)), db: Session = Depends(get_db)):
    return rx_to_dict(rx_svc.sign(db, user, rx_id, body.confirm_reviewed))


@app.post("/api/prescriptions/{rx_id}/amend", status_code=201)
def amend_prescription(rx_id: int, body: RxAmend, user: User = Depends(require(Role.doctor)), db: Session = Depends(get_db)):
    return rx_to_dict(rx_svc.amend(db, user, rx_id, body.reason, [i.model_dump() for i in body.items]))


@app.get("/api/prescriptions/{rx_id}")
def get_prescription(rx_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rx = get_or_404(db, Prescription, rx_id, "Prescription")
    ensure_prescription_access(user, rx, db)
    if user.role == Role.patient and rx.status == RxStatus.draft:
        raise NotFound("not_found", "Prescription not found.")
    audit.record(db, user, "prescription.viewed", "prescription", rx.id)
    db.commit()
    return rx_to_dict(rx)


@app.get("/api/doctor/clarifications")
def doctor_clarifications(user: User = Depends(require(Role.doctor)), db: Session = Depends(get_db)):
    rows = db.scalars(select(PrescriptionClarification).join(Prescription,
                      Prescription.id == PrescriptionClarification.prescription_id)
                      .where(Prescription.doctor_id == user.doctor_id).order_by(PrescriptionClarification.id.desc())).all()
    return [{"id": c.id, "prescription_id": c.prescription_id, "order_id": c.order_id, "reason": c.reason,
             "message": c.message, "status": c.status, "response": c.response,
             "at": c.created_at.isoformat()} for c in rows]


@app.post("/api/clarifications/{cid}/respond")
def respond_clarification(cid: int, body: ClarifyResponseIn, user: User = Depends(require(Role.doctor)),
                          db: Session = Depends(get_db)):
    c = order_svc.respond_clarification(db, user, cid, body.response, body.authorize)
    return {"id": c.id, "status": c.status}


# ----------------------------------------------------------------- patient
@app.get("/api/patient/prescriptions")
def patient_prescriptions(user: User = Depends(require(Role.patient)), db: Session = Depends(get_db)):
    return [rx_to_dict(rx) for rx in rx_svc.list_for_patient(db, user.patient_id)]


@app.get("/api/patient/carts")
def patient_carts(user: User = Depends(require(Role.patient)), db: Session = Depends(get_db)):
    rows = db.scalars(select(SuggestedCart).where(SuggestedCart.patient_id == user.patient_id)
                      .order_by(SuggestedCart.id.desc())).all()
    return [{"id": c.id, "prescription_id": c.prescription_id, "reference_no": c.prescription.reference_no,
             "created_at": c.created_at.isoformat()} for c in rows]


@app.get("/api/carts/{cart_id}")
def get_cart(cart_id: int, user: User = Depends(require(Role.patient)), db: Session = Depends(get_db)):
    return cart_svc.serialize_cart(db, cart_svc.get_cart_for_patient(db, user, cart_id))


@app.post("/api/cart-items/{item_id}/messages", status_code=201)
def cart_item_message(item_id: int, body: MessageIn, user: User = Depends(require(Role.patient)),
                      db: Session = Depends(get_db)):
    return cart_svc.send_message(db, user, item_id, body.recipient, body.body)


@app.post("/api/cart-items/{item_id}/{action}")
def cart_item_action(item_id: int, action: Literal["add", "remove", "buy_later"], user: User = Depends(require(Role.patient)), db: Session = Depends(get_db)):
    return cart_svc.set_status(db, user, item_id, action)


@app.put("/api/cart-items/{item_id}/quantity")
def cart_item_quantity(item_id: int, body: QuantityIn, user: User = Depends(require(Role.patient)),
                       db: Session = Depends(get_db)):
    return cart_svc.request_quantity(db, user, item_id, body.requested_quantity)


@app.get("/api/carts/{cart_id}/pharmacies")
def cart_pharmacies(cart_id: int, sort: str = Query("nearest"), user: User = Depends(require(Role.patient)),
                    db: Session = Depends(get_db)):
    cart = cart_svc.get_cart_for_patient(db, user, cart_id)
    patient = db.get(Patient, user.patient_id)
    if sort not in SORTS:
        sort = "nearest"
    return {"sort": sort, "currency": policy_for(cart.prescription.jurisdiction).currency,
            "pharmacies": [match_to_dict(m) for m in match_pharmacies(db, cart, patient, sort=sort)]}


@app.post("/api/carts/{cart_id}/checkout", status_code=201)
def checkout(cart_id: int, body: CheckoutIn, user: User = Depends(require(Role.patient)), db: Session = Depends(get_db)):
    privacy_svc.require_care(db, user)
    order = order_svc.checkout(
        db, user, cart_id, pharmacy_id=body.pharmacy_id, fulfillment=body.fulfillment,
        delivery_option=body.delivery_option, scheduled_for=body.scheduled_for,
        payment_method=body.payment_method, payment_token=body.payment_token,
        idempotency_key=body.idempotency_key, expected_total=body.expected_total,
    )
    return order_svc.serialize_order(db, order, user)


@app.get("/api/patient/medicines")
def my_medicines(user: User = Depends(require(Role.patient)), db: Session = Depends(get_db)):
    """My Medicines dashboard. Prescribed, ordered and dispensed are kept distinct;
    nothing here implies a medicine has been taken."""
    from .services.dispatch import sweep
    sweep(db)  # moves shop orders along (packing, rider offers) for the demo
    rxs = rx_svc.list_for_patient(db, user.patient_id)
    out_rx = []
    for rx in rxs:
        items = []
        for i in rx.items:
            ordered = db.scalar(select(func.coalesce(func.sum(OrderItem.requested_quantity), 0))
                .join(PharmacyOrder, PharmacyOrder.id == OrderItem.order_id)
                .where(OrderItem.prescription_item_id == i.id,
                       PharmacyOrder.status.notin_([OrderStatus.cancelled, OrderStatus.rejected])))
            dispensed = order_svc.dispensed_so_far(db, i.id)
            remaining = order_svc.max_dispensable(i) - dispensed
            items.append({
                "prescription_item_id": i.id, "medicine": f"{i.medication.brand_name} {i.medication.strength}",
                "prescribed_quantity": i.quantity, "ordered_quantity": ordered, "dispensed_quantity": dispensed,
                "unit": i.medication.unit, "dosage": i.dosage, "frequency": i.frequency,
                "refills_allowed": i.refills_allowed,
                "refill_eligible": i.refills_allowed > 0 and dispensed >= i.quantity and remaining > 0,
            })
        expired = bool(rx.valid_until and utcnow() > rx.valid_until)
        out_rx.append({"id": rx.id, "reference_no": rx.reference_no, "doctor": rx.doctor.name,
                       "status": "expired" if expired and rx.status == RxStatus.signed else rx.status.value,
                       "valid_until": rx.valid_until.isoformat() if rx.valid_until else None, "items": items})
    orders = db.scalars(select(PharmacyOrder).where(PharmacyOrder.patient_id == user.patient_id)
                        .order_by(PharmacyOrder.id.desc())).all()
    active_states = {OrderStatus.prescription_received, OrderStatus.pharmacist_reviewing,
                     OrderStatus.awaiting_clarification, OrderStatus.order_accepted, OrderStatus.preparing,
                     OrderStatus.ready_for_pickup, OrderStatus.out_for_delivery}
    msgs = db.scalars(select(PatientMessage).where(PatientMessage.patient_id == user.patient_id)
                      .order_by(PatientMessage.id.desc())).all()
    return {
        "prescriptions": out_rx,
        "active_orders": [order_svc.serialize_order(db, o, user) for o in orders if o.status in active_states],
        "purchase_history": [order_svc.serialize_order(db, o, user) for o in orders if o.status not in active_states],
        "messages": [{"id": m.id, "recipient": m.recipient, "body": m.body, "at": m.created_at.isoformat(),
                      "from_me": m.sender_user_id == user.id} for m in msgs],
        "note": "Prescribed medicines are not the same as purchased or taken medicines. "
                "Talk to your doctor before changing your treatment.",
        "doctor_follow_up": {"action": "book_home_visit", "label": "Book a follow-up home visit"},
    }


# --------------------------------------------------------------- orders
@app.get("/api/orders/{order_id}")
def get_order(order_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from .services.dispatch import sweep
    sweep(db)
    order = get_or_404(db, PharmacyOrder, order_id, "Order")
    ensure_order_access(user, order)
    return order_svc.serialize_order(db, order, user)


@app.post("/api/orders/{order_id}/cancel")
def cancel_order(order_id: int, body: CancelIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return order_svc.serialize_order(db, order_svc.cancel(db, user, order_id, body.reason), user)


@app.get("/api/pharmacy/orders")
def pharmacy_orders(user: User = Depends(require(Role.pharmacist, Role.courier)), db: Session = Depends(get_db)):
    from .services.dispatch import sweep
    sweep(db)
    rows = db.scalars(select(PharmacyOrder).where(PharmacyOrder.pharmacy_id == user.pharmacy_id)
                      .order_by(PharmacyOrder.id.desc())).all()
    out = []
    for o in rows:
        d = order_svc.serialize_order(db, o, user)
        rx = db.get(Prescription, o.prescription_id) if o.prescription_id else None
        if rx is not None:
            ok, why = rx_svc.is_dispensable(rx)
            d["prescription"] = {"reference_no": rx.reference_no, "doctor": rx.doctor.name,
                                 "license_no": rx.doctor.license_no, "valid": ok, "issue": why}
        else:  # over-the-counter shop order: no prescription needed
            d["prescription"] = None
        patient = db.get(Patient, o.patient_id)
        d["patient"] = {"name": patient.name, "patient_ref": patient.patient_ref}
        out.append(d)
    return out


@app.post("/api/pharmacy/orders/{order_id}/start-review")
def start_review(order_id: int, user: User = Depends(require(Role.pharmacist)), db: Session = Depends(get_db)):
    return order_svc.serialize_order(db, order_svc.start_review(db, user, order_id), user)


@app.post("/api/pharmacy/orders/{order_id}/review")
def review_order(order_id: int, body: ReviewIn, user: User = Depends(require(Role.pharmacist)), db: Session = Depends(get_db)):
    order = order_svc.review(db, user, order_id, body.decision, body.notes, body.adjustments,
                             body.h1_register_confirmed)
    return order_svc.serialize_order(db, order, user)


@app.post("/api/pharmacy/orders/{order_id}/clarify", status_code=201)
def clarify(order_id: int, body: ClarifyIn, user: User = Depends(require(Role.pharmacist)), db: Session = Depends(get_db)):
    c = order_svc.request_clarification(db, user, order_id, body.reason, body.message)
    return {"id": c.id, "status": c.status}


@app.post("/api/pharmacy/orders/{order_id}/{action}")
def fulfil(order_id: int, action: Literal["prepare", "ready", "dispatch"], user: User = Depends(require(Role.pharmacist, Role.courier)),
           db: Session = Depends(get_db)):
    return order_svc.serialize_order(db, order_svc.advance(db, user, order_id, action), user)


@app.post("/api/orders/{order_id}/handover")
def handover(order_id: int, body: HandoverIn, user: User = Depends(require(Role.pharmacist, Role.courier)),
             db: Session = Depends(get_db)):
    order = order_svc.complete_handover(db, user, order_id, body.code, body.recipient_name, body.id_verified)
    return order_svc.serialize_order(db, order, user)


# ------------------------------------------------------- hospitals & drones
class ShipmentIn(BaseModel):
    origin_kind: Literal["pharmacy", "hospital"]
    origin_id: int
    dest_hospital_id: int
    category: str = "medicines"
    contents: str = Field(default="", max_length=300)
    weight_kg: float = Field(gt=0, le=50)
    cold_chain: bool = False
    controlled: bool = False
    urgency: Literal["routine", "urgent", "emergency"] = "routine"
    mode: Literal["auto", "road"] = "auto"


class MissionActionIn(BaseModel):
    reason: str = Field(default="", max_length=200)
    received_by: str = Field(default="", max_length=120)
    temperature_ok: bool | None = None


@app.get("/api/hospital/network")
def hospital_network(user: User = Depends(require(Role.hospital)), db: Session = Depends(get_db)):
    """Which hospitals and pharmacies a drone can serve from this hospital, and why not where it can't."""
    return hospital_svc.network(db, user)


@app.post("/api/shipments/quote")
def shipment_quote(body: ShipmentIn, user: User = Depends(require(Role.hospital)), db: Session = Depends(get_db)):
    return hospital_svc.quote(db, user, body.model_dump())


@app.post("/api/shipments", status_code=201)
def create_shipment(body: ShipmentIn, user: User = Depends(require(Role.hospital)), db: Session = Depends(get_db)):
    s = hospital_svc.create(db, user, body.model_dump())
    return hospital_svc.shipment_to_dict(db, s, _zones(db))


@app.get("/api/shipments")
def list_shipments(user: User = Depends(require(Role.hospital, Role.pharmacist)), db: Session = Depends(get_db)):
    zones = _zones(db)
    return [hospital_svc.shipment_to_dict(db, s, zones) for s in hospital_svc.list_for(db, user)]


@app.get("/api/missions/{mission_id}")
def get_mission(mission_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from .services.drones import serialize_mission
    return serialize_mission(hospital_svc.mission_for_user(db, user, mission_id), _zones(db))


@app.post("/api/missions/{mission_id}/{action}")
def mission_action(mission_id: int, action: Literal["launch", "arrive", "divert", "confirm"], body: MissionActionIn,
                   user: User = Depends(require(Role.hospital, Role.pharmacist)), db: Session = Depends(get_db)):
    from .services.drones import serialize_mission
    m = hospital_svc.mission_action(db, user, mission_id, action, body.model_dump())
    return serialize_mission(m, _zones(db))


def _zones(db: Session):
    from .models import AirspaceZone
    return list(db.scalars(select(AirspaceZone)))


# ------------------------------------------------------------------- yana
@app.post("/api/yana")
def yana(body: YanaIn, user: User = Depends(require(Role.patient)), db: Session = Depends(get_db)):
    return yana_svc.handle(db, user, body.message)


# ------------------------------------------------------------------ audit
@app.get("/api/audit/prescriptions/{rx_id}")
def prescription_audit(rx_id: int, user: User = Depends(require(Role.doctor)), db: Session = Depends(get_db)):
    rx = get_or_404(db, Prescription, rx_id, "Prescription")
    ensure_prescription_access(user, rx, db)
    rows = db.scalars(select(AuditLog).where(AuditLog.entity == "prescription", AuditLog.entity_id == rx_id)
                      .order_by(AuditLog.id)).all()
    return {"chain_valid": audit.verify_chain(db),
            "entries": [{"at": r.created_at.isoformat(), "action": r.action, "actor_role": r.actor_role,
                         "details": r.details} for r in rows]}


# ------------------------------------------------------------------- demo
DEMO_APPS = {
    "patient": {"patient": "Meera (patient)", "patient2": "Arjun (patient)",
                "hospital": "Nisha · hospital (Lotus Hospital)", "hospital2": "Dev · hospital (District Hospital)"},
    "provider": {
        "doctor": "Dr. Carter · doctor", "doctor_rohan": "Dr. Rohan · doctor", "doctor_vikram": "Dr. Vikram · doctor",
        "doctor_sana": "Dr. Sana · doctor", "physio": "Ananya · physiotherapist", "physio_arun": "Arun · physiotherapist",
        "physio_meghna": "Meghna · physiotherapist", "courier": "Asha · courier (GreenLeaf)", "courier2": "Kiran · courier",
        "pharmacist": "Ravi · pharmacist (GreenLeaf)", "pharmacist2": "Lina · pharmacist (Sunrise)",
        "phlebotomist": "Priya · phlebotomist (sample collector)", "phlebotomist2": "Suresh · phlebotomist",
        "phlebotomist3": "Fatima · phlebotomist",
    },
}


@app.get("/api/demo/accounts")
def demo_accounts(app_name: Literal["patient", "provider"] | None = Query(None, alias="app")):
    if os.environ.get("TRIYANA_DEMO", "1") != "1":
        raise NotFound("not_found", "Not available.")
    from .seed import DEMO_TOKENS
    apps = [app_name] if app_name else list(DEMO_APPS)
    return [{"key": k, "label": v, "token": DEMO_TOKENS[k], "app": a} for a in apps for k, v in DEMO_APPS[a].items()]


@app.post("/api/demo/reset")
def demo_reset():
    if os.environ.get("TRIYANA_DEMO", "1") != "1":
        raise NotFound("not_found", "Not available.")
    from .services.accounts import registered_accounts_exist
    with SessionLocal() as db:
        if registered_accounts_exist(db) and os.environ.get("TRIYANA_ALLOW_DEMO_RESET") != "1":
            # A reset rebuilds the whole database, which would erase people's real accounts and history.
            raise Forbidden("reset_disabled", "Reset is off because people have signed up with their own accounts.")
    from .seed import seed
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    return {"ok": True}


app.include_router(auth_router)
app.include_router(live_router)
app.include_router(visit_notes_router)
app.include_router(labs_router)
app.include_router(shop_router)
app.include_router(physio_router)
app.include_router(face_router)
app.include_router(perks_router)
app.include_router(care_router)
app.include_router(family_router)

# --------------------------------------------------------------- frontend
FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.get("/")
    def index():
        """Triyana: the patient app."""
        return FileResponse(FRONTEND / "index.html")

    @app.get("/provider")
    def provider_app():
        """Nabzo: the app for doctors, couriers and pharmacists."""
        return FileResponse(FRONTEND / "provider.html")

    @app.get("/admin")
    def admin_app():
        """Triyana Ops: final review of provider verification (needs the admin key)."""
        return FileResponse(FRONTEND / "admin.html")

    @app.get("/track/{token}")
    def family_tracking_page(token: str):
        """Read-only live map a family member opens from an SOS text or a shared link."""
        return FileResponse(FRONTEND / "track.html")

    @app.get("/sw.js")
    def service_worker():
        return FileResponse(FRONTEND / "sw.js", media_type="text/javascript",
                            headers={"Service-Worker-Allowed": "/"})


@app.on_event("startup")
def startup():
    if os.environ.get("TRIYANA_SKIP_STARTUP_SEED") == "1":
        return
    Base.metadata.create_all(engine)
    from .db import add_missing_columns
    add_missing_columns(engine)
    with SessionLocal() as db:
        if not db.scalars(select(User)).first():
            from .seed import seed
            seed(db)
        from .services.face_verification import seed_demo_enrollments
        seed_demo_enrollments(db)
        db.commit()
