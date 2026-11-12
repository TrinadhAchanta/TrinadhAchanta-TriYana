"""Provider earnings, Dasher style: pay per completed job, today/this week, balance and payouts.

Demo rules (replace with the real commission and payout contract before launch):
* Doctors earn the visit fee; "Doctor now" visits add an on-demand bonus.
* Couriers earn the delivery pay shown on the offer card.
* Earnings collect in a balance; it is paid out every Monday, or now with "Cash out".
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..adapters.geo import haversine_km
from ..errors import Conflict, Forbidden
from ..models import Doctor, Earning, HomeVisit, Patient, Payout, PharmacyOrder, Role, User, utcnow
from .common import notify

IST = timezone(timedelta(hours=5, minutes=30))
ON_DEMAND_BONUS = 100.0
MIN_CASH_OUT = 1.0


def delivery_pay(order: PharmacyOrder) -> float:
    """Same number the courier saw on the request card."""
    return round(max(order.delivery_fee, 30) * 0.8, 2)


def record_visit(db: Session, visit: HomeVisit) -> Earning | None:
    user = db.scalars(select(User).where(User.doctor_id == visit.doctor_id)).first()
    if user is None or db.scalars(select(Earning.id).where(Earning.visit_id == visit.id)).first():
        return None
    p = db.get(Patient, visit.patient_id)
    doc = db.get(Doctor, visit.doctor_id)
    base = float(visit.fee or doc.visit_fee)
    bonus = ON_DEMAND_BONUS if visit.on_demand else 0.0
    e = Earning(user_id=user.id, kind="visit", visit_id=visit.id, base=base, bonus=bonus, total=base + bonus,
                title=f"{'Doctor now' if visit.on_demand else 'Home visit'} · {p.name.split()[0]}",
                distance_km=round(haversine_km(p.lat, p.lng, doc.lat, doc.lng), 1))
    db.add(e)
    notify(db, [user], f"You earned ₹{e.total:,.0f}", f"{e.title}. Added to your balance.", "earnings")
    return e


def record_delivery(db: Session, order: PharmacyOrder, courier: User) -> Earning | None:
    if courier.role != Role.courier or db.scalars(select(Earning.id).where(Earning.order_id == order.id)).first():
        return None
    p = db.get(Patient, order.patient_id)
    pay = delivery_pay(order)
    e = Earning(user_id=courier.id, kind="delivery", order_id=order.id, base=pay, total=pay,
                title=f"Delivery · {order.pharmacy.name.replace(' (Demo)', '')} → {p.name.split()[0]}",
                distance_km=round(haversine_km(p.lat, p.lng, order.pharmacy.lat, order.pharmacy.lng), 1))
    db.add(e)
    notify(db, [courier], f"You earned ₹{e.total:,.0f}", f"{e.title}. Added to your balance.", "earnings")
    return e


PHYSIO_SHARE = 0.8  # physiotherapists keep 80% of each session's price (demo)


def physio_pay(session_fee: float) -> float:
    """Same number the physiotherapist saw on the request card."""
    return float(round(session_fee * PHYSIO_SHARE))


def record_physio(db: Session, session, user: User) -> Earning | None:
    if user.role != Role.physio or db.scalars(select(Earning.id).where(Earning.physio_session_id == session.id)).first():
        return None
    b = session.booking
    p = db.get(Patient, b.patient_id)
    base = physio_pay(b.session_fee)
    bonus = ON_DEMAND_BONUS if b.on_demand and session.number == 1 else 0.0
    e = Earning(user_id=user.id, kind="physio", physio_session_id=session.id, base=base, bonus=bonus, total=base + bonus,
                title=f"Physio session {session.number}/{b.sessions_total} · {p.name.split()[0]}",
                distance_km=round(haversine_km(p.lat, p.lng, b.physio.lat, b.physio.lng), 1))
    db.add(e)
    notify(db, [user], f"You earned ₹{e.total:,.0f}", f"{e.title}. Added to your balance.", "earnings")
    return e


# ------------------------------------------------------------------ dashboard
def _local(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc).astimezone(IST)


def _week_start(now_local: datetime) -> datetime:
    d = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return d - timedelta(days=d.weekday())


def _job(e: Earning) -> dict:
    return {"id": e.id, "kind": e.kind, "title": e.title, "base": e.base, "bonus": e.bonus, "tip": e.tip,
            "total": e.total, "distance_km": e.distance_km, "earned_at": e.earned_at.isoformat(),
            "paid_out": e.payout_id is not None}


def summary(db: Session, user: User) -> dict:
    if user.role not in (Role.doctor, Role.courier, Role.phlebotomist, Role.physio):
        raise Forbidden("forbidden_role", "Earnings are for doctors, physiotherapists, couriers and sample collectors.")
    now_l = _local(utcnow())
    week0 = _week_start(now_l)
    rows = db.scalars(select(Earning).where(Earning.user_id == user.id).order_by(Earning.earned_at.desc())).all()
    today = [e for e in rows if _local(e.earned_at).date() == now_l.date()]
    week = [e for e in rows if _local(e.earned_at) >= week0]
    days = []
    for i in range(7):
        d = (week0 + timedelta(days=i)).date()
        js = [e for e in week if _local(e.earned_at).date() == d]
        days.append({"date": d.isoformat(), "label": (week0 + timedelta(days=i)).strftime("%a"),
                     "total": round(sum(e.total for e in js), 2), "jobs": len(js), "today": d == now_l.date(),
                     "future": d > now_l.date()})
    balance = round(sum(e.total for e in rows if e.payout_id is None), 2)
    payouts = db.scalars(select(Payout).where(Payout.user_id == user.id).order_by(Payout.id.desc())).all()
    next_monday = week0 + timedelta(days=7)
    return {
        "currency": "INR",
        "today": {"total": round(sum(e.total for e in today), 2), "jobs": len(today)},
        "week": {"total": round(sum(e.total for e in week), 2), "jobs": len(week),
                 "bonus": round(sum(e.bonus + e.tip for e in week), 2), "start": week0.date().isoformat(),
                 "days": days},
        "lifetime": {"total": round(sum(e.total for e in rows), 2), "jobs": len(rows)},
        "balance": balance,
        "next_payout": {"date": next_monday.date().isoformat(), "amount": balance},
        "payout_method": f"UPI · {user.name.split()[0].lower().strip('.')}@triyana (demo)",
        "jobs": [_job(e) for e in rows[:30]],
        "payouts": [{"id": p.id, "amount": p.amount, "fee": p.fee, "kind": p.kind, "destination": p.destination,
                     "reference": p.reference, "status": p.status, "at": p.created_at.isoformat()} for p in payouts[:10]],
        "rules": ("Demo pay: you keep the visit fee, plus ₹100 for each Doctor now visit." if user.role == Role.doctor
                  else "Demo pay: you keep 80% of each session's price, plus ₹100 for an as-soon-as-possible first session."
                  if user.role == Role.physio else "Demo pay: you earn the delivery pay shown on each request."),
    }


def cash_out(db: Session, user: User) -> dict:
    if user.role not in (Role.doctor, Role.courier, Role.phlebotomist, Role.physio):
        raise Forbidden("forbidden_role", "Earnings are for doctors, physiotherapists, couriers and sample collectors.")
    unpaid = db.scalars(select(Earning).where(Earning.user_id == user.id, Earning.payout_id.is_(None))).all()
    amount = round(sum(e.total for e in unpaid), 2)
    if amount < MIN_CASH_OUT:
        raise Conflict("nothing_to_cash_out", "There's nothing to cash out yet. Complete a job first.")
    p = Payout(user_id=user.id, amount=amount, fee=0, kind="instant", status="paid",
               destination=f"UPI · {user.name.split()[0].lower().strip('.')}@triyana (demo)",
               reference=f"PO-{secrets.token_hex(4).upper()}")
    db.add(p)
    db.flush()
    for e in unpaid:
        e.payout_id = p.id
    audit.record(db, user, "earnings.cash_out", "payout", p.id, amount=amount)
    db.commit()
    return summary(db, user)


def seed_history(db: Session, users: dict) -> None:
    """A few past jobs so the demo dashboards aren't empty (fictional)."""
    now = utcnow()
    plan = {
        "doctor": [(0, 600, 0, "Home visit · Arjun"), (1, 600, 100, "Doctor now · Priya"), (2, 600, 0, "Home visit · Ravi"),
                   (3, 600, 0, "Follow-up · Meera"), (8, 600, 0, "Home visit · Kavya"), (9, 600, 100, "Doctor now · Sam")],
        "doctor_rohan": [(1, 700, 0, "Home visit · Anu"), (2, 700, 100, "Doctor now · Dev")],
        "courier": [(0, 24, 0, "Delivery · GreenLeaf → Arjun"), (0, 36, 0, "Delivery · GreenLeaf → Leela"),
                    (1, 24, 0, "Delivery · GreenLeaf → Om"), (2, 48, 0, "Delivery · GreenLeaf → Zara"),
                    (8, 30, 0, "Delivery · GreenLeaf → Ira")],
        "courier2": [(1, 24, 0, "Delivery · Sunrise → Nia"), (3, 30, 0, "Delivery · GreenLeaf → Joy")],
    }
    for key, jobs in plan.items():
        user = users.get(key)
        if user is None:
            continue
        old = []
        for days_ago, base, bonus, title in jobs:
            when = now - timedelta(days=days_ago, hours=1 + 3 * jobs.index((days_ago, base, bonus, title)), minutes=17 * len(title) % 50)
            e = Earning(user_id=user.id, kind="delivery" if key.startswith("courier") else "visit", title=title,
                        base=base, bonus=bonus, total=base + bonus, distance_km=round(1.2 + len(old) * 0.7, 1),
                        earned_at=when)
            db.add(e)
            if days_ago >= 7:
                old.append(e)
        if old:  # last week's earnings were paid out on Monday
            p = Payout(user_id=user.id, amount=sum(e.total for e in old), kind="weekly",
                       destination=f"UPI · {user.name.split()[0].lower().strip('.')}@triyana (demo)",
                       reference=f"PO-{secrets.token_hex(4).upper()}",
                       created_at=now - timedelta(days=max(1, _local(now).weekday())))
            db.add(p)
            db.flush()
            for e in old:
                e.payout_id = p.id
