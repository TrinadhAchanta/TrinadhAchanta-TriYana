"""Ambulance hand-off for serious SOS cases.

India's 108 emergency ambulance is run state by state and has no public booking API, so the patient app
always shows a one-tap "Call 108" (and 112). This adapter is for a *private* ambulance partner that can be
booked by API and sent to the patient's location.

TRIYANA_AMBULANCE_PROVIDER:
* ``sandbox`` (default): nothing is dispatched. A reference is returned so the flow can be shown in the demo.
  The patient is told plainly to call 108.
* anything else: not built yet. A partner (a private ambulance network with a B2B API) is to be chosen;
  ``request`` is the one function to fill in.
"""
from __future__ import annotations

import logging
import os
import secrets

log = logging.getLogger("triyana.ambulance")


def provider_name() -> str:
    return os.environ.get("TRIYANA_AMBULANCE_PROVIDER", "sandbox").lower()


def is_sandbox() -> bool:
    return provider_name() == "sandbox"


def request(lat: float, lng: float, address: str, patient_name: str, summary: str) -> dict:
    ref = "AMB-" + secrets.token_hex(3).upper()
    if is_sandbox():
        log.warning("SANDBOX ambulance request %s for %s at %.5f,%.5f: %s", ref, patient_name, lat, lng, summary)
        return {"ref": ref, "status": "requested", "provider": "sandbox", "eta_min": None}
    log.error("Ambulance provider %r is not built; request %s not sent", provider_name(), ref)
    return {"ref": ref, "status": "failed", "provider": provider_name(), "eta_min": None}
