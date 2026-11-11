"""Shared helpers: access control, notifications, reference numbers."""
from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import Forbidden, NotFound
from ..models import (
    HomeVisit,
    Notification,
    PharmacyOrder,
    Prescription,
    Role,
    User,
)


def new_ref(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(4).upper()}"


def get_or_404(db: Session, model, obj_id: int, label: str):
    obj = db.get(model, obj_id)
    if obj is None:
        raise NotFound("not_found", f"{label} not found.")
    return obj


def ensure_prescription_access(user: User, rx: Prescription, db: Session) -> None:
    """Patient: own prescriptions (signed only). Doctor: prescriptions they wrote.
    Pharmacist: only prescriptions attached to an order placed with their pharmacy."""
    if user.role == Role.patient and user.patient_id == rx.patient_id:
        return
    if user.role == Role.doctor and user.doctor_id == rx.doctor_id:
        return
    if user.role == Role.pharmacist:
        has_order = db.scalars(
            select(PharmacyOrder.id).where(
                PharmacyOrder.prescription_id == rx.id, PharmacyOrder.pharmacy_id == user.pharmacy_id
            )
        ).first()
        if has_order:
            return
    # Do not reveal whether the record exists.
    raise NotFound("not_found", "Prescription not found.")


def ensure_order_access(user: User, order: PharmacyOrder) -> None:
    if user.role == Role.patient and user.patient_id == order.patient_id:
        return
    if user.role in (Role.pharmacist, Role.courier) and user.pharmacy_id == order.pharmacy_id:
        return
    raise NotFound("not_found", "Order not found.")


def ensure_visit_doctor(user: User, visit: HomeVisit) -> None:
    if user.role != Role.doctor or visit.doctor_id != user.doctor_id:
        raise Forbidden("not_your_visit", "This visit is not assigned to you.")


def users_for_patient(db: Session, patient_id: int) -> list[User]:
    return list(db.scalars(select(User).where(User.patient_id == patient_id)))


def users_for_doctor(db: Session, doctor_id: int) -> list[User]:
    return list(db.scalars(select(User).where(User.doctor_id == doctor_id)))


def users_for_pharmacy(db: Session, pharmacy_id: int, role: Role = Role.pharmacist) -> list[User]:
    return list(db.scalars(select(User).where(User.pharmacy_id == pharmacy_id, User.role == role)))


def notify(db: Session, users: list[User], title: str, body: str, link: str = "") -> None:
    for u in users:
        db.add(Notification(user_id=u.id, title=title, body=body, link=link))
