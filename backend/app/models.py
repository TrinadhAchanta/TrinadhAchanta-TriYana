"""Database models for the Digital Prescription -> Medicine Delivery flow.

Core Triyana entities (users, patients, verified doctors, home visits,
pharmacies) are included in the minimal form this feature depends on.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .security import EncryptedText


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------------- enums
class Role(str, enum.Enum):
    patient = "patient"
    doctor = "doctor"
    pharmacist = "pharmacist"
    courier = "courier"
    hospital = "hospital"  # hospital pharmacy / logistics staff


class VisitStatus(str, enum.Enum):
    requested = "requested"
    accepted = "accepted"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"


class RxStatus(str, enum.Enum):
    draft = "draft"
    signed = "signed"
    superseded = "superseded"
    cancelled = "cancelled"


class MedSchedule(str, enum.Enum):
    otc = "otc"
    rx = "rx"                # ordinary prescription-only medicine
    restricted = "restricted"  # e.g. antibiotics / Schedule H1-style: prescriber sign-off for partial fills
    controlled = "controlled"  # controlled substances: no patient-initiated partial fills


class CartItemStatus(str, enum.Enum):
    in_cart = "in_cart"
    removed = "removed"
    buy_later = "buy_later"
    ordered = "ordered"


class QuantityStatus(str, enum.Enum):
    full = "full"                          # buying the prescribed quantity
    pending_pharmacist = "pending_pharmacist"
    pending_prescriber = "pending_prescriber"
    approved = "approved"
    rejected = "rejected"
    not_permitted = "not_permitted"


class OrderStatus(str, enum.Enum):
    prescription_received = "prescription_received"
    pharmacist_reviewing = "pharmacist_reviewing"
    awaiting_clarification = "awaiting_clarification"
    order_accepted = "order_accepted"
    preparing = "preparing"
    ready_for_pickup = "ready_for_pickup"
    out_for_delivery = "out_for_delivery"
    delivered = "delivered"
    picked_up = "picked_up"
    rejected = "rejected"
    cancelled = "cancelled"


class PaymentStatus(str, enum.Enum):
    authorized = "authorized"
    captured = "captured"
    voided = "voided"
    failed = "failed"
    refunded = "refunded"
    partially_refunded = "partially_refunded"


# ------------------------------------------------------------------- core triyana
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[Role] = mapped_column(Enum(Role))
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id"))
    doctor_id: Mapped[int | None] = mapped_column(ForeignKey("doctors.id"))
    pharmacy_id: Mapped[int | None] = mapped_column(ForeignKey("pharmacies.id"))
    hospital_id: Mapped[int | None] = mapped_column(ForeignKey("hospitals.id"))
    # Provider app: availability ("Go online") and last known location.
    on_duty: Mapped[bool] = mapped_column(Boolean, default=False)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    vehicle: Mapped[str] = mapped_column(String(40), default="")
    loc_updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class Patient(Base):
    __tablename__ = "patients"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    patient_ref: Mapped[str] = mapped_column(String(32), unique=True)
    date_of_birth: Mapped[str] = mapped_column(EncryptedText)
    address: Mapped[str] = mapped_column(EncryptedText)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    jurisdiction: Mapped[str] = mapped_column(String(16))


class Doctor(Base):
    __tablename__ = "doctors"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    specialty: Mapped[str] = mapped_column(String(80))
    license_no: Mapped[str] = mapped_column(String(40), unique=True)  # NMC / State Medical Council registration no.
    license_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    medical_council: Mapped[str] = mapped_column(String(120), default="")
    qualification: Mapped[str] = mapped_column(String(120), default="")
    registration_year: Mapped[int | None] = mapped_column(Integer)
    jurisdiction: Mapped[str] = mapped_column(String(16))
    rating: Mapped[float] = mapped_column(Float, default=0)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)
    experience_years: Mapped[int] = mapped_column(Integer, default=0)
    visit_fee: Mapped[float] = mapped_column(Float, default=500)
    languages: Mapped[list] = mapped_column(JSON, default=list)
    about: Mapped[str] = mapped_column(String(300), default="")
    lat: Mapped[float] = mapped_column(Float, default=0)
    lng: Mapped[float] = mapped_column(Float, default=0)
    area: Mapped[str] = mapped_column(String(80), default="")


class HomeVisit(Base):
    __tablename__ = "home_visits"
    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int | None] = mapped_column(ForeignKey("doctors.id"))  # None while dispatch is searching
    on_demand: Mapped[bool] = mapped_column(Boolean, default=False)  # "Doctor now" vs a booked time
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"))
    status: Mapped[VisitStatus] = mapped_column(Enum(VisitStatus), default=VisitStatus.requested)
    reason: Mapped[str] = mapped_column(EncryptedText, default="")
    scheduled_for: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    booking_ref: Mapped[str | None] = mapped_column(String(24))
    address: Mapped[str] = mapped_column(EncryptedText, default="")
    fee: Mapped[float | None] = mapped_column(Float)
    follow_up_of_id: Mapped[int | None] = mapped_column(ForeignKey("home_visits.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    doctor = relationship("Doctor")
    patient = relationship("Patient")
    follow_up_of = relationship("HomeVisit", remote_side=[id])


class DoctorAvailability(Base):
    """The hours a doctor opens for home visits on one local calendar day.

    A day with no row uses the default working hours, so a new doctor is bookable straight away.
    A row with an empty list means the doctor has taken that day off.
    """
    __tablename__ = "doctor_availability"
    __table_args__ = (UniqueConstraint("doctor_id", "day"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"), index=True)
    day: Mapped[str] = mapped_column(String(10))  # local date, YYYY-MM-DD
    hours: Mapped[list] = mapped_column(JSON, default=list)  # local start hours, e.g. [9, 10, 14]
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


# --------------------------------------------------------------- medication data
class Medication(Base):
    __tablename__ = "medications"
    id: Mapped[int] = mapped_column(primary_key=True)
    brand_name: Mapped[str] = mapped_column(String(120))
    generic_name: Mapped[str] = mapped_column(String(120))
    strength: Mapped[str] = mapped_column(String(40))
    form: Mapped[str] = mapped_column(String(40))          # tablet, capsule, syrup ...
    unit: Mapped[str] = mapped_column(String(20))          # tablets, capsules, ml
    schedule: Mapped[MedSchedule] = mapped_column(Enum(MedSchedule))
    pack_sizes: Mapped[list] = mapped_column(JSON)         # e.g. [1, 5, 15] units per pack
    loose_units_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    cold_chain: Mapped[bool] = mapped_column(Boolean, default=False)
    id_check_required: Mapped[bool] = mapped_column(Boolean, default=False)
    reference_unit_price: Mapped[float] = mapped_column(Float)
    # India Drugs and Cosmetics Rules schedule: OTC, G, H, H1 or X (demo classification).
    india_schedule: Mapped[str] = mapped_column(String(4), default="H")


# ----------------------------------------------------------------- prescriptions
class Prescription(Base):
    __tablename__ = "prescriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    reference_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    visit_id: Mapped[int | None] = mapped_column(ForeignKey("home_visits.id"))
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"))
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    jurisdiction: Mapped[str] = mapped_column(String(16))
    status: Mapped[RxStatus] = mapped_column(Enum(RxStatus), default=RxStatus.draft)
    consultation_date: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    diagnosis_note: Mapped[str] = mapped_column(EncryptedText, default="")
    valid_until: Mapped[datetime | None] = mapped_column(DateTime)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("prescriptions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime)

    items = relationship("PrescriptionItem", back_populates="prescription", order_by="PrescriptionItem.id")
    doctor = relationship("Doctor")
    patient = relationship("Patient")
    signature = relationship("PrescriberSignature", uselist=False, back_populates="prescription")


class PrescriptionItem(Base):
    __tablename__ = "prescription_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    prescription_id: Mapped[int] = mapped_column(ForeignKey("prescriptions.id"))
    medication_id: Mapped[int] = mapped_column(ForeignKey("medications.id"))
    dosage: Mapped[str] = mapped_column(String(80))
    frequency: Mapped[str] = mapped_column(String(80))
    duration_days: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    route: Mapped[str] = mapped_column(String(40))
    instructions: Mapped[str] = mapped_column(EncryptedText, default="")
    refills_allowed: Mapped[int] = mapped_column(Integer, default=0)

    prescription = relationship("Prescription", back_populates="items")
    medication = relationship("Medication")


class PrescriberSignature(Base):
    __tablename__ = "prescriber_signatures"
    id: Mapped[int] = mapped_column(primary_key=True)
    prescription_id: Mapped[int] = mapped_column(ForeignKey("prescriptions.id"), unique=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"))
    content_hash: Mapped[str] = mapped_column(String(64))
    signature: Mapped[str] = mapped_column(String(128))
    method: Mapped[str] = mapped_column(String(40), default="demo-hmac-sha256")
    signed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    prescription = relationship("Prescription", back_populates="signature")


# -------------------------------------------------------------------- pharmacies
class Pharmacy(Base):
    __tablename__ = "pharmacies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    license_no: Mapped[str] = mapped_column(String(40), unique=True)
    license_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    business_reg_no: Mapped[str] = mapped_column(String(40))
    jurisdiction: Mapped[str] = mapped_column(String(16))
    address: Mapped[str] = mapped_column(String(200))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    service_radius_km: Mapped[float] = mapped_column(Float)
    opens_at: Mapped[int] = mapped_column(Integer)   # hour 0-23 local
    closes_at: Mapped[int] = mapped_column(Integer)  # hour 1-24 local
    rating: Mapped[float] = mapped_column(Float)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)
    pickup_available: Mapped[bool] = mapped_column(Boolean, default=True)
    delivery_available: Mapped[bool] = mapped_column(Boolean, default=True)
    delivery_fee: Mapped[float] = mapped_column(Float)
    prep_minutes: Mapped[int] = mapped_column(Integer, default=30)
    allows_partial_dispensing: Mapped[bool] = mapped_column(Boolean, default=True)
    delivery_options: Mapped[list] = mapped_column(JSON, default=list)
    integration: Mapped[str] = mapped_column(String(40), default="mock-live")  # mock-live | mock-catalog
    drone_pad: Mapped[bool] = mapped_column(Boolean, default=False)  # surveyed launch/landing point


class PharmacyInventory(Base):
    __tablename__ = "pharmacy_inventory"
    __table_args__ = (UniqueConstraint("pharmacy_id", "medication_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    pharmacy_id: Mapped[int] = mapped_column(ForeignKey("pharmacies.id"))
    medication_id: Mapped[int] = mapped_column(ForeignKey("medications.id"))
    units_in_stock: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[float] = mapped_column(Float)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)  # None => not live-verified


# ------------------------------------------------------------------------- carts
class SuggestedCart(Base):
    __tablename__ = "suggested_carts"
    id: Mapped[int] = mapped_column(primary_key=True)
    prescription_id: Mapped[int] = mapped_column(ForeignKey("prescriptions.id"), unique=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    items = relationship("CartItem", back_populates="cart", order_by="CartItem.id")
    prescription = relationship("Prescription")


class CartItem(Base):
    __tablename__ = "cart_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    cart_id: Mapped[int] = mapped_column(ForeignKey("suggested_carts.id"))
    prescription_item_id: Mapped[int] = mapped_column(ForeignKey("prescription_items.id"), unique=True)
    status: Mapped[CartItemStatus] = mapped_column(Enum(CartItemStatus), default=CartItemStatus.in_cart)
    requested_quantity: Mapped[int] = mapped_column(Integer)
    quantity_status: Mapped[QuantityStatus] = mapped_column(Enum(QuantityStatus), default=QuantityStatus.full)
    quantity_note: Mapped[str] = mapped_column(Text, default="")

    cart = relationship("SuggestedCart", back_populates="items")
    prescription_item = relationship("PrescriptionItem")


class PartialDispenseRequest(Base):
    """History of every requested purchase quantity and how it was decided."""

    __tablename__ = "partial_dispense_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    cart_item_id: Mapped[int] = mapped_column(ForeignKey("cart_items.id"))
    prescribed_quantity: Mapped[int] = mapped_column(Integer)
    requested_quantity: Mapped[int] = mapped_column(Integer)
    status: Mapped[QuantityStatus] = mapped_column(Enum(QuantityStatus))
    rule_code: Mapped[str] = mapped_column(String(40))
    explanation: Mapped[str] = mapped_column(Text)
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ------------------------------------------------------------------------ orders
class PharmacyOrder(Base):
    __tablename__ = "pharmacy_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_no: Mapped[str] = mapped_column(String(32), unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(80), unique=True)
    cart_id: Mapped[int] = mapped_column(ForeignKey("suggested_carts.id"))
    prescription_id: Mapped[int] = mapped_column(ForeignKey("prescriptions.id"))
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    pharmacy_id: Mapped[int] = mapped_column(ForeignKey("pharmacies.id"), index=True)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.prescription_received)
    fulfillment: Mapped[str] = mapped_column(String(16))   # delivery | pickup
    delivery_option: Mapped[str | None] = mapped_column(String(20))
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime)
    subtotal: Mapped[float] = mapped_column(Float)
    delivery_fee: Mapped[float] = mapped_column(Float)
    tax: Mapped[float] = mapped_column(Float)
    discount: Mapped[float] = mapped_column(Float, default=0)
    total: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    items = relationship("OrderItem", back_populates="order", order_by="OrderItem.id")
    pharmacy = relationship("Pharmacy")
    payment = relationship("Payment", uselist=False, back_populates="order")
    delivery = relationship("DeliveryAssignment", uselist=False, back_populates="order")
    events = relationship("TrackingEvent", order_by="TrackingEvent.id")


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("pharmacy_orders.id"))
    cart_item_id: Mapped[int] = mapped_column(ForeignKey("cart_items.id"))
    prescription_item_id: Mapped[int] = mapped_column(ForeignKey("prescription_items.id"))
    medication_id: Mapped[int] = mapped_column(ForeignKey("medications.id"))
    prescribed_quantity: Mapped[int] = mapped_column(Integer)
    requested_quantity: Mapped[int] = mapped_column(Integer)
    approved_quantity: Mapped[int | None] = mapped_column(Integer)
    unit_price: Mapped[float] = mapped_column(Float)

    order = relationship("PharmacyOrder", back_populates="items")
    medication = relationship("Medication")


class PharmacistApproval(Base):
    __tablename__ = "pharmacist_approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("pharmacy_orders.id"))
    pharmacist_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(16))  # approve | adjust | reject
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PrescriptionClarification(Base):
    __tablename__ = "prescription_clarifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    prescription_id: Mapped[int] = mapped_column(ForeignKey("prescriptions.id"))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("pharmacy_orders.id"))
    raised_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(EncryptedText)
    status: Mapped[str] = mapped_column(String(16), default="open")
    response: Mapped[str | None] = mapped_column(EncryptedText)
    responded_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PatientMessage(Base):
    """Secure messages between patient and pharmacist / doctor."""

    __tablename__ = "patient_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    prescription_item_id: Mapped[int | None] = mapped_column(ForeignKey("prescription_items.id"))
    recipient: Mapped[str] = mapped_column(String(16))   # pharmacist | doctor | patient
    sender_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(EncryptedText)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------------- payments
class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("pharmacy_orders.id"), unique=True)
    method: Mapped[str] = mapped_column(String(24))
    provider_ref: Mapped[str] = mapped_column(String(64))
    amount_authorized: Mapped[float] = mapped_column(Float)
    amount_captured: Mapped[float] = mapped_column(Float, default=0)
    amount_refunded: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    order = relationship("PharmacyOrder", back_populates="payment")
    refunds = relationship("Refund")


class Refund(Base):
    __tablename__ = "refunds"
    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"))
    amount: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(200))
    provider_ref: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------------- delivery
class DeliveryAssignment(Base):
    __tablename__ = "delivery_assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("pharmacy_orders.id"), unique=True)
    provider: Mapped[str] = mapped_column(String(40))
    option: Mapped[str] = mapped_column(String(20))
    courier_name: Mapped[str | None] = mapped_column(String(80))
    courier_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    tracking_ref: Mapped[str] = mapped_column(String(40))
    eta: Mapped[datetime | None] = mapped_column(DateTime)
    handover_code: Mapped[str] = mapped_column(EncryptedText)
    cold_chain: Mapped[bool] = mapped_column(Boolean, default=False)
    id_check_required: Mapped[bool] = mapped_column(Boolean, default=False)
    signature_required: Mapped[bool] = mapped_column(Boolean, default=True)
    proof_of_delivery: Mapped[dict | None] = mapped_column(JSON)

    order = relationship("PharmacyOrder", back_populates="delivery")


class DispatchOffer(Base):
    """A job offered to one provider at a time, nearest first (DoorDash/Dasher style)."""
    __tablename__ = "dispatch_offers"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))            # visit | delivery
    visit_id: Mapped[int | None] = mapped_column(ForeignKey("home_visits.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("pharmacy_orders.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="offered")  # offered|accepted|declined|expired|withdrawn
    distance_km: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)  # None = waits for an answer (booked times)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime)

    user = relationship("User")
    visit = relationship("HomeVisit")
    order = relationship("PharmacyOrder")


class Trip(Base):
    """A provider travelling to a place. Position is simulated along the route unless real GPS is sent."""
    __tablename__ = "trips"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    visit_id: Mapped[int | None] = mapped_column(ForeignKey("home_visits.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("pharmacy_orders.id"), index=True)
    leg: Mapped[str] = mapped_column(String(16))             # to_patient | to_pharmacy
    dest_label: Mapped[str] = mapped_column(String(160), default="")
    route: Mapped[list] = mapped_column(JSON, default=list)  # [[lat, lng], ...]
    steps: Mapped[list] = mapped_column(JSON, default=list)  # [{text, along_m, type, modifier}]
    distance_m: Mapped[float] = mapped_column(Float, default=0)
    duration_s: Mapped[float] = mapped_column(Float, default=0)
    source: Mapped[str] = mapped_column(String(16), default="synthetic")  # synthetic | osrm
    speedup: Mapped[float] = mapped_column(Float, default=8)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    gps_lat: Mapped[float | None] = mapped_column(Float)
    gps_lng: Mapped[float | None] = mapped_column(Float)
    gps_at: Mapped[datetime | None] = mapped_column(DateTime)

    user = relationship("User")


class TrackingEvent(Base):
    __tablename__ = "tracking_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("pharmacy_orders.id"), index=True)
    status: Mapped[str] = mapped_column(String(40))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DispensingRecord(Base):
    __tablename__ = "dispensing_records"
    __table_args__ = (UniqueConstraint("order_item_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    order_item_id: Mapped[int] = mapped_column(ForeignKey("order_items.id"))
    prescription_item_id: Mapped[int] = mapped_column(ForeignKey("prescription_items.id"), index=True)
    pharmacy_id: Mapped[int] = mapped_column(ForeignKey("pharmacies.id"))
    pharmacist_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    dispensed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ------------------------------------------------------------- audit & notices
class AuditLog(Base):
    """Append-only, hash-chained audit trail (tamper evident)."""

    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    actor_role: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text)
    link: Mapped[str] = mapped_column(String(120), default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Consent(Base):
    """DPDP Act 2023: a record of each consent a patient gives or withdraws (append-only)."""
    __tablename__ = "consents"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(32))
    granted: Mapped[bool] = mapped_column(Boolean)
    notice_version: Mapped[str] = mapped_column(String(16))
    language: Mapped[str] = mapped_column(String(8), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DataRequest(Base):
    """DPDP data principal requests (erasure / correction), handled by the grievance officer."""
    __tablename__ = "data_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    details: Mapped[str] = mapped_column(EncryptedText, default="")
    status: Mapped[str] = mapped_column(String(16), default="received")
    reference: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ------------------------------------------------------------ hospitals & drones
class Hospital(Base):
    __tablename__ = "hospitals"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(40))            # multi_speciality | district | phc | specialty
    registration_no: Mapped[str] = mapped_column(String(40), unique=True)  # e.g. state CEA / NABH ref
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    jurisdiction: Mapped[str] = mapped_column(String(16))
    address: Mapped[str] = mapped_column(String(200))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    drone_pad: Mapped[bool] = mapped_column(Boolean, default=False)
    cold_storage: Mapped[bool] = mapped_column(Boolean, default=False)


class AirspaceZone(Base):
    """Drone Rules 2021 airspace map zones (fictional demo geometry).
    Anything outside a red or yellow zone is green."""

    __tablename__ = "airspace_zones"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(10))   # red | yellow
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    radius_km: Mapped[float] = mapped_column(Float)
    authority: Mapped[str] = mapped_column(String(120), default="")


class Shipment(Base):
    """A medical consignment to a hospital: pharmacy -> hospital or hospital -> hospital."""

    __tablename__ = "shipments"
    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(24), unique=True)
    requested_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    origin_kind: Mapped[str] = mapped_column(String(12))   # pharmacy | hospital
    origin_id: Mapped[int] = mapped_column(Integer)
    dest_hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id"), index=True)
    category: Mapped[str] = mapped_column(String(24))      # medicines | blood | vaccines | lab_samples | antivenom
    contents: Mapped[str] = mapped_column(EncryptedText)
    weight_kg: Mapped[float] = mapped_column(Float)
    cold_chain: Mapped[bool] = mapped_column(Boolean, default=False)
    controlled: Mapped[bool] = mapped_column(Boolean, default=False)
    urgency: Mapped[str] = mapped_column(String(12), default="routine")  # routine | urgent | emergency
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    dest_hospital = relationship("Hospital")
    mission = relationship("DeliveryMission", uselist=False, back_populates="shipment")


class DeliveryMission(Base):
    """One delivery leg, flown by drone or driven by road courier (fallback)."""

    __tablename__ = "delivery_missions"
    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(24), unique=True)
    shipment_id: Mapped[int | None] = mapped_column(ForeignKey("shipments.id"), unique=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("pharmacy_orders.id"), unique=True)
    mode: Mapped[str] = mapped_column(String(8))           # drone | road
    provider: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20))        # scheduled | in_flight | in_transit | arrived | delivered | cancelled
    origin: Mapped[dict] = mapped_column(JSON)             # {name, lat, lng}
    destination: Mapped[dict] = mapped_column(JSON)
    distance_km: Mapped[float] = mapped_column(Float)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    eta: Mapped[datetime | None] = mapped_column(DateTime)
    vehicle: Mapped[dict] = mapped_column(JSON, default=dict)      # drone UIN/model or courier details
    compliance: Mapped[dict] = mapped_column(JSON, default=dict)   # permission refs, pilot cert, altitude cap
    checks: Mapped[list] = mapped_column(JSON, default=list)       # eligibility checks at booking
    fallback_reason: Mapped[str | None] = mapped_column(Text)
    cold_chain: Mapped[bool] = mapped_column(Boolean, default=False)
    temperature_log: Mapped[list] = mapped_column(JSON, default=list)
    handover_code: Mapped[str] = mapped_column(EncryptedText)
    received_by: Mapped[str | None] = mapped_column(String(120))
    events: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    launched_at: Mapped[datetime | None] = mapped_column(DateTime)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime)

    shipment = relationship("Shipment", back_populates="mission")
