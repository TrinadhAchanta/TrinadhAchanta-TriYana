"""Verification partners for providers who sign up in Triyana Partner.

Two independent checks, each with its own partner, picked by environment variables:

* **Registry check** (doctors, physios): is this registration number on the official
  register, under this name? ``TRIYANA_REGISTRY_PROVIDER``:

  - ``demo`` (default): no network. Any registration number is found under the name
    the provider typed, except numbers containing ``FAIL`` (not on the register) or
    ``MISMATCH`` (on the register under a different name).
  - ``hpr``: ABDM Healthcare Professionals Registry. Needs ``ABDM_CLIENT_ID`` and
    ``ABDM_CLIENT_SECRET`` from ABDM onboarding (sandbox first, then production).
    ``ABDM_GATEWAY_URL`` / ``HPR_BASE_URL`` / ``HPR_SEARCH_PATH`` default to the
    sandbox and can be pointed at production without a code change.

* **ID and background check** (every provider): does the PAN / driving licence match
  the person, and are there court records against them? ``TRIYANA_BACKGROUND_PROVIDER``:

  - ``demo`` (default): no network. PAN must be an individual PAN (4th letter ``P``);
    numbers containing ``9999`` come back with a court record that needs review.
  - ``idfy``: IDfy (eve.idfy.com). Needs ``IDFY_ACCOUNT_ID`` and ``IDFY_API_KEY``.
    Court-record checks run only when ``IDFY_COURT_TASK`` names the task type your
    IDfy contract enables. Results arrive asynchronously and are fetched with ``poll``.

  AuthBridge can replace IDfy by adding another branch with the same three functions.

Every function returns a ``Result``; a partner outage raises ``PartnerError`` so the
check is recorded as ``error`` and can be retried, never silently passed.
"""
from __future__ import annotations

import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field

import httpx

log = logging.getLogger("triyana.verification")


class PartnerError(Exception):
    pass


@dataclass
class Result:
    status: str  # passed | needs_review | failed | in_progress
    summary: str
    reference: str | None = None
    details: dict = field(default_factory=dict)


def registry_partner() -> str:
    return os.environ.get("TRIYANA_REGISTRY_PROVIDER", "demo").lower()


def background_partner() -> str:
    return os.environ.get("TRIYANA_BACKGROUND_PROVIDER", "demo").lower()


def _norm_name(name: str) -> set[str]:
    words = re.sub(r"[^a-z ]", " ", (name or "").lower()).split()
    return {w for w in words if w not in {"dr", "doctor", "mr", "mrs", "ms"} and len(w) > 1}


def names_match(a: str, b: str) -> bool:
    """Same person if every word of the shorter name appears in the longer one (initials allowed)."""
    x, y = _norm_name(a), _norm_name(b)
    if not x or not y:
        return False
    short, long_ = (x, y) if len(x) <= len(y) else (y, x)
    return all(w in long_ or any(l.startswith(w) for l in long_) for w in short)


# ------------------------------------------------------------- registry (HPR)
def lookup_registration(name: str, registration_no: str, council: str) -> Result:
    partner = registry_partner()
    if partner == "demo":
        reg = registration_no.upper()
        if "FAIL" in reg:
            return Result("failed", f"No registration {registration_no} found with {council} (demo registry).",
                          details={"found": False})
        reg_name = "Dr. Someone Else" if "MISMATCH" in reg else name
        return _registry_result(name, reg_name, registration_no, council, "HPR-DEMO-" + reg[-6:], active=True)
    if partner == "hpr":
        return _hpr_lookup(name, registration_no, council)
    raise PartnerError(f"Unknown registry provider {partner!r}")


def _registry_result(name: str, reg_name: str, reg_no: str, council: str, ref: str | None, active: bool,
                     reg_council: str | None = None) -> Result:
    details = {"found": True, "registered_name": reg_name, "registration_no": reg_no,
               "council": reg_council or council, "active": active}
    if not active:
        return Result("failed", f"Registration {reg_no} is on the register but not active.", ref, details)
    if not names_match(name, reg_name):
        return Result("needs_review", f"Registration found, but under the name “{reg_name}”.", ref, details)
    return Result("passed", f"Registered with {reg_council or council} as {reg_name}.", ref, details)


_abdm_token: dict = {}


def _abdm_access_token() -> str:
    if _abdm_token.get("exp", 0) > time.time() + 30:
        return _abdm_token["token"]
    gateway = os.environ.get("ABDM_GATEWAY_URL", "https://dev.abdm.gov.in/gateway")
    r = httpx.post(f"{gateway}/v0.5/sessions", timeout=15,
                   json={"clientId": os.environ["ABDM_CLIENT_ID"], "clientSecret": os.environ["ABDM_CLIENT_SECRET"]})
    r.raise_for_status()
    body = r.json()
    _abdm_token.update(token=body["accessToken"], exp=time.time() + int(body.get("expiresIn", 600)))
    return _abdm_token["token"]


def _hpr_lookup(name: str, reg_no: str, council: str) -> Result:
    base = os.environ.get("HPR_BASE_URL", "https://hpridsbx.abdm.gov.in/api")
    path = os.environ.get("HPR_SEARCH_PATH", "/v1/search/searchHpByRegistrationNumber")
    try:
        r = httpx.post(base + path, timeout=15,
                       headers={"Authorization": f"Bearer {_abdm_access_token()}"},
                       json={"registrationNumber": reg_no, "councilName": council})
        if r.status_code == 404:
            return Result("failed", f"No registration {reg_no} found on the ABDM HPR.", details={"found": False})
        r.raise_for_status()
        body = r.json()
    except (KeyError, httpx.HTTPError, ValueError) as e:
        log.error("HPR lookup failed: %s", e)
        raise PartnerError("The HPR registry could not be reached") from e
    rows = body if isinstance(body, list) else body.get("results") or body.get("data") or [body]
    if not rows or not isinstance(rows[0], dict):
        return Result("failed", f"No registration {reg_no} found on the ABDM HPR.", details={"found": False})
    row = rows[0]
    reg_name = row.get("name") or " ".join(filter(None, [row.get("firstName"), row.get("middleName"),
                                                          row.get("lastName")]))
    status = str(row.get("status") or row.get("registrationStatus") or "active").lower()
    return _registry_result(name, reg_name, reg_no, council, row.get("hprId") or row.get("hprIdNumber"),
                            active=status in ("active", "verified", "approved"),
                            reg_council=row.get("councilName") or row.get("registeredWithCouncil"))


# ------------------------------------------------------- ID + background (IDfy)
ID_TYPES = {"pan": "PAN", "driving_licence": "Driving licence"}
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
DL_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[0-9A-Z]{9,13}$")


def clean_id(id_type: str, number: str) -> str:
    n = re.sub(r"[\s-]", "", number or "").upper()
    if id_type == "pan" and not PAN_RE.match(n):
        raise ValueError("Enter a valid 10-character PAN, like ABCPE1234F.")
    if id_type == "driving_licence" and not DL_RE.match(n):
        raise ValueError("Enter your driving licence number as printed, like TS0920190012345.")
    if id_type not in ID_TYPES:
        raise ValueError("Choose PAN or driving licence.")
    return n


def mask(number: str) -> str:
    return "•" * max(0, len(number) - 4) + number[-4:]


def verify_id(name: str, dob: str, id_type: str, number: str) -> Result:
    partner = background_partner()
    if partner == "demo":
        if id_type == "pan" and number[3] != "P":
            return Result("failed", "This PAN is not an individual's PAN (demo check).", "IDFY-DEMO-" + number[-4:],
                          {"id_type": id_type, "id_masked": mask(number)})
        return Result("passed", f"{ID_TYPES[id_type]} matches {name} (demo check).", "IDFY-DEMO-" + number[-4:],
                      {"id_type": id_type, "id_masked": mask(number), "name_match": True})
    if partner == "idfy":
        task = {"pan": "ind_pan", "driving_licence": "ind_driving_license"}[id_type]
        data = {"id_number": number, "full_name": name, "dob": dob}
        return _idfy_start(f"/v3/tasks/async/verify_with_source/{task}", data,
                           {"id_type": id_type, "id_masked": mask(number)}, "ID check sent to IDfy.")
    raise PartnerError(f"Unknown background provider {partner!r}")


def court_record_check(name: str, dob: str, address: str, father_name: str | None, number: str) -> Result | None:
    """Criminal / civil court-record search. Returns None when the partner contract has no such check."""
    partner = background_partner()
    if partner == "demo":
        if "9999" in number:
            return Result("needs_review", "1 court record found under a similar name. Please review (demo check).",
                          "IDFY-DEMO-CRT-" + number[-4:], {"records": 1})
        return Result("passed", "No court records found (demo check).", "IDFY-DEMO-CRT-" + number[-4:],
                      {"records": 0})
    if partner == "idfy":
        task = os.environ.get("IDFY_COURT_TASK", "")
        if not task:
            return None
        data = {"name": name, "dob": dob, "address": address, "father_name": father_name or ""}
        return _idfy_start(f"/v3/tasks/async/{task}", data, {}, "Court-record check sent to IDfy.")
    raise PartnerError(f"Unknown background provider {partner!r}")


def _idfy_headers() -> dict:
    return {"account-id": os.environ["IDFY_ACCOUNT_ID"], "api-key": os.environ["IDFY_API_KEY"]}


def _idfy_base() -> str:
    return os.environ.get("IDFY_BASE_URL", "https://eve.idfy.com")


def _idfy_start(path: str, data: dict, details: dict, summary: str) -> Result:
    try:
        r = httpx.post(_idfy_base() + path, timeout=15, headers=_idfy_headers(),
                       json={"task_id": str(uuid.uuid4()), "group_id": str(uuid.uuid4()), "data": data})
        r.raise_for_status()
        req = r.json()["request_id"]
    except (KeyError, httpx.HTTPError, ValueError) as e:
        log.error("IDfy request failed: %s", e)
        raise PartnerError("IDfy could not be reached") from e
    return Result("in_progress", summary, req, details)


def poll(kind: str, reference: str) -> Result | None:
    """Fetch the result of an asynchronous IDfy task. None while it is still running."""
    if background_partner() != "idfy" or not reference:
        return None
    try:
        r = httpx.get(_idfy_base() + "/v3/tasks", params={"request_id": reference}, timeout=15,
                      headers=_idfy_headers())
        r.raise_for_status()
        tasks = r.json()
    except (KeyError, httpx.HTTPError, ValueError) as e:
        log.error("IDfy poll failed: %s", e)
        raise PartnerError("IDfy could not be reached") from e
    task = tasks[0] if isinstance(tasks, list) and tasks else {}
    if task.get("status") not in ("completed", "failed"):
        return None
    if task.get("status") == "failed":
        return Result("failed" if kind == "identity" else "needs_review",
                      task.get("error") or "IDfy could not complete the check.", reference)
    out = task.get("result") or {}
    if kind == "identity":
        src = out.get("source_output") or {}
        ok = str(src.get("status", "")).lower() in ("id_found", "valid", "active")
        name_ok = src.get("name_match", True) not in (False, "no")
        status = "passed" if ok and name_ok else "needs_review" if ok else "failed"
        text = {"passed": "ID matches the government record.",
                "needs_review": "ID found, but the name does not match exactly.",
                "failed": "ID not found in the government record."}[status]
        return Result(status, text, reference, {"source_status": src.get("status")})
    records = out.get("records") or out.get("cases") or []
    if records:
        return Result("needs_review", f"{len(records)} court record(s) found. Please review.", reference,
                      {"records": len(records)})
    return Result("passed", "No court records found.", reference, {"records": 0})
