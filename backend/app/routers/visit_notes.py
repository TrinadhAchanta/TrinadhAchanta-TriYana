"""Visit notes: the doctor's record of a home visit (complaint, findings, vitals, diagnosis, advice)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require
from ..models import Role, User
from ..services import visit_notes as notes_svc

router = APIRouter()


class VisitNoteIn(BaseModel):
    chief_complaint: str = Field(default="", max_length=500)
    findings: str = Field(default="", max_length=4000)
    diagnosis: str = Field(default="", max_length=1000)
    advice: str = Field(default="", max_length=2000)
    follow_up_in_days: int | None = Field(default=None, ge=1, le=365)
    temperature_c: float | None = None
    temperature_f: float | None = None
    bp_systolic: int | None = None
    bp_diastolic: int | None = None
    pulse_bpm: int | None = None
    spo2_pct: int | None = None
    resp_rate: int | None = None
    weight_kg: float | None = None
    complete: bool = False  # also mark the visit completed


@router.get("/api/doctor/visits/{visit_id}/notes")
def doctor_get_notes(visit_id: int, user: User = Depends(require(Role.doctor)), db: Session = Depends(get_db)):
    return notes_svc.get_for_doctor(db, user, visit_id)


@router.put("/api/doctor/visits/{visit_id}/notes")
def doctor_save_notes(visit_id: int, body: VisitNoteIn, user: User = Depends(require(Role.doctor)),
                      db: Session = Depends(get_db)):
    data = body.model_dump()
    complete = data.pop("complete")
    return notes_svc.save(db, user, visit_id, data, complete=complete)


@router.get("/api/patient/visits/{visit_id}/notes")
def patient_get_notes(visit_id: int, user: User = Depends(require(Role.patient)), db: Session = Depends(get_db)):
    return notes_svc.get_for_patient(db, user, visit_id)
