"""Promo codes: a code the patient types at payment for money off a doctor visit or a medicine order.

Triyana Ops makes and pauses codes at /admin. How they sit with the other offers:

* Doctor visits: one offer per visit. A code competes with the automatic offer (₹99 first visit or a
  partner discount) and the patient gets whichever saves more. Not used when Triyana Family or cashless
  insurance already covers the visit. Triyana credit is used after the code.
* Medicines (prescription orders and the shop): money off the medicine price, before tax and delivery.

Like every other discount, a code is Triyana's cost: doctors and pharmacies are paid in full. A code's use
is given back when the visit or order is cancelled, rejected, or made free because the doctor was late.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import Conflict, NotFound, Unprocessable
from ..models import HomeVisit, PharmacyOrder, VisitStatus
from ..models_perks import PromoCode, PromoRedemption

IST = timezone(timedelta(hours=5, minutes=30))
SCOPES = {"all": "Doctor visits and medicines", "visits": "Doctor visits", "medicines": "Medicines"}
KINDS = {"flat": "₹ off", "percent": "% off"}


def _r(x: float) -> float:
    return round(float(x) + 1e-9, 2)


def normalize(code: str | None) -> str:
    return re.sub(r"\s", "", code or "").upper()


def _today() -> str:
    return datetime.now(IST).date().isoformat()


def _money(x: float) -> str:
    return f"₹{x:,.0f}" if float(x).is_integer() else f"₹{x:,.2f}"


def headline(p: PromoCode) -> str:
    """'₹100 off' or '20% off (up to ₹150)'."""
    if p.kind == "percent":
        return f"{p.value:g}% off" + (f" (up to {_money(p.max_discount)})" if p.max_discount else "")
    return f"{_money(p.value)} off"


def discount_for(p: PromoCode, amount: float) -> float:
    amount = max(0.0, float(amount or 0))
    off = amount * p.value / 100 if p.kind == "percent" else p.value
    if p.kind == "percent" and p.max_discount:
        off = min(off, p.max_discount)
    return _r(max(0.0, min(off, amount)))


def _uses(db: Session, promo_id: int, patient_id: int | None = None) -> int:
    q = select(func.count(PromoRedemption.id)).where(PromoRedemption.promo_id == promo_id,
                                                     PromoRedemption.status == "used")
    if patient_id is not None:
        q = q.where(PromoRedemption.patient_id == patient_id)
    return db.scalar(q) or 0


def _is_new_customer(db: Session, patient_id: int) -> bool:
    visits = db.scalar(select(func.count(HomeVisit.id)).where(HomeVisit.patient_id == patient_id,
                                                              HomeVisit.status != VisitStatus.cancelled)) or 0
    if visits:
        return False
    orders = db.scalars(select(PharmacyOrder).where(PharmacyOrder.patient_id == patient_id)).all()
    return not any(o.status.value not in ("cancelled", "rejected") for o in orders)


def check(db: Session, patient_id: int, code: str, scope: str, amount: float, *,
          new_customer: bool | None = None) -> tuple[PromoCode, float]:
    """The promo and the money it takes off `amount`, or a friendly Unprocessable saying why not.

    `scope` is "visits" or "medicines". `new_customer` lets the caller say whether the patient counts as
    new (a visit being billed has already been saved, so it would otherwise count itself).
    """
    code = normalize(code)
    p = db.scalars(select(PromoCode).where(PromoCode.code == code)).first() if code else None
    if p is None:
        raise Unprocessable("promo_not_found", "That promo code doesn't exist. Check the spelling and try again.")
    today = _today()
    if not p.active or (p.ends_on and today > p.ends_on):
        raise Unprocessable("promo_expired", f"{p.code} has expired.")
    if p.starts_on and today < p.starts_on:
        raise Unprocessable("promo_not_started", f"{p.code} starts on {p.starts_on}.")
    if p.applies_to not in ("all", scope):
        where = "doctor visits" if p.applies_to == "visits" else "medicines"
        raise Unprocessable("promo_wrong_use", f"{p.code} is only for {where}.")
    if p.min_amount and amount < p.min_amount:
        raise Unprocessable("promo_min_amount", f"{p.code} works on bills of {_money(p.min_amount)} or more.")
    if p.max_uses is not None and _uses(db, p.id) >= p.max_uses:
        raise Unprocessable("promo_used_up", f"{p.code} has been fully used. Look out for the next offer.")
    if p.per_patient_limit and _uses(db, p.id, patient_id) >= p.per_patient_limit:
        raise Unprocessable("promo_already_used", "You've already used this code."
                            if p.per_patient_limit == 1 else f"You've used {p.code} the most times allowed.")
    if p.new_customers_only:
        is_new = _is_new_customer(db, patient_id) if new_customer is None else new_customer
        if not is_new:
            raise Unprocessable("promo_new_only", f"{p.code} is for your first Triyana visit or order.")
    off = discount_for(p, amount)
    if off <= 0:
        raise Unprocessable("promo_nothing_off", "There's nothing left to take off this bill.")
    return p, off


def preview(db: Session, patient_id: int, code: str, scope: str, amount: float) -> dict:
    """For the payment screen: what the code takes off, or why it can't be used. Never raises."""
    try:
        p, off = check(db, patient_id, code, scope, amount)
    except Unprocessable as e:
        return {"ok": False, "code": normalize(code), "discount": 0, "message": e.message, "reason": e.code}
    return {"ok": True, "code": p.code, "discount": off, "label": label(p), "message": f"{label(p)} applied"}


def label(p: PromoCode) -> str:
    return f"Promo {p.code}: {headline(p)}"


def redeem(db: Session, p: PromoCode, patient_id: int, ref_kind: str, ref_id: int, amount: float) -> PromoRedemption:
    r = PromoRedemption(promo_id=p.id, patient_id=patient_id, ref_kind=ref_kind, ref_id=ref_id, amount=_r(amount))
    db.add(r)
    db.flush()
    audit.record(db, None, "promo.used", ref_kind, ref_id, code=p.code, amount=_r(amount))
    return r


def redemption_for(db: Session, ref_kind: str, ref_id: int) -> PromoRedemption | None:
    return db.scalars(select(PromoRedemption).where(PromoRedemption.ref_kind == ref_kind,
                                                    PromoRedemption.ref_id == ref_id,
                                                    PromoRedemption.status == "used")).first()


def release(db: Session, ref_kind: str, ref_id: int) -> None:
    """Give the code's use back (visit or order cancelled, rejected or made free)."""
    r = redemption_for(db, ref_kind, ref_id)
    if r:
        r.status = "released"


def readjust_order(db: Session, order: PharmacyOrder) -> None:
    """The pharmacist approved less than was ordered: a % code shrinks with the bill, and no code exceeds it."""
    if not order.discount:
        return
    r = redemption_for(db, "order", order.id)
    off = order.discount
    if r and r.promo.kind == "percent":
        off = min(off, discount_for(r.promo, order.subtotal))
    off = _r(min(off, order.subtotal))
    order.discount = off
    if r:
        r.amount = off


# ------------------------------------------------------------------ Triyana Ops
def promo_dict(db: Session, p: PromoCode) -> dict:
    today = _today()
    status = ("paused" if not p.active else "expired" if p.ends_on and today > p.ends_on
              else "scheduled" if p.starts_on and today < p.starts_on
              else "used_up" if p.max_uses is not None and _uses(db, p.id) >= p.max_uses else "live")
    saved = db.scalar(select(func.coalesce(func.sum(PromoRedemption.amount), 0))
                      .where(PromoRedemption.promo_id == p.id, PromoRedemption.status == "used")) or 0
    return {"id": p.id, "code": p.code, "description": p.description, "kind": p.kind, "value": p.value,
            "max_discount": p.max_discount, "min_amount": p.min_amount, "applies_to": p.applies_to,
            "applies_to_label": SCOPES.get(p.applies_to, p.applies_to), "headline": headline(p),
            "new_customers_only": p.new_customers_only, "per_patient_limit": p.per_patient_limit,
            "max_uses": p.max_uses, "starts_on": p.starts_on, "ends_on": p.ends_on, "active": p.active,
            "status": status, "uses": _uses(db, p.id), "total_discount": _r(saved), "created_by": p.created_by,
            "created_at": p.created_at.isoformat() if p.created_at else None}


def list_promos(db: Session) -> list[dict]:
    return [promo_dict(db, p) for p in db.scalars(select(PromoCode).order_by(PromoCode.id.desc()))]


_FIELDS = ("description", "kind", "value", "max_discount", "min_amount", "applies_to", "new_customers_only",
           "per_patient_limit", "max_uses", "starts_on", "ends_on", "active")


def save_promo(db: Session, data: dict, admin_name: str, promo_id: int | None = None) -> dict:
    if promo_id is None:
        code = normalize(data.get("code"))
        if not re.fullmatch(r"[A-Z0-9]{3,24}", code):
            raise Unprocessable("bad_code", "Use 3 to 24 letters and numbers for the code, e.g. SAVE100.")
        if db.scalars(select(PromoCode).where(PromoCode.code == code)).first():
            raise Conflict("code_taken", f"{code} already exists. Pick another code or edit that one.")
        p = PromoCode(code=code, created_by=admin_name, description="", kind="flat", value=0, min_amount=0,
                      applies_to="all", new_customers_only=False, per_patient_limit=1, active=True)
        db.add(p)
    else:
        p = db.get(PromoCode, promo_id)
        if p is None:
            raise NotFound("not_found", "Promo code not found.")
    for k in _FIELDS:
        if k in data and (data[k] is not None or k in ("max_discount", "max_uses", "starts_on", "ends_on")):
            setattr(p, k, data[k] if data[k] != "" else None)
    if p.kind not in KINDS:
        raise Unprocessable("bad_kind", "Choose ₹ off or % off.")
    if p.applies_to not in SCOPES:
        raise Unprocessable("bad_scope", "Choose doctor visits, medicines, or both.")
    if not p.value or p.value <= 0 or (p.kind == "percent" and p.value > 100):
        raise Unprocessable("bad_value", "Give a discount above 0 (and at most 100%).")
    if p.starts_on and p.ends_on and p.ends_on < p.starts_on:
        raise Unprocessable("bad_dates", "The end date is before the start date.")
    p.per_patient_limit = p.per_patient_limit or 0
    p.min_amount = p.min_amount or 0
    db.flush()
    audit.record(db, None, "promo.save", "promo_code", p.id, code=p.code, by=admin_name,
                 active=p.active, created=promo_id is None)
    db.commit()
    return promo_dict(db, p)


def seed_promos(db: Session) -> None:
    for code, desc, kind, value, cap, min_amt, scope in [
        ("DOC100", "₹100 off a doctor visit", "flat", 100, None, 500, "visits"),
        ("MEDS20", "20% off medicines, up to ₹150", "percent", 20, 150, 200, "medicines"),
        ("TRIYANA50", "₹50 off anything", "flat", 50, None, 0, "all"),
    ]:
        db.add(PromoCode(code=code, description=desc, kind=kind, value=value, max_discount=cap, min_amount=min_amt,
                         applies_to=scope, per_patient_limit=1, created_by="demo"))
    db.flush()
