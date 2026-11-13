"""SOS: one tap sends the nearest doctor first, tells the family, and hands serious cases to an ambulance.

* The SOS becomes a "Doctor now" visit marked ``sos``. It goes ahead with the nearest online doctor
  however far they are (no 10-minute check), its offer is shown first and expires faster, and if
  nobody takes it the patient is told to call 108.
* Emergency contacts get an SMS with a live tracking link; family accounts that manage the patient
  get it in their app.
* Red-flag symptoms (chest pain, breathing trouble, stroke signs...) mean a doctor at home is not
  enough: the app tells them to call 108 straight away and can request a partner ambulance.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..adapters import ambulance, sms
from ..errors import Conflict, NotFound, Unprocessable
from ..models import DispatchOffer, HomeVisit, Patient, SosAlert, User, utcnow
from . import family
from .common import notify, users_for_doctor, users_for_patient

SOS_OFFER_SECONDS = 30
EMERGENCY_NUMBER = "108"   # India: emergency ambulance
GENERAL_EMERGENCY = "112"  # India: all emergencies

# A doctor at home is not enough for these: call an ambulance now.
RED_FLAGS = {
    "chest_pain": "Chest pain or pressure",
    "breathing": "Severe breathing trouble",
    "unconscious": "Fainted or not responding",
    "stroke": "Face drooping, slurred speech or a weak arm",
    "bleeding": "Heavy bleeding",
    "seizure": "Fit or seizure",
    "injury": "Serious injury or fall",
}
URGENT = {
    "fever": "Very high fever",
    "vomiting": "Vomiting or diarrhoea, can't keep fluids down",
    "sugar": "Very high or very low sugar",
    "bp": "Very high BP or dizziness",
    "pain": "Severe pain",
    "fall": "Fell and can't get up",
    "other": "Something else",
}
LABELS = {**RED_FLAGS, **URGENT}


def options(db: Session, user: User) -> dict:
    fam = family.list_members(db, user)
    return {"red_flags": [{"key": k, "label": v} for k, v in RED_FLAGS.items()],
            "urgent": [{"key": k, "label": v} for k, v in URGENT.items()],
            "members": [{"id": m["id"], "name": m["name"], "relation": m["relation"], "address": m["address"]}
                        for m in fam["members"]],
            "me": fam["me"], "contacts": fam["contacts"],
            "emergency_number": EMERGENCY_NUMBER, "general_emergency": GENERAL_EMERGENCY,
            "ambulance_partner": not ambulance.is_sandbox()}


def trigger(db: Session, user: User, member_id: int | None, symptoms: list[str], note: str = "",
            lat: float | None = None, lng: float | None = None) -> dict:
    patient = family.patient_for(db, user, member_id)
    unknown = [s for s in symptoms if s not in LABELS]
    if unknown:
        raise Unprocessable("bad_symptom", "Pick symptoms from the list.")
    symptoms = list(dict.fromkeys(symptoms))
    serious = any(s in RED_FLAGS for s in symptoms)
    labels = [LABELS[s] for s in symptoms]
    reason = "SOS" + (": " + ", ".join(labels) if labels else ": urgent help requested")
    if note.strip():
        reason += f" · {note.strip()}"
    alert = SosAlert(user_id=user.id, patient_id=patient.id, symptoms=symptoms, note=note.strip()[:300],
                     serious=serious, lat=lat, lng=lng, ambulance_status="advised" if serious else "none")
    db.add(alert)
    db.flush()

    from . import visits  # local import avoids a cycle
    visit = None
    try:
        visit = visits.book_now(db, user, reason[:300], "", member_id=member_id, sos=True)
    except Conflict:  # no doctor online: the family and 108 still matter
        alert.ambulance_status = "advised"
    if visit is not None:
        alert.visit_id = visit.id
        for o in db.scalars(select(DispatchOffer).where(DispatchOffer.visit_id == visit.id,
                                                        DispatchOffer.status == "offered")):
            o.expires_at = utcnow() + timedelta(seconds=SOS_OFFER_SECONDS)
    else:
        notify(db, users_for_patient(db, patient.id), "SOS sent: no doctor online nearby",
               f"No Triyana doctor is online near {patient.address}. Call {EMERGENCY_NUMBER} for an ambulance now.",
               f"sos:{alert.id}")

    # Tell the family: SMS with a live tracking link to each emergency contact.
    link = family.create_share(db, user, visit, label="SOS alert", commit=False)["url"] if visit else None
    who = patient.name.split(" ")[0]
    text = (f"Triyana SOS: {user.name} asked for urgent help for {patient.name if patient.id != user.patient_id else 'themselves'}"
            f"{' (' + ', '.join(labels) + ')' if labels else ''}. "
            + (f"The nearest doctor is being sent to {who}'s home. Follow live: {link}" if link
               else f"No doctor is online nearby; please call {who} or {EMERGENCY_NUMBER}."))
    alerted = []
    for c in family.contacts_for(db, user):
        status = sms.send_text(c.phone, text[:600])
        alerted.append({"name": c.name, "relation": c.relation, "channel": "sms", "status": status})
    for u in users_for_patient(db, patient.id):
        if u.id != user.id:
            alerted.append({"name": u.name, "relation": family.relation_for(db, u, patient.id) or "",
                            "channel": "app", "status": "sent"})
    alert.contacts_alerted = alerted
    audit.record(db, user, "sos.trigger", "sos_alert", alert.id, visit_id=alert.visit_id, serious=serious,
                 symptoms=symptoms, alerted=len(alerted))
    db.commit()
    return to_dict(db, alert)


def _alert_or_404(db: Session, user: User, sos_id: int) -> SosAlert:
    a = db.get(SosAlert, sos_id)
    if a is None or not family.can_view_patient(db, user, a.patient_id):
        raise NotFound("not_found", "SOS not found.")
    return a


def get(db: Session, user: User, sos_id: int) -> dict:
    return to_dict(db, _alert_or_404(db, user, sos_id))


def ambulance_action(db: Session, user: User, sos_id: int, action: str) -> dict:
    """``request``: ask the partner ambulance to come. ``called``: the patient rang 108 themselves."""
    a = _alert_or_404(db, user, sos_id)
    p = db.get(Patient, a.patient_id)
    if action == "called":
        a.ambulance_status = "called"
    elif action == "request":
        if a.ambulance_status == "requested":
            raise Conflict("already_requested", "An ambulance has already been requested.")
        res = ambulance.request(a.lat or p.lat, a.lng or p.lng, p.address, p.name,
                                ", ".join(LABELS[s] for s in a.symptoms) or "SOS")
        if res["status"] != "requested":
            raise Conflict("ambulance_unavailable", f"We couldn't reach the ambulance partner. Call {EMERGENCY_NUMBER} now.")
        a.ambulance_status, a.ambulance_ref = "requested", res["ref"]
    else:
        raise NotFound("not_found", "Unknown action.")
    v = db.get(HomeVisit, a.visit_id) if a.visit_id else None
    if v is not None and v.doctor_id:  # the doctor on the way should know an ambulance is coming too
        notify(db, users_for_doctor(db, v.doctor_id), "Ambulance on the way to your SOS patient",
               f"{p.name}'s family {'called ' + EMERGENCY_NUMBER if action == 'called' else 'requested an ambulance'}. "
               "Stabilise and hand over when it arrives.", f"visit:{v.id}")
    notify(db, [u for u in users_for_patient(db, p.id) if u.id != user.id], "Ambulance requested",
           f"An ambulance is on the way to {p.name}.", f"sos:{a.id}")
    audit.record(db, user, f"sos.ambulance.{action}", "sos_alert", a.id, ref=a.ambulance_ref)
    db.commit()
    return to_dict(db, a)


def to_dict(db: Session, a: SosAlert) -> dict:
    p = db.get(Patient, a.patient_id)
    v = db.get(HomeVisit, a.visit_id) if a.visit_id else None
    return {"id": a.id, "visit_id": a.visit_id, "serious": a.serious,
            "symptoms": [{"key": s, "label": LABELS.get(s, s), "red_flag": s in RED_FLAGS} for s in a.symptoms],
            "patient": {"id": p.id, "name": p.name, "address": p.address},
            "doctor_status": (v.status.value if v else "none_online"),
            "contacts_alerted": a.contacts_alerted or [],
            "ambulance": {"status": a.ambulance_status, "ref": a.ambulance_ref, "partner": not ambulance.is_sandbox(),
                          "number": EMERGENCY_NUMBER},
            "emergency_number": EMERGENCY_NUMBER, "general_emergency": GENERAL_EMERGENCY,
            "created_at": a.created_at.isoformat() + "Z"}


def for_visit(db: Session, v: HomeVisit) -> dict | None:
    if not v.sos:
        return None
    a = db.scalars(select(SosAlert).where(SosAlert.visit_id == v.id)).first()
    return to_dict(db, a) if a else None
