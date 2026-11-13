"""Money and growth: what a home visit costs the patient, and the offers that bring patients back.

* ₹99 first visit for new patients.
* Triyana Family membership: one yearly fee, visit fees covered.
* Cashless visits billed to the patient's health insurer (sandbox adapter).
* Refer a friend: ₹200 Triyana credit each once the friend's first visit is done.
* Partner organisations (housing societies, offices, old-age homes): member discount and priority.
* "Promise kept" guarantee: a 10-minute visit is free if the doctor arrives late.

The doctor always earns their full fee. Every discount here is Triyana's cost, never the doctor's.
"""
from __future__ import annotations

import os
import re
import secrets
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, object_session

from .. import audit
from ..adapters.insurance import INSURERS
from ..adapters.insurance import adapter as insurer_api
from ..adapters.payments import SandboxPaymentGateway
from ..errors import Conflict, NotFound, Unprocessable
from ..models import HomeVisit, Patient, User, VisitStatus, utcnow
from ..models_perks import (CreditEntry, InsurancePolicy, Membership, OrgMember, PartnerOrg, Referral,
                            ReferralCode, VisitBill)
from .common import notify, users_for_patient


def _num(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


FIRST_VISIT_PRICE = _num("TRIYANA_FIRST_VISIT_PRICE", 99)
MEMBERSHIP_PRICE = _num("TRIYANA_MEMBERSHIP_PRICE", 4999)
MEMBERSHIP_DAYS = 365
REFERRAL_REWARD = _num("TRIYANA_REFERRAL_REWARD", 200)
ORG_KINDS = {"society": "Housing society", "office": "Office", "old_age_home": "Old-age home"}
_gateway = SandboxPaymentGateway()
_CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _r(x: float) -> float:
    return round(float(x) + 1e-9, 2)


# ------------------------------------------------------------------ lookups
def active_membership(db: Session, patient_id: int) -> Membership | None:
    now = utcnow()
    return db.scalars(select(Membership).where(Membership.patient_id == patient_id, Membership.status == "active",
                                               Membership.starts_at <= now, Membership.ends_at > now)
                      .order_by(Membership.ends_at.desc())).first()


def org_for(db: Session, patient_id: int) -> PartnerOrg | None:
    m = db.scalars(select(OrgMember).where(OrgMember.patient_id == patient_id)).first()
    return m.org if m and m.org.active else None


def is_priority(db: Session, patient_id: int) -> bool:
    org = org_for(db, patient_id)
    return bool(org and org.priority)


def credit_balance(db: Session, patient_id: int) -> float:
    return _r(db.scalar(select(func.coalesce(func.sum(CreditEntry.amount), 0))
                        .where(CreditEntry.patient_id == patient_id)) or 0)


def active_policy(db: Session, patient_id: int) -> InsurancePolicy | None:
    today = date.today().isoformat()
    return db.scalars(select(InsurancePolicy).where(InsurancePolicy.patient_id == patient_id,
                                                    InsurancePolicy.status == "active",
                                                    InsurancePolicy.valid_until >= today)
                      .order_by(InsurancePolicy.id.desc())).first()


def is_new_patient(db: Session, patient_id: int, exclude_visit_id: int | None = None) -> bool:
    """No earlier home visit (other than cancelled ones)."""
    q = select(func.count(HomeVisit.id)).where(HomeVisit.patient_id == patient_id,
                                               HomeVisit.status != VisitStatus.cancelled)
    if exclude_visit_id is not None:
        q = q.where(HomeVisit.id != exclude_visit_id)
    return (db.scalar(q) or 0) == 0


# ------------------------------------------------------------------ pricing
def _price(db: Session, patient_id: int, fee: float, *, cashless: bool, exclude_visit_id: int | None = None) -> dict:
    """Price lines before credit. Best single offer wins: membership, then first visit, then partner discount."""
    fee = _r(fee or 0)
    lines = [{"code": "fee", "label": "Doctor's visit fee", "amount": fee}]
    due = fee
    m = active_membership(db, patient_id)
    org = org_for(db, patient_id)
    if m:
        lines.append({"code": "membership", "label": "Covered by Triyana Family", "amount": -due})
        due = 0.0
    elif is_new_patient(db, patient_id, exclude_visit_id) and fee > FIRST_VISIT_PRICE:
        off = _r(fee - FIRST_VISIT_PRICE)
        lines.append({"code": "first_visit", "label": f"First visit offer: just ₹{FIRST_VISIT_PRICE:g}", "amount": -off})
        due = FIRST_VISIT_PRICE
    elif org and org.discount_pct:
        off = _r(fee * org.discount_pct / 100)
        lines.append({"code": "partner", "label": f"{org.name} member: {org.discount_pct}% off", "amount": -off})
        due = _r(fee - off)
    policy = active_policy(db, patient_id) if cashless and due > 0 else None
    if cashless and due > 0 and policy is None:
        raise Unprocessable("no_policy", "Add an active health insurance policy to use cashless.")
    insurer = 0.0
    if policy:
        insurer = due
        lines.append({"code": "insurance", "label": f"Cashless: billed to {INSURERS.get(policy.insurer, policy.insurer)}",
                      "amount": -due})
        due = 0.0
    return {"lines": lines, "due": _r(due), "insurer": _r(insurer), "policy": policy}


def quote(db: Session, patient_id: int, fee: float, cashless: bool = False) -> dict:
    """What the patient would pay for a visit at this fee, including Triyana credit."""
    try:
        p = _price(db, patient_id, fee, cashless=cashless)
    except Unprocessable as e:
        return {"error": e.message, "patient_pays": None, "lines": []}
    credit = min(credit_balance(db, patient_id), p["due"])
    lines = list(p["lines"])
    if credit > 0:
        lines.append({"code": "credit", "label": "Triyana credit", "amount": -credit})
    return {"lines": lines, "patient_pays": _r(p["due"] - credit), "insurer_pays": p["insurer"],
            "base_fee": _r(fee or 0)}


def bill_visit(db: Session, visit: HomeVisit, cashless: bool = False) -> VisitBill:
    """Price a freshly created visit. Call after the visit is flushed and before commit."""
    p = _price(db, visit.patient_id, visit.fee or 0, cashless=cashless, exclude_visit_id=visit.id)
    bill = VisitBill(visit_id=visit.id, patient_id=visit.patient_id, base_fee=_r(visit.fee or 0),
                     lines=p["lines"], patient_pays=p["due"], insurer_pays=p["insurer"])
    if p["policy"]:
        res = insurer_api.submit_claim(p["policy"].insurer, p["policy"].policy_no, p["insurer"])
        if not res.ok:
            raise Conflict("cashless_declined", f"{res.message} You can still book and pay after the visit.")
        bill.policy_id, bill.claim_ref, bill.claim_status = p["policy"].id, res.ref, "approved"
    credit = min(credit_balance(db, visit.patient_id), bill.patient_pays)
    if credit > 0:
        db.add(CreditEntry(patient_id=visit.patient_id, amount=-credit, kind="spent", visit_id=visit.id,
                           note=f"Used on visit {visit.booking_ref}"))
        bill.credit_used = credit
        bill.lines = bill.lines + [{"code": "credit", "label": "Triyana credit", "amount": -credit}]
        bill.patient_pays = _r(bill.patient_pays - credit)
    db.add(bill)
    db.flush()
    return bill


def _bill(db: Session, visit_id: int) -> VisitBill | None:
    return db.scalars(select(VisitBill).where(VisitBill.visit_id == visit_id)).first()


def _release(db: Session, bill: VisitBill, visit: HomeVisit, why: str) -> None:
    """Give back credit and withdraw an insurance claim (cancelled or free visit)."""
    if bill.credit_used:
        db.add(CreditEntry(patient_id=bill.patient_id, amount=bill.credit_used, kind="refund", visit_id=visit.id,
                           note=f"Returned: {why} ({visit.booking_ref})"))
        bill.credit_used = 0
    if bill.claim_ref and bill.claim_status in ("submitted", "approved"):
        insurer_api.withdraw_claim(bill.claim_ref)
        bill.claim_status = "withdrawn"
    bill.insurer_pays = 0


def on_cancel(db: Session, visit: HomeVisit) -> None:
    bill = _bill(db, visit.id)
    if bill:
        _release(db, bill, visit, "visit cancelled")


def on_arrival(db: Session, visit: HomeVisit, arrived_at) -> None:
    """"Promise kept" guarantee: if a 10-minute visit arrives late, the visit is free, automatically."""
    if not (visit.on_demand and visit.promise_min):
        return
    bill = _bill(db, visit.id)
    if bill is None or bill.promise_result:
        return
    took = (arrived_at - visit.created_at).total_seconds()
    if took <= visit.promise_min * 60:
        bill.promise_result = "kept"
        return
    bill.promise_result = "late"
    _release(db, bill, visit, "doctor arrived late")
    owed = _r(sum(line["amount"] for line in bill.lines if line["code"] not in ("credit", "insurance")))
    kept = [line for line in bill.lines if line["code"] not in ("credit", "insurance")]
    bill.lines = kept + ([{"code": "promise", "label": f"Late by {max(1, round(took / 60 - visit.promise_min))} min: "
                           f"this visit is free", "amount": -owed}] if owed > 0 else [])
    bill.patient_pays = 0
    notify(db, users_for_patient(db, visit.patient_id), "Sorry we were late. This visit is free",
           f"We promised a doctor within {visit.promise_min} minutes and took {round(took / 60)}. "
           "You won't be charged for this visit.", f"visit:{visit.id}")
    audit.record(db, None, "visit.promise_late", "home_visit", visit.id, took_s=round(took))


def on_complete(db: Session, visit: HomeVisit) -> None:
    """Referral reward once the referred friend's first visit is done."""
    ref = db.scalars(select(Referral).where(Referral.referred_patient_id == visit.patient_id,
                                            Referral.status == "pending")).first()
    if ref is None:
        return
    ref.status, ref.reward, ref.rewarded_visit_id, ref.rewarded_at = "rewarded", REFERRAL_REWARD, visit.id, utcnow()
    friend, referrer = db.get(Patient, ref.referred_patient_id), db.get(Patient, ref.referrer_patient_id)
    db.add(CreditEntry(patient_id=referrer.id, amount=REFERRAL_REWARD, kind="referral",
                       note=f"{friend.name} had their first Triyana visit"))
    db.add(CreditEntry(patient_id=friend.id, amount=REFERRAL_REWARD, kind="referral_welcome",
                       note=f"Welcome reward, invited by {referrer.name}"))
    notify(db, users_for_patient(db, referrer.id), f"You earned ₹{REFERRAL_REWARD:g}",
           f"{friend.name} had their first visit with your code. ₹{REFERRAL_REWARD:g} credit is in your account.", "perks")
    notify(db, users_for_patient(db, friend.id), f"₹{REFERRAL_REWARD:g} credit added",
           f"Thanks for joining through {referrer.name}. Your credit is used on your next visit.", "perks")


def bill_dict(visit: HomeVisit) -> dict:
    db = object_session(visit)
    bill = _bill(db, visit.id) if db else None
    if bill is None:  # visits made before bills existed
        fee = _r(visit.fee or 0)
        return {"base_fee": fee, "patient_pays": fee, "insurer_pays": 0, "cashless": False,
                "lines": [{"code": "fee", "label": "Doctor's visit fee", "amount": fee}],
                "promise": None, "claim": None}
    return {"base_fee": bill.base_fee, "patient_pays": bill.patient_pays, "insurer_pays": bill.insurer_pays,
            "cashless": bool(bill.claim_ref and bill.claim_status == "approved"),
            "lines": bill.lines, "promise": bill.promise_result,
            "claim": {"ref": bill.claim_ref, "status": bill.claim_status,
                      "insurer": INSURERS.get(bill.policy.insurer, bill.policy.insurer) if bill.policy else None}
            if bill.claim_ref else None}


# ------------------------------------------------------------------ membership
def buy_membership(db: Session, user: User, method: str, token: str) -> Membership:
    if active_membership(db, user.patient_id):
        raise Conflict("already_member", "You already have Triyana Family.")
    res = _gateway.authorize(method, MEMBERSHIP_PRICE, token)
    if not res.ok:
        raise Conflict("payment_failed", res.message)
    _gateway.capture(res.ref, MEMBERSHIP_PRICE)
    now = utcnow()
    m = Membership(patient_id=user.patient_id, price=MEMBERSHIP_PRICE, starts_at=now,
                   ends_at=now + timedelta(days=MEMBERSHIP_DAYS), payment_ref=res.ref, payment_method=method)
    db.add(m)
    db.flush()
    notify(db, [user], "Welcome to Triyana Family",
           "Doctor visits for everyone you book for are now covered for a year.", "perks")
    audit.record(db, user, "membership.buy", "membership", m.id, price=MEMBERSHIP_PRICE)
    db.commit()
    return m


# ------------------------------------------------------------------ insurance
def add_policy(db: Session, user: User, insurer: str, policy_no: str, member_name: str, valid_until: str) -> InsurancePolicy:
    policy_no = policy_no.strip()
    res = insurer_api.verify_policy(insurer, policy_no, valid_until)
    for old in db.scalars(select(InsurancePolicy).where(InsurancePolicy.patient_id == user.patient_id,
                                                        InsurancePolicy.status == "active")):
        old.status = "removed"
    p = InsurancePolicy(patient_id=user.patient_id, insurer=insurer if insurer in INSURERS else "other",
                        policy_no=policy_no, member_name=member_name.strip(), valid_until=valid_until,
                        status="active" if res.ok else "rejected", status_note=res.message, verified_ref=res.ref)
    db.add(p)
    db.flush()
    audit.record(db, user, "insurance.add", "insurance_policy", p.id, insurer=insurer, ok=res.ok)
    db.commit()
    if not res.ok:
        raise Unprocessable("policy_rejected", res.message)
    return p


def remove_policy(db: Session, user: User, policy_id: int) -> None:
    p = db.get(InsurancePolicy, policy_id)
    if p is None or p.patient_id != user.patient_id:
        raise NotFound("not_found", "Policy not found.")
    p.status = "removed"
    audit.record(db, user, "insurance.remove", "insurance_policy", p.id)
    db.commit()


def _policy_dict(p: InsurancePolicy) -> dict:
    no = p.policy_no or ""
    return {"id": p.id, "insurer": p.insurer, "insurer_name": INSURERS.get(p.insurer, p.insurer),
            "policy_no": ("•" * max(0, len(no) - 4)) + no[-4:], "member_name": p.member_name,
            "valid_until": p.valid_until, "status": p.status}


# ------------------------------------------------------------------ referrals
def referral_code(db: Session, patient_id: int) -> str:
    row = db.scalars(select(ReferralCode).where(ReferralCode.patient_id == patient_id)).first()
    if row:
        return row.code
    while True:
        code = "TRI" + "".join(secrets.choice(_CODE_CHARS) for _ in range(5))
        if not db.scalars(select(ReferralCode).where(ReferralCode.code == code)).first():
            break
    db.add(ReferralCode(patient_id=patient_id, code=code))
    db.flush()
    return code


def redeem_referral(db: Session, user: User, code: str) -> Referral:
    code = re.sub(r"\s", "", code or "").upper()
    row = db.scalars(select(ReferralCode).where(ReferralCode.code == code)).first()
    if row is None:
        raise NotFound("bad_code", "That referral code doesn't exist. Check it and try again.")
    if row.patient_id == user.patient_id:
        raise Unprocessable("own_code", "You can't use your own code. Share it with a friend instead.")
    if db.scalars(select(Referral).where(Referral.referred_patient_id == user.patient_id)).first():
        raise Conflict("already_referred", "You've already used a referral code.")
    if not is_new_patient(db, user.patient_id):
        raise Conflict("not_new", "Referral codes are for people who haven't had a Triyana visit yet.")
    ref = Referral(referrer_patient_id=row.patient_id, referred_patient_id=user.patient_id)
    db.add(ref)
    db.flush()
    audit.record(db, user, "referral.redeem", "referral", ref.id)
    db.commit()
    return ref


# ------------------------------------------------------------------ partner organisations
def join_org(db: Session, user: User, code: str) -> PartnerOrg:
    code = re.sub(r"\s", "", code or "").upper()
    org = db.scalars(select(PartnerOrg).where(PartnerOrg.join_code == code, PartnerOrg.active.is_(True))).first()
    if org is None:
        raise NotFound("bad_code", "We couldn't find a partner with that code. Ask your society, office or home for it.")
    m = db.scalars(select(OrgMember).where(OrgMember.patient_id == user.patient_id)).first()
    if m is None:
        db.add(OrgMember(patient_id=user.patient_id, org_id=org.id))
    else:
        m.org_id, m.joined_at = org.id, utcnow()
    audit.record(db, user, "org.join", "partner_org", org.id)
    db.commit()
    return org


def leave_org(db: Session, user: User) -> None:
    m = db.scalars(select(OrgMember).where(OrgMember.patient_id == user.patient_id)).first()
    if m:
        db.delete(m)
        audit.record(db, user, "org.leave", "partner_org", m.org_id)
        db.commit()


def org_dict(db: Session, org: PartnerOrg, with_count: bool = False) -> dict:
    d = {"id": org.id, "name": org.name, "kind": org.kind, "kind_label": ORG_KINDS.get(org.kind, org.kind),
         "join_code": org.join_code, "discount_pct": org.discount_pct, "priority": org.priority, "area": org.area,
         "contact": org.contact, "active": org.active}
    if with_count:
        d["members"] = db.scalar(select(func.count(OrgMember.id)).where(OrgMember.org_id == org.id)) or 0
    return d


def list_orgs(db: Session) -> list[dict]:
    return [org_dict(db, o, True) for o in db.scalars(select(PartnerOrg).order_by(PartnerOrg.id))]


def save_org(db: Session, data: dict, org_id: int | None = None) -> dict:
    if data.get("kind") and data["kind"] not in ORG_KINDS:
        raise Unprocessable("bad_kind", "Choose housing society, office or old-age home.")
    code = re.sub(r"\s", "", data.get("join_code") or "").upper()
    if org_id is None:
        org = PartnerOrg(name="", kind="society", join_code="")
        db.add(org)
        if not code:
            code = re.sub(r"[^A-Z]", "", (data.get("name") or "").upper())[:6] + str(secrets.randbelow(90) + 10)
    else:
        org = db.get(PartnerOrg, org_id)
        if org is None:
            raise NotFound("not_found", "Partner not found.")
    if code:
        clash = db.scalars(select(PartnerOrg).where(PartnerOrg.join_code == code)).first()
        if clash and clash is not org:
            raise Conflict("code_taken", "Another partner already uses that join code.")
        org.join_code = code
    for k in ("name", "kind", "discount_pct", "priority", "area", "contact", "active"):
        if data.get(k) is not None:
            setattr(org, k, data[k])
    if not org.name:
        raise Unprocessable("bad_name", "Give the partner a name.")
    db.flush()
    audit.record(db, None, "org.save", "partner_org", org.id, name=org.name)
    db.commit()
    return org_dict(db, org, True)


# ------------------------------------------------------------------ patient summary
def summary(db: Session, user: User) -> dict:
    pid = user.patient_id
    m = active_membership(db, pid)
    org = org_for(db, pid)
    code = referral_code(db, pid)
    referred_by = db.scalars(select(Referral).where(Referral.referred_patient_id == pid)).first()
    friends = db.scalars(select(Referral).where(Referral.referrer_patient_id == pid).order_by(Referral.id.desc())).all()
    history = db.scalars(select(CreditEntry).where(CreditEntry.patient_id == pid)
                         .order_by(CreditEntry.id.desc()).limit(20)).all()
    policies = db.scalars(select(InsurancePolicy).where(InsurancePolicy.patient_id == pid,
                                                        InsurancePolicy.status == "active")).all()
    new = is_new_patient(db, pid)
    db.commit()  # keeps a newly made referral code
    from .dispatch import PROMISE_MIN
    return {
        "first_visit": {"eligible": new and not m, "price": FIRST_VISIT_PRICE},
        "membership": {"active": bool(m), "price": MEMBERSHIP_PRICE, "days": MEMBERSHIP_DAYS,
                       "ends_at": m.ends_at.isoformat() if m else None, "since": m.starts_at.isoformat() if m else None},
        "credit": {"balance": credit_balance(db, pid),
                   "history": [{"amount": e.amount, "kind": e.kind, "note": e.note, "at": e.created_at.isoformat()}
                               for e in history]},
        "referral": {"code": code, "reward": REFERRAL_REWARD, "can_redeem": new and referred_by is None,
                     "referred_by": db.get(Patient, referred_by.referrer_patient_id).name if referred_by else None,
                     "referred_status": referred_by.status if referred_by else None,
                     "friends": [{"name": db.get(Patient, f.referred_patient_id).name.split(" ")[0], "status": f.status}
                                 for f in friends]},
        "insurance": {"policies": [_policy_dict(p) for p in policies],
                      "insurers": [{"code": k, "name": v} for k, v in INSURERS.items()]},
        "org": org_dict(db, org) if org else None,
        "promise_min": PROMISE_MIN,
    }


# ------------------------------------------------------------------ demo data
def seed_perks(db: Session) -> None:
    for name, kind, code, pct, prio, area in [
        ("Green Meadows Residency", "society", "GREENMEADOWS", 10, True, "Lotus Lane, Demo City"),
        ("Sunrise Elders Home", "old_age_home", "SUNRISE", 20, True, "Banyan Road, Demo City"),
        ("Orbit Tech Park", "office", "ORBIT", 15, False, "Ring Road, Demo City"),
    ]:
        db.add(PartnerOrg(name=name, kind=kind, join_code=code, discount_pct=pct, priority=prio, area=area,
                          contact="Demo partner"))
    db.flush()
