"""Fictional physiotherapists and a part-done package for the physiotherapy-at-home demo."""
from __future__ import annotations

from datetime import timedelta, timezone

from sqlalchemy.orm import Session

from .models import Earning, Patient, PhysioBooking, PhysioSession, Physiotherapist, Role, User, utcnow

PHYSIO_TOKENS = {
    "physio": "demo-physio-ananya",
    "physio_arun": "demo-physio-arun",
    "physio_meghna": "demo-physio-meghna",
    "physio_unverified": "demo-physio-unverified",
}

COUNCIL = "NCAHP / State Allied & Healthcare Council (demo)"


def seed_physio(db: Session, meera: Patient, arjun: Patient) -> dict:
    priya = Physiotherapist(name="Ananya Rao", qualification="BPT, MPT (Orthopaedics)", registration_no="AHP-TS-DEMO-2207",
                            council=COUNCIL, verified=True, jurisdiction="DEMO-IN",
                            focus=["back_neck", "knee_joint", "post_surgery", "sports"], rating=4.9, rating_count=318,
                            experience_years=8, languages=["English", "Hindi", "Kannada", "Telugu"], gender="female",
                            about="Back, neck and knee pain, and rehab after knee or hip replacement.",
                            lat=17.4415, lng=78.3540, area="Lotus Lane")
    arun = Physiotherapist(name="Arun Kumar", qualification="BPT, MPT (Neurology)", registration_no="AHP-TS-DEMO-1874",
                           council=COUNCIL, verified=True, jurisdiction="DEMO-IN",
                           focus=["stroke_neuro", "elderly", "back_neck"], rating=4.8, rating_count=205,
                           experience_years=11, languages=["English", "Hindi", "Tamil", "Telugu"], gender="male",
                           about="Stroke and Parkinson's rehab, balance and fall prevention for older adults.",
                           lat=17.4560, lng=78.3720, area="Ring Road")
    fatima = Physiotherapist(name="Meghna Iyer", qualification="BPT", registration_no="AHP-TS-DEMO-3302",
                             council=COUNCIL, verified=True, jurisdiction="DEMO-IN",
                             focus=["elderly", "knee_joint", "post_surgery"], rating=4.7, rating_count=96,
                             experience_years=5, languages=["English", "Tamil", "Hindi"], gender="female",
                             about="Gentle home rehab for seniors and women's health physiotherapy.",
                             lat=17.4330, lng=78.3420, area="Lake View")
    pending = Physiotherapist(name="Physio Pending Check", qualification="BPT", registration_no="AHP-TS-DEMO-0000",
                              council=COUNCIL, verified=False, jurisdiction="DEMO-IN", lat=17.4405, lng=78.3495)
    db.add_all([priya, arun, fatima, pending])
    db.flush()
    users = {
        "physio": User(name=priya.name, role=Role.physio, token=PHYSIO_TOKENS["physio"], physio_id=priya.id,
                       on_duty=True, lat=priya.lat, lng=priya.lng, vehicle="Scooter"),
        "physio_arun": User(name=arun.name, role=Role.physio, token=PHYSIO_TOKENS["physio_arun"], physio_id=arun.id,
                            on_duty=True, lat=arun.lat, lng=arun.lng, vehicle="Motorbike"),
        "physio_meghna": User(name=fatima.name, role=Role.physio, token=PHYSIO_TOKENS["physio_meghna"],
                              physio_id=fatima.id, on_duty=False, lat=fatima.lat, lng=fatima.lng, vehicle="Scooter"),
        "physio_unverified": User(name=pending.name, role=Role.physio, token=PHYSIO_TOKENS["physio_unverified"],
                                  physio_id=pending.id),
    }
    db.add_all(users.values())

    # Arjun is part-way through a knee package with Ananya: two sessions done with notes, three to go.
    now = utcnow()
    from .services.physio import LOCAL_TZ, price, slots
    nxt = next(s for s in slots(now) if s >= now + timedelta(hours=12)
               and s.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ).hour == 10)
    pr = price("pack5")
    pkg = PhysioBooking(ref="PT-DEMO0001", patient_id=arjun.id, physio_id=priya.id, condition="knee_joint",
                        details="Right knee pain climbing stairs (fictional)", plan="pack5", sessions_total=5,
                        session_fee=pr["per_session"], price_total=pr["price"], address=arjun.address, status="active",
                        created_at=now - timedelta(days=5))
    db.add(pkg)
    db.flush()
    notes = [
        dict(pain_before=7, pain_after=5, exercises=["Quad sets", "Straight leg raises", "Heel slides", "Ice therapy"],
             notes="Assessment: reduced knee bend (95°), quad weakness, mild swelling. Started gentle strengthening.",
             home_plan="Quad sets 3×10 and heel slides 2×10, twice a day. Ice 15 min after.",
             next_focus="Increase bend to 110°, start mini squats."),
        dict(pain_before=5, pain_after=3, exercises=["Quad sets", "Mini squats", "Step-ups", "Heel slides"],
             notes="Bend now 105°. Stairs easier. Swelling down. Added step-ups with rail support.",
             home_plan="Mini squats 2×10 holding a counter, step-ups 2×8 on the bottom stair, daily.",
             next_focus="Balance work and stair practice without the rail."),
    ]
    for i in range(5):
        when = nxt - timedelta(days=2 * (2 - i)) if i < 2 else nxt + timedelta(days=2 * (i - 2))
        s = PhysioSession(booking_id=pkg.id, number=i + 1, scheduled_for=when.replace(second=0, microsecond=0),
                          status="completed" if i < 2 else "scheduled")
        if i < 2:
            s.started_at, s.completed_at = when, when + timedelta(minutes=45)
            for k, v in notes[i].items():
                setattr(s, k, v)
        db.add(s)
        if i < 2:
            from .services.earnings import physio_pay
            db.flush()
            db.add(Earning(user_id=users["physio"].id, kind="physio", physio_session_id=s.id, base=physio_pay(pkg.session_fee),
                           total=physio_pay(pkg.session_fee), title=f"Physio session {i + 1}/5 · Arjun", distance_km=2.9,
                           earned_at=s.completed_at))
    db.flush()
    return {"physios": {"ananya": priya.id, "arun": arun.id, "meghna": fatima.id, "pending": pending.id},
            "physio_booking": pkg.id}
