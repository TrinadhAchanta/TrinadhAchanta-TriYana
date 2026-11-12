"""Provider app (Triyana Partner) and live tracking endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require
from ..errors import NotFound
from ..models import Patient, Role, Trip, User
from ..services import dispatch
from ..services import earnings as earnings_svc
from ..services import privacy as privacy_svc
from ..services import visits as visit_svc

router = APIRouter()
provider = require(Role.doctor, Role.courier, Role.pharmacist, Role.phlebotomist, Role.physio)
traveller = require(Role.doctor, Role.courier, Role.phlebotomist, Role.physio)


class DutyIn(BaseModel):
    online: bool


class LocationIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class StepIn(BaseModel):
    text: str = Field(max_length=200)
    along_m: float = Field(ge=0)
    type: str = Field(default="turn", max_length=24)
    modifier: str = Field(default="straight", max_length=24)


class RouteIn(BaseModel):
    route: list[list[float]] = Field(min_length=2, max_length=5000)
    steps: list[StepIn] = Field(default_factory=list, max_length=200)
    distance_m: float = Field(gt=0)
    duration_s: float = Field(gt=0)
    source: str = Field(default="osrm", max_length=16)


class BookNowIn(BaseModel):
    reason: str = Field(min_length=2, max_length=300)
    address: str = Field(default="", max_length=300)


# ------------------------------------------------------------------ patient
@router.post("/api/patient/visits/now", status_code=201)
def book_doctor_now(body: BookNowIn, user: User = Depends(require(Role.patient)), db: Session = Depends(get_db)):
    privacy_svc.require_care(db, user)
    v = visit_svc.book_now(db, user, body.reason, body.address)
    return visit_svc.visit_to_dict(v, db.get(Patient, user.patient_id))


@router.get("/api/patient/visits/{visit_id}/live")
def visit_live(visit_id: int, user: User = Depends(require(Role.patient)), db: Session = Depends(get_db)):
    return dispatch.visit_live(db, user, visit_id)


@router.get("/api/orders/{order_id}/live")
def order_live(order_id: int, user: User = Depends(require(Role.patient)), db: Session = Depends(get_db)):
    return dispatch.order_live(db, user, order_id)


@router.get("/api/patient/online-nearby")
def online_nearby(user: User = Depends(require(Role.patient)), db: Session = Depends(get_db)):
    p = db.get(Patient, user.patient_id)
    return {"doctors": dispatch.online_count(db, "visit", p.lat, p.lng), "home": [p.lat, p.lng]}


# ------------------------------------------------------------------ provider
@router.get("/api/provider/status")
def provider_status(user: User = Depends(provider), db: Session = Depends(get_db)):
    return dispatch.provider_status(db, user)


@router.post("/api/provider/duty")
def provider_duty(body: DutyIn, user: User = Depends(traveller), db: Session = Depends(get_db)):
    dispatch.set_duty(db, user, body.online)
    return dispatch.provider_status(db, user)


@router.post("/api/provider/offers/{offer_id}/{action}")
def provider_offer(offer_id: int, action: str, user: User = Depends(traveller), db: Session = Depends(get_db)):
    if action == "accept":
        o = dispatch.accept(db, user, offer_id)
    elif action == "decline":
        o = dispatch.decline(db, user, offer_id)
    else:
        raise NotFound("not_found", "Unknown action.")
    return {"id": o.id, "status": o.status, "trip": (dispatch.trip_to_dict(db, t) if (t := dispatch.active_trip(db, user.id)) else None)}


@router.get("/api/provider/earnings")
def provider_earnings(user: User = Depends(traveller), db: Session = Depends(get_db)):
    return earnings_svc.summary(db, user)


@router.post("/api/provider/earnings/cash-out")
def provider_cash_out(user: User = Depends(traveller), db: Session = Depends(get_db)):
    return earnings_svc.cash_out(db, user)


@router.get("/api/provider/jobs")
def provider_jobs(user: User = Depends(traveller), db: Session = Depends(get_db)):
    return dispatch.provider_jobs(db, user)


@router.post("/api/provider/visits/{visit_id}/depart")
def provider_depart(visit_id: int, user: User = Depends(require(Role.doctor)), db: Session = Depends(get_db)):
    return dispatch.trip_to_dict(db, dispatch.depart(db, user, visit_id))


@router.get("/api/provider/trip")
def provider_trip(user: User = Depends(traveller), db: Session = Depends(get_db)):
    t = dispatch.active_trip(db, user.id)
    return dispatch.trip_to_dict(db, t) if t else None


@router.put("/api/provider/trips/{trip_id}/route")
def provider_route(trip_id: int, body: RouteIn, user: User = Depends(traveller), db: Session = Depends(get_db)):
    t = dispatch.set_route(db, user, trip_id, body.route, [s.model_dump() for s in body.steps], body.distance_m,
                           body.duration_s, body.source)
    return dispatch.trip_to_dict(db, t)


@router.post("/api/provider/location")
def provider_location(body: LocationIn, user: User = Depends(traveller), db: Session = Depends(get_db)):
    dispatch.update_location(db, user, body.lat, body.lng)
    return {"ok": True}


@router.get("/api/provider/trips/{trip_id}")
def provider_trip_by_id(trip_id: int, user: User = Depends(traveller), db: Session = Depends(get_db)):
    t = db.get(Trip, trip_id)
    if t is None or t.user_id != user.id:
        raise NotFound("not_found", "Trip not found.")
    return dispatch.trip_to_dict(db, t)
