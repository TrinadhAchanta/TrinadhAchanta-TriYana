"""Money and growth: ₹99 first visit, Triyana Family, cashless insurance, referrals, partner orgs, promise kept."""
from datetime import date, timedelta

from conftest import Api, face_pass, start_visit
from test_dispatch import _age_trip, _status

FUTURE = (date.today() + timedelta(days=200)).isoformat()
ADMIN = {"X-Admin-Key": "demo-admin"}


def new_patient(env, name="Nisha New", token="demo-test-patient-new"):
    """A patient who has never had a Triyana visit, living near the demo doctors."""
    from app.models import Consent, Patient, Role, User
    with env["Session"]() as s:
        n = s.query(Patient).count()
        p = Patient(name=name, patient_ref=f"PT-TEST-{n}", date_of_birth="1990-01-01", address="5 Lotus Lane, Demo City",
                    lat=17.4405, lng=78.3492, jurisdiction="DEMO-IN")
        s.add(p)
        s.flush()
        u = User(name=name, role=Role.patient, token=token, patient_id=p.id)
        s.add(u)
        s.flush()
        s.add(Consent(user_id=u.id, purpose="care", granted=True, notice_version="test"))
        s.commit()
    return Api(env["client"], token)


def book_carter(api, env, **extra):
    carter_id = env["ids"]["doctors"]["carter"] if "doctors" in env["ids"] else None
    if carter_id is None:
        carter_id = next(d["id"] for d in api.get("/api/doctors").json()["doctors"] if "Carter" in d["name"])
    slot = api.get(f"/api/visit-slots?doctor_id={carter_id}").json()[0]
    r = api.post("/api/patient/visits", {"doctor_id": carter_id, "scheduled_for": slot, "reason": "Fever",
                                         "address": "", **extra})
    return r


def complete(env, doc, vid):
    assert doc.post(f"/api/doctor/visits/{vid}/accept").status_code == 200
    start_visit(env, doc, vid)
    assert doc.post(f"/api/doctor/visits/{vid}/complete").status_code == 200


def test_first_visit_is_99_and_doctor_still_earns_full_fee(env, as_):
    nisha = new_patient(env)
    perks = nisha.get("/api/perks").json()
    assert perks["first_visit"] == {"eligible": True, "price": 99}
    q = nisha.get("/api/perks/quote?fee=600").json()
    assert q["patient_pays"] == 99 and any(line["code"] == "first_visit" for line in q["lines"])

    v = book_carter(nisha, env).json()
    assert v["fee"] == 600 and v["bill"]["patient_pays"] == 99 and v["bill"]["base_fee"] == 600
    # Only the first visit gets the offer.
    v2 = book_carter(nisha, env).json()
    assert v2["bill"]["patient_pays"] == 600
    assert nisha.get("/api/perks").json()["first_visit"]["eligible"] is False

    complete(env, as_("doctor"), v["id"])
    job = as_("doctor").get("/api/provider/earnings").json()["jobs"][0]
    assert job["base"] == 600  # the discount is Triyana's cost, not the doctor's

    # Existing patients don't get it.
    assert as_("patient").get("/api/perks").json()["first_visit"]["eligible"] is False


def test_cancelling_first_visit_keeps_the_offer(env):
    nisha = new_patient(env)
    v = book_carter(nisha, env).json()
    nisha.post(f"/api/patient/visits/{v['id']}/cancel")
    assert nisha.get("/api/perks").json()["first_visit"]["eligible"] is True


def test_family_membership_covers_visits(env, as_):
    meera = as_("patient")
    r = meera.post("/api/perks/membership", {"payment_method": "upi", "payment_token": "decline-me"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "payment_failed"
    s = meera.post("/api/perks/membership", {"payment_method": "upi"}).json()
    assert s["membership"]["active"] and s["membership"]["price"] == 4999 and s["membership"]["ends_at"]
    assert meera.post("/api/perks/membership", {}).status_code == 409

    v = book_carter(meera, env).json()
    assert v["bill"]["patient_pays"] == 0 and v["bill"]["lines"][-1]["code"] == "membership"
    now = meera.post("/api/patient/visits/now", {"reason": "Cough"}).json()
    assert now["bill"]["patient_pays"] == 0


def test_cashless_insurance(env, as_):
    meera = as_("patient")
    r = book_carter(meera, env, cashless=True)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "no_policy"

    bad = meera.post("/api/perks/insurance", {"insurer": "star_health", "policy_no": "INVALID-1", "valid_until": FUTURE})
    assert bad.status_code == 422
    old = meera.post("/api/perks/insurance", {"insurer": "star_health", "policy_no": "SH-1234", "valid_until": "2020-01-01"})
    assert old.status_code == 422

    s = meera.post("/api/perks/insurance", {"insurer": "star_health", "policy_no": "SH-99887766",
                                            "member_name": "Meera", "valid_until": FUTURE}).json()
    pol = s["insurance"]["policies"][0]
    assert pol["insurer_name"] == "Star Health" and pol["policy_no"].endswith("7766") and "9988" not in pol["policy_no"]

    v = book_carter(meera, env, cashless=True).json()
    b = v["bill"]
    assert b["patient_pays"] == 0 and b["insurer_pays"] == 600 and b["cashless"]
    assert b["claim"]["status"] == "approved" and b["claim"]["insurer"] == "Star Health"
    meera.post(f"/api/patient/visits/{v['id']}/cancel")
    after = next(x for x in meera.get("/api/patient/visits").json() if x["id"] == v["id"])
    assert after["bill"]["claim"]["status"] == "withdrawn" and after["bill"]["insurer_pays"] == 0

    # An insurer that won't approve: the booking is refused and nothing is created.
    meera.post("/api/perks/insurance", {"insurer": "hdfc_ergo", "policy_no": "DENY-555", "valid_until": FUTURE})
    n = len(meera.get("/api/patient/visits").json())
    r = book_carter(meera, env, cashless=True)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "cashless_declined"
    assert len(meera.get("/api/patient/visits").json()) == n


def test_referral_gives_both_200_after_first_visit(env, as_):
    meera = as_("patient")
    code = meera.get("/api/perks").json()["referral"]["code"]
    assert code.startswith("TRI") and meera.get("/api/perks").json()["referral"]["code"] == code
    assert meera.post("/api/perks/referral", {"code": code}).status_code == 422          # own code
    nisha = new_patient(env)
    assert nisha.post("/api/perks/referral", {"code": "TRINOPE1"}).status_code == 404
    s = nisha.post("/api/perks/referral", {"code": code.lower()}).json()
    assert s["referral"]["referred_by"] and s["referral"]["can_redeem"] is False
    assert nisha.post("/api/perks/referral", {"code": code}).status_code == 409          # only once
    # Someone who already had visits can't use a code.
    other = as_("patient2").get("/api/perks").json()["referral"]["code"]
    assert meera.post("/api/perks/referral", {"code": other}).status_code == 409

    v = book_carter(nisha, env).json()
    assert nisha.get("/api/perks").json()["credit"]["balance"] == 0
    complete(env, as_("doctor"), v["id"])
    assert nisha.get("/api/perks").json()["credit"]["balance"] == 200
    m = meera.get("/api/perks").json()
    assert m["credit"]["balance"] == 200 and m["referral"]["friends"][0]["status"] == "rewarded"
    assert any(n["title"] == "You earned ₹200" for n in meera.get("/api/notifications").json())

    # Credit is spent on the next visit, and given back if that visit is cancelled.
    v2 = book_carter(nisha, env).json()
    assert v2["bill"]["patient_pays"] == 400 and nisha.get("/api/perks").json()["credit"]["balance"] == 0
    nisha.post(f"/api/patient/visits/{v2['id']}/cancel")
    assert nisha.get("/api/perks").json()["credit"]["balance"] == 200


def test_partner_org_discount_priority_and_admin(env, as_):
    c = env["client"]
    assert c.get("/api/admin/partners").status_code == 403
    orgs = c.get("/api/admin/partners", headers=ADMIN).json()
    assert {o["kind"] for o in orgs} == {"society", "office", "old_age_home"}
    r = c.post("/api/admin/partners", headers=ADMIN, json={"name": "Lakeview Towers", "kind": "society",
                                                            "join_code": "lakeview", "discount_pct": 25, "priority": True})
    assert r.status_code == 201, r.text
    org = r.json()
    assert org["join_code"] == "LAKEVIEW" and org["members"] == 0
    assert c.post("/api/admin/partners", headers=ADMIN, json={"name": "Dup", "join_code": "LAKEVIEW"}).status_code == 409

    meera = as_("patient")
    assert meera.post("/api/perks/org", {"code": "NOPE"}).status_code == 404
    s = meera.post("/api/perks/org", {"code": "lakeview"}).json()
    assert s["org"]["name"] == "Lakeview Towers"
    v = book_carter(meera, env).json()
    assert v["bill"]["patient_pays"] == 450
    titles = [n["title"] for n in as_("doctor").get("/api/notifications").json()]
    assert any(t.startswith("Priority ·") for t in titles)
    assert c.get("/api/admin/partners", headers=ADMIN).json()[-1]["members"] == 1

    # Switching a partner off stops the discount.
    c.post(f"/api/admin/partners/{org['id']}", headers=ADMIN, json={"active": False})
    assert book_carter(meera, env).json()["bill"]["patient_pays"] == 600
    meera.delete = lambda url: meera.c.delete(url, headers=meera.h)
    assert meera.delete("/api/perks/org").json()["org"] is None


def _doctor_now_to_door(env, patient, carter, late_by_min=0):
    v = patient.post("/api/patient/visits/now", {"reason": "Fever"}).json()
    offer = next(o for o in _status(carter)["offers"] if o["on_demand"])
    carter.post(f"/api/provider/offers/{offer['id']}/accept")
    face_pass(carter, v["id"])
    t = carter.post(f"/api/provider/visits/{v['id']}/depart").json()
    if late_by_min:
        from app.models import HomeVisit
        with env["Session"]() as s:
            hv = s.get(HomeVisit, v["id"])
            hv.created_at = hv.created_at - timedelta(minutes=10 + late_by_min)
            s.commit()
    _age_trip(env, t["id"], 10_000)
    patient.get(f"/api/patient/visits/{v['id']}/live")
    return next(x for x in patient.get("/api/patient/visits").json() if x["id"] == v["id"])


def test_promise_kept_visit_is_charged(env, as_):
    v = _doctor_now_to_door(env, as_("patient"), as_("doctor"))
    assert v["bill"]["promise"] == "kept" and v["bill"]["patient_pays"] == v["fee"]


def test_late_doctor_now_visit_is_free_automatically(env, as_):
    meera, carter = as_("patient"), as_("doctor")
    v = _doctor_now_to_door(env, meera, carter, late_by_min=4)
    assert v["bill"]["promise"] == "late" and v["bill"]["patient_pays"] == 0
    assert v["bill"]["lines"][-1]["code"] == "promise"
    assert any(n["title"].startswith("Sorry we were late") for n in meera.get("/api/notifications").json())
