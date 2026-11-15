"""Patients rate a finished visit out of 5 with a comment; the next patient sees it when booking (Tri, 2026-11-15)."""
import pytest

ADMIN = {"X-Admin-Key": "demo-admin"}


@pytest.fixture(autouse=True)
def _demo(monkeypatch):
    monkeypatch.delenv("TRIYANA_ADMIN_KEY", raising=False)
    monkeypatch.setenv("TRIYANA_DEMO", "1")


def _sana(env, as_):
    return as_("patient2").get(f"/api/doctors/{env['ids']['doctors']['sana']}/reviews").json()


def test_rate_finished_visit_and_others_see_it(env, as_):
    meera, vid = as_("patient"), env["ids"]["visits"]["meera_past"]
    pend = meera.get("/api/patient/reviews/pending").json()
    assert any(p["kind"] == "visit" and p["job_id"] == vid and p["provider"] == "Dr. Sana Sample" for p in pend)

    before = _sana(env, as_)
    assert any(r["sample"] for r in before["reviews"])  # demo samples so profiles aren't empty
    r = meera.post("/api/patient/reviews", {"kind": "visit", "job_id": vid, "stars": 3,
                                            "comment": "  Good check-up   but came late. "})
    assert r.status_code == 201, r.text
    after = _sana(env, as_)
    assert after["rating_count"] == before["rating_count"] + 1
    assert after["rating"] <= before["rating"]
    top = after["reviews"][0]
    assert top["comment"] == "Good check-up but came late." and top["stars"] == 3 and top["name"] == "Meera D."

    # Once only, and it leaves the "How was your visit?" prompt.
    assert meera.post("/api/patient/reviews", {"kind": "visit", "job_id": vid, "stars": 5}).status_code == 409
    assert not any(p["job_id"] == vid and p["kind"] == "visit" for p in meera.get("/api/patient/reviews/pending").json())
    v = next(x for x in meera.get("/api/patient/visits").json() if x["id"] == vid)
    assert v["review"]["stars"] == 3

    # The next patient booking sees the comment on the doctor's card.
    docs = as_("patient2").get("/api/doctors").json()["doctors"]
    sana = next(d for d in docs if d["id"] == env["ids"]["doctors"]["sana"])
    assert sana["reviews"][0]["comment"] == "Good check-up but came late."
    assert sana["rating_count"] == after["rating_count"]

    # The doctor sees it in Heros.
    mine = as_("doctor_sana").get("/api/provider/reviews").json()
    assert mine["reviews"][0]["stars"] == 3


def test_cannot_rate_unfinished_or_someone_elses_visit(env, as_):
    meera = as_("patient")
    assert meera.post("/api/patient/reviews", {"kind": "visit", "job_id": env["ids"]["visits"]["meera"],
                                               "stars": 5}).status_code == 409
    assert meera.post("/api/patient/reviews", {"kind": "visit", "job_id": env["ids"]["visits"]["arjun_past"],
                                               "stars": 1}).status_code == 404
    assert meera.post("/api/patient/reviews", {"kind": "visit", "job_id": env["ids"]["visits"]["meera_past"],
                                               "stars": 6}).status_code == 422
    assert as_("doctor").post("/api/patient/reviews", {"kind": "visit", "job_id": env["ids"]["visits"]["meera_past"],
                                                       "stars": 5}).status_code in (401, 403)


def test_physio_package_review(env, as_):
    arjun = as_("patient2")
    pkg = arjun.get("/api/patient/physio/bookings").json()[0]
    assert pkg["can_review"] and pkg["review"] is None
    r = arjun.post("/api/patient/reviews", {"kind": "physio", "job_id": pkg["id"], "stars": 5, "comment": "Knee much better"})
    assert r.status_code == 201, r.text
    prof = arjun.get(f"/api/physios/{pkg['physio']['id']}/reviews").json()
    assert prof["reviews"][0]["comment"] == "Knee much better"
    assert as_("physio").get("/api/provider/reviews").json()["reviews"][0]["stars"] == 5


def test_admin_hides_abusive_review(env, as_):
    meera, vid = as_("patient"), env["ids"]["visits"]["meera_past"]
    before = _sana(env, as_)
    meera.post("/api/patient/reviews", {"kind": "visit", "job_id": vid, "stars": 1, "comment": "rude words here"})
    c = env["client"]
    low = c.get("/api/admin/reviews?show=low", headers=ADMIN).json()
    rid = next(r["id"] for r in low if r["comment"] == "rude words here")
    assert c.post(f"/api/admin/reviews/{rid}/hide", headers=ADMIN, json={"hidden": True, "reason": "Abusive"}).status_code == 200
    hidden = _sana(env, as_)
    assert all(r["id"] != rid for r in hidden["reviews"])
    assert hidden["rating_count"] == before["rating_count"]
    assert abs(hidden["rating"] - before["rating"]) < 0.01
    assert c.post(f"/api/admin/reviews/{rid}/hide", headers=ADMIN, json={"hidden": False}).status_code == 200
    assert _sana(env, as_)["rating_count"] == before["rating_count"] + 1
