"""Family care: book doctors for parents and children, alert family in an emergency, share live tracking.

* A family member is their own ``Patient`` (own home, own records), linked to the account that
  manages them. Booking "for Mom" sends the nearest doctor to *Mom's* door, even in another city.
* Managers see the member's visits and live map in their own app, and get the same updates.
* Emergency contacts get an SMS with a read-only live tracking link when an SOS is sent.
* A tracking link can also be shared by hand (WhatsApp etc.) for anyone without the app.
"""
from __future__ import annotations

import os
import secrets
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import Conflict, NotFound, Unprocessable
from ..models import (
    EmergencyContact,
    FamilyMember,
    HomeVisit,
    Patient,
    TrackingShare,
    User,
    VisitStatus,
    utcnow,
)
from .accounts import normalize_phone
from .common import new_ref

MAX_MEMBERS = 8
MAX_CONTACTS = 5
SHARE_HOURS = 12
RELATIONS = ["Mother", "Father", "Spouse", "Son", "Daughter", "Grandmother", "Grandfather", "Sibling",
             "Mother-in-law", "Father-in-law", "Other"]


def public_base() -> str:
    return os.environ.get("TRIYANA_PUBLIC_URL", "https://triyana-demo.onrender.com").rstrip("/")


# ------------------------------------------------------------------ members
def _active_members(db: Session, user: User) -> list[FamilyMember]:
    return list(db.scalars(select(FamilyMember).where(FamilyMember.owner_user_id == user.id,
                                                      FamilyMember.removed_at.is_(None))
                           .order_by(FamilyMember.id)))


def _age(dob: str | None) -> int | None:
    try:
        d = date.fromisoformat(dob or "")
    except ValueError:
        return None
    t = date.today()
    return t.year - d.year - ((t.month, t.day) < (d.month, d.day))


def member_to_dict(db: Session, m: FamilyMember, owner: Patient | None = None) -> dict:
    p = m.patient
    same = owner is not None and abs(p.lat - owner.lat) < 1e-6 and abs(p.lng - owner.lng) < 1e-6
    return {"id": m.id, "patient_id": p.id, "name": p.name, "relation": m.relation, "age": _age(p.date_of_birth),
            "date_of_birth": p.date_of_birth, "gender": p.gender, "phone": m.phone, "address": p.address,
            "lat": p.lat, "lng": p.lng, "same_home": same}


def list_members(db: Session, user: User) -> dict:
    me = db.get(Patient, user.patient_id)
    return {"me": {"name": me.name, "address": me.address, "lat": me.lat, "lng": me.lng},
            "members": [member_to_dict(db, m, me) for m in _active_members(db, user)],
            "contacts": [contact_to_dict(c) for c in _active_contacts(db, user)],
            "relations": RELATIONS}


def add_member(db: Session, user: User, body: dict) -> dict:
    me = db.get(Patient, user.patient_id)
    if len(_active_members(db, user)) >= MAX_MEMBERS:
        raise Conflict("too_many_members", f"You can add up to {MAX_MEMBERS} family members.")
    name = (body.get("name") or "").strip()
    if len(name) < 2:
        raise Unprocessable("name_required", "Enter their full name.")
    relation = (body.get("relation") or "Other").strip()[:40]
    dob = (body.get("date_of_birth") or "").strip()
    if dob:
        try:
            if date.fromisoformat(dob) > date.today():
                raise ValueError
        except ValueError as exc:
            raise Unprocessable("bad_dob", "Enter a valid date of birth.") from exc
    phone = normalize_phone(body["phone"]) if (body.get("phone") or "").strip() else None
    if body.get("same_home", True):
        address, lat, lng = me.address, me.lat, me.lng
    else:
        address = (body.get("address") or "").strip()
        lat, lng = body.get("lat"), body.get("lng")
        if len(address) < 5:
            raise Unprocessable("address_required", "Enter their home address.")
        if lat is None or lng is None:
            raise Unprocessable("location_required", "Tap their home on the map so the nearest doctor is sent there.")
    p = Patient(name=name[:120], patient_ref=new_ref("PT"), date_of_birth=dob, address=address[:300],
                lat=float(lat), lng=float(lng), jurisdiction=me.jurisdiction,
                gender=(body.get("gender") or None))
    db.add(p)
    db.flush()
    m = FamilyMember(owner_user_id=user.id, patient_id=p.id, relation=relation, phone=phone)
    db.add(m)
    db.flush()
    audit.record(db, user, "family.member.add", "family_member", m.id, relation=relation)
    db.commit()
    return member_to_dict(db, m, me)


def remove_member(db: Session, user: User, member_id: int) -> None:
    m = _member_or_404(db, user, member_id)
    m.removed_at = utcnow()
    audit.record(db, user, "family.member.remove", "family_member", m.id)
    db.commit()


def _member_or_404(db: Session, user: User, member_id: int) -> FamilyMember:
    m = db.get(FamilyMember, member_id)
    if m is None or m.owner_user_id != user.id or m.removed_at is not None:
        raise NotFound("not_found", "Family member not found.")
    return m


def patient_for(db: Session, user: User, member_id: int | None) -> Patient:
    """Whose care this is: the account holder (no member) or one of their family members."""
    if not member_id:
        return db.get(Patient, user.patient_id)
    return _member_or_404(db, user, member_id).patient


def can_view_patient(db: Session, user: User, patient_id: int) -> bool:
    if user.patient_id == patient_id:
        return True
    return db.scalars(select(FamilyMember.id).where(FamilyMember.owner_user_id == user.id,
                                                    FamilyMember.patient_id == patient_id,
                                                    FamilyMember.removed_at.is_(None))).first() is not None


def managed_patient_ids(db: Session, user: User) -> list[int]:
    return [m.patient_id for m in _active_members(db, user)]


def relation_for(db: Session, user: User, patient_id: int) -> str | None:
    m = db.scalars(select(FamilyMember).where(FamilyMember.owner_user_id == user.id,
                                              FamilyMember.patient_id == patient_id,
                                              FamilyMember.removed_at.is_(None))).first()
    return m.relation if m else None


def visit_or_404(db: Session, user: User, visit_id: int) -> HomeVisit:
    v = db.get(HomeVisit, visit_id)
    if v is None or not can_view_patient(db, user, v.patient_id):
        raise NotFound("not_found", "Visit not found.")
    return v


# ------------------------------------------------------------------ emergency contacts
def _active_contacts(db: Session, user: User) -> list[EmergencyContact]:
    return list(db.scalars(select(EmergencyContact).where(EmergencyContact.owner_user_id == user.id,
                                                          EmergencyContact.removed_at.is_(None))
                           .order_by(EmergencyContact.id)))


def contacts_for(db: Session, user: User) -> list[EmergencyContact]:
    return _active_contacts(db, user)


def contact_to_dict(c: EmergencyContact) -> dict:
    return {"id": c.id, "name": c.name, "relation": c.relation, "phone": c.phone}


def add_contact(db: Session, user: User, body: dict) -> dict:
    if len(_active_contacts(db, user)) >= MAX_CONTACTS:
        raise Conflict("too_many_contacts", f"You can add up to {MAX_CONTACTS} emergency contacts.")
    name = (body.get("name") or "").strip()
    if len(name) < 2:
        raise Unprocessable("name_required", "Enter their name.")
    c = EmergencyContact(owner_user_id=user.id, name=name[:120], relation=(body.get("relation") or "").strip()[:40],
                         phone=normalize_phone(body.get("phone") or ""))
    db.add(c)
    db.flush()
    audit.record(db, user, "family.contact.add", "emergency_contact", c.id)
    db.commit()
    return contact_to_dict(c)


def remove_contact(db: Session, user: User, contact_id: int) -> None:
    c = db.get(EmergencyContact, contact_id)
    if c is None or c.owner_user_id != user.id or c.removed_at is not None:
        raise NotFound("not_found", "Contact not found.")
    c.removed_at = utcnow()
    audit.record(db, user, "family.contact.remove", "emergency_contact", c.id)
    db.commit()


# ------------------------------------------------------------------ live tracking links
def create_share(db: Session, user: User | None, v: HomeVisit, label: str = "", commit: bool = True) -> dict:
    if v.status in (VisitStatus.completed, VisitStatus.cancelled):
        raise Conflict("bad_visit_state", "This visit has ended, so there is nothing live to share.")
    s = TrackingShare(token=secrets.token_urlsafe(18), visit_id=v.id, created_by_user_id=user.id if user else None,
                      label=label.strip()[:80], expires_at=utcnow() + timedelta(hours=SHARE_HOURS))
    db.add(s)
    db.flush()
    audit.record(db, user, "visit.share", "home_visit", v.id, share_id=s.id, label=s.label)
    if commit:
        db.commit()
    return share_to_dict(s)


def share_to_dict(s: TrackingShare) -> dict:
    return {"id": s.id, "url": f"{public_base()}/track/{s.token}", "path": f"/track/{s.token}",
            "label": s.label, "expires_at": s.expires_at.isoformat()}


def list_shares(db: Session, user: User, visit_id: int) -> list[dict]:
    v = visit_or_404(db, user, visit_id)
    now = utcnow()
    rows = db.scalars(select(TrackingShare).where(TrackingShare.visit_id == v.id, TrackingShare.revoked_at.is_(None),
                                                  TrackingShare.expires_at > now)).all()
    return [share_to_dict(s) for s in rows]


def revoke_share(db: Session, user: User, visit_id: int, share_id: int) -> None:
    v = visit_or_404(db, user, visit_id)
    s = db.get(TrackingShare, share_id)
    if s is None or s.visit_id != v.id:
        raise NotFound("not_found", "Link not found.")
    s.revoked_at = utcnow()
    audit.record(db, user, "visit.share.revoke", "home_visit", v.id, share_id=s.id)
    db.commit()


def share_by_token(db: Session, token: str) -> TrackingShare:
    s = db.scalars(select(TrackingShare).where(TrackingShare.token == token)).first()
    if s is None or s.revoked_at is not None or s.expires_at < utcnow():
        raise NotFound("link_expired", "This tracking link has expired or was turned off.")
    return s


def seed_demo(db: Session, owner: User, me: Patient) -> dict:
    """Meera manages her mother (own home across town) and her father (same home), and has two
    emergency contacts. All fictional; phone numbers only ever go to the sandbox SMS log."""
    mom = Patient(name="Kamala Demo", patient_ref="PT-DEMO-101", date_of_birth="1952-03-08", gender="Female",
                  address="4 Neem Street, Demo City (Mom's house)", lat=17.4482, lng=78.3655, jurisdiction=me.jurisdiction)
    dad = Patient(name="Raghav Demo", patient_ref="PT-DEMO-102", date_of_birth="1949-11-21", gender="Male",
                  address=me.address, lat=me.lat, lng=me.lng, jurisdiction=me.jurisdiction)
    db.add_all([mom, dad])
    db.flush()
    db.add_all([
        FamilyMember(owner_user_id=owner.id, patient_id=mom.id, relation="Mother", phone="+919000000001"),
        FamilyMember(owner_user_id=owner.id, patient_id=dad.id, relation="Father"),
        EmergencyContact(owner_user_id=owner.id, name="Arjun (brother, Bengaluru)", relation="Brother",
                         phone="+919876500011"),
        EmergencyContact(owner_user_id=owner.id, name="Dr. Neighbour Rao", relation="Neighbour", phone="+919848000021"),
    ])
    db.flush()
    return {"mom": mom.id, "dad": dad.id}
