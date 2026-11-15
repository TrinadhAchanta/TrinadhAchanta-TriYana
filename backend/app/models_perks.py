"""Money and growth: visit bills, ₹99 first visit, family membership, insurance, referrals, partner organisations.

Kept in their own tables so the core visit model stays unchanged: every home visit gets one VisitBill that
says what the patient pays and who covers the rest (Triyana, a membership, an insurer or a late-arrival refund).
The doctor is always paid their full fee; discounts are Triyana's cost.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .models import utcnow
from .security import EncryptedText


class VisitBill(Base):
    """What one home visit costs the patient, line by line."""
    __tablename__ = "visit_bills"
    id: Mapped[int] = mapped_column(primary_key=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("home_visits.id"), unique=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    base_fee: Mapped[float] = mapped_column(Float, default=0)          # the doctor's fee (what the doctor earns)
    lines: Mapped[list] = mapped_column(JSON, default=list)            # [{code, label, amount}] negative = discount
    patient_pays: Mapped[float] = mapped_column(Float, default=0)
    insurer_pays: Mapped[float] = mapped_column(Float, default=0)
    credit_used: Mapped[float] = mapped_column(Float, default=0)
    policy_id: Mapped[int | None] = mapped_column(ForeignKey("insurance_policies.id"))
    claim_ref: Mapped[str | None] = mapped_column(String(40))
    claim_status: Mapped[str | None] = mapped_column(String(20))       # submitted|approved|withdrawn|rejected
    # "Promise kept" guarantee: None until the doctor arrives on a 10-minute visit, then kept|late.
    promise_result: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    policy = relationship("InsurancePolicy")


class Membership(Base):
    """Triyana Family: one yearly fee, visit fees covered for everyone booked from this account."""
    __tablename__ = "memberships"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    plan: Mapped[str] = mapped_column(String(24), default="family_yearly")
    price: Mapped[float] = mapped_column(Float, default=0)
    starts_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), default="active")   # active|cancelled
    payment_ref: Mapped[str] = mapped_column(String(64), default="")
    payment_method: Mapped[str] = mapped_column(String(24), default="upi")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class InsurancePolicy(Base):
    __tablename__ = "insurance_policies"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    insurer: Mapped[str] = mapped_column(String(40))                    # insurer code from adapters/insurance.py
    policy_no: Mapped[str] = mapped_column(EncryptedText)
    member_name: Mapped[str] = mapped_column(String(120), default="")
    valid_until: Mapped[str] = mapped_column(String(10), default="")    # YYYY-MM-DD
    status: Mapped[str] = mapped_column(String(16), default="pending")  # active|rejected|removed
    status_note: Mapped[str] = mapped_column(String(200), default="")
    verified_ref: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CreditEntry(Base):
    """Triyana credit (referral rewards, refunds). Balance = sum of amounts; spent automatically on visits."""
    __tablename__ = "credit_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    amount: Mapped[float] = mapped_column(Float)
    kind: Mapped[str] = mapped_column(String(24))      # referral|referral_welcome|spent|refund
    note: Mapped[str] = mapped_column(String(200), default="")
    visit_id: Mapped[int | None] = mapped_column(ForeignKey("home_visits.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ReferralCode(Base):
    __tablename__ = "referral_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), unique=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)


class Referral(Base):
    """A friend joined with someone's code. Both get the reward when the friend's first visit is done."""
    __tablename__ = "referrals"
    id: Mapped[int] = mapped_column(primary_key=True)
    referrer_patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    referred_patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|rewarded
    reward: Mapped[float] = mapped_column(Float, default=0)
    rewarded_visit_id: Mapped[int | None] = mapped_column(ForeignKey("home_visits.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    rewarded_at: Mapped[datetime | None] = mapped_column(DateTime)


class PartnerOrg(Base):
    """A housing society, office or old-age home Triyana has a tie-up with."""
    __tablename__ = "partner_orgs"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20))           # society|office|old_age_home
    join_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    discount_pct: Mapped[int] = mapped_column(Integer, default=10)
    priority: Mapped[bool] = mapped_column(Boolean, default=True)
    area: Mapped[str] = mapped_column(String(120), default="")
    contact: Mapped[str] = mapped_column(String(120), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OrgMember(Base):
    __tablename__ = "org_members"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), unique=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("partner_orgs.id"), index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    org = relationship("PartnerOrg")


class PromoCode(Base):
    """A code a patient types at payment for money off (made and paused by Triyana Ops at /admin)."""
    __tablename__ = "promo_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    description: Mapped[str] = mapped_column(String(160), default="")
    kind: Mapped[str] = mapped_column(String(10), default="flat")         # flat (₹ off) | percent
    value: Mapped[float] = mapped_column(Float, default=0)                # ₹ for flat, % for percent
    max_discount: Mapped[float | None] = mapped_column(Float)             # cap for percent codes
    min_amount: Mapped[float] = mapped_column(Float, default=0)           # smallest bill the code works on
    applies_to: Mapped[str] = mapped_column(String(12), default="all")    # all | visits | medicines
    new_customers_only: Mapped[bool] = mapped_column(Boolean, default=False)
    per_patient_limit: Mapped[int] = mapped_column(Integer, default=1)    # 0 = no limit
    max_uses: Mapped[int | None] = mapped_column(Integer)                 # all patients together; None = no limit
    starts_on: Mapped[str | None] = mapped_column(String(10))             # YYYY-MM-DD (India time), inclusive
    ends_on: Mapped[str | None] = mapped_column(String(10))               # YYYY-MM-DD (India time), inclusive
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String(254), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PromoRedemption(Base):
    """One use of a promo code on a home visit or a medicine order. Released (given back) if that is cancelled."""
    __tablename__ = "promo_redemptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    promo_id: Mapped[int] = mapped_column(ForeignKey("promo_codes.id"), index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    ref_kind: Mapped[str] = mapped_column(String(10))                     # visit | order
    ref_id: Mapped[int] = mapped_column(Integer, index=True)
    amount: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(10), default="used")       # used | released
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    promo = relationship("PromoCode")
