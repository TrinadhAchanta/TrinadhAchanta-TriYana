"""Eye, ear-nose-throat and teeth doctors: booked home visits that go only to that kind of doctor."""
from tests.test_accounts import H, _phone, otp


def test_care_types_listed(env):
    kinds = {k["key"]: k for k in env["client"].get("/api/care-types").json()}
    assert set(kinds) == {"general", "eye", "ent", "dental"}
    assert kinds["dental"]["label"] == "Dentist" and kinds["eye"]["formal"] == "Ophthalmologist"
    assert kinds["ent"]["reasons"] and kinds["eye"]["at_home"]


def test_each_specialty_lists_only_its_own_doctors(as_):
    meera = as_("patient")
    general = meera.get("/api/doctors").json()["doctors"]
    assert {d["care_type"] for d in general} == {"general"}
    assert "Dr. Kavya Iyer" not in [d["name"] for d in general]
    for kind, name in (("eye", "Dr. Kavya Iyer"), ("ent", "Dr. Farhan Ali"), ("dental", "Dr. Nisha Reddy")):
        r = meera.get("/api/doctors", params={"care_type": kind}).json()
        assert [d["name"] for d in r["doctors"]] == [name]
        assert r["soonest"]["doctor"]["name"] == name
        assert meera.get("/api/visit-slots", params={"care_type": kind}).json()
    assert meera.get("/api/doctors", params={"care_type": "skin"}).status_code == 422


def test_book_eye_visit_goes_to_eye_doctor_with_promo(env, as_):
    meera, kavya = as_("patient"), as_("doctor_kavya")
    slot = meera.get("/api/visit-slots", params={"care_type": "eye"}).json()[-1]
    r = meera.post("/api/patient/visits", {"doctor_id": None, "scheduled_for": slot, "reason": "Red or itchy eyes",
                                           "care_type": "eye", "promo_code": "DOC100"})
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["doctor"]["name"] == "Dr. Kavya Iyer" and v["care_type"] == "eye" and v["care_label"] == "Eye doctor"
    assert v["fee"] == 900 and v["bill"]["patient_pays"] < 900  # promo / first-visit offer still apply
    assert any(n["title"] == "New eye home visit request" for n in kavya.get("/api/notifications").json())
    assert any(x["id"] == v["id"] for x in kavya.get("/api/doctor/visits").json())
    # A general doctor can't be booked for an eye visit.
    carter = next(d for d in meera.get("/api/doctors").json()["doctors"] if d["name"] == "Dr. Emily Carter")
    bad = meera.post("/api/patient/visits", {"doctor_id": carter["id"], "scheduled_for": slot,
                                             "reason": "Blurred vision", "care_type": "eye"})
    assert bad.status_code == 404


def test_asap_dental_and_general_unchanged(as_):
    arjun = as_("patient2")
    r = arjun.post("/api/patient/visits", {"asap": True, "reason": "Toothache", "care_type": "dental"})
    assert r.status_code == 201, r.text
    assert r.json()["doctor"]["name"] == "Dr. Nisha Reddy"
    g = arjun.post("/api/patient/visits", {"asap": True, "reason": "Fever or cold"})
    assert g.status_code == 201 and g.json()["care_type"] == "general"
    assert g.json()["doctor"]["name"] != "Dr. Nisha Reddy"


def test_specialists_never_get_doctor_now(env, as_):
    """The 10-minute "Doctor now" is for general doctors; eye, ENT and dental doctors are booked for a time."""
    from app.models import DispatchOffer, Doctor, User
    r = as_("patient").post("/api/patient/visits/now", {"reason": "Fever", "accept_longer": True})
    assert r.status_code == 201, r.text
    with env["Session"]() as db:
        offered = [db.get(User, o.user_id) for o in db.query(DispatchOffer).filter(DispatchOffer.visit_id == r.json()["id"])]
        assert offered and all((db.get(Doctor, u.doctor_id).care_type or "general") == "general" for u in offered)
        specialists = db.query(Doctor).filter(Doctor.care_type.in_(["eye", "ent", "dental"])).count()
        assert specialists == 3


def test_doctor_signs_up_as_dentist(env):
    c = env["client"]
    phone = _phone()
    r = c.post("/api/auth/register", json={
        "app": "provider", "role": "doctor", "name": "Lakshmi Rao", "email": "dr.lakshmi@example.com",
        "password": "Secret123", "phone": phone, "otp": otp(c, phone), "address": "Lake View",
        "doctor": {"license_no": "TSDC-7781", "medical_council": "Telangana State Dental Council",
                   "care_type": "dental", "registration_year": 2018}})
    assert r.status_code == 201, r.text
    doc = r.json()["account"]["doctor"]
    assert doc["care_type"] == "dental" and doc["specialty"] == "Teeth (Dental Surgery)"
    me = c.get("/api/account", headers=H(r.json()["token"], "provider")).json()
    assert me["doctor"]["care_type"] == "dental"
