"""Specialist doctors at home: eye, ear-nose-throat and teeth.

Every doctor has a `care_type`. "general" doctors (the default, and every doctor from before this
existed) do the 10-minute "Doctor now" visits and general bookings. Specialists come for a home visit
at a time the patient books: they bring portable kits (vision charts and a handheld slit lamp, an
otoscope, a portable dental unit), so they are matched only to bookings of their own kind and never
to the 10-minute dispatch.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import Unprocessable

GENERAL = "general"

CARE_TYPES: dict[str, dict] = {
    GENERAL: {
        "label": "General doctor", "short": "Doctor", "formal": "General physician",
        "specialty": "General Medicine", "qualification": "MBBS", "icon": "stethoscope",
        "council_hint": "State Medical Council or NMC", "from_fee": 500,
        "reasons": [["Fever or cold", "bolt"], ["General check-up", "stethoscope"], ["Child is unwell", "user"],
                    ["Elderly parent care", "shield"], ["Joint or back pain", "pin"], ["Follow-up visit", "calendar"]],
    },
    "eye": {
        "label": "Eye doctor", "short": "Eye", "formal": "Ophthalmologist",
        "specialty": "Eye (Ophthalmology)", "qualification": "MBBS, MS (Ophthalmology)", "icon": "eye",
        "council_hint": "State Medical Council or NMC", "from_fee": 800,
        "reasons": [["Red or itchy eyes", "eye"], ["Blurred vision", "eye"], ["Eye check-up", "stethoscope"],
                    ["Glasses check", "eye"], ["Elderly eye care", "shield"], ["Follow-up visit", "calendar"]],
        "at_home": "Vision test, eye pressure check and a full eye exam with a portable lamp.",
    },
    "ent": {
        "label": "Ear, nose & throat doctor", "short": "Ear & nose", "formal": "ENT specialist",
        "specialty": "Ear, Nose & Throat (ENT)", "qualification": "MBBS, MS (ENT)", "icon": "ear",
        "council_hint": "State Medical Council or NMC", "from_fee": 800,
        "reasons": [["Ear pain or blocked ear", "ear"], ["Ear wax cleaning", "ear"], ["Blocked or runny nose", "bolt"],
                    ["Sore throat", "chat"], ["Hearing check", "ear"], ["Follow-up visit", "calendar"]],
        "at_home": "Ear, nose and throat exam with a scope, ear wax cleaning and a simple hearing check.",
    },
    "dental": {
        "label": "Dentist", "short": "Teeth", "formal": "Dentist",
        "specialty": "Teeth (Dental Surgery)", "qualification": "BDS", "icon": "tooth",
        "council_hint": "State Dental Council or DCI", "from_fee": 700,
        "reasons": [["Toothache", "tooth"], ["Teeth cleaning", "tooth"], ["Dental check-up", "stethoscope"],
                    ["Bleeding gums", "tooth"], ["Denture problem", "shield"], ["Follow-up visit", "calendar"]],
        "at_home": "Check-up, cleaning and small fixes with a portable dental kit. Anything bigger is booked at a clinic.",
    },
}


def normalise(care_type: str | None) -> str:
    """Unknown or missing values mean a general doctor (doctors from before specialists existed)."""
    return care_type if care_type in CARE_TYPES else GENERAL


def check(care_type: str | None) -> str:
    if care_type is None or care_type == "":
        return GENERAL
    if care_type not in CARE_TYPES:
        raise Unprocessable("bad_care_type", "Choose general, eye, ENT or dental.")
    return care_type


def of_doctor(doc) -> str:
    return normalise(getattr(doc, "care_type", None))


def of_visit(visit) -> str:
    return normalise(getattr(visit, "care_type", None))


def public() -> list[dict]:
    """What the apps show: labels, reasons and starting fees for each kind of doctor."""
    return [{"key": k, **{f: v for f, v in c.items()}} for k, c in CARE_TYPES.items()]


def label(care_type: str | None) -> str:
    return CARE_TYPES[normalise(care_type)]["label"]


# ------------------------------------------------------------------ demo data
DEMO_SPECIALISTS = [
    # (persona key, token, care type, name, licence, council, qualification, years, fee, rating, count,
    #  languages, about, lat, lng, area)
    ("doctor_kavya", "demo-doctor-kavya", "eye", "Dr. Kavya Iyer", "TSMC-DEMO-70411", "Telangana State Medical Council (demo)",
     "MBBS, MS (Ophthalmology)", 10, 900, 4.9, 214, ["English", "Hindi", "Tamil"],
     "Eye check-ups, red eyes, vision tests and eye care for elders, at home.", 17.4470, 78.3610, "Lotus Lane"),
    ("doctor_farhan", "demo-doctor-farhan", "ent", "Dr. Farhan Ali", "TSMC-DEMO-70522", "Telangana State Medical Council (demo)",
     "MBBS, MS (ENT)", 8, 850, 4.8, 156, ["English", "Hindi", "Urdu", "Telugu"],
     "Ear pain, ear wax cleaning, blocked nose, sinus and sore throat, at home.", 17.4350, 78.3450, "Lake View"),
    ("doctor_nisha", "demo-doctor-nisha", "dental", "Dr. Nisha Reddy", "TSDC-DEMO-70633", "Telangana State Dental Council (demo)",
     "BDS, MDS (Conservative Dentistry)", 7, 750, 4.8, 189, ["English", "Telugu", "Hindi"],
     "Toothache, cleaning, check-ups and denture care, with a portable dental kit.", 17.4520, 78.3530, "Banyan Road"),
]


def seed_demo(db: Session) -> dict[str, str]:
    """Add one demo eye doctor, ENT doctor and dentist near the demo patients. Safe to run again."""
    from ..models import Doctor, Role, User
    tokens = {}
    for (key, token, care, name, lic, council, qual, years, fee, rating, count, langs, about, lat, lng,
         area) in DEMO_SPECIALISTS:
        tokens[key] = token
        if db.scalars(select(Doctor).where(Doctor.license_no == lic)).first():
            continue
        doc = Doctor(name=name, care_type=care, specialty=CARE_TYPES[care]["specialty"], license_no=lic,
                     license_verified=True, medical_council=council, qualification=qual,
                     registration_year=2026 - years, jurisdiction="DEMO-IN", rating=rating, rating_count=count,
                     experience_years=years, visit_fee=fee, languages=langs, about=about, lat=lat, lng=lng, area=area)
        db.add(doc)
        db.flush()
        db.add(User(name=name, role=Role.doctor, token=token, doctor_id=doc.id, on_duty=True,
                    lat=lat, lng=lng, vehicle="Car"))
    db.flush()
    return tokens
