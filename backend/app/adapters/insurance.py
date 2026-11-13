"""Sandbox health-insurance adapter for cashless home visits.

Real cashless billing needs a contract with each insurer (or their TPA) and an API or portal integration
for policy checks, pre-authorisation and claim settlement. Until then this stand-in approves valid-looking
policies and claims so the patient journey can be shown end to end.

Demo rules: a policy number containing "invalid" is rejected; one containing "deny" is accepted but its
claims are rejected; a policy past its valid-until date is rejected.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

INSURERS = {
    "star_health": "Star Health",
    "hdfc_ergo": "HDFC ERGO",
    "icici_lombard": "ICICI Lombard",
    "niva_bupa": "Niva Bupa",
    "care_health": "Care Health",
    "bajaj_allianz": "Bajaj Allianz",
    "tata_aig": "Tata AIG",
    "aditya_birla": "Aditya Birla Health",
    "other": "Other insurer / TPA",
}


@dataclass
class InsurerResult:
    ok: bool
    ref: str = ""
    message: str = ""


class SandboxInsuranceAdapter:
    name = "sandbox-insurance"

    def verify_policy(self, insurer: str, policy_no: str, valid_until: str) -> InsurerResult:
        if insurer not in INSURERS:
            return InsurerResult(False, message="Choose your insurer from the list.")
        if "invalid" in policy_no.lower():
            return InsurerResult(False, message="The insurer could not find this policy (sandbox).")
        try:
            if date.fromisoformat(valid_until) < date.today():
                return InsurerResult(False, message="This policy has expired.")
        except ValueError:
            return InsurerResult(False, message="Enter the policy's valid-until date.")
        return InsurerResult(True, ref=f"POL-{uuid.uuid4().hex[:8].upper()}")

    def submit_claim(self, insurer: str, policy_no: str, amount: float) -> InsurerResult:
        if "deny" in policy_no.lower():
            return InsurerResult(False, message="The insurer did not approve cashless for this visit (sandbox).")
        return InsurerResult(True, ref=f"CLM-{uuid.uuid4().hex[:8].upper()}")

    def withdraw_claim(self, ref: str) -> InsurerResult:
        return InsurerResult(True, ref=ref)


adapter = SandboxInsuranceAdapter()
