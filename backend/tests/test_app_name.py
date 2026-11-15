"""The provider app is called Triyana Heros everywhere people see it, from one constant."""
from fastapi.testclient import TestClient

from app import config
from app.main import app


def test_provider_app_name_is_filled_in():
    c = TestClient(app)
    page = c.get("/provider").text
    assert f"<title>{config.PROVIDER_APP_NAME}</title>" in page
    assert "__PROVIDER_APP" not in page and "Triyana Partner" not in page
    home = c.get("/").text
    assert f"Open {config.PROVIDER_APP_NAME}" in home and "__PROVIDER_APP" not in home
    m = c.get("/provider.webmanifest")
    assert m.headers["content-type"].startswith("application/manifest+json")
    assert m.json()["name"] == config.PROVIDER_APP_NAME
    assert m.json()["short_name"] == config.PROVIDER_APP_SHORT
    assert m.json()["start_url"] == "/provider"
