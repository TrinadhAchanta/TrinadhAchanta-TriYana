"""Money and growth: offers, Triyana Family membership, insurance, referrals and partner organisations."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require
from ..models import Role, User
from ..models_perks import PromoCode  # noqa: F401  (table registration)
from ..services import perks, promos
from .auth import _admin, _admin_name

router = APIRouter()
patient_only = require(Role.patient)


class MembershipIn(BaseModel):
    payment_method: str = Field(default="upi", max_length=24)
    payment_token: str = Field(default="sandbox-ok", max_length=80)


class PolicyIn(BaseModel):
    insurer: str = Field(max_length=40)
    policy_no: str = Field(min_length=4, max_length=40)
    member_name: str = Field(default="", max_length=120)
    valid_until: str = Field(min_length=10, max_length=10)


class CodeIn(BaseModel):
    code: str = Field(min_length=3, max_length=24)


class PromoCheckIn(BaseModel):
    code: str = Field(max_length=24)
    scope: Literal["visits", "medicines"]
    amount: float = Field(ge=0, le=1000000)  # the bill the code would come off (medicine price for orders)


class PromoIn(BaseModel):
    code: str | None = Field(None, max_length=24)  # only when creating
    description: str | None = Field(None, max_length=160)
    kind: Literal["flat", "percent"] | None = None
    value: float | None = Field(None, gt=0, le=100000)
    max_discount: float | None = Field(None, ge=0, le=100000)
    min_amount: float | None = Field(None, ge=0, le=1000000)
    applies_to: Literal["all", "visits", "medicines"] | None = None
    new_customers_only: bool | None = None
    per_patient_limit: int | None = Field(None, ge=0, le=1000)
    max_uses: int | None = Field(None, ge=1, le=10000000)
    starts_on: str | None = Field(None, pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    ends_on: str | None = Field(None, pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    active: bool | None = None


class OrgIn(BaseModel):
    name: str | None = Field(None, max_length=120)
    kind: Literal["society", "office", "old_age_home"] | None = None
    join_code: str | None = Field(None, max_length=20)
    discount_pct: int | None = Field(None, ge=0, le=100)
    priority: bool | None = None
    area: str | None = Field(None, max_length=120)
    contact: str | None = Field(None, max_length=120)
    active: bool | None = None


# ------------------------------------------------------------------ patient
@router.get("/api/perks")
def my_perks(user: User = Depends(patient_only), db: Session = Depends(get_db)):
    return perks.summary(db, user)


@router.get("/api/perks/quote")
def price_quote(fee: float = Query(ge=0, le=100000), cashless: bool = False, promo: str = Query("", max_length=24),
                user: User = Depends(patient_only), db: Session = Depends(get_db)):
    return perks.quote(db, user.patient_id, fee, cashless, promo or None)


@router.post("/api/promos/check")
def check_promo(body: PromoCheckIn, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    """Payment screen: what a promo code takes off this bill, or why it can't be used."""
    return promos.preview(db, user.patient_id, body.code, body.scope, body.amount)


@router.post("/api/perks/membership", status_code=201)
def buy_membership(body: MembershipIn, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    perks.buy_membership(db, user, body.payment_method, body.payment_token)
    return perks.summary(db, user)


@router.post("/api/perks/insurance", status_code=201)
def add_policy(body: PolicyIn, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    perks.add_policy(db, user, body.insurer, body.policy_no, body.member_name, body.valid_until)
    return perks.summary(db, user)


@router.delete("/api/perks/insurance/{policy_id}")
def remove_policy(policy_id: int, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    perks.remove_policy(db, user, policy_id)
    return perks.summary(db, user)


@router.post("/api/perks/referral")
def use_referral(body: CodeIn, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    perks.redeem_referral(db, user, body.code)
    return perks.summary(db, user)


@router.post("/api/perks/org")
def join_org(body: CodeIn, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    perks.join_org(db, user, body.code)
    return perks.summary(db, user)


@router.delete("/api/perks/org")
def leave_org(user: User = Depends(patient_only), db: Session = Depends(get_db)):
    perks.leave_org(db, user)
    return perks.summary(db, user)


# ------------------------------------------------------------------ Triyana ops
@router.get("/api/admin/partners", dependencies=[Depends(_admin)])
def list_partners(db: Session = Depends(get_db)):
    return perks.list_orgs(db)


@router.post("/api/admin/partners", status_code=201, dependencies=[Depends(_admin)])
def create_partner(body: OrgIn, db: Session = Depends(get_db)):
    return perks.save_org(db, body.model_dump())


@router.post("/api/admin/partners/{org_id}", dependencies=[Depends(_admin)])
def update_partner(org_id: int, body: OrgIn, db: Session = Depends(get_db)):
    return perks.save_org(db, body.model_dump(), org_id)


@router.get("/api/admin/promos", dependencies=[Depends(_admin)])
def list_promos(db: Session = Depends(get_db)):
    return promos.list_promos(db)


@router.post("/api/admin/promos", status_code=201)
def create_promo(body: PromoIn, admin=Depends(_admin), db: Session = Depends(get_db)):
    return promos.save_promo(db, body.model_dump(exclude_unset=True), _admin_name(admin))


@router.post("/api/admin/promos/{promo_id}")
def update_promo(promo_id: int, body: PromoIn, admin=Depends(_admin), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_unset=True)
    data.pop("code", None)  # a code's text never changes: patients may already have it
    return promos.save_promo(db, data, _admin_name(admin), promo_id)
