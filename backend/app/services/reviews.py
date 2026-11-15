"""Patient reviews: 1-5 stars and a comment after a finished home visit or physio package (Tri, 2026-11-15).

* Doctor home visits (general, eye, ENT, dental): one review per completed visit.
* Physiotherapy: one review per package, once at least one session is done.
* Sample collections are not rated yet (collectors have no profile patients choose from).

A new review moves the doctor's or physio's average straight away. Triyana ops can hide an abusive or
off-topic review in /admin; hiding takes it out of the average and off every screen, un-hiding puts it back.
Sample reviews (``Review.sample``) only exist on the demo so profiles aren't empty: they show as normal
comments but never change the average, which the demo seed already set.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..config import is_demo
from ..errors import Conflict, NotFound, Unprocessable
from ..models import (Doctor, HomeVisit, PhysioBooking, Physiotherapist, Review, Role, User, VisitStatus,
                      utcnow)
from .common import notify, users_for_doctor

KINDS = ("visit", "physio")
PROMPT_DAYS = 14          # Home keeps asking "How was your visit?" this long after the visit
PREVIEW = 2               # comments shown on a doctor card while booking
STAR_WORDS = {1: "Very poor", 2: "Poor", 3: "Okay", 4: "Good", 5: "Excellent"}


def short_name(name: str) -> str:
    """'Meera Sharma' -> 'Meera S.' (patients' full names are never shown on a public review)."""
    parts = (name or "").split()
    if not parts:
        return "A patient"
    return parts[0] + (f" {parts[-1][0]}." if len(parts) > 1 else "")


# ------------------------------------------------------------------ averages
def _provider(db: Session, r: Review):
    return db.get(Doctor, r.doctor_id) if r.doctor_id else db.get(Physiotherapist, r.physio_id) if r.physio_id else None


def _add_to_average(p, stars: int) -> None:
    n = p.rating_count or 0
    p.rating = round(((p.rating or 0) * n + stars) / (n + 1), 3)
    p.rating_count = n + 1


def _remove_from_average(p, stars: int) -> None:
    n = p.rating_count or 0
    if n <= 1:
        p.rating, p.rating_count = 0, 0
        return
    p.rating = round(max(0.0, ((p.rating or 0) * n - stars) / (n - 1)), 3)
    p.rating_count = n - 1


# ------------------------------------------------------------------ the job being reviewed
def _job(db: Session, user: User, kind: str, job_id: int):
    """(job, doctor_id, physio_id, patient_id, provider name) for a finished job this account can review."""
    from . import family
    if kind == "visit":
        v = db.get(HomeVisit, job_id)
        if v is None or not family.can_view_patient(db, user, v.patient_id):
            raise NotFound("not_found", "Visit not found.")
        if v.status != VisitStatus.completed or not v.doctor_id:
            raise Conflict("not_finished", "You can rate the doctor once the visit is finished.")
        return v, v.doctor_id, None, v.patient_id, v.doctor.name
    if kind == "physio":
        b = db.get(PhysioBooking, job_id)
        if b is None or not family.can_view_patient(db, user, b.patient_id):
            raise NotFound("not_found", "Booking not found.")
        if not b.physio_id or not any(s.status == "completed" for s in b.sessions):
            raise Conflict("not_finished", "You can rate your physiotherapist after your first session.")
        return b, None, b.physio_id, b.patient_id, b.physio.name
    raise NotFound("not_found", "Nothing to rate here.")


def for_job(db: Session, kind: str, job_id: int) -> Review | None:
    return db.scalars(select(Review).where(Review.kind == kind, Review.job_id == job_id)).first()


def mine(db: Session, kind: str, job_id: int) -> dict | None:
    r = for_job(db, kind, job_id)
    return {"stars": r.stars, "comment": r.comment, "at": r.created_at.isoformat() + "Z", "hidden": bool(r.hidden)} if r else None


def submit(db: Session, user: User, kind: str, job_id: int, stars: int, comment: str = "") -> Review:
    if user.role != Role.patient:
        raise NotFound("not_found", "Only patients can leave a review.")
    if not isinstance(stars, int) or not 1 <= stars <= 5:
        raise Unprocessable("bad_stars", "Pick from 1 to 5 stars.")
    comment = " ".join((comment or "").split())[:500]
    _, doctor_id, physio_id, patient_id, provider_name = _job(db, user, kind, job_id)
    if for_job(db, kind, job_id):
        raise Conflict("already_reviewed", "You've already rated this visit. Thank you!")
    r = Review(kind=kind, job_id=job_id, doctor_id=doctor_id, physio_id=physio_id, patient_id=patient_id,
               author_user_id=user.id, author_name=short_name(user.name), stars=stars, comment=comment)
    db.add(r)
    p = db.get(Doctor, doctor_id) if doctor_id else db.get(Physiotherapist, physio_id)
    _add_to_average(p, stars)
    db.flush()
    audit.record(db, user, "review.create", "review", r.id, kind=kind, job_id=job_id, stars=stars)
    who = users_for_doctor(db, doctor_id) if doctor_id else list(
        db.scalars(select(User).where(User.physio_id == physio_id)))
    notify(db, who, f"New {stars}★ review", f"{r.author_name}: “{comment}”" if comment else
           f"{r.author_name} rated your {'visit' if kind == 'visit' else 'sessions'} {stars} out of 5.", "reviews")
    db.commit()
    return r


# ------------------------------------------------------------------ "How was your visit?" on patient Home
def pending(db: Session, user: User) -> list[dict]:
    """Finished jobs from the last two weeks the patient hasn't rated yet, newest first."""
    from . import family
    ids = [user.patient_id, *family.managed_patient_ids(db, user)]
    since = utcnow() - timedelta(days=PROMPT_DAYS)
    out = []
    visits = db.scalars(select(HomeVisit).where(HomeVisit.patient_id.in_(ids), HomeVisit.status == VisitStatus.completed,
                                                HomeVisit.doctor_id.isnot(None), HomeVisit.completed_at >= since)
                        .order_by(HomeVisit.completed_at.desc())).all()
    for v in visits:
        if not for_job(db, "visit", v.id):
            out.append({"kind": "visit", "job_id": v.id, "at": v.completed_at.isoformat() + "Z",
                        "provider": v.doctor.name, "role": v.doctor.specialty,
                        "for_name": v.patient.name if v.patient_id != user.patient_id else None})
    books = db.scalars(select(PhysioBooking).where(PhysioBooking.patient_id.in_(ids), PhysioBooking.physio_id.isnot(None))).all()
    for b in books:
        done = [s.completed_at for s in b.sessions if s.status == "completed" and s.completed_at]
        if done and max(done) >= since and not for_job(db, "physio", b.id):
            out.append({"kind": "physio", "job_id": b.id, "at": max(done).isoformat() + "Z", "provider": b.physio.name,
                        "role": "Physiotherapist", "for_name": None})
    return sorted(out, key=lambda x: x["at"], reverse=True)


# ------------------------------------------------------------------ what patients see when choosing
def _public(r: Review) -> dict:
    return {"id": r.id, "stars": r.stars, "comment": r.comment, "name": r.author_name or "A patient",
            "at": r.created_at.isoformat() + "Z", "sample": bool(r.sample)}


def _visible(db: Session, *, doctor_id: int | None = None, physio_id: int | None = None, limit: int = 20,
             with_comment: bool = False) -> list[Review]:
    q = select(Review).where(Review.hidden.isnot(True))
    q = q.where(Review.doctor_id == doctor_id) if doctor_id else q.where(Review.physio_id == physio_id)
    if with_comment:
        q = q.where(Review.comment != "")
    return list(db.scalars(q.order_by(Review.created_at.desc(), Review.id.desc()).limit(limit)))


def preview(db: Session | None, *, doctor_id: int | None = None, physio_id: int | None = None) -> list[dict]:
    """The latest couple of written comments, for doctor cards while booking and the matched-doctor card."""
    if db is None:
        return []
    return [_public(r) for r in _visible(db, doctor_id=doctor_id, physio_id=physio_id, limit=PREVIEW, with_comment=True)]


def profile(db: Session, kind: str, provider_id: int) -> dict:
    p = db.get(Doctor, provider_id) if kind == "doctor" else db.get(Physiotherapist, provider_id) if kind == "physio" else None
    if p is None:
        raise NotFound("not_found", "Not found.")
    rows = _visible(db, doctor_id=provider_id if kind == "doctor" else None,
                    physio_id=provider_id if kind == "physio" else None, limit=30)
    return {"name": p.name, "rating": round(p.rating or 0, 2), "rating_count": p.rating_count or 0,
            "reviews": [_public(r) for r in rows], "demo_samples": is_demo() and any(r.sample for r in rows)}


# ------------------------------------------------------------------ Heros: my rating
def for_provider(db: Session, user: User) -> dict | None:
    if user.role == Role.doctor and user.doctor_id:
        return profile(db, "doctor", user.doctor_id)
    if user.role == Role.physio and user.physio_id:
        return profile(db, "physio", user.physio_id)
    return None


# ------------------------------------------------------------------ /admin
def admin_list(db: Session, show: str = "all") -> list[dict]:
    q = select(Review)
    if show == "low":
        q = q.where(Review.stars <= 2)
    elif show == "hidden":
        q = q.where(Review.hidden.is_(True))
    out = []
    for r in db.scalars(q.order_by(Review.created_at.desc(), Review.id.desc()).limit(300)):
        p = _provider(db, r)
        out.append({**_public(r), "kind": r.kind, "job_id": r.job_id, "hidden": bool(r.hidden),
                    "hidden_reason": r.hidden_reason, "hidden_by": r.hidden_by,
                    "provider": p.name if p else "—", "provider_role": "Physiotherapist" if r.physio_id else (p.specialty if p else ""),
                    "provider_rating": round(p.rating or 0, 2) if p else None, "provider_count": p.rating_count if p else 0})
    return out


def set_hidden(db: Session, review_id: int, hidden: bool, reason: str = "", admin_name: str = "") -> Review:
    r = db.get(Review, review_id)
    if r is None:
        raise NotFound("not_found", "Review not found.")
    if bool(r.hidden) == hidden:
        return r
    p = _provider(db, r)
    if p and not r.sample:
        (_remove_from_average if hidden else _add_to_average)(p, r.stars)
    r.hidden = hidden
    r.hidden_reason = (reason or "").strip()[:200] or None if hidden else None
    r.hidden_by = admin_name[:120] or "Triyana ops" if hidden else None
    audit.record(db, None, "review.hide" if hidden else "review.unhide", "review", r.id, reason=r.hidden_reason or "",
                 by=admin_name or "ops")
    db.commit()
    return r


# ------------------------------------------------------------------ demo samples
SAMPLE_REVIEWS: dict[str, list[tuple[str, int, str, int]]] = {
    # doctor licence no -> (name, stars, comment, days ago)
    "TSMC-DEMO-55821": [("Priya R.", 5, "Came in 9 minutes at night for my son's fever. Very calm and explained everything.", 2),
                        ("Suresh K.", 5, "Checked my father's BP and sugar properly and wrote clear medicines. Very kind.", 6),
                        ("Anita M.", 4, "Good doctor. Was a few minutes late but called ahead to tell us.", 11)],
    "TSMC-DEMO-61204": [("Kiran P.", 5, "So gentle with my 3 year old. She wasn't scared at all.", 3),
                        ("Lakshmi V.", 5, "Explained the vaccination schedule clearly. Highly recommend.", 9)],
    "NMC-DEMO-47719": [("Ravi T.", 5, "Very patient with my grandmother and spoke to her in Telugu.", 4),
                       ("Fatima S.", 4, "Thorough check-up for my mother. Follow-up call came on time.", 12)],
    "KMC-DEMO-58833": [("Arvind N.", 5, "Sorted my back pain with simple exercises. No unnecessary medicines.", 5),
                       ("Deepa J.", 4, "Knowledgeable, gave a clear plan for my knee.", 15)],
}
SAMPLE_PHYSIO_REVIEWS: dict[str, list[tuple[str, int, str, int]]] = {
    "AHP-TS-DEMO-2207": [("Rahul D.", 5, "My knee pain went from 7 to 2 in five sessions. Great home exercises.", 4)],
    "AHP-TS-DEMO-1874": [("Sunita G.", 5, "Helped my father walk again after his stroke. Very encouraging.", 8)],
}


def seed_samples(db: Session) -> int:
    """Add a few sample reviews to the demo doctors and physios (once). They don't change the averages."""
    if db.scalars(select(Review.id).where(Review.sample.is_(True))).first():
        return 0
    added, now = 0, utcnow()
    from ..services.specialties import DEMO_SPECIALISTS
    by_care = {
        "eye": [("Neha B.", 5, "Tested my mother's eyes at home and explained her cataract options patiently.", 3),
                ("Mohan R.", 4, "Brought proper equipment. Got my new glasses power the same day.", 10)],
        "ent": [("Sameer A.", 5, "Cleared my son's blocked ear at home, no hospital waiting.", 4),
                ("Geeta L.", 4, "Clear advice for my sinus problem. Fair fee.", 13)],
        "dental": [("Pooja S.", 5, "Checked my toothache at home and was very gentle.", 2),
                   ("Imran K.", 4, "Good check-up for my father, who can't travel easily.", 9)],
    }
    specs = {row[4]: by_care.get(row[2], []) for row in DEMO_SPECIALISTS}
    for lic, rows in {**SAMPLE_REVIEWS, **specs}.items():
        d = db.scalars(select(Doctor).where(Doctor.license_no == lic)).first()
        for name, stars, comment, days in rows if d else []:
            db.add(Review(kind="visit", doctor_id=d.id, author_name=name, stars=stars, comment=comment, sample=True,
                          created_at=now - timedelta(days=days)))
            added += 1
    for reg, rows in SAMPLE_PHYSIO_REVIEWS.items():
        ph = db.scalars(select(Physiotherapist).where(Physiotherapist.registration_no == reg)).first()
        for name, stars, comment, days in rows if ph else []:
            db.add(Review(kind="physio", physio_id=ph.id, author_name=name, stars=stars, comment=comment, sample=True,
                          created_at=now - timedelta(days=days)))
            added += 1
    db.flush()
    return added
