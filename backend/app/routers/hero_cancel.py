"""Heros cancel at the door (with a reason), call-the-patient logging, and the /admin list."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require
from ..models import Role, User
from ..services import hero_cancel
from .auth import _admin

router = APIRouter()
hero = require(Role.doctor, Role.phlebotomist, Role.physio)


class HeroCancelIn(BaseModel):
    reason: str = Field(max_length=24)
    note: str = Field("", max_length=300)


@router.get("/api/provider/jobs/{kind}/{job_id}/cancel-info")
def cancel_info(kind: str, job_id: int, user: User = Depends(hero), db: Session = Depends(get_db)):
    return hero_cancel.info(db, user, kind, job_id)


@router.post("/api/provider/jobs/{kind}/{job_id}/call")
def call_patient(kind: str, job_id: int, user: User = Depends(hero), db: Session = Depends(get_db)):
    return hero_cancel.call(db, user, kind, job_id)


@router.post("/api/provider/jobs/{kind}/{job_id}/cancel")
def cancel_at_door(kind: str, job_id: int, body: HeroCancelIn, user: User = Depends(hero), db: Session = Depends(get_db)):
    rec = hero_cancel.cancel(db, user, kind, job_id, body.reason, body.note)
    return {"id": rec.id, "kind": rec.kind, "job_id": rec.job_id, "reason": rec.reason, "hero_paid": rec.hero_paid}


@router.get("/api/admin/hero-cancellations", dependencies=[Depends(_admin)])
def admin_hero_cancellations(db: Session = Depends(get_db)):
    return hero_cancel.admin_list(db)
