"""Sign up, sign in and account endpoints for the Triyana and Nabzo apps."""
from __future__ import annotations

import hmac
import os
from typing import Literal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..errors import Forbidden, NotFound
from ..models import Patient, User
from ..services import accounts, verification

router = APIRouter(prefix="/api", tags=["accounts"])


class DoctorIn(BaseModel):
    license_no: str = Field(max_length=40)
    medical_council: str = Field(max_length=120)
    qualification: str = Field("MBBS", max_length=120)
    specialty: str = Field("General Medicine", max_length=80)
    registration_year: int | None = Field(None, ge=1950, le=2100)
    visit_fee: float | None = Field(None, ge=0, le=100000)


class RegisterIn(BaseModel):
    app: Literal["patient", "provider"]
    name: str = Field(max_length=120)
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)
    phone: str | None = Field(None, max_length=30)
    otp: str | None = Field(None, max_length=10)
    gender: Literal["female", "male", "other", "prefer_not"] | None = None
    address: str | None = Field(None, max_length=300)
    date_of_birth: str | None = Field(None, max_length=10)
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    role: Literal["doctor", "physio", "courier", "phlebotomist"] | None = None
    vehicle: str | None = Field(None, max_length=40)
    doctor: DoctorIn | None = None


class LoginIn(BaseModel):
    app: Literal["patient", "provider"]
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class PasswordIn(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


class OtpIn(BaseModel):
    phone: str = Field(max_length=30)
    country: str | None = Field(None, min_length=2, max_length=2)  # ISO code from the country picker
    app: Literal["patient", "provider"] | None = None  # which app the sign-up is for


class PhoneIn(BaseModel):
    phone: str = Field(max_length=30)
    otp: str = Field(max_length=10)


class ProfileIn(BaseModel):
    name: str | None = Field(None, max_length=120)
    gender: Literal["female", "male", "other", "prefer_not"] | None = None
    date_of_birth: str | None = Field(None, max_length=10)
    address: str | None = Field(None, max_length=300)
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)


class VerifyIn(BaseModel):
    status: Literal["verified", "rejected", "pending"]
    note: str = Field("", max_length=300)
    override: bool = False


class IdentityIn(BaseModel):
    id_type: Literal["pan", "driving_licence"] = "pan"
    id_number: str = Field(max_length=24)
    date_of_birth: str = Field(max_length=10)
    address: str = Field("", max_length=300)
    consent: bool = False


def _bearer(authorization: str | None) -> str:
    return authorization.split(" ", 1)[1].strip() if authorization and " " in authorization else ""


@router.post("/auth/register", status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    data = body.model_dump()
    data["doctor"] = body.doctor.model_dump() if body.doctor else None
    user, token = accounts.register(db, data)
    return {"token": token, "account": accounts.account_dict(db, user)}


@router.post("/auth/otp")
def send_otp(body: OtpIn, db: Session = Depends(get_db)):
    """Send a 6-digit code to verify a mobile number before sign-up."""
    return accounts.send_phone_otp(db, body.phone, country=body.country, app=body.app)


@router.get("/countries")
def countries():
    """Country picker data: ISO code, name, dial code and an example mobile number."""
    return accounts.countries()


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user, token = accounts.login(db, body.email, body.password, body.app)
    return {"token": token, "account": accounts.account_dict(db, user)}


@router.post("/auth/logout")
def logout(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    accounts.close_session(db, _bearer(authorization))
    return {"ok": True}


@router.get("/account")
def get_account(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return accounts.account_dict(db, user)


@router.patch("/account")
def update_account(body: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.name and len(body.name.strip()) >= 2:
        user.name = body.name.strip()
    if user.patient_id:
        p = db.get(Patient, user.patient_id)
        if body.name and len(body.name.strip()) >= 2:
            p.name = body.name.strip()
        if body.address and len(body.address.strip()) >= 5:
            p.address = body.address.strip()
        if body.lat is not None and body.lng is not None:
            p.lat, p.lng = body.lat, body.lng
        if body.gender:
            p.gender = body.gender
        if body.date_of_birth:
            p.date_of_birth = body.date_of_birth
    db.commit()
    return accounts.account_dict(db, user)


@router.post("/account/phone/otp")
def account_phone_otp(body: OtpIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return accounts.send_phone_otp(db, body.phone, country=body.country, for_user=user)


@router.post("/account/phone")
def account_phone(body: PhoneIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.password_hash:
        raise Forbidden("demo_account", "Demo accounts can't change their phone number.")
    accounts.change_phone(db, user, body.phone, body.otp)
    return accounts.account_dict(db, user)


@router.post("/account/password")
def change_password(body: PasswordIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.password_hash:
        raise Forbidden("demo_account", "Demo accounts have no password.")
    accounts.change_password(db, user, body.current_password, body.new_password)
    return {"ok": True}


@router.post("/account/demo-verify")
def demo_verify(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Demo only: lets a tester approve their own new provider account. Off when TRIYANA_DEMO != 1."""
    if os.environ.get("TRIYANA_DEMO", "1") != "1":
        raise NotFound("not_found", "Not available.")
    accounts.set_verification(db, user.id, "verified", "Approved in demo mode", actor=user)
    return accounts.account_dict(db, user)


@router.get("/account/verification")
def my_verification(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The provider's own checks: registry lookup, ID check, court records, then Triyana's review."""
    verification.refresh(db, user)
    return verification.status(db, user)


@router.post("/account/verification/identity")
def submit_identity(body: IdentityIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return verification.submit_identity(db, user, body.model_dump())


# --------------------------------------------------------------- Triyana ops
DEMO_ADMIN_KEY = "demo-admin"


def _admin(x_admin_key: str | None = Header(default=None)) -> None:
    key = os.environ.get("TRIYANA_ADMIN_KEY", "")
    if not key and verification.demo_admin_key_allowed():
        key = DEMO_ADMIN_KEY  # demo site only, until TRIYANA_ADMIN_KEY is set
    if not key or not x_admin_key or not hmac.compare_digest(key, x_admin_key):
        raise Forbidden("forbidden", "Admin key required.")


@router.get("/admin/providers/pending", dependencies=[Depends(_admin)])
def pending(status: Literal["pending", "rejected", "verified"] = "pending", db: Session = Depends(get_db)):
    return accounts.pending_providers(db, status)


@router.post("/admin/providers/{user_id}/verification", dependencies=[Depends(_admin)])
def verify(user_id: int, body: VerifyIn, db: Session = Depends(get_db)):
    user = accounts.set_verification(db, user_id, body.status, body.note, override=body.override,
                                     require_checks=True)
    return accounts.account_dict(db, user) | {"verification": verification.status(db, user)}


@router.post("/admin/providers/{user_id}/checks/rerun", dependencies=[Depends(_admin)])
def rerun_checks(user_id: int, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user or user.role not in accounts.PROVIDER_ROLES:
        raise NotFound("not_found", "Provider not found.")
    return verification.rerun(db, user)
