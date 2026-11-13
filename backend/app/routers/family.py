"""Family booking, SOS, live tracking links and the verified doctor card (patient app)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require
from ..models import Role, User
from ..services import dispatch, doctor_card, family
from ..services import privacy as privacy_svc
from ..services import sos as sos_svc

router = APIRouter()
patient = require(Role.patient)


class MemberIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    relation: str = Field(default="Other", max_length=40)
    date_of_birth: str = Field(default="", max_length=10)
    gender: str | None = Field(default=None, max_length=20)
    phone: str = Field(default="", max_length=20)
    same_home: bool = True
    address: str = Field(default="", max_length=300)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)


class ContactIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    relation: str = Field(default="", max_length=40)
    phone: str = Field(min_length=6, max_length=20)


class SosIn(BaseModel):
    member_id: int | None = None
    symptoms: list[str] = Field(default_factory=list, max_length=14)
    note: str = Field(default="", max_length=300)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)


class ShareIn(BaseModel):
    label: str = Field(default="", max_length=80)


# ------------------------------------------------------------------ family
@router.get("/api/patient/family")
def get_family(user: User = Depends(patient), db: Session = Depends(get_db)):
    return family.list_members(db, user)


@router.post("/api/patient/family/members", status_code=201)
def add_member(body: MemberIn, user: User = Depends(patient), db: Session = Depends(get_db)):
    return family.add_member(db, user, body.model_dump())


@router.delete("/api/patient/family/members/{member_id}")
def remove_member(member_id: int, user: User = Depends(patient), db: Session = Depends(get_db)):
    family.remove_member(db, user, member_id)
    return {"ok": True}


@router.post("/api/patient/family/contacts", status_code=201)
def add_contact(body: ContactIn, user: User = Depends(patient), db: Session = Depends(get_db)):
    return family.add_contact(db, user, body.model_dump())


@router.delete("/api/patient/family/contacts/{contact_id}")
def remove_contact(contact_id: int, user: User = Depends(patient), db: Session = Depends(get_db)):
    family.remove_contact(db, user, contact_id)
    return {"ok": True}


# ------------------------------------------------------------------ SOS
@router.get("/api/patient/sos/options")
def sos_options(user: User = Depends(patient), db: Session = Depends(get_db)):
    return sos_svc.options(db, user)


@router.post("/api/patient/sos", status_code=201)
def send_sos(body: SosIn, user: User = Depends(patient), db: Session = Depends(get_db)):
    privacy_svc.require_care(db, user)
    return sos_svc.trigger(db, user, body.member_id, body.symptoms, body.note, body.lat, body.lng)


@router.get("/api/patient/sos/{sos_id}")
def get_sos(sos_id: int, user: User = Depends(patient), db: Session = Depends(get_db)):
    return sos_svc.get(db, user, sos_id)


@router.post("/api/patient/sos/{sos_id}/ambulance/{action}")
def sos_ambulance(sos_id: int, action: str, user: User = Depends(patient), db: Session = Depends(get_db)):
    return sos_svc.ambulance_action(db, user, sos_id, action)


# ------------------------------------------------------------------ visit: doctor card + sharing
@router.get("/api/patient/visits/{visit_id}/doctor-card")
def visit_doctor_card(visit_id: int, user: User = Depends(patient), db: Session = Depends(get_db)):
    return {"card": doctor_card.card(db, family.visit_or_404(db, user, visit_id))}


@router.post("/api/patient/visits/{visit_id}/share", status_code=201)
def share_visit(visit_id: int, body: ShareIn, user: User = Depends(patient), db: Session = Depends(get_db)):
    return family.create_share(db, user, family.visit_or_404(db, user, visit_id), body.label)


@router.get("/api/patient/visits/{visit_id}/shares")
def visit_shares(visit_id: int, user: User = Depends(patient), db: Session = Depends(get_db)):
    return family.list_shares(db, user, visit_id)


@router.delete("/api/patient/visits/{visit_id}/shares/{share_id}")
def revoke_share(visit_id: int, share_id: int, user: User = Depends(patient), db: Session = Depends(get_db)):
    family.revoke_share(db, user, visit_id, share_id)
    return {"ok": True}


# ------------------------------------------------------------------ public tracking link (no sign-in)
@router.get("/api/track/{token}")
def public_track(token: str, db: Session = Depends(get_db)):
    """What family sees from a shared link: where the doctor is and who they are. No health details,
    no arrival code, no doctor photo."""
    dispatch.sweep(db)
    s = family.share_by_token(db, token)
    d = dispatch.visit_view(db, s.visit, None)
    card = d.get("doctor_card")
    p = s.visit.patient
    return {
        "patient_first_name": p.name.split(" ")[0], "sos": bool(s.visit.sos),
        "phase": d["phase"], "status": d["status"], "promise": d["promise"], "arrived_in_s": d["arrived_in_s"],
        "home": {"lat": d["home"]["lat"], "lng": d["home"]["lng"]},
        "provider_location": d["provider_location"],
        "trip": ({k: d["trip"][k] for k in ("eta_min", "remaining_m", "arrived", "fraction", "route", "heading", "position", "source", "speedup")
                  if k in d["trip"]} if d["trip"] else None),
        "doctor": ({k: card[k] for k in ("name", "specialty", "qualification", "experience_years", "rating",
                                         "rating_count", "license_no", "medical_council", "verified", "face_verified")}
                   if card else None),
        "ambulance": (d["sos"] or {}).get("ambulance"),
        "expires_at": s.expires_at.isoformat() + "Z",
    }
