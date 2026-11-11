import os

os.environ["TRIYANA_DATABASE_URL"] = "sqlite://"
os.environ["TRIYANA_SKIP_STARTUP_SEED"] = "1"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db, make_engine
from app.main import app
from app.seed import seed


@pytest.fixture()
def env():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with Session() as s:
        ids = seed(s)
        # Demo patients start without consent; tests act as patients who already agreed (DPDP).
        from app.models import Consent, User
        for u in s.query(User).filter(User.patient_id.isnot(None)):
            s.add(Consent(user_id=u.id, purpose="care", granted=True, notice_version="test"))
        s.commit()

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    client = TestClient(app)
    yield {"client": client, "ids": ids, "Session": Session}
    app.dependency_overrides.clear()
    engine.dispose()


class Api:
    def __init__(self, client, token):
        self.c = client
        self.h = {"Authorization": f"Bearer {token}"}

    def get(self, url, **kw):
        return self.c.get(url, headers=self.h, **kw)

    def post(self, url, json=None):
        return self.c.post(url, headers=self.h, json=json or {})

    def put(self, url, json=None):
        return self.c.put(url, headers=self.h, json=json or {})

    def patch(self, url, json=None):
        return self.c.patch(url, headers=self.h, json=json or {})


@pytest.fixture()
def as_(env):
    tokens = env["ids"]["tokens"]
    return lambda who: Api(env["client"], tokens[who])


def rx_items(ids, *keys_and_qty):
    meds = ids["medications"]
    items = []
    for key, qty in keys_and_qty:
        items.append({"medication_id": meds[key], "dosage": "1 unit", "frequency": "twice daily",
                      "duration_days": 3, "quantity": qty, "route": "oral",
                      "instructions": "As entered and approved by the licensed doctor (demo)."})
    return items


@pytest.fixture()
def signed_rx(env, as_):
    """Doctor completes Meera's visit and signs Dolo 650 x5 + Pantodemo x10."""
    doc = as_("doctor")
    vid = env["ids"]["visits"]["meera"]
    for a in ("accept", "start", "complete"):
        assert doc.post(f"/api/doctor/visits/{vid}/{a}").status_code == 200
    r = doc.post("/api/prescriptions", {"visit_id": vid, "diagnosis_note": "Demo",
                                         "items": rx_items(env["ids"], ("dolo", 5), ("panto", 10))})
    assert r.status_code == 201, r.text
    rx = r.json()
    r = doc.post(f"/api/prescriptions/{rx['id']}/sign", {"confirm_reviewed": True})
    assert r.status_code == 200, r.text
    cart_id = as_("patient").get("/api/patient/carts").json()[0]["id"]
    return {"rx": r.json(), "cart_id": cart_id}
