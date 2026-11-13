"""Lab tests at home: catalog, slots, booking, live tracking, reports, and the collector's actions."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user, require
from ..models import Patient, Role, User
from ..services import dispatch
from ..services import labs
from ..services import privacy as privacy_svc

router = APIRouter()
patient_only = require(Role.patient)
collector = require(Role.phlebotomist)


class QuoteIn(BaseModel):
    test_ids: list[int] = Field(min_length=1, max_length=30)
    on_demand: bool = False


class LabBookIn(BaseModel):
    test_ids: list[int] = Field(min_length=1, max_length=30)
    slot: str = Field(default="now", max_length=40)   # "now" or a slot start from /api/labs/slots
    address: str = Field(default="", max_length=300)
    payment_method: str = Field(default="cash", max_length=24)
    payment_token: str = Field(default="sandbox-ok", max_length=80)


class CollectIn(BaseModel):
    code: str = Field(min_length=4, max_length=4)
    fasting_confirmed: bool = False


# ------------------------------------------------------------------ patient
@router.get("/api/labs/catalog")
def lab_catalog(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return labs.catalog(db)


@router.get("/api/labs/slots")
def lab_slots(fasting_hours: int = Query(0, ge=0, le=24), _: User = Depends(patient_only), db: Session = Depends(get_db)):
    return labs.slots(db, fasting_hours)


@router.post("/api/labs/quote")
def lab_quote(body: QuoteIn, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    q = labs.quote(db, body.test_ids, body.on_demand)
    p = db.get(Patient, user.patient_id)
    q["collectors_online"] = dispatch.online_count(db, "lab", p.lat, p.lng)
    q["address"] = p.address
    return q


@router.post("/api/labs/bookings", status_code=201)
def lab_book(body: LabBookIn, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    privacy_svc.require_care(db, user)
    b = labs.book(db, user, body.test_ids, body.slot, body.address, body.payment_method, body.payment_token)
    return labs.booking_to_dict(db, b)


@router.get("/api/labs/bookings")
def lab_bookings(user: User = Depends(patient_only), db: Session = Depends(get_db)):
    return labs.list_for_patient(db, user)


@router.get("/api/labs/bookings/{booking_id}")
def lab_booking(booking_id: int, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    return labs.get_for_patient(db, user, booking_id)


@router.get("/api/labs/bookings/{booking_id}/live")
def lab_live(booking_id: int, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    return labs.live(db, user, booking_id)


@router.post("/api/labs/bookings/{booking_id}/cancel")
def lab_cancel(booking_id: int, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    return labs.booking_to_dict(db, labs.cancel(db, user, booking_id))


@router.get("/api/patient/collectors-nearby")
def collectors_nearby(user: User = Depends(patient_only), db: Session = Depends(get_db)):
    p = db.get(Patient, user.patient_id)
    return {"collectors": dispatch.online_count(db, "lab", p.lat, p.lng)}


# ------------------------------------------------------------------ phlebotomist (Nabzo)
@router.post("/api/provider/labs/{booking_id}/depart")
def lab_depart(booking_id: int, user: User = Depends(collector), db: Session = Depends(get_db)):
    return dispatch.trip_to_dict(db, labs.depart(db, user, booking_id))


@router.post("/api/provider/labs/{booking_id}/collect")
def lab_collect(booking_id: int, body: CollectIn, user: User = Depends(collector), db: Session = Depends(get_db)):
    b = labs.collect(db, user, booking_id, body.code, body.fasting_confirmed)
    return {**labs.booking_to_dict(db, b, for_patient=False),
            "trip": dispatch.trip_to_dict(db, t) if (t := dispatch.active_trip(db, user.id)) else None}


@router.post("/api/provider/labs/{booking_id}/handover")
def lab_handover(booking_id: int, user: User = Depends(collector), db: Session = Depends(get_db)):
    return labs.booking_to_dict(db, labs.handover(db, user, booking_id), for_patient=False)
