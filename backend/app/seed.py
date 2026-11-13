"""Fictional demonstration data. No real patients, doctors, pharmacies or payments."""
from __future__ import annotations


from datetime import timedelta

from sqlalchemy.orm import Session

from .seed_physio import PHYSIO_TOKENS, seed_physio
from .models import (
    AirspaceZone,
    DispatchOffer,
    Doctor,
    Hospital,
    DoctorAvailability,
    HomeVisit,
    VisitNote,
    Medication,
    MedSchedule,
    Patient,
    Pharmacy,
    PharmacyInventory,
    Role,
    User,
    VisitStatus,
    utcnow,
)

DEMO_TOKENS = {
    "patient": "demo-patient-meera",
    "patient2": "demo-patient-arjun",
    "doctor": "demo-doctor-carter",
    "doctor_unverified": "demo-doctor-unverified",
    "pharmacist": "demo-pharmacist-greenleaf",
    "pharmacist2": "demo-pharmacist-sunrise",
    "courier": "demo-courier-greenleaf",
    "hospital": "demo-hospital-lotus",
    "hospital2": "demo-hospital-district",
    "courier2": "demo-courier-kiran",
    "doctor_rohan": "demo-doctor-rohan",
    "doctor_sana": "demo-doctor-sana",
    "doctor_vikram": "demo-doctor-vikram",
    "phlebotomist": "demo-phlebotomist-priya",
    "phlebotomist2": "demo-phlebotomist-suresh",
    "phlebotomist3": "demo-phlebotomist-fatima",
}
DEMO_TOKENS.update(PHYSIO_TOKENS)


def seed(db: Session) -> dict:
    now = utcnow()
    meera = Patient(name="Meera Demo", patient_ref="PT-DEMO-001", date_of_birth="1990-04-12",
                    address="12 Lotus Lane, Demo City", lat=17.4400, lng=78.3489, jurisdiction="DEMO-IN")
    arjun = Patient(name="Arjun Sample", patient_ref="PT-DEMO-002", date_of_birth="1985-09-30",
                    address="88 Banyan Road, Demo City", lat=17.4500, lng=78.3800, jurisdiction="DEMO-IN")
    carter = Doctor(name="Dr. Emily Carter", specialty="General Medicine", license_no="TSMC-DEMO-55821", medical_council="Telangana State Medical Council (demo)",
                   qualification="MBBS, MD (General Medicine)", registration_year=2013,
                   license_verified=True, jurisdiction="DEMO-IN", rating=4.9, rating_count=412,
                   experience_years=12, visit_fee=600, languages=["English", "Hindi", "Telugu"],
                   about="Fever, infections, BP and sugar checks, and everyday family care at home.",
                   lat=17.4460, lng=78.3560, area="Lotus Lane clinic")
    unverified = Doctor(name="Dr. Pending Check", specialty="General Medicine", license_no="TSMC-DEMO-00000", medical_council="Telangana State Medical Council (demo)",
                   qualification="MBBS", registration_year=2024,
                        license_verified=False, jurisdiction="DEMO-IN", rating=0)
    others = [
        Doctor(name="Dr. Rohan Example", specialty="Child Health (Paediatrics)", license_no="TSMC-DEMO-61204", medical_council="Telangana State Medical Council (demo)",
                   qualification="MBBS, MD (Paediatrics)", registration_year=2016,
               license_verified=True, jurisdiction="DEMO-IN", rating=4.8, rating_count=268, experience_years=9,
               visit_fee=700, languages=["English", "Hindi"],
               about="Home visits for babies and children: fever, coughs, colds and growth checks.",
               lat=17.4290, lng=78.3380, area="Lake View"),
        Doctor(name="Dr. Sana Sample", specialty="Elderly Care (Geriatrics)", license_no="NMC-DEMO-47719", medical_council="National Medical Commission (demo)",
                   qualification="MBBS, MD (Geriatrics)", registration_year=2010,
               license_verified=True, jurisdiction="DEMO-IN", rating=4.9, rating_count=530, experience_years=15,
               visit_fee=800, languages=["English", "Urdu", "Telugu"],
               about="Care for parents and grandparents at home: BP, diabetes, mobility and medicine reviews.",
               lat=17.4620, lng=78.3720, area="Ring Road"),
        Doctor(name="Dr. Vikram Demo", specialty="Bones & Joints (Orthopaedics)", license_no="KMC-DEMO-58833", medical_council="Karnataka Medical Council (demo)",
                   qualification="MBBS, MS (Orthopaedics)", registration_year=2014,
               license_verified=True, jurisdiction="DEMO-IN", rating=4.7, rating_count=190, experience_years=11,
               visit_fee=900, languages=["English", "Hindi", "Kannada"],
               about="Back, knee and joint pain, sprains and post-surgery follow-ups at home.",
               lat=17.4880, lng=78.4010, area="Hill Park"),
    ]
    db.add_all([meera, arjun, carter, unverified, *others])
    db.flush()

    meds = {
        "dolo": Medication(category="Fever & pain", description="Paracetamol for fever and pain. Prescription only in this demo.", india_schedule="H", brand_name="Dolo", generic_name="Paracetamol", strength="650 mg", form="tablet",
                           unit="tablets", schedule=MedSchedule.rx, pack_sizes=[1, 15], loose_units_allowed=True,
                           reference_unit_price=2.0),
        "cetri": Medication(category="Cold & allergy", description="Non-drowsy allergy relief for sneezing, runny nose and itchy eyes.", india_schedule="OTC", brand_name="Cetrizet", generic_name="Cetirizine", strength="10 mg", form="tablet",
                            unit="tablets", schedule=MedSchedule.otc, pack_sizes=[10], loose_units_allowed=False,
                            reference_unit_price=1.8),
        "amoxi": Medication(category="Antibiotics", description="Antibiotic. Only with a doctor's prescription.", india_schedule="H1", brand_name="Amoxidemo", generic_name="Amoxicillin", strength="500 mg", form="capsule",
                            unit="capsules", schedule=MedSchedule.restricted, pack_sizes=[1, 10],
                            loose_units_allowed=True, reference_unit_price=6.5),
        "trama": Medication(category="Pain relief", description="Strong pain medicine with extra controls.", india_schedule="H1", brand_name="Tramademo", generic_name="Tramadol", strength="50 mg", form="tablet",
                            unit="tablets", schedule=MedSchedule.controlled, pack_sizes=[10],
                            loose_units_allowed=False, id_check_required=True, reference_unit_price=9.0),
        "insu": Medication(category="Diabetes", description="Long-acting insulin pen. Kept cold all the way to your door.", india_schedule="H", brand_name="Insudemo Pen", generic_name="Insulin glargine", strength="100 IU/ml",
                           form="pen", unit="pens", schedule=MedSchedule.rx, pack_sizes=[1, 5],
                           loose_units_allowed=True, cold_chain=True, reference_unit_price=420.0),
        "panto": Medication(category="Digestive care", description="Reduces stomach acid. Prescription only.", india_schedule="H", brand_name="Pantodemo", generic_name="Pantoprazole", strength="40 mg", form="tablet",
                            unit="tablets", schedule=MedSchedule.rx, pack_sizes=[1, 15], loose_units_allowed=True,
                            reference_unit_price=3.2),
        "rita": Medication(category="Restricted", description="Schedule X. Not sold online.", india_schedule="X", brand_name="Ritademo", generic_name="Methylphenidate", strength="10 mg",
                           form="tablet", unit="tablets", schedule=MedSchedule.controlled, pack_sizes=[10],
                           loose_units_allowed=False, id_check_required=True, reference_unit_price=12.0),
    }
    # Over-the-counter products for the online shop (fictional brands, illustrative demo prices).
    def otc(brand, generic, strength, form, unit, pack, price, category, description):
        return Medication(india_schedule="OTC", brand_name=brand, generic_name=generic, strength=strength, form=form,
                          unit=unit, schedule=MedSchedule.otc, pack_sizes=[pack], loose_units_allowed=False,
                          reference_unit_price=price, category=category, description=description)

    meds.update({
        "ors": otc("Hydrademo ORS", "Oral rehydration salts", "21 g", "sachet", "sachets", 5, 21.0, "Digestive care",
                   "WHO-formula ORS to replace fluids and salts lost through diarrhoea, vomiting or heat."),
        "antacid": otc("Gelademo Antacid", "Aluminium + magnesium hydroxide", "170 ml", "liquid", "bottles", 1, 112.0,
                       "Digestive care", "Fast relief from acidity, heartburn and gas. Mint flavour."),
        "vitc": otc("Vitademo C", "Vitamin C (ascorbic acid)", "500 mg", "chewable tablet", "tablets", 15, 2.4,
                    "Vitamins & nutrition", "Orange-flavoured chewable vitamin C for everyday immunity support."),
        "multi": otc("Dailydemo Multivitamin", "Multivitamin + minerals", "1 tablet", "tablet", "tablets", 30, 5.5,
                     "Vitamins & nutrition", "A once-a-day multivitamin with zinc, iron and B-complex."),
        "lozenge": otc("Throatdemo Lozenges", "Amylmetacresol + dichlorobenzyl alcohol", "honey lemon", "lozenge",
                       "lozenges", 8, 4.0, "Cold & allergy", "Soothes a sore, scratchy throat. Honey lemon flavour."),
        "steam": otc("Breathdemo Vapour Rub", "Menthol + camphor + eucalyptus oil", "25 g", "balm", "jars", 1, 95.0,
                     "Cold & allergy", "Rub on chest and back for blocked-nose relief from colds."),
        "gel": otc("Reliefdemo Pain Gel", "Diclofenac diethylamine 1.16%", "30 g", "gel", "tubes", 1, 145.0,
                   "Pain relief", "Rub-on gel for back, neck, knee and muscle pain."),
        "antiseptic": otc("Germidemo Antiseptic", "Chloroxylenol", "100 ml", "liquid", "bottles", 1, 86.0, "First aid",
                          "Antiseptic liquid for cuts, scrapes and personal hygiene."),
        "bandage": otc("Healdemo Bandages", "Sterile adhesive strips", "assorted", "strip", "strips", 20, 2.5, "First aid",
                       "Breathable, water-resistant strips for small cuts."),
        "thermo": otc("Thermodemo Digital Thermometer", "Digital thermometer", "1 unit", "device", "units", 1, 199.0,
                      "Devices & hygiene", "Reads in about 60 seconds, with a fever beep and memory of the last reading."),
        "sanitiser": otc("Cleandemo Hand Sanitiser", "Ethyl alcohol 70%", "200 ml", "gel", "bottles", 1, 99.0,
                         "Devices & hygiene", "Kills 99.9% of germs without water."),
    })
    db.add_all(meds.values())
    db.flush()

    pharmacies = [
        Pharmacy(name="GreenLeaf Pharmacy (Demo)", license_no="DEMO-PH-1001", license_verified=True,
                 business_reg_no="DEMO-GST-11", jurisdiction="DEMO-IN", address="4 Market St, Demo City",
                 lat=17.4430, lng=78.3520, service_radius_km=8, opens_at=0, closes_at=24, rating=4.8,
                 rating_count=1240, delivery_fee=30, prep_minutes=20, allows_partial_dispensing=True,
                 delivery_options=["standard", "same_day", "priority", "scheduled", "drone"], integration="mock-live",
                 drone_pad=True),
        Pharmacy(name="Sunrise Chemists (Demo)", license_no="DEMO-PH-1002", license_verified=True,
                 business_reg_no="DEMO-GST-12", jurisdiction="DEMO-IN", address="210 Ring Rd, Demo City",
                 lat=17.4650, lng=78.3700, service_radius_km=10, opens_at=0, closes_at=24, rating=4.4,
                 rating_count=530, delivery_fee=15, prep_minutes=45, allows_partial_dispensing=True,
                 delivery_options=["standard", "same_day", "scheduled", "drone"], integration="mock-live",
                 drone_pad=True),
        Pharmacy(name="WholePack Pharmacy (Demo)", license_no="DEMO-PH-1003", license_verified=True,
                 business_reg_no="DEMO-GST-13", jurisdiction="DEMO-IN", address="9 Lake View, Demo City",
                 lat=17.4300, lng=78.3400, service_radius_km=6, opens_at=0, closes_at=24, rating=4.6,
                 rating_count=310, delivery_fee=25, prep_minutes=30, allows_partial_dispensing=False,
                 delivery_options=["standard"], integration="mock-catalog"),
        Pharmacy(name="Unverified Meds (Demo)", license_no="DEMO-PH-9999", license_verified=False,
                 business_reg_no="-", jurisdiction="DEMO-IN", address="Unknown", lat=17.4401, lng=78.3490,
                 service_radius_km=50, opens_at=0, closes_at=24, rating=5.0, rating_count=3, delivery_fee=0,
                 delivery_options=["standard"]),
    ]
    db.add_all(pharmacies)

    # Fictional airspace map in the style of the Drone Rules 2021 zones (green = everywhere else).
    db.add_all([
        AirspaceZone(name="Demo City Airport (fictional) perimeter", kind="red", lat=17.452, lng=78.475,
                     radius_km=3.0, authority="Central government permission only"),
        AirspaceZone(name="Demo City Airport (fictional) approach", kind="yellow", lat=17.452, lng=78.475,
                     radius_km=12.0, authority="Airport ATC permission via Digital Sky"),
        AirspaceZone(name="Demo Cantonment (fictional) defence area", kind="red", lat=17.425, lng=78.31,
                     radius_km=1.5, authority="Ministry of Defence"),
    ])
    hospitals = {
        "lotus": Hospital(name="Lotus Multi-Speciality Hospital (Demo)", kind="multi_speciality",
                          registration_no="DEMO-CEA-TS-0101", verified=True, jurisdiction="DEMO-IN",
                          address="1 Lotus Lane, Demo City", lat=17.4475, lng=78.3420, drone_pad=True, cold_storage=True),
        "district": Hospital(name="Demo City District Hospital", kind="district", registration_no="DEMO-CEA-TS-0102",
                             verified=True, jurisdiction="DEMO-IN", address="District Rd, Demo City",
                             lat=17.4950, lng=78.3300, drone_pad=True, cold_storage=True),
        "children": Hospital(name="Ring Road Children's Hospital (Demo)", kind="specialty",
                             registration_no="DEMO-CEA-TS-0103", verified=True, jurisdiction="DEMO-IN",
                             address="Ring Rd East, Demo City", lat=17.4700, lng=78.4300, drone_pad=True,
                             cold_storage=True),
        "lakeside": Hospital(name="Lakeside Cancer Centre (Demo)", kind="specialty", registration_no="DEMO-CEA-TS-0104",
                             verified=True, jurisdiction="DEMO-IN", address="Lakeside, Demo City",
                             lat=17.4000, lng=78.2800, drone_pad=True, cold_storage=True),
        "hillpark": Hospital(name="Hill Park Rural PHC (Demo)", kind="phc", registration_no="DEMO-CEA-TS-0105",
                             verified=True, jurisdiction="DEMO-IN", address="Hill Park village, Demo District",
                             lat=17.7000, lng=78.2000, drone_pad=True, cold_storage=False),
        "riverside": Hospital(name="Riverside Nursing Home (Demo)", kind="multi_speciality",
                              registration_no="DEMO-CEA-TS-0106", verified=True, jurisdiction="DEMO-IN",
                              address="River Rd, Demo City", lat=17.4250, lng=78.3550, drone_pad=False,
                              cold_storage=False),
    }
    db.add_all(hospitals.values())
    db.flush()
    stock = {
        0: {"dolo": (200, 1.9), "cetri": (100, 1.7), "amoxi": (60, 6.2), "trama": (20, 8.5), "insu": (10, 410.0), "panto": (90, 3.0), "rita": (20, 11.0)},
        1: {"dolo": (150, 1.6), "cetri": (80, 1.5), "amoxi": (40, 6.0), "insu": (4, 399.0), "panto": (50, 2.9)},
        2: {"dolo": (300, 1.5), "cetri": (100, 1.4), "amoxi": (100, 5.5), "panto": (100, 2.6)},
        3: {"dolo": (999, 0.5), "cetri": (999, 0.5)},
    }
    # Shop stock: GreenLeaf carries everything, Sunrise most things, WholePack the basics.
    shop_stock = {
        0: ("ors", "antacid", "vitc", "multi", "lozenge", "steam", "gel", "antiseptic", "bandage", "thermo", "sanitiser"),
        1: ("ors", "antacid", "vitc", "multi", "lozenge", "gel", "antiseptic", "bandage", "sanitiser"),
        2: ("ors", "antacid", "vitc", "bandage", "antiseptic"),
    }
    for idx, keys in shop_stock.items():
        for key in keys:
            ref = meds[key].reference_unit_price
            stock[idx][key] = (60 * max(meds[key].pack_sizes), round(ref * (1.0, 0.95, 0.92)[idx], 2))
    for idx, items in stock.items():
        ph = pharmacies[idx]
        for key, (units, price) in items.items():
            db.add(PharmacyInventory(pharmacy_id=ph.id, medication_id=meds[key].id, units_in_stock=units,
                                     unit_price=price, verified_at=now if ph.integration == "mock-live" else None))

    users = {
        "patient": User(name=meera.name, role=Role.patient, token=DEMO_TOKENS["patient"], patient_id=meera.id),
        "patient2": User(name=arjun.name, role=Role.patient, token=DEMO_TOKENS["patient2"], patient_id=arjun.id),
        "doctor": User(name=carter.name, role=Role.doctor, token=DEMO_TOKENS["doctor"], doctor_id=carter.id),
        "doctor_unverified": User(name=unverified.name, role=Role.doctor, token=DEMO_TOKENS["doctor_unverified"],
                                  doctor_id=unverified.id),
        "pharmacist": User(name="Ravi (Pharmacist, GreenLeaf)", role=Role.pharmacist,
                           token=DEMO_TOKENS["pharmacist"], pharmacy_id=pharmacies[0].id),
        "pharmacist2": User(name="Lina (Pharmacist, Sunrise)", role=Role.pharmacist,
                            token=DEMO_TOKENS["pharmacist2"], pharmacy_id=pharmacies[1].id),
        "courier": User(name="Asha (Courier, GreenLeaf)", role=Role.courier, token=DEMO_TOKENS["courier"],
                        pharmacy_id=pharmacies[0].id, on_duty=True, lat=17.4425, lng=78.3530, vehicle="Scooter"),
        "courier2": User(name="Kiran (Triyana courier)", role=Role.courier, token=DEMO_TOKENS["courier2"],
                         on_duty=True, lat=17.4560, lng=78.3650, vehicle="Motorbike"),
        "hospital": User(name="Nisha (Pharmacy in-charge, Lotus Hospital)", role=Role.hospital,
                         token=DEMO_TOKENS["hospital"], hospital_id=hospitals["lotus"].id),
        "hospital2": User(name="Dev (Stores, District Hospital)", role=Role.hospital,
                          token=DEMO_TOKENS["hospital2"], hospital_id=hospitals["district"].id),
    }
    # Provider app: doctors start online at their clinics (Dr. Sana starts offline).
    carter_user = users["doctor"]
    carter_user.on_duty, carter_user.lat, carter_user.lng, carter_user.vehicle = True, carter.lat, carter.lng, "Car"
    for key, doc, online in (("doctor_rohan", others[0], True), ("doctor_sana", others[1], False),
                             ("doctor_vikram", others[2], True)):
        users[key] = User(name=doc.name, role=Role.doctor, token=DEMO_TOKENS[key], doctor_id=doc.id,
                          on_duty=online, lat=doc.lat, lng=doc.lng, vehicle="Car")
    db.add_all(users.values())
    db.flush()
    from .services.earnings import seed_history
    seed_history(db, users)

    from .services.visits import _all_slots, _local_days  # aligned to real bookable slots
    slots = _all_slots(now)
    visit = HomeVisit(doctor_id=carter.id, patient_id=meera.id, status=VisitStatus.requested,
                      reason="Fever and body ache (fictional)", scheduled_for=slots[0],
                      booking_ref="BK-DEMO0001", fee=carter.visit_fee, address=meera.address)
    visit2 = HomeVisit(doctor_id=carter.id, patient_id=arjun.id, status=VisitStatus.requested,
                       reason="Follow-up (fictional)", scheduled_for=slots[2],
                       booking_ref="BK-DEMO0002", fee=carter.visit_fee, address=arjun.address)
    visit3 = HomeVisit(doctor_id=unverified.id, patient_id=arjun.id, status=VisitStatus.in_progress,
                       reason="(fictional)", scheduled_for=now)
    # Past visits, so "book a follow-up" can suggest the same doctor again.
    sana = others[1]
    past_meera = HomeVisit(doctor_id=sana.id, patient_id=meera.id, status=VisitStatus.completed,
                           reason="BP and sugar review (fictional)", scheduled_for=now - timedelta(days=12),
                           completed_at=now - timedelta(days=12), booking_ref="BK-DEMO0000",
                           fee=sana.visit_fee, address=meera.address)
    past_arjun = HomeVisit(doctor_id=carter.id, patient_id=arjun.id, status=VisitStatus.completed,
                           reason="Viral fever (fictional)", scheduled_for=now - timedelta(days=9),
                           completed_at=now - timedelta(days=9), booking_ref="BK-DEMO0009",
                           fee=carter.visit_fee, address=arjun.address)
    db.add_all([visit, visit2, visit3, past_meera, past_arjun])
    db.flush()
    db.add_all([
        VisitNote(visit_id=past_meera.id, doctor_id=sana.id, patient_id=meera.id,
                  chief_complaint="Routine BP and sugar review (fictional)",
                  findings="Feels well, no dizziness or chest pain. Taking medicines regularly. Mild ankle swelling by evening.",
                  diagnosis="Hypertension, controlled (fictional)",
                  advice="Keep salt low, walk 30 minutes a day, check BP twice a week. Call if you get headache or swelling gets worse.",
                  follow_up_in_days=14, temperature_c=36.8, bp_systolic=134, bp_diastolic=86, pulse_bpm=78,
                  spo2_pct=98, resp_rate=16, weight_kg=64.5,
                  created_at=past_meera.completed_at, updated_at=past_meera.completed_at),
        VisitNote(visit_id=past_arjun.id, doctor_id=carter.id, patient_id=arjun.id,
                  chief_complaint="Fever for 2 days with body ache (fictional)",
                  findings="Fever since 2 days, sore throat, no breathlessness. Throat mildly red, chest clear.",
                  diagnosis="Viral fever (fictional)",
                  advice="Drink plenty of fluids and rest. Take paracetamol only as prescribed. Come back if fever lasts beyond 3 days.",
                  follow_up_in_days=3, temperature_c=38.6, bp_systolic=118, bp_diastolic=76, pulse_bpm=104,
                  spo2_pct=97, resp_rate=18, weight_kg=72.0,
                  created_at=past_arjun.completed_at, updated_at=past_arjun.completed_at),
    ])
    # Dr. Sana is away for the next two days, so Meera's follow-up shows the "book her next opening" path.
    for day in _local_days(now)[:2]:
        db.add(DoctorAvailability(doctor_id=sana.id, day=day.isoformat(), hours=[]))
    db.flush()
    db.add_all([DispatchOffer(kind="visit", visit_id=v.id, user_id=carter_user.id, distance_km=km)
                for v, km in ((visit, 0.8), (visit2, 2.6))])
    from .services.face_verification import seed_demo_enrollments
    seed_demo_enrollments(db)
    from .services.family import seed_demo as seed_family
    family_ids = seed_family(db, users["patient"], meera)
    labs = seed_labs(db, users, meera)
    physio_ids = seed_physio(db, meera, arjun)
    from .services.perks import seed_perks
    seed_perks(db)
    db.commit()
    return {
        "patients": {"meera": meera.id, "arjun": arjun.id},
        "doctors": {"carter": carter.id, "unverified": unverified.id, "sana": sana.id},
        "medications": {k: m.id for k, m in meds.items()},
        "pharmacies": {"greenleaf": pharmacies[0].id, "sunrise": pharmacies[1].id,
                       "wholepack": pharmacies[2].id, "unverified": pharmacies[3].id},
        "hospitals": {k: h.id for k, h in hospitals.items()},
        "visits": {"meera": visit.id, "arjun": visit2.id, "unverified_doctor": visit3.id,
                   "meera_past": past_meera.id, "arjun_past": past_arjun.id},
        "tokens": DEMO_TOKENS,
        "family": family_ids,
        "lab_tests": labs["tests"],
        "lab_bookings": labs["bookings"],
        **physio_ids,
    }


# ------------------------------------------------------------------ lab tests at home
def _p(name, unit, low, high, typical, dp=1, rng=None):
    return {"name": name, "unit": unit, "low": low, "high": high, "typical": typical, "dp": dp, "range": rng}


LAB_TESTS = [
    # code, name, category, sample, fasting h, turnaround h, price, mrp, popular, about, parameters
    ("CBC", "Complete Blood Count (CBC)", "Blood health", "Blood", 0, 12, 299, 450, True,
     "Checks red cells, white cells and platelets. Useful for fever, tiredness and infections.",
     [_p("Haemoglobin", "g/dL", 12.0, 15.5, 13.4), _p("Total WBC count", "x10³/µL", 4.0, 11.0, 7.2),
      _p("Platelet count", "x10³/µL", 150, 410, 260, 0), _p("RBC count", "million/µL", 4.0, 5.5, 4.7, 2),
      _p("Haematocrit (PCV)", "%", 36, 46, 41)]),
    ("FBS", "Blood Sugar, Fasting", "Diabetes", "Blood", 10, 6, 99, 150, False,
     "Your blood sugar after an overnight fast. Screens for diabetes.",
     [_p("Glucose, fasting", "mg/dL", 70, 100, 94, 0)]),
    ("HBA1C", "HbA1c (3-month sugar average)", "Diabetes", "Blood", 0, 12, 449, 700, True,
     "Average blood sugar over the last 2 to 3 months. No fasting needed.",
     [_p("HbA1c", "%", 4.0, 5.6, 5.5), _p("Estimated average glucose", "mg/dL", 68, 114, 110, 0)]),
    ("LIPID", "Lipid Profile (Cholesterol)", "Heart", "Blood", 12, 12, 399, 650, True,
     "Cholesterol and triglycerides, for heart health. Fast for 10 to 12 hours.",
     [_p("Total cholesterol", "mg/dL", None, 200, 182, 0), _p("LDL cholesterol", "mg/dL", None, 100, 104, 0),
      _p("HDL cholesterol", "mg/dL", 40, None, 48, 0), _p("Triglycerides", "mg/dL", None, 150, 138, 0)]),
    ("LFT", "Liver Function Test (LFT)", "Liver", "Blood", 0, 12, 499, 800, False,
     "Liver enzymes, bilirubin and protein. Checks how your liver is working.",
     [_p("Bilirubin, total", "mg/dL", 0.2, 1.2, 0.7), _p("SGPT (ALT)", "U/L", 7, 56, 28, 0),
      _p("SGOT (AST)", "U/L", 8, 48, 24, 0), _p("Alkaline phosphatase", "U/L", 44, 147, 88, 0),
      _p("Albumin", "g/dL", 3.5, 5.0, 4.3)]),
    ("KFT", "Kidney Function Test (KFT)", "Kidney", "Blood", 0, 12, 549, 850, False,
     "Creatinine, urea, uric acid and salts. Checks how your kidneys are working.",
     [_p("Creatinine", "mg/dL", 0.6, 1.2, 0.9, 2), _p("Blood urea", "mg/dL", 15, 40, 26, 0),
      _p("Uric acid", "mg/dL", 3.5, 7.2, 5.4), _p("Sodium", "mmol/L", 135, 145, 139, 0),
      _p("Potassium", "mmol/L", 3.5, 5.1, 4.3)]),
    ("THYROID", "Thyroid Profile (T3, T4, TSH)", "Thyroid", "Blood", 0, 12, 349, 600, True,
     "Thyroid hormones. Useful for weight change, tiredness, hair fall and mood.",
     [_p("T3, total", "ng/dL", 80, 200, 120, 0), _p("T4, total", "µg/dL", 5.1, 14.1, 8.4),
      _p("TSH", "µIU/mL", 0.4, 4.0, 2.4, 2)]),
    ("VITD", "Vitamin D (25-OH)", "Vitamins", "Blood", 0, 24, 799, 1400, True,
     "Vitamin D level. Low levels are common and can cause bone pain and tiredness.",
     [_p("25-OH Vitamin D", "ng/mL", 30, 100, 31)]),
    ("VITB12", "Vitamin B12", "Vitamins", "Blood", 0, 24, 599, 1000, False,
     "Vitamin B12 level. Low levels can cause tiredness, tingling and memory problems.",
     [_p("Vitamin B12", "pg/mL", 211, 911, 420, 0)]),
    ("CRP", "C-Reactive Protein (CRP)", "Infection", "Blood", 0, 12, 399, 650, False,
     "A marker of inflammation or infection in the body.",
     [_p("CRP, quantitative", "mg/L", None, 6.0, 3.0)]),
    ("URINE", "Urine Routine & Microscopy", "Kidney", "Urine", 0, 12, 149, 250, False,
     "Checks urine for infection, sugar and protein. First morning urine is best.",
     [_p("pH", "", 4.5, 8.0, 6.0), _p("Specific gravity", "", 1.005, 1.030, 1.018, 3),
      _p("Pus cells", "/hpf", 0, 5, 2, 0)]),
]

LAB_PACKAGES = [
    ("PKG-FULL", "Full Body Checkup", "Most booked: 8 tests in one visit. Sugar, cholesterol, liver, kidney, thyroid and more.",
     ["CBC", "FBS", "HBA1C", "LIPID", "LFT", "KFT", "THYROID", "URINE"], 1499, 4800, True),
    ("PKG-DIAB", "Diabetes Care", "Sugar control, kidney and cholesterol checks for people with diabetes.",
     ["FBS", "HBA1C", "KFT", "LIPID", "URINE"], 999, 2600, True),
    ("PKG-FEVER", "Fever Panel", "For fever over 2 days: blood count, infection marker, liver and urine.",
     ["CBC", "CRP", "LFT", "URINE"], 699, 1500, False),
    ("PKG-WOMEN", "Women's Wellness", "Blood count, thyroid, vitamin D and B12. Common causes of tiredness.",
     ["CBC", "THYROID", "VITD", "VITB12"], 1299, 3400, False),
    ("PKG-SENIOR", "Senior Citizen Care", "A complete yearly check for parents and grandparents.",
     ["CBC", "FBS", "HBA1C", "LIPID", "LFT", "KFT", "THYROID", "VITD", "VITB12"], 1999, 6200, False),
]


def seed_labs(db: Session, users: dict, meera: Patient) -> dict:
    from .models import Lab, LabBooking, LabTest
    lab = Lab(name="Triyana Diagnostics Lab (Demo)", accreditation="NABL MC-DEMO-4412",
              address="7 Science Park Rd, Demo City", lat=17.4480, lng=78.3610)
    db.add(lab)
    tests = {}
    for code, name, cat, sample, fast, tat, price, mrp, pop, about, params in LAB_TESTS:
        tests[code] = LabTest(code=code, name=name, kind="test", category=cat, sample=sample, fasting_hours=fast,
                              turnaround_hours=tat, price=price, mrp=mrp, popular=pop, about=about, parameters=params)
    for code, name, about, inc, price, mrp, pop in LAB_PACKAGES:
        subs = [tests[c] for c in inc]
        tests[code] = LabTest(code=code, name=name, kind="package", category="Packages", about=about,
                              sample=", ".join(sorted({s.sample for s in subs})), includes=inc,
                              fasting_hours=max(s.fasting_hours for s in subs),
                              turnaround_hours=max(s.turnaround_hours for s in subs), price=price, mrp=mrp, popular=pop)
    db.add_all(tests.values())
    # Sample collectors (phlebotomists) for the Partner app. Priya and Suresh start online.
    for key, name, lat, lng, online in (("phlebotomist", "Priya (Phlebotomist)", 17.4415, 78.3525, True),
                                        ("phlebotomist2", "Suresh (Phlebotomist)", 17.4560, 78.3740, True),
                                        ("phlebotomist3", "Fatima (Phlebotomist)", 17.4700, 78.3900, False)):
        users[key] = User(name=name, role=Role.phlebotomist, token=DEMO_TOKENS[key], on_duty=online,
                          lat=lat, lng=lng, vehicle="Scooter")
        db.add(users[key])
    db.flush()
    # Meera already has a past report, so the report screen has something to show.
    now = utcnow()
    t = tests["PKG-DIAB"]
    past = LabBooking(booking_ref="LB-DEMO0001", patient_id=meera.id, lab_id=lab.id,
                      items=[{"id": t.id, "code": t.code, "name": t.name, "kind": t.kind, "price": t.price, "mrp": t.mrp}],
                      status="at_lab", slot_start=now - timedelta(days=20, hours=3), address=meera.address,
                      lat=meera.lat, lng=meera.lng, fasting_hours=t.fasting_hours, subtotal=t.price, collection_fee=0,
                      total=t.price, payment_method="upi", payment_status="captured", payment_ref="auth_demo",
                      collection_code="0000", phlebotomist_user_id=users["phlebotomist"].id,
                      sample_ids=["0001-BLO-7A1C", "0001-URI-2F9B"], collected_at=now - timedelta(days=20, hours=3),
                      at_lab_at=now - timedelta(days=20, hours=2), created_at=now - timedelta(days=21),
                      events=[{"at": (now - timedelta(days=21)).isoformat(), "status": "booked", "note": "Collection booked"},
                              {"at": (now - timedelta(days=20, hours=3)).isoformat(), "status": "collected",
                               "note": "2 samples collected and sealed"}])
    db.add(past)
    db.flush()
    from .services.labs import _report
    past.report = _report(db, past)
    past.report["reported_at"] = (now - timedelta(days=19, hours=20)).isoformat()
    past.status, past.report_ready_at = "report_ready", now - timedelta(days=19, hours=20)
    past.events = [*past.events, {"at": past.report_ready_at.isoformat(), "status": "report_ready", "note": "Report ready"}]
    return {"tests": {k: v.id for k, v in tests.items()}, "bookings": {"meera_past": past.id}}
