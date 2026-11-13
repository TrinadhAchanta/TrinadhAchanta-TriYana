"""Care that keeps patients coming back: monthly care plans, the free 48-hour follow-up call, health records.

Care plans book their check-ups as ordinary home visits (same doctors, same slots), so the doctor app,
dispatch, live map, visit notes and prescriptions all work for them unchanged.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import Conflict, DomainError, NotFound, Unprocessable
from ..models import (CarePlan, FollowUpCall, HomeVisit, LabBooking, Patient, PhysioBooking, PhysioSession,
                      Prescription, RxStatus, User, VisitNote, VisitStatus, utcnow)
from . import visit_notes, visits
from .common import new_ref, notify, users_for_doctor, users_for_patient

LOCAL_TZ = visits.LOCAL_TZ
PLAN_DAYS = 30

# Prices are placeholders for the demo; Tri to confirm before launch.
PLANS = {
    "diabetes": {
        "title": "Diabetes care", "visits_per_month": 2, "monthly_fee": 1499, "icon": "pills",
        "for": "Type 1 or type 2 diabetes, on tablets or insulin",
        "checks": ["Blood sugar (glucometer) and BP at home", "Foot and skin check", "Medicine and insulin review",
                   "Diet and sugar log review"],
        "reason": "Diabetes care plan check-up",
    },
    "bp": {
        "title": "Blood pressure care", "visits_per_month": 2, "monthly_fee": 1299, "icon": "heart",
        "for": "High blood pressure or heart patients",
        "checks": ["BP and pulse, sitting and standing", "Swelling and breathlessness check",
                   "Medicine review and dose advice", "Salt, diet and walking plan"],
        "reason": "BP care plan check-up",
    },
    "bedridden": {
        "title": "Bedridden patient care", "visits_per_month": 4, "monthly_fee": 3499, "icon": "home2",
        "for": "Patients who can't leave bed: after a stroke, surgery or long illness",
        "checks": ["Weekly doctor visit at home", "Bedsore and skin check", "Chest, feeding and catheter review",
                   "Guidance for the family caregiver"],
        "reason": "Bedridden care plan check-up",
    },
    "elderly": {
        "title": "Senior wellness", "visits_per_month": 1, "monthly_fee": 799, "icon": "shield",
        "for": "Parents and grandparents over 60",
        "checks": ["Monthly full check-up at home", "BP, sugar, SpO2 and weight", "Fall risk and memory check",
                   "Review of all medicines"],
        "reason": "Senior wellness check-up",
    },
}
PLAN_HOURS = list(range(9, 20))  # check-up start hours a patient can choose (local)

FOLLOW_UP_WINDOW = timedelta(hours=48)
CALL_FIRST_AFTER = timedelta(hours=20)  # first call time offered: about a day after the visit
CALL_HOURS = list(range(9, 21))         # doctors call between 9 AM and 8 PM (local)


def _local(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)


def _utc(local: datetime) -> datetime:
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def _patient(db: Session, user: User) -> Patient:
    return db.get(Patient, user.patient_id)


# ======================================================================= care plans
def catalog() -> list[dict]:
    return [{"kind": k, **{f: p[f] for f in ("title", "visits_per_month", "monthly_fee", "icon", "for", "checks")},
             "per_visit": round(p["monthly_fee"] / p["visits_per_month"])} for k, p in PLANS.items()]


def _due_days(start: date, n: int) -> list[str]:
    gap = PLAN_DAYS / n
    return [(start + timedelta(days=round(i * gap))).isoformat() for i in range(n)]


def _book_checkup(db: Session, user: User, plan: CarePlan, entry: dict) -> None:
    """Book one check-up as a home visit: the plan's doctor at the preferred hour if free, else the nearest
    hour that day with them, else whoever nearby is free that day."""
    patient = _patient(db, user)
    day = date.fromisoformat(entry["due"])
    slots_by_doc = []
    near = [d for d, _ in visits._nearby_doctors(db, patient)]
    order = sorted(near, key=lambda d: d.id != plan.doctor_id)  # the regular doctor first
    for doc in order:
        free = [s for s in visits.free_slots(db, doc.id) if _local(s).date() == day]
        if free:
            best = min(free, key=lambda s: abs(_local(s).hour - plan.preferred_hour))
            slots_by_doc.append((doc, best))
            break
    if not slots_by_doc:
        entry["note"] = "No doctor is free that day yet. We'll keep trying."
        return
    doc, when = slots_by_doc[0]
    try:
        v = visits.book(db, user, doc.id, when.isoformat(), PLANS[plan.kind]["reason"], "")
    except DomainError as exc:
        entry["note"] = exc.message
        return
    _cover_by_plan(db, v)
    entry["visit_id"] = v.id
    entry.pop("note", None)
    if plan.doctor_id is None:
        plan.doctor_id = doc.id


def _cover_by_plan(db: Session, visit: HomeVisit) -> None:
    """The monthly fee pays for plan check-ups: nothing to pay at the door, and no credit or offer used up.
    The doctor still earns their full fee."""
    from ..models_perks import CreditEntry, VisitBill
    bill = db.scalars(select(VisitBill).where(VisitBill.visit_id == visit.id)).first()
    if bill is None:
        return
    for c in db.scalars(select(CreditEntry).where(CreditEntry.visit_id == visit.id, CreditEntry.kind == "spent")):
        db.delete(c)
    fee = bill.base_fee
    bill.lines = [{"code": "fee", "label": "Doctor's visit fee", "amount": fee},
                  {"code": "care_plan", "label": "Covered by your care plan", "amount": -fee}]
    bill.patient_pays, bill.credit_used = 0.0, 0.0
    db.commit()


def sync(db: Session, user: User, plan: CarePlan) -> None:
    """Renew the month when it ends, and book check-ups that are now inside the booking window."""
    if plan.status != "active":
        return
    now = utcnow()
    sched = [dict(e) for e in (plan.schedule or [])]
    while now >= plan.renews_on:  # sandbox auto-renewal: next month's check-ups
        start = _local(plan.renews_on).date()
        sched += [{"due": d, "visit_id": None} for d in _due_days(start, plan.visits_per_month)]
        plan.renews_on = plan.renews_on + timedelta(days=PLAN_DAYS)
    last_bookable = visits._local_days(now)[-1].isoformat()
    for e in sched:
        if e.get("visit_id") is None and e["due"] <= last_bookable:
            if e["due"] < _local(now).date().isoformat():
                e["due"] = _local(now).date().isoformat()  # a missed day moves to the first open day
            _book_checkup(db, user, plan, e)
    plan.schedule = sched
    db.commit()


def enrol(db: Session, user: User, kind: str, preferred_hour: int, doctor_id: int | None = None) -> CarePlan:
    if kind not in PLANS:
        raise Unprocessable("bad_plan", "Please choose one of the care plans.")
    if preferred_hour not in PLAN_HOURS:
        raise Unprocessable("bad_hour", "Check-ups can start between 9 AM and 7 PM.")
    patient = _patient(db, user)
    if db.scalars(select(CarePlan).where(CarePlan.patient_id == patient.id, CarePlan.kind == kind,
                                         CarePlan.status == "active")).first():
        raise Conflict("plan_exists", f"You already have the {PLANS[kind]['title']} plan.")
    if doctor_id is not None:
        visits._nearby_doctor_or_404(db, patient, doctor_id)
    p = PLANS[kind]
    now = utcnow()
    first = _local(now).date() + timedelta(days=1)
    plan = CarePlan(ref=new_ref("CP"), patient_id=patient.id, kind=kind, preferred_hour=preferred_hour,
                    doctor_id=doctor_id, monthly_fee=p["monthly_fee"], visits_per_month=p["visits_per_month"],
                    schedule=[{"due": d, "visit_id": None} for d in _due_days(first, p["visits_per_month"])],
                    started_at=now, renews_on=now + timedelta(days=PLAN_DAYS))
    db.add(plan)
    db.flush()
    notify(db, users_for_patient(db, patient.id), f"{p['title']} plan started",
           f"{p['visits_per_month']} doctor check-up{'s' if p['visits_per_month'] > 1 else ''} at home every month. "
           "We book each one for you and remind you the day before.", f"careplan:{plan.id}")
    audit.record(db, user, "careplan.enrol", "care_plan", plan.id, kind=kind)
    db.commit()
    sync(db, user, plan)
    return plan


def _plan_for(db: Session, user: User, plan_id: int) -> CarePlan:
    plan = db.get(CarePlan, plan_id)
    if plan is None or plan.patient_id != user.patient_id:
        raise NotFound("not_found", "Care plan not found.")
    return plan


def cancel(db: Session, user: User, plan_id: int) -> CarePlan:
    plan = _plan_for(db, user, plan_id)
    if plan.status != "active":
        raise Conflict("plan_not_active", "This plan is already cancelled.")
    for e in plan.schedule or []:
        v = db.get(HomeVisit, e["visit_id"]) if e.get("visit_id") else None
        if v and v.status in (VisitStatus.requested, VisitStatus.accepted):
            visits.cancel(db, user, v.id)
    plan.status, plan.cancelled_at = "cancelled", utcnow()
    audit.record(db, user, "careplan.cancel", "care_plan", plan.id)
    db.commit()
    return plan


def plan_to_dict(db: Session, plan: CarePlan) -> dict:
    p = PLANS[plan.kind]
    checkups = []
    for e in plan.schedule or []:
        v = db.get(HomeVisit, e["visit_id"]) if e.get("visit_id") else None
        checkups.append({"due": e["due"], "visit_id": v.id if v else None,
                         "status": v.status.value if v else ("waiting" if plan.status == "active" else "cancelled"),
                         "scheduled_for": v.scheduled_for.isoformat() if v else None,
                         "doctor": v.doctor.name if v and v.doctor else None, "note": e.get("note")})
    done = sum(c["status"] == "completed" for c in checkups)
    return {"id": plan.id, "ref": plan.ref, "kind": plan.kind, "title": p["title"], "icon": p["icon"],
            "checks": p["checks"], "status": plan.status, "monthly_fee": plan.monthly_fee,
            "visits_per_month": plan.visits_per_month, "preferred_hour": plan.preferred_hour,
            "doctor": visits.doctor_to_dict(plan.doctor, None) if plan.doctor else None,
            "started_at": plan.started_at.isoformat(), "renews_on": plan.renews_on.isoformat(),
            "checkups": checkups, "completed": done,
            "next": next((c for c in checkups if c["status"] in ("requested", "accepted", "waiting")), None)}


def list_plans(db: Session, user: User) -> list[dict]:
    rows = db.scalars(select(CarePlan).where(CarePlan.patient_id == user.patient_id)
                      .order_by(CarePlan.status, CarePlan.id.desc())).all()
    for plan in rows:
        sync(db, user, plan)
    return [plan_to_dict(db, p) for p in rows]


# ================================================================ free follow-up call
def _first_call_time(completed: datetime) -> datetime:
    """The first calling hour at least ~20 hours after the visit, so the doctor calls about a day later."""
    t = _local(completed + CALL_FIRST_AFTER)
    t = t.replace(minute=0, second=0, microsecond=0) + (timedelta(hours=1) if t.minute or t.second else timedelta())
    for _ in range(48):
        if t.hour in CALL_HOURS:
            break
        t += timedelta(hours=1)
    out = _utc(t)
    due = completed + FOLLOW_UP_WINDOW
    return out if out <= due else due - timedelta(hours=1)


def on_visit_completed(db: Session, visit: HomeVisit) -> FollowUpCall | None:
    """Every completed home visit gets a free doctor call within 48 hours. Called in the same transaction."""
    if visit.doctor_id is None:
        return None
    existing = db.scalars(select(FollowUpCall).where(FollowUpCall.visit_id == visit.id)).first()
    if existing:
        return existing
    done = visit.completed_at or utcnow()
    call = FollowUpCall(visit_id=visit.id, patient_id=visit.patient_id, doctor_id=visit.doctor_id,
                        scheduled_for=_first_call_time(done), due_by=done + FOLLOW_UP_WINDOW)
    db.add(call)
    db.flush()
    local = _local(call.scheduled_for).strftime("%a %d %b, %I:%M %p")
    notify(db, users_for_patient(db, visit.patient_id), "Free follow-up call booked",
           f"{visit.doctor.name} will call you on {local} to see how you are. It's free.", f"call:{call.id}")
    notify(db, users_for_doctor(db, visit.doctor_id), "Follow-up call to make",
           f"Call {visit.patient.name} on {local} (within 48 hours of the visit).", f"call:{call.id}")
    return call


def _status(c: FollowUpCall) -> str:
    if c.status == "done":
        return "done"
    return "missed" if utcnow() > c.due_by else "scheduled"


def call_slots(c: FollowUpCall) -> list[str]:
    """Times the patient can move the call to: whole hours from an hour from now until the 48-hour mark."""
    now = utcnow()
    t = _local(now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    out = []
    while _utc(t) <= c.due_by:
        if t.hour in CALL_HOURS:
            out.append(_utc(t).isoformat())
        t += timedelta(hours=1)
    return out


def call_to_dict(db: Session, c: FollowUpCall, for_doctor: bool = False) -> dict:
    v = c.visit
    out = {"id": c.id, "visit_id": c.visit_id, "status": _status(c), "scheduled_for": c.scheduled_for.isoformat(),
           "due_by": c.due_by.isoformat(), "feeling": c.feeling, "patient_note": c.patient_note,
           "doctor_note": c.doctor_note, "done_at": c.done_at.isoformat() if c.done_at else None,
           "visit": {"booking_ref": v.booking_ref, "date": v.scheduled_for.isoformat(), "reason": v.reason,
                     "diagnosis": v.note.diagnosis if v.note else None},
           "doctor": {"id": c.doctor_id, "name": c.doctor.name, "specialty": c.doctor.specialty}, "free": True}
    if for_doctor:
        phone = next((u.phone for u in users_for_patient(db, c.patient_id) if u.phone), None)
        out["patient"] = {"name": v.patient.name, "phone": phone}
    elif _status(c) == "scheduled":
        out["slots"] = call_slots(c)
    return out


def _call_for_patient(db: Session, user: User, call_id: int) -> FollowUpCall:
    c = db.get(FollowUpCall, call_id)
    if c is None or c.patient_id != user.patient_id:
        raise NotFound("not_found", "Call not found.")
    return c


def patient_calls(db: Session, user: User) -> list[dict]:
    rows = db.scalars(select(FollowUpCall).where(FollowUpCall.patient_id == user.patient_id)
                      .order_by(FollowUpCall.scheduled_for.desc())).all()
    return [call_to_dict(db, c) for c in rows]


def reschedule_call(db: Session, user: User, call_id: int, when: str) -> dict:
    c = _call_for_patient(db, user, call_id)
    if _status(c) != "scheduled":
        raise Conflict("call_closed", "This call can no longer be moved.")
    t = visits._parse(when)
    if t.isoformat() not in call_slots(c):
        raise Unprocessable("bad_time", "Please pick a time within 48 hours of your visit.")
    c.scheduled_for = t
    local = _local(t).strftime("%a %d %b, %I:%M %p")
    notify(db, users_for_doctor(db, c.doctor_id), "Follow-up call moved",
           f"{c.visit.patient.name} asked for the call on {local}.", f"call:{c.id}")
    audit.record(db, user, "call.reschedule", "follow_up_call", c.id)
    db.commit()
    return call_to_dict(db, c)


def share_feeling(db: Session, user: User, call_id: int, feeling: str, note: str) -> dict:
    c = _call_for_patient(db, user, call_id)
    if feeling not in ("better", "same", "worse"):
        raise Unprocessable("bad_feeling", "Choose better, the same or worse.")
    c.feeling, c.patient_note = feeling, note.strip()[:500]
    if feeling == "worse":
        notify(db, users_for_doctor(db, c.doctor_id), "Patient feels worse",
               f"{c.visit.patient.name} says they feel worse since your visit. Please call them soon."
               + (f" They wrote: {c.patient_note}" if c.patient_note else ""), f"call:{c.id}")
    audit.record(db, user, "call.feeling", "follow_up_call", c.id, feeling=feeling)
    db.commit()
    return call_to_dict(db, c)


def doctor_calls(db: Session, user: User) -> list[dict]:
    rows = db.scalars(select(FollowUpCall).where(FollowUpCall.doctor_id == user.doctor_id)
                      .order_by(FollowUpCall.scheduled_for)).all()
    out = [call_to_dict(db, c, for_doctor=True) for c in rows]
    # Patients who feel worse first, then the next due.
    return sorted(out, key=lambda c: ({"scheduled": 0, "missed": 1, "done": 2}[c["status"]],
                                      c["feeling"] != "worse", c["scheduled_for"]))


def complete_call(db: Session, user: User, call_id: int, note: str) -> dict:
    c = db.get(FollowUpCall, call_id)
    if c is None or c.doctor_id != user.doctor_id:
        raise NotFound("not_found", "Call not found.")
    if c.status == "done":
        raise Conflict("call_done", "This call is already marked done.")
    if not note.strip():
        raise Unprocessable("no_note", "Write a short note on how the patient is doing.")
    c.status, c.done_at, c.doctor_note = "done", utcnow(), note.strip()[:1000]
    notify(db, users_for_patient(db, c.patient_id), "Notes from your follow-up call",
           f"{c.doctor.name}: {c.doctor_note}", f"call:{c.id}")
    audit.record(db, user, "call.complete", "follow_up_call", c.id)
    db.commit()
    return call_to_dict(db, c, for_doctor=True)


# ===================================================================== health records
def records(db: Session, user: User) -> dict:
    """Visit notes, vitals, prescriptions, lab reports, physio sessions and follow-up calls in one timeline."""
    pid = user.patient_id
    items: list[dict] = []
    for v in db.scalars(select(HomeVisit).where(HomeVisit.patient_id == pid, HomeVisit.status == VisitStatus.completed)):
        s = visit_notes.summary(v)
        items.append({"kind": "visit", "id": v.id, "at": (v.completed_at or v.scheduled_for).isoformat(),
                      "title": f"Home visit · {v.doctor.name}" if v.doctor else "Home visit",
                      "subtitle": (s or {}).get("diagnosis") or v.reason,
                      "detail": {"reason": v.reason, "notes": s}})
    for rx in db.scalars(select(Prescription).where(Prescription.patient_id == pid,
                                                    Prescription.status.in_([RxStatus.signed, RxStatus.superseded]))):
        items.append({"kind": "prescription", "id": rx.id, "at": (rx.signed_at or rx.created_at).isoformat(),
                      "title": f"Prescription {rx.reference_no}",
                      "subtitle": ", ".join(i.medication.name for i in rx.items if i.medication),
                      "detail": {"doctor": rx.doctor.name, "status": rx.status.value,
                                 "valid_until": rx.valid_until.isoformat() if rx.valid_until else None}})
    for b in db.scalars(select(LabBooking).where(LabBooking.patient_id == pid, LabBooking.status == "report_ready")):
        flagged = (b.report or {}).get("flagged", [])
        items.append({"kind": "lab", "id": b.id, "at": (b.report_ready_at or b.created_at).isoformat(),
                      "title": "Lab report · " + ", ".join(i["name"] for i in b.items),
                      "subtitle": (b.report or {}).get("summary", ""), "detail": {"flagged": flagged}})
    for s in db.scalars(select(PhysioSession).join(PhysioBooking)
                        .where(PhysioBooking.patient_id == pid, PhysioSession.status == "completed")):
        items.append({"kind": "physio", "id": s.id, "at": (s.completed_at or s.scheduled_for).isoformat(),
                      "title": f"Physio session {s.number}" + (f" · {s.booking.physio.name}" if s.booking.physio else ""),
                      "subtitle": s.notes or s.booking.condition,
                      "detail": {"pain_before": s.pain_before, "pain_after": s.pain_after}})
    for c in db.scalars(select(FollowUpCall).where(FollowUpCall.patient_id == pid, FollowUpCall.status == "done")):
        items.append({"kind": "call", "id": c.id, "at": c.done_at.isoformat(),
                      "title": f"Follow-up call · {c.doctor.name}", "subtitle": c.doctor_note,
                      "detail": {"feeling": c.feeling}})
    items.sort(key=lambda i: i["at"], reverse=True)

    notes = db.scalars(select(VisitNote).join(HomeVisit, VisitNote.visit_id == HomeVisit.id)
                       .where(VisitNote.patient_id == pid, HomeVisit.status == VisitStatus.completed)).all()
    vitals = sorted(({"at": (n.visit.completed_at or n.visit.scheduled_for).isoformat(),
                      "bp_systolic": n.bp_systolic, "bp_diastolic": n.bp_diastolic, "pulse_bpm": n.pulse_bpm,
                      "spo2_pct": n.spo2_pct, "temperature_c": n.temperature_c, "weight_kg": n.weight_kg}
                     for n in notes), key=lambda r: r["at"])
    counts = {k: sum(i["kind"] == k for i in items) for k in ("visit", "prescription", "lab", "physio", "call")}
    return {"items": items, "vitals": vitals, "counts": counts}
