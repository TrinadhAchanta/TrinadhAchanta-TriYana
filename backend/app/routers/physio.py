"""Physiotherapy at home: patient booking and tracking, physiotherapist sessions and notes."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require
from ..models import Role, User
from ..services import dispatch
from ..services import physio as svc
from ..services import privacy as privacy_svc

router = APIRouter()
patient = require(Role.patient)
physio = require(Role.physio)


class BookIn(BaseModel):
    condition: str = Field(max_length=32)
    plan: Literal["single", "pack5", "pack10"] = "single"
    when: Literal["now"] | datetime = "now"
    details: str = Field(default="", max_length=300)
    address: str = Field(default="", max_length=300)


class RescheduleIn(BaseModel):
    when: datetime


class NotesIn(BaseModel):
    pain_before: int = Field(ge=0, le=10)
    pain_after: int = Field(ge=0, le=10)
    exercises: list[str] = Field(default_factory=list, max_length=20)
    notes: str = Field(default="", max_length=2000)
    home_plan: str = Field(default="", max_length=1000)
    next_focus: str = Field(default="", max_length=300)


# ------------------------------------------------------------------ patient
@router.get("/api/physio/catalogue")
def catalogue(user: User = Depends(patient), db: Session = Depends(get_db)):
    return svc.catalogue(db, user)


@router.post("/api/patient/physio/bookings", status_code=201)
def book(body: BookIn, user: User = Depends(patient), db: Session = Depends(get_db)):
    privacy_svc.require_care(db, user)
    b = svc.book(db, user, condition=body.condition, plan=body.plan, when=body.when, details=body.details,
                 address=body.address)
    return svc.booking_to_dict(db, b)


@router.get("/api/patient/physio/bookings")
def my_bookings(user: User = Depends(patient), db: Session = Depends(get_db)):
    return svc.list_for_patient(db, user)


@router.get("/api/patient/physio/bookings/{booking_id}")
def my_booking(booking_id: int, user: User = Depends(patient), db: Session = Depends(get_db)):
    return svc.get_for_patient(db, user, booking_id)


@router.post("/api/patient/physio/bookings/{booking_id}/cancel")
def cancel(booking_id: int, user: User = Depends(patient), db: Session = Depends(get_db)):
    return svc.booking_to_dict(db, svc.cancel(db, user, booking_id))


@router.put("/api/patient/physio/sessions/{session_id}/time")
def reschedule(session_id: int, body: RescheduleIn, user: User = Depends(patient), db: Session = Depends(get_db)):
    s = svc.reschedule(db, user, session_id, body.when)
    return svc.booking_to_dict(db, s.booking)


@router.get("/api/patient/physio/sessions/{session_id}/live")
def live(session_id: int, user: User = Depends(patient), db: Session = Depends(get_db)):
    return svc.live(db, user, session_id)


# ------------------------------------------------------------------ physiotherapist
@router.get("/api/physio/bookings")
def physio_bookings(user: User = Depends(physio), db: Session = Depends(get_db)):
    return svc.physio_bookings(db, user)


@router.post("/api/physio/sessions/{session_id}/depart")
def depart(session_id: int, user: User = Depends(physio), db: Session = Depends(get_db)):
    return dispatch.trip_to_dict(db, svc.depart(db, user, session_id))


@router.post("/api/physio/sessions/{session_id}/start")
def start(session_id: int, user: User = Depends(physio), db: Session = Depends(get_db)):
    return svc.session_to_dict(svc.start(db, user, session_id))


@router.post("/api/physio/sessions/{session_id}/complete")
def complete(session_id: int, body: NotesIn, user: User = Depends(physio), db: Session = Depends(get_db)):
    s = svc.complete(db, user, session_id, **body.model_dump())
    return svc.session_to_dict(s)
