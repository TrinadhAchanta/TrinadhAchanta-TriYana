"""Lab tests at home: pick tests, book a collection slot (or "collect now"), a phlebotomist is
dispatched like a Dasher (nearest first, accept/decline, live map), collects the sample at the door,
drops it at the partner lab, and the report appears in the patient app.

Statuses: booked -> assigned -> collected -> at_lab -> report_ready (or cancelled).
Reports in the demo are generated from fictional reference ranges a short while after the
sample reaches the lab (TRIYANA_LAB_REPORT_SECONDS, default 60).
"""
from __future__ import annotations

import math
import os
import random
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..adapters.geo import haversine_km
from ..adapters.payments import INDIA_METHODS, SandboxPaymentGateway
from ..errors import Conflict, NotFound, PaymentDeclined, Unprocessable
from ..models import DispatchOffer, Earning, Lab, LabBooking, LabTest, Patient, Role, Trip, User, utcnow
from . import dispatch
from .common import new_ref, notify, users_for_patient

LOCAL_TZ = timezone(timedelta(hours=5, minutes=30))
SLOT_HOURS = list(range(6, 19))          # collection windows start 6 AM to 6 PM, one hour each
FASTING_HOURS_END = 10                   # fasting samples are best collected before 10 AM
BOOKING_DAYS = 4
MIN_LEAD = timedelta(minutes=60)
SLOT_CAPACITY = 4
RADIUS_KM = 15.0
FREE_COLLECTION_ABOVE = 499.0
COLLECTION_FEE = 75.0
COLLECT_NOW_FEE = 99.0
REPORT_SECONDS = int(os.environ.get("TRIYANA_LAB_REPORT_SECONDS", "60"))
PAY_METHODS = {"cash": "Cash or UPI at collection", **{m: m for m in INDIA_METHODS}}
OPEN = ("booked", "assigned", "collected", "at_lab")
_gateway = SandboxPaymentGateway()


# ------------------------------------------------------------------ catalog
def test_to_dict(t: LabTest, by_code: dict[str, LabTest] | None = None) -> dict:
    out = {"id": t.id, "code": t.code, "name": t.name, "kind": t.kind, "category": t.category, "about": t.about,
           "sample": t.sample, "fasting_hours": t.fasting_hours, "turnaround_hours": t.turnaround_hours,
           "price": t.price, "mrp": t.mrp, "discount_pct": round(100 * (1 - t.price / t.mrp)) if t.mrp else 0,
           "popular": t.popular, "parameter_count": len(_params(t, by_code or {}))}
    if t.kind == "package" and by_code:
        out["includes"] = [by_code[c].name for c in t.includes if c in by_code]
    return out


def _params(t: LabTest, by_code: dict[str, LabTest]) -> list[dict]:
    if t.kind == "package":
        return [p for c in t.includes if c in by_code for p in by_code[c].parameters]
    return list(t.parameters)


def catalog(db: Session) -> dict:
    tests = db.scalars(select(LabTest).order_by(LabTest.id)).all()
    by_code = {t.code: t for t in tests}
    lab = db.scalars(select(Lab)).first()
    return {"packages": [test_to_dict(t, by_code) for t in tests if t.kind == "package"],
            "tests": [test_to_dict(t, by_code) for t in tests if t.kind == "test"],
            "categories": sorted({t.category for t in tests if t.kind == "test"}),
            "lab": {"name": lab.name, "accreditation": lab.accreditation} if lab else None,
            "fees": {"collection_fee": COLLECTION_FEE, "free_above": FREE_COLLECTION_ABOVE,
                     "collect_now_fee": COLLECT_NOW_FEE},
            "payment_methods": PAY_METHODS}


# ------------------------------------------------------------------ slots
def _local(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)


def _utc(day, hour: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=LOCAL_TZ).astimezone(timezone.utc).replace(tzinfo=None)


def slots(db: Session, fasting_hours: int = 0) -> list[dict]:
    now = utcnow()
    today = _local(now).date()
    taken: dict[datetime, int] = {}
    for b in db.scalars(select(LabBooking).where(LabBooking.status.in_(OPEN), LabBooking.on_demand.is_(False))):
        taken[b.slot_start] = taken.get(b.slot_start, 0) + 1
    out = []
    for d in range(BOOKING_DAYS):
        day = today + timedelta(days=d)
        for h in SLOT_HOURS:
            start = _utc(day, h)
            if start < now + MIN_LEAD:
                continue
            left = SLOT_CAPACITY - taken.get(start, 0)
            out.append({"start": start.isoformat(), "end": (start + timedelta(hours=1)).isoformat(),
                        "available": left > 0, "spots_left": max(left, 0),
                        "fasting_friendly": h < FASTING_HOURS_END,
                        "recommended": bool(fasting_hours) and h < FASTING_HOURS_END})
    return out


# ------------------------------------------------------------------ pricing
def _selected(db: Session, test_ids: list[int]) -> list[LabTest]:
    ids = list(dict.fromkeys(test_ids))
    if not ids:
        raise Unprocessable("no_tests", "Choose at least one test or package.")
    rows = db.scalars(select(LabTest).where(LabTest.id.in_(ids))).all()
    if len(rows) != len(ids):
        raise NotFound("not_found", "One of these tests is no longer available.")
    return sorted(rows, key=lambda t: ids.index(t.id))


def quote(db: Session, test_ids: list[int], on_demand: bool = False) -> dict:
    rows = _selected(db, test_ids)
    by_code = {t.code: t for t in db.scalars(select(LabTest)).all()}
    # Don't charge twice for a test already inside a chosen package.
    in_pkgs = {c for t in rows if t.kind == "package" for c in t.includes}
    dupes = [t for t in rows if t.kind == "test" and t.code in in_pkgs]
    rows = [t for t in rows if t not in dupes]
    subtotal = round(sum(t.price for t in rows), 2)
    mrp = round(sum(t.mrp for t in rows), 2)
    fee = COLLECT_NOW_FEE if on_demand else (0.0 if subtotal >= FREE_COLLECTION_ABOVE else COLLECTION_FEE)
    fasting = max((t.fasting_hours for t in rows), default=0)
    samples = sorted({s.strip() for t in rows for s in (t.sample.split(",") if t.kind == "test" else
                      [by_code[c].sample for c in t.includes if c in by_code]) for s in s.split(",")})
    return {"items": [{"id": t.id, "code": t.code, "name": t.name, "kind": t.kind, "price": t.price, "mrp": t.mrp}
                      for t in rows],
            "removed_duplicates": [t.name for t in dupes], "subtotal": subtotal, "mrp": mrp,
            "savings": round(mrp - subtotal, 2), "collection_fee": fee, "total": round(subtotal + fee, 2),
            "fasting_hours": fasting, "samples": samples,
            "report_hours": max((t.turnaround_hours for t in rows), default=24)}


# ------------------------------------------------------------------ booking
def _event(b: LabBooking, status: str, note: str) -> None:
    b.events = [*(b.events or []), {"at": utcnow().isoformat(), "status": status, "note": note}]


def book(db: Session, user: User, test_ids: list[int], slot: str | None, address: str, payment_method: str,
         payment_token: str = "sandbox-ok") -> LabBooking:
    patient = db.get(Patient, user.patient_id)
    on_demand = not slot or slot == "now"
    q = quote(db, test_ids, on_demand)
    if payment_method not in PAY_METHODS:
        raise Unprocessable("bad_payment_method", "Choose how you'd like to pay.")
    if on_demand:
        if not dispatch.online_count(db, "lab", patient.lat, patient.lng):
            raise Conflict("no_collector_online", "No sample collector is online near you right now. Please pick a time slot.")
        start = utcnow()
    else:
        try:
            start = datetime.fromisoformat(slot.replace("Z", "+00:00"))
        except ValueError:
            raise Unprocessable("bad_slot", "Choose a collection slot.")
        if start.tzinfo:
            start = start.astimezone(timezone.utc).replace(tzinfo=None)
        match = next((s for s in slots(db, q["fasting_hours"]) if s["start"] == start.isoformat()), None)
        if not match:
            raise Unprocessable("bad_slot", "That slot isn't available. Please pick another time.")
        if not match["available"]:
            raise Conflict("slot_full", "That slot just filled up. Please pick another time.")
    lab = min(db.scalars(select(Lab)).all(), key=lambda l: haversine_km(l.lat, l.lng, patient.lat, patient.lng))
    pay_status, pay_ref = "due", ""
    if payment_method != "cash":
        res = _gateway.authorize(payment_method, q["total"], payment_token)
        if not res.ok:
            raise PaymentDeclined("payment_declined", res.message)
        pay_status, pay_ref = "authorized", res.ref
    b = LabBooking(booking_ref=new_ref("LB"), patient_id=patient.id, lab_id=lab.id, items=q["items"],
                   on_demand=on_demand, slot_start=start, address=address.strip() or patient.address,
                   lat=patient.lat, lng=patient.lng, fasting_hours=q["fasting_hours"], subtotal=q["subtotal"],
                   collection_fee=q["collection_fee"], total=q["total"], payment_method=payment_method,
                   payment_status=pay_status, payment_ref=pay_ref, collection_code=f"{secrets.randbelow(10000):04d}")
    db.add(b)
    db.flush()
    _event(b, "booked", "Collection booked" + ("" if on_demand else f" for {_local(start):%d %b, %I:%M %p}"))
    audit.record(db, user, "lab.book", "lab_booking", b.id, on_demand=on_demand, tests=len(q["items"]))
    offer_next(db, b)
    db.commit()
    return b


def _candidates(db: Session, b: LabBooking, online_only: bool) -> list[tuple[User, float]]:
    asked = set(db.scalars(select(DispatchOffer.user_id).where(DispatchOffer.lab_booking_id == b.id)))
    busy_at_slot = set() if b.on_demand else set(db.scalars(select(LabBooking.phlebotomist_user_id).where(
        LabBooking.slot_start == b.slot_start, LabBooking.status.in_(OPEN), LabBooking.id != b.id)))
    out = []
    for u in db.scalars(select(User).where(User.role == Role.phlebotomist)):
        if u.id in asked or u.id in busy_at_slot or (online_only and (not u.on_duty or dispatch._busy(db, u))):
            continue
        plat, plng = dispatch.provider_point(db, u)
        km = round(haversine_km(b.lat, b.lng, plat, plng), 1)
        if km <= RADIUS_KM:
            out.append((u, km))
    return sorted(out, key=lambda r: r[1])


def offer_next(db: Session, b: LabBooking) -> DispatchOffer | None:
    """Offer the booking to the nearest phlebotomist not yet asked. Collect-now offers time out."""
    cands = _candidates(db, b, online_only=b.on_demand)
    if not cands:
        return None
    u, km = cands[0]
    o = DispatchOffer(kind="lab", lab_booking_id=b.id, user_id=u.id, distance_km=km,
                      expires_at=utcnow() + timedelta(seconds=dispatch.OFFER_SECONDS) if b.on_demand else None)
    db.add(o)
    db.flush()
    names = ", ".join(i["name"] for i in b.items[:2]) + (f" +{len(b.items) - 2}" if len(b.items) > 2 else "")
    notify(db, [u], "New sample collection near you" if b.on_demand else "New sample collection booking",
           f"{km} km away · {names}", f"offer:{o.id}")
    return o


def redispatch(db: Session, offer: DispatchOffer) -> None:
    """After a decline or timeout, ask the next nearest collector."""
    b = offer.lab_booking
    if b.status != "booked":
        return
    if offer_next(db, b) is None and b.on_demand:
        _cancel(db, b, "No sample collector is free right now", "Everyone nearby is busy. Nothing was charged. Please book a time slot.")


def on_accept(db: Session, user: User, offer: DispatchOffer) -> None:
    b = offer.lab_booking
    if b.status != "booked":
        raise Conflict("offer_closed", "This collection is no longer available.")
    b.status, b.phlebotomist_user_id = "assigned", user.id
    first = user.name.split(" (")[0]
    _event(b, "assigned", f"{first} will collect your sample")
    if b.on_demand:
        trip = start_trip_to_patient(db, user, b)
        notify(db, users_for_patient(db, b.patient_id), "Your sample collector is on the way",
               f"{first} is heading to you. Arriving in about {math.ceil(trip.duration_s / 60)} min.", f"lab:{b.id}")
    else:
        notify(db, users_for_patient(db, b.patient_id), "Sample collector confirmed",
               f"{first} will collect your sample at {_local(b.slot_start):%I:%M %p, %d %b}.", f"lab:{b.id}")
    audit.record(db, user, "lab.accept", "lab_booking", b.id)


def start_trip_to_patient(db: Session, user: User, b: LabBooking) -> Trip:
    p = db.get(Patient, b.patient_id)
    return dispatch.start_trip(db, user, leg="to_patient", dest=(b.lat, b.lng), dest_label=f"{p.name.split()[0]}'s home",
                               lab_booking_id=b.id)


def _mine(db: Session, user: User, booking_id: int) -> LabBooking:
    b = db.get(LabBooking, booking_id)
    if b is None or b.phlebotomist_user_id != user.id:
        raise NotFound("not_found", "Collection not found.")
    return b


def depart(db: Session, user: User, booking_id: int) -> Trip:
    b = _mine(db, user, booking_id)
    if b.status != "assigned":
        raise Conflict("bad_lab_state", "This collection isn't waiting for you.")
    t = dispatch.active_trip(db, user.id)
    if t and t.lab_booking_id == b.id:
        return t
    trip = start_trip_to_patient(db, user, b)
    _event(b, "on_the_way", "Collector is on the way")
    notify(db, users_for_patient(db, b.patient_id), "Your sample collector is on the way",
           f"{user.name.split(' (')[0]} is heading to you. Follow them live on the map.", f"lab:{b.id}")
    audit.record(db, user, "lab.depart", "lab_booking", b.id)
    db.commit()
    return trip


def collect(db: Session, user: User, booking_id: int, code: str, fasting_confirmed: bool) -> LabBooking:
    """At the door: the patient's 4-digit code proves the right person; tubes get barcodes."""
    b = _mine(db, user, booking_id)
    if b.status != "assigned":
        raise Conflict("bad_lab_state", "This sample was already collected.")
    t = dispatch.active_trip(db, user.id)
    if not (t and t.lab_booking_id == b.id and dispatch.tick(db, t)["remaining_m"] <= 0):
        raise Conflict("not_arrived", "Collect the sample once you've reached the patient.")
    if (code or "").strip() != b.collection_code:
        raise Unprocessable("bad_code", "That collection code doesn't match. Ask the patient for the code in their app.")
    if b.fasting_hours and not fasting_confirmed:
        raise Unprocessable("fasting_unconfirmed", f"Confirm the patient has fasted for {b.fasting_hours} hours.")
    now = utcnow()
    tubes = sorted({s for i in b.items for s in _samples_for(db, i["id"])})
    b.sample_ids = [f"{b.booking_ref[-4:]}-{s[:3].upper()}-{secrets.token_hex(2).upper()}" for s in tubes]
    b.status, b.collected_at = "collected", now
    if b.payment_status == "authorized":
        _gateway.capture(b.payment_ref, b.total)
        b.payment_status = "captured"
    elif b.payment_status == "due":
        b.payment_status = "paid_at_door"
    _event(b, "collected", f"{len(tubes)} sample{'s' if len(tubes) != 1 else ''} collected and sealed")
    lab = b.lab
    dispatch.start_trip(db, user, leg="to_lab", dest=(lab.lat, lab.lng), dest_label=lab.name, lab_booking_id=b.id)
    notify(db, users_for_patient(db, b.patient_id), "Sample collected",
           f"Your sample is on its way to {lab.name}. We'll tell you when your report is ready.", f"lab:{b.id}")
    audit.record(db, user, "lab.collect", "lab_booking", b.id, tubes=len(tubes))
    db.commit()
    return b


def _samples_for(db: Session, test_id: int) -> list[str]:
    t = db.get(LabTest, test_id)
    if t.kind == "package":
        subs = db.scalars(select(LabTest).where(LabTest.code.in_(t.includes))).all()
        return [s.strip() for x in subs for s in x.sample.split(",")]
    return [s.strip() for s in t.sample.split(",")]


def handover(db: Session, user: User, booking_id: int) -> LabBooking:
    b = _mine(db, user, booking_id)
    if b.status != "collected":
        raise Conflict("bad_lab_state", "Collect the sample before handing it to the lab.")
    b.status, b.at_lab_at = "at_lab", utcnow()
    dispatch.end_trips_for(db, lab_booking_id=b.id)
    p = db.get(Patient, b.patient_id)
    pay = collector_pay(b)
    db.add(Earning(user_id=user.id, kind="lab", title=f"Sample collection · {p.name.split()[0]} → lab", base=pay - (50 if b.on_demand else 0),
                   bonus=50 if b.on_demand else 0, total=pay, distance_km=round(haversine_km(b.lat, b.lng, b.lab.lat, b.lab.lng), 1)))
    notify(db, [user], f"You earned ₹{pay:,.0f}", "Sample collection. Added to your balance.", "earnings")
    _event(b, "at_lab", f"Received at {b.lab.name}; testing started")
    notify(db, users_for_patient(db, b.patient_id), "Sample reached the lab",
           f"{b.lab.name} has started your tests.", f"lab:{b.id}")
    audit.record(db, user, "lab.handover", "lab_booking", b.id)
    db.commit()
    return b


def _cancel(db: Session, b: LabBooking, title: str, body: str) -> None:
    b.status = "cancelled"
    if b.payment_status == "authorized":
        _gateway.void(b.payment_ref)
        b.payment_status = "voided"
    for o in db.scalars(select(DispatchOffer).where(DispatchOffer.lab_booking_id == b.id, DispatchOffer.status == "offered")):
        o.status, o.responded_at = "withdrawn", utcnow()
    dispatch.end_trips_for(db, lab_booking_id=b.id)
    _event(b, "cancelled", title)
    notify(db, users_for_patient(db, b.patient_id), title, body, f"lab:{b.id}")


def cancel(db: Session, user: User, booking_id: int) -> LabBooking:
    b = _for_patient(db, user, booking_id)
    if b.status not in ("booked", "assigned"):
        raise Conflict("bad_lab_state", "The sample has already been collected, so this booking can't be cancelled.")
    if b.phlebotomist_user_id:
        notify(db, [db.get(User, b.phlebotomist_user_id)], "Collection cancelled",
               f"{b.booking_ref} was cancelled by the patient.", f"lab:{b.id}")
    _cancel(db, b, "Lab booking cancelled", "Your booking is cancelled and any payment hold has been released.")
    audit.record(db, user, "lab.cancel", "lab_booking", b.id)
    db.commit()
    return b


# ------------------------------------------------------------------ reports
def _report(db: Session, b: LabBooking) -> dict:
    by_code = {t.code: t for t in db.scalars(select(LabTest)).all()}
    rng = random.Random(f"{b.booking_ref}")
    sections = []
    for item in b.items:
        t = db.get(LabTest, item["id"])
        subs = [by_code[c] for c in t.includes if c in by_code] if t.kind == "package" else [t]
        for s in subs:
            rows = []
            for p in s.parameters:
                lo, hi, typ = p.get("low"), p.get("high"), p["typical"]
                # Most results sit in range; now and then one is a little out, as in real life.
                spread = (hi - lo) if lo is not None and hi is not None else abs(typ) * 0.4 or 1
                v = typ + rng.gauss(0, spread * 0.28)
                if v < 0:
                    v = abs(typ) * 0.5
                dp = p.get("dp", 1)
                v = round(v, dp) if dp else int(round(v))
                flag = "low" if lo is not None and v < lo else "high" if hi is not None and v > hi else "normal"
                rows.append({"name": p["name"], "value": v, "unit": p.get("unit", ""), "low": lo, "high": hi,
                             "range": p.get("range") or (f"{lo}–{hi}" if lo is not None and hi is not None
                                                         else f"< {hi}" if hi is not None else f"> {lo}"),
                             "flag": flag})
            sections.append({"code": s.code, "name": s.name, "sample": s.sample, "results": rows})
    flagged = [r["name"] for s in sections for r in s["results"] if r["flag"] != "normal"]
    return {"sections": sections, "flagged": flagged,
            "summary": (f"{len(flagged)} result{'s are' if len(flagged) != 1 else ' is'} outside the reference range: "
                        f"{', '.join(flagged[:5])}. Please discuss them with a doctor.") if flagged
                       else "All results are within the reference range.",
            "lab": {"name": b.lab.name, "accreditation": b.lab.accreditation, "address": b.lab.address},
            "pathologist": "Dr. Kavya Demo, MD (Pathology) · Reg. TSMC-DEMO-70112",
            "reported_at": utcnow().isoformat()}


def sweep(db: Session) -> None:
    """Finish reports whose lab time has passed, and keep looking for collectors for booked slots."""
    now = utcnow()
    changed = False
    for b in db.scalars(select(LabBooking).where(LabBooking.status == "at_lab")):
        if b.at_lab_at and now - b.at_lab_at >= timedelta(seconds=REPORT_SECONDS):
            b.report, b.status, b.report_ready_at = _report(db, b), "report_ready", now
            _event(b, "report_ready", "Report ready")
            n = len(b.report["flagged"])
            notify(db, users_for_patient(db, b.patient_id), "Your lab report is ready",
                   f"{b.booking_ref}: " + (f"{n} result{'s' if n != 1 else ''} to discuss with a doctor." if n
                                           else "all results are in the normal range."), f"lab:{b.id}")
            changed = True
    for b in db.scalars(select(LabBooking).where(LabBooking.status == "booked", LabBooking.on_demand.is_(False))):
        open_offer = db.scalars(select(DispatchOffer.id).where(DispatchOffer.lab_booking_id == b.id,
                                                               DispatchOffer.status == "offered")).first()
        if not open_offer and offer_next(db, b):
            changed = True
    if changed:
        db.commit()


# ------------------------------------------------------------------ views
def _for_patient(db: Session, user: User, booking_id: int) -> LabBooking:
    b = db.get(LabBooking, booking_id)
    if b is None or user.role != Role.patient or b.patient_id != user.patient_id:
        raise NotFound("not_found", "Booking not found.")
    return b


PHASE_LABEL = {"booked": "Finding a sample collector", "assigned": "Collector confirmed", "collected": "Sample collected",
               "at_lab": "Testing at the lab", "report_ready": "Report ready", "cancelled": "Cancelled"}


def booking_to_dict(db: Session, b: LabBooking, *, for_patient: bool = True) -> dict:
    phleb = db.get(User, b.phlebotomist_user_id) if b.phlebotomist_user_id else None
    out = {"id": b.id, "booking_ref": b.booking_ref, "status": b.status, "status_label": PHASE_LABEL.get(b.status, b.status),
           "on_demand": b.on_demand, "slot_start": b.slot_start.isoformat(),
           "slot_end": (b.slot_start + timedelta(hours=1)).isoformat(), "items": b.items, "address": b.address,
           "fasting_hours": b.fasting_hours, "subtotal": b.subtotal, "collection_fee": b.collection_fee, "total": b.total,
           "payment_method": b.payment_method, "payment_label": PAY_METHODS.get(b.payment_method, b.payment_method),
           "payment_status": b.payment_status, "sample_ids": b.sample_ids, "events": b.events,
           "lab": {"name": b.lab.name, "accreditation": b.lab.accreditation},
           "phlebotomist": {"name": phleb.name.split(" (")[0], "vehicle": phleb.vehicle} if phleb else None,
           "created_at": b.created_at.isoformat(), "collected_at": b.collected_at.isoformat() if b.collected_at else None,
           "report_ready": b.report is not None,
           "report_eta": (b.at_lab_at + timedelta(seconds=REPORT_SECONDS)).isoformat() if b.at_lab_at and not b.report else None,
           "can_cancel": b.status in ("booked", "assigned")}
    if for_patient and b.status in ("booked", "assigned"):
        out["collection_code"] = b.collection_code
    return out


def list_for_patient(db: Session, user: User) -> list[dict]:
    dispatch.sweep(db)
    rows = db.scalars(select(LabBooking).where(LabBooking.patient_id == user.patient_id).order_by(LabBooking.id.desc()))
    return [booking_to_dict(db, b) for b in rows]


def get_for_patient(db: Session, user: User, booking_id: int) -> dict:
    dispatch.sweep(db)
    b = _for_patient(db, user, booking_id)
    out = booking_to_dict(db, b)
    p = db.get(Patient, b.patient_id)
    if b.report:
        out["report"] = {**b.report, "patient": {"name": p.name, "ref": p.patient_ref, "dob": p.date_of_birth},
                         "booking_ref": b.booking_ref, "sample_ids": b.sample_ids,
                         "collected_at": b.collected_at.isoformat() if b.collected_at else None}
    return out


def live(db: Session, user: User, booking_id: int) -> dict:
    dispatch.sweep(db)
    b = _for_patient(db, user, booking_id)
    phleb = db.get(User, b.phlebotomist_user_id) if b.phlebotomist_user_id else None
    trip = db.scalars(select(Trip).where(Trip.lab_booking_id == b.id).order_by(Trip.id.desc())).first()
    t = dispatch.trip_to_dict(db, trip) if trip and not trip.ended_at else None
    if b.status == "booked":
        phase = "searching" if b.on_demand else "waiting"
    elif b.status == "assigned":
        phase = ("arrived" if t["arrived"] else "on_the_way") if t else "confirmed"
    elif b.status == "collected":
        phase = "to_lab"
    else:
        phase = {"at_lab": "testing", "report_ready": "done", "cancelled": "cancelled"}[b.status]
    asked = len(set(db.scalars(select(DispatchOffer.user_id).where(DispatchOffer.lab_booking_id == b.id))))
    card = None
    if phleb:
        card = {"name": phleb.name.split(" (")[0], "role": "phlebotomist", "vehicle": phleb.vehicle,
                "rating": 4.8, "specialty": "Certified phlebotomist"}
    return {"kind": "lab", "id": b.id, "booking_ref": b.booking_ref, "status": b.status, "phase": phase,
            "on_demand": b.on_demand, "scheduled_for": b.slot_start.isoformat(),
            "home": {"lat": b.lat, "lng": b.lng, "label": "Home", "address": b.address},
            "pharmacy": {"lat": b.lab.lat, "lng": b.lab.lng, "label": b.lab.name},
            "provider": card, "trip": t, "providers_asked": asked,
            "online_nearby": dispatch.online_count(db, "lab", b.lat, b.lng),
            "provider_location": t["position"] if t else (list(dispatch.provider_point(db, phleb)) if phleb else None),
            "collection_code": b.collection_code if b.status in ("booked", "assigned") else None,
            "items": b.items, "fasting_hours": b.fasting_hours,
            "report_eta": (b.at_lab_at + timedelta(seconds=REPORT_SECONDS)).isoformat() if b.at_lab_at and not b.report else None}


def collector_pay(b: LabBooking) -> float:
    """What the phlebotomist earns per collection: the number shown on the request card."""
    return round(120 + 0.1 * b.subtotal + (50 if b.on_demand else 0), 2)


def offer_fields(db: Session, o: DispatchOffer) -> dict:
    b = o.lab_booking
    p = db.get(Patient, b.patient_id)
    lab_km = round(haversine_km(b.lat, b.lng, b.lab.lat, b.lab.lng), 1)
    return {"title": "Sample collection now" if b.on_demand else "Sample collection booking", "on_demand": b.on_demand,
            "patient": p.name, "address": b.address, "scheduled_for": b.slot_start.isoformat(),
            "reason": " · ".join(i["name"] for i in b.items) + (f" · Fasting {b.fasting_hours} h" if b.fasting_hours else ""),
            "earning": collector_pay(b),
            "dropoff": {"lat": b.lat, "lng": b.lng, "label": p.name},
            "lab": {"lat": b.lab.lat, "lng": b.lab.lng, "label": b.lab.name}, "lab_km": lab_km,
            "drive_min": math.ceil((o.distance_km + lab_km) * 1.3 / dispatch.CITY_KMH * 60 + 10)}


def provider_jobs(db: Session, user: User) -> list[dict]:
    out = []
    q = select(LabBooking).where(LabBooking.phlebotomist_user_id == user.id).order_by(LabBooking.slot_start.desc())
    for b in db.scalars(q):
        p = db.get(Patient, b.patient_id)
        trip = db.scalars(select(Trip).where(Trip.lab_booking_id == b.id, Trip.ended_at.is_(None))).first()
        out.append({"kind": "lab", "id": b.id, "status": b.status, "patient": p.name, "booking_ref": b.booking_ref,
                    "address": b.address, "scheduled_for": b.slot_start.isoformat(), "on_demand": b.on_demand,
                    "reason": " · ".join(i["name"] for i in b.items), "fasting_hours": b.fasting_hours,
                    "trip_id": trip.id if trip else None, "trip_leg": trip.leg if trip else None,
                    "sample_ids": b.sample_ids, "payment_due": b.total if b.payment_status == "due" else 0,
                    "dropoff": {"lat": b.lat, "lng": b.lng, "label": p.name},
                    "lab": {"lat": b.lab.lat, "lng": b.lab.lng, "label": b.lab.name}})
    order = {"assigned": 0, "collected": 1, "at_lab": 2, "report_ready": 3, "cancelled": 4}
    return sorted(out, key=lambda j: order.get(j["status"], 5))


def arrival_notice(db: Session, trip: Trip) -> None:
    b = db.get(LabBooking, trip.lab_booking_id)
    if trip.leg == "to_patient":
        notify(db, users_for_patient(db, b.patient_id), "Your sample collector has arrived",
               "Please open the door and share your 4-digit collection code.", f"lab:{b.id}")
