"""Doctor's visit notes: what happened at a home visit, the vitals taken, diagnosis and advice.

The assigned doctor writes the note while the visit is in progress or after it is completed.
The patient sees it in their visit history once the visit is completed.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import Conflict, Forbidden, Unprocessable
from ..models import HomeVisit, Prescription, RxStatus, User, VisitNote, VisitStatus
from .common import ensure_visit_doctor, get_or_404, notify, users_for_patient

TEXT_FIELDS = ("chief_complaint", "findings", "diagnosis", "advice")
VITAL_FIELDS = ("temperature_c", "bp_systolic", "bp_diastolic", "pulse_bpm", "spo2_pct", "resp_rate", "weight_kg")

# Plausible ranges: anything outside is almost certainly a typing mistake.
RANGES = {
    "temperature_c": (30.0, 45.0, "Temperature"),
    "bp_systolic": (50, 260, "Systolic BP"),
    "bp_diastolic": (30, 160, "Diastolic BP"),
    "pulse_bpm": (20, 250, "Pulse"),
    "spo2_pct": (50, 100, "SpO2"),
    "resp_rate": (4, 60, "Respiratory rate"),
    "weight_kg": (0.5, 300.0, "Weight"),
}


def f_to_c(f: float) -> float:
    return round((f - 32) * 5 / 9, 2)


def c_to_f(c: float) -> float:
    return round(c * 9 / 5 + 32, 1)


def _validate(data: dict) -> None:
    for k, (lo, hi, label) in RANGES.items():
        v = data.get(k)
        if v is not None and not lo <= v <= hi:
            raise Unprocessable("vital_out_of_range", f"{label} {v} looks wrong. Expected {lo} to {hi}.")
    sys, dia = data.get("bp_systolic"), data.get("bp_diastolic")
    if (sys is None) != (dia is None):
        raise Unprocessable("bp_incomplete", "Enter both numbers of the blood pressure, like 120/80.")
    if sys is not None and dia >= sys:
        raise Unprocessable("bp_order", "Systolic BP (top number) must be higher than diastolic.")
    if not (data.get("chief_complaint") or "").strip():
        raise Unprocessable("no_complaint", "Write the chief complaint (why the patient called the doctor).")


def flags(n: VisitNote) -> list[dict]:
    """Simple adult reference flags so the patient and doctor can spot values worth a second look."""
    out = []
    t = n.temperature_c
    if t is not None:
        if t >= 39.0:
            out.append({"vital": "temperature", "level": "high", "label": "High fever"})
        elif t >= 37.8:
            out.append({"vital": "temperature", "level": "watch", "label": "Fever"})
        elif t < 35.0:
            out.append({"vital": "temperature", "level": "high", "label": "Low temperature"})
    if n.bp_systolic is not None:
        if n.bp_systolic >= 180 or n.bp_diastolic >= 120:
            out.append({"vital": "bp", "level": "high", "label": "Very high BP"})
        elif n.bp_systolic >= 140 or n.bp_diastolic >= 90:
            out.append({"vital": "bp", "level": "watch", "label": "High BP"})
        elif n.bp_systolic < 90:
            out.append({"vital": "bp", "level": "watch", "label": "Low BP"})
    if n.pulse_bpm is not None and (n.pulse_bpm > 100 or n.pulse_bpm < 50):
        out.append({"vital": "pulse", "level": "watch", "label": "Fast pulse" if n.pulse_bpm > 100 else "Slow pulse"})
    if n.spo2_pct is not None and n.spo2_pct < 95:
        out.append({"vital": "spo2", "level": "high" if n.spo2_pct < 92 else "watch", "label": "Low oxygen"})
    if n.resp_rate is not None and (n.resp_rate > 20 or n.resp_rate < 12):
        out.append({"vital": "resp_rate", "level": "watch", "label": "Fast breathing" if n.resp_rate > 20 else "Slow breathing"})
    return out


def _prescriptions(db: Session, visit_id: int, signed_only: bool) -> list[dict]:
    q = select(Prescription).where(Prescription.visit_id == visit_id).order_by(Prescription.id)
    rows = db.scalars(q).all()
    return [{"id": rx.id, "reference_no": rx.reference_no, "status": rx.status.value,
             "items": [f"{i.medication.brand_name} {i.medication.strength}" for i in rx.items]}
            for rx in rows if not signed_only or rx.status in (RxStatus.signed, RxStatus.superseded)]


def note_to_dict(db: Session, n: VisitNote, for_patient: bool = False) -> dict:
    v = n.visit
    return {
        "id": n.id, "visit_id": n.visit_id, "booking_ref": v.booking_ref,
        "visit_date": (v.completed_at or v.scheduled_for).isoformat(),
        "doctor": {"name": n.doctor.name, "specialty": n.doctor.specialty},
        **{k: getattr(n, k) for k in TEXT_FIELDS},
        "follow_up_in_days": n.follow_up_in_days,
        "vitals": {
            "temperature_c": n.temperature_c,
            "temperature_f": c_to_f(n.temperature_c) if n.temperature_c is not None else None,
            "bp": f"{n.bp_systolic}/{n.bp_diastolic}" if n.bp_systolic is not None else None,
            "bp_systolic": n.bp_systolic, "bp_diastolic": n.bp_diastolic,
            "pulse_bpm": n.pulse_bpm, "spo2_pct": n.spo2_pct, "resp_rate": n.resp_rate, "weight_kg": n.weight_kg,
        },
        "flags": flags(n),
        "prescriptions": _prescriptions(db, n.visit_id, signed_only=for_patient),
        "updated_at": n.updated_at.isoformat(),
    }


def _note_for(db: Session, visit_id: int) -> VisitNote | None:
    return db.scalars(select(VisitNote).where(VisitNote.visit_id == visit_id)).first()


def get_for_doctor(db: Session, user: User, visit_id: int) -> dict | None:
    visit = get_or_404(db, HomeVisit, visit_id, "Visit")
    ensure_visit_doctor(user, visit)
    n = _note_for(db, visit_id)
    return note_to_dict(db, n) if n else None


def save(db: Session, user: User, visit_id: int, data: dict, complete: bool = False) -> dict:
    visit = get_or_404(db, HomeVisit, visit_id, "Visit")
    ensure_visit_doctor(user, visit)
    if visit.status not in (VisitStatus.in_progress, VisitStatus.completed):
        raise Conflict("visit_not_started", "Start the visit before writing visit notes.")
    temp_f = data.pop("temperature_f", None)
    if temp_f is not None and data.get("temperature_c") is None:
        if not 86 <= temp_f <= 113:
            raise Unprocessable("vital_out_of_range", f"Temperature {temp_f} °F looks wrong. Expected 86 to 113.")
        data["temperature_c"] = f_to_c(temp_f)
    for k in TEXT_FIELDS:
        data[k] = (data.get(k) or "").strip()
    _validate(data)

    n = _note_for(db, visit_id)
    created = n is None
    if created:
        n = VisitNote(visit_id=visit.id, doctor_id=visit.doctor_id, patient_id=visit.patient_id)
        db.add(n)
    changed = [k for k in (*TEXT_FIELDS, *VITAL_FIELDS, "follow_up_in_days") if getattr(n, k) != data.get(k)]
    for k in (*TEXT_FIELDS, *VITAL_FIELDS, "follow_up_in_days"):
        setattr(n, k, data.get(k))
    db.flush()
    audit.record(db, user, "visit_note.create" if created else "visit_note.update", "home_visit", visit.id,
                 fields=changed)

    if complete and visit.status == VisitStatus.in_progress:
        from .prescriptions import advance_visit  # commits
        advance_visit(db, user, visit.id, "complete")
    if visit.status == VisitStatus.completed and (created or complete):
        notify(db, users_for_patient(db, visit.patient_id), "Your visit notes are ready",
               f"{visit.doctor.name} added notes and vitals from your home visit.", f"visit:{visit.id}")
    db.commit()
    db.refresh(n)
    return note_to_dict(db, n)


def get_for_patient(db: Session, user: User, visit_id: int) -> dict | None:
    visit = get_or_404(db, HomeVisit, visit_id, "Visit")
    from .family import can_view_patient  # family managers see a parent's or child's notes too
    if not can_view_patient(db, user, visit.patient_id):
        raise Forbidden("not_your_visit", "This is not your visit.")
    n = _note_for(db, visit_id)
    if n is None or visit.status != VisitStatus.completed:
        return None
    return note_to_dict(db, n, for_patient=True)


def summary(v: HomeVisit) -> dict | None:
    """Short version for visit lists (patient only sees it once the visit is completed)."""
    n = v.note
    if n is None:
        return None
    return {"diagnosis": n.diagnosis, "chief_complaint": n.chief_complaint, "temperature_c": n.temperature_c,
            "bp": f"{n.bp_systolic}/{n.bp_diastolic}" if n.bp_systolic is not None else None,
            "spo2_pct": n.spo2_pct, "flags": flags(n)}
