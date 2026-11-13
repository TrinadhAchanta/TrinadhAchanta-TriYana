"""Care plans, free follow-up calls, health records and voice booking."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require
from ..models import Role, User
from ..services import care, voice

router = APIRouter()
patient_only = require(Role.patient)
doctor_only = require(Role.doctor)


class PlanIn(BaseModel):
    kind: str
    preferred_hour: int = 10
    doctor_id: int | None = None


class CallTimeIn(BaseModel):
    scheduled_for: str


class FeelingIn(BaseModel):
    feeling: str
    note: str = Field(default="", max_length=500)


class CallDoneIn(BaseModel):
    note: str = Field(default="", max_length=1000)


class VoiceIn(BaseModel):
    text: str = Field(max_length=500)
    lang: str = "en"


@router.get("/api/care-plans/catalog")
def plan_catalog(_: User = Depends(patient_only)):
    return care.catalog()


@router.get("/api/care-plans")
def my_plans(user: User = Depends(patient_only), db: Session = Depends(get_db)):
    return care.list_plans(db, user)


@router.post("/api/care-plans", status_code=201)
def start_plan(body: PlanIn, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    plan = care.enrol(db, user, body.kind, body.preferred_hour, body.doctor_id)
    return care.plan_to_dict(db, plan)


@router.post("/api/care-plans/{plan_id}/cancel")
def stop_plan(plan_id: int, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    return care.plan_to_dict(db, care.cancel(db, user, plan_id))


@router.get("/api/patient/follow-up-calls")
def my_calls(user: User = Depends(patient_only), db: Session = Depends(get_db)):
    return care.patient_calls(db, user)


@router.post("/api/patient/follow-up-calls/{call_id}/time")
def move_call(call_id: int, body: CallTimeIn, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    return care.reschedule_call(db, user, call_id, body.scheduled_for)


@router.post("/api/patient/follow-up-calls/{call_id}/feeling")
def call_feeling(call_id: int, body: FeelingIn, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    return care.share_feeling(db, user, call_id, body.feeling, body.note)


@router.get("/api/doctor/follow-up-calls")
def doctor_calls(user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    return care.doctor_calls(db, user)


@router.post("/api/doctor/follow-up-calls/{call_id}/done")
def call_done(call_id: int, body: CallDoneIn, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    return care.complete_call(db, user, call_id, body.note)


@router.get("/api/patient/records")
def health_records(user: User = Depends(patient_only), db: Session = Depends(get_db)):
    return care.records(db, user)


@router.post("/api/voice/understand")
def voice_understand(body: VoiceIn, _: User = Depends(patient_only)):
    return voice.understand(body.text, body.lang)
