"""Doctor face verification: Partner app, patient app and Triyana Ops endpoints."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require
from ..models import Role, User
from ..services import face_verification as face
from .auth import _admin

router = APIRouter(prefix="/api", tags=["face verification"])
doctor = require(Role.doctor)


class ChallengeIn(BaseModel):
    purpose: Literal["visit", "enroll"]
    visit_id: int | None = None
    consent: bool = False


class SubmitIn(BaseModel):
    nonce: str = Field(max_length=64)
    frames: list[str] = Field(min_length=1, max_length=6)
    demo_scenario: str | None = Field(None, max_length=24)


class AlternativeIn(BaseModel):
    visit_id: int | None = None
    reason: Literal["camera_unavailable", "accessibility", "keeps_failing", "other"] = "other"


class ResolveIn(BaseModel):
    action: Literal[face.RESOLUTIONS]  # type: ignore[valid-type]
    note: str = Field(max_length=300)


# ------------------------------------------------------------------ Partner app (doctors)
@router.get("/provider/face")
def my_face(user: User = Depends(doctor), db: Session = Depends(get_db)):
    return face.provider_state(db, user)


@router.post("/provider/face/challenges", status_code=201)
def new_challenge(body: ChallengeIn, user: User = Depends(doctor), db: Session = Depends(get_db)):
    return face.start_challenge(db, user, body.purpose, body.visit_id, body.consent)


@router.post("/provider/face/challenges/{check_id}/submit")
def submit_challenge(check_id: int, body: SubmitIn, user: User = Depends(doctor), db: Session = Depends(get_db)):
    return face.submit(db, user, check_id, body.nonce, body.frames, body.demo_scenario)


@router.get("/provider/visits/{visit_id}/identity")
def visit_identity(visit_id: int, user: User = Depends(doctor), db: Session = Depends(get_db)):
    return face.visit_state(db, user, visit_id)


@router.post("/provider/face/alternative", status_code=201)
def ask_alternative(body: AlternativeIn, user: User = Depends(doctor), db: Session = Depends(get_db)):
    return face.request_alternative(db, user, body.visit_id, body.reason)


@router.delete("/provider/face/enrollment")
def withdraw(user: User = Depends(doctor), db: Session = Depends(get_db)):
    return face.withdraw_consent(db, user)


# ------------------------------------------------------------------ patient app
@router.get("/patient/visits/{visit_id}/doctor-identity")
def doctor_identity(visit_id: int, user: User = Depends(require(Role.patient)), db: Session = Depends(get_db)):
    """The verified doctor's photo, name and credentials, once they pass the check for this visit."""
    return face.patient_profile(db, user, visit_id)


# ------------------------------------------------------------------ Triyana Ops / security team
@router.get("/admin/identity/cases", dependencies=[Depends(_admin)])
def cases(status: Literal["open", "resolved"] = "open", db: Session = Depends(get_db)):
    return face.list_cases(db, status)


@router.post("/admin/identity/cases/{case_id}/resolve", dependencies=[Depends(_admin)])
def resolve(case_id: int, body: ResolveIn, db: Session = Depends(get_db)):
    return face.resolve_case(db, case_id, body.action, body.note)


@router.get("/admin/identity/checks", dependencies=[Depends(_admin)])
def checks(limit: int = 100, db: Session = Depends(get_db)):
    """Audit view of face checks: outcome, scores and times. Never images."""
    return face.recent_checks(db, limit)
