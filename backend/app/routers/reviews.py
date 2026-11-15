"""Patient reviews of doctors and physios: rate after a visit, read before booking, ops can hide."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user, require
from ..models import Role, User
from ..services import reviews
from .auth import _admin

router = APIRouter()
patient = require(Role.patient)
hero = require(Role.doctor, Role.physio)


class ReviewIn(BaseModel):
    kind: str = Field(max_length=12)
    job_id: int
    stars: int = Field(ge=1, le=5)
    comment: str = Field("", max_length=500)


class HideIn(BaseModel):
    hidden: bool = True
    reason: str = Field("", max_length=200)


@router.post("/api/patient/reviews", status_code=201)
def leave_review(body: ReviewIn, user: User = Depends(patient), db: Session = Depends(get_db)):
    r = reviews.submit(db, user, body.kind, body.job_id, body.stars, body.comment)
    return {"id": r.id, "stars": r.stars, "comment": r.comment}


@router.get("/api/patient/reviews/pending")
def to_review(user: User = Depends(patient), db: Session = Depends(get_db)):
    return reviews.pending(db, user)


@router.get("/api/doctors/{doctor_id}/reviews")
def doctor_reviews(doctor_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return reviews.profile(db, "doctor", doctor_id)


@router.get("/api/physios/{physio_id}/reviews")
def physio_reviews(physio_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return reviews.profile(db, "physio", physio_id)


@router.get("/api/provider/reviews")
def my_reviews(user: User = Depends(hero), db: Session = Depends(get_db)):
    return reviews.for_provider(db, user)


@router.get("/api/admin/reviews", dependencies=[Depends(_admin)])
def admin_reviews(show: str = "all", db: Session = Depends(get_db)):
    return reviews.admin_list(db, show)


@router.post("/api/admin/reviews/{review_id}/hide")
def admin_hide(review_id: int, body: HideIn, admin=Depends(_admin), db: Session = Depends(get_db)):
    r = reviews.set_hidden(db, review_id, body.hidden, body.reason, getattr(admin, "name", "") or "")
    return {"id": r.id, "hidden": bool(r.hidden)}
