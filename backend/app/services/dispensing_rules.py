"""Partial-dispensing rules engine.

Decides whether a patient may *request* to buy fewer units than prescribed.
The result is never final on its own: every permitted reduction is routed to
the dispensing pharmacist (and, where the policy says so, the prescriber).

Jurisdiction policies below are FICTIONAL demo policies. Real deployments must
load the rules for each jurisdiction from a maintained regulatory source and
have them reviewed by qualified pharmacy/legal staff.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations_with_replacement

from ..models import MedSchedule, Medication, Pharmacy, QuantityStatus


@dataclass(frozen=True)
class JurisdictionPolicy:
    code: str
    name: str
    currency: str
    tax_rate: float
    partial_fill_allowed: bool
    prescriber_auth_for: frozenset = field(default_factory=frozenset)  # schedules needing prescriber OK
    partial_fill_blocked_for: frozenset = field(default_factory=lambda: frozenset({MedSchedule.controlled}))
    drone_delivery_permitted: bool = False
    prescription_validity_days: int = 30


POLICIES: dict[str, JurisdictionPolicy] = {
    "DEMO-IN": JurisdictionPolicy(
        code="DEMO-IN", name="Demo Region (India-style)", currency="INR", tax_rate=0.12,
        partial_fill_allowed=True,
        prescriber_auth_for=frozenset({MedSchedule.restricted}),
        drone_delivery_permitted=False, prescription_validity_days=30,
    ),
    "DEMO-US": JurisdictionPolicy(
        code="DEMO-US", name="Demo Region (US-style)", currency="USD", tax_rate=0.0,
        partial_fill_allowed=True,
        prescriber_auth_for=frozenset(),
        drone_delivery_permitted=True, prescription_validity_days=365,
    ),
    "DEMO-NOPARTIAL": JurisdictionPolicy(
        code="DEMO-NOPARTIAL", name="Demo Region (no partial fills)", currency="EUR", tax_rate=0.07,
        partial_fill_allowed=False, drone_delivery_permitted=False, prescription_validity_days=90,
    ),
}


def policy_for(code: str) -> JurisdictionPolicy:
    return POLICIES.get(code, POLICIES["DEMO-NOPARTIAL"])


COURSE_WARNING = (
    "Buying fewer than the prescribed quantity may leave you without the full course your "
    "doctor intended. Please talk to your doctor or pharmacist before changing your treatment."
)


@dataclass
class QuantityDecision:
    status: QuantityStatus
    rule_code: str
    explanation: str
    allowed_quantities: list[int] = field(default_factory=list)

    @property
    def permitted(self) -> bool:
        return self.status not in (QuantityStatus.rejected, QuantityStatus.not_permitted)


def achievable_quantities(med: Medication, limit: int) -> list[int]:
    """Quantities <= limit that can be dispensed given pack sizes."""
    if med.loose_units_allowed:
        return list(range(1, limit + 1))
    sizes = sorted(set(int(s) for s in med.pack_sizes if 0 < int(s) <= limit))
    found: set[int] = set()
    for n in range(1, 6):  # up to 5 packs is plenty for demo catalogue
        for combo in combinations_with_replacement(sizes, n):
            total = sum(combo)
            if total <= limit:
                found.add(total)
    return sorted(found)


def evaluate_quantity_request(
    *,
    med: Medication,
    prescribed: int,
    requested: int,
    jurisdiction: str,
    pharmacy: Pharmacy | None = None,
) -> QuantityDecision:
    policy = policy_for(jurisdiction)

    if requested == prescribed:
        return QuantityDecision(QuantityStatus.full, "FULL_QUANTITY", "You are buying the full prescribed quantity.")
    if requested > prescribed:
        return QuantityDecision(
            QuantityStatus.rejected, "EXCEEDS_PRESCRIPTION",
            "You cannot buy more than your doctor prescribed. Please contact your doctor if you think you need more.",
        )
    if requested < 1:
        return QuantityDecision(
            QuantityStatus.rejected, "INVALID_QUANTITY",
            "To skip this medicine, use 'Remove from cart' or 'Buy later' instead.",
        )
    if med.schedule in policy.partial_fill_blocked_for:
        return QuantityDecision(
            QuantityStatus.not_permitted, "CONTROLLED_MEDICINE",
            "This is a controlled medicine, so the quantity cannot be changed in the app. "
            "Please contact the pharmacy or your doctor to discuss it.",
        )
    if not policy.partial_fill_allowed:
        return QuantityDecision(
            QuantityStatus.not_permitted, "JURISDICTION_PROHIBITS",
            f"Partial dispensing is not permitted in {policy.name}. "
            "You can contact the pharmacy or your doctor to discuss your options.",
        )
    if pharmacy is not None and not pharmacy.allows_partial_dispensing:
        return QuantityDecision(
            QuantityStatus.not_permitted, "PHARMACY_POLICY",
            f"{pharmacy.name} does not dispense partial quantities. Choose another pharmacy, "
            "or contact the pharmacy or your doctor.",
        )
    allowed = achievable_quantities(med, prescribed)
    if requested not in allowed:
        return QuantityDecision(
            QuantityStatus.not_permitted, "PACK_SIZE",
            f"{med.brand_name} is only supplied in packs of "
            f"{', '.join(str(s) for s in med.pack_sizes)} {med.unit}, so {requested} cannot be dispensed.",
            allowed_quantities=allowed,
        )
    if med.schedule in policy.prescriber_auth_for:
        return QuantityDecision(
            QuantityStatus.pending_prescriber, "PRESCRIBER_AUTH_REQUIRED",
            "This medicine needs your doctor's authorisation for a smaller quantity. "
            "We have sent the request; the pharmacist will review it after your doctor responds. "
            + COURSE_WARNING,
            allowed_quantities=allowed,
        )
    return QuantityDecision(
        QuantityStatus.pending_pharmacist, "PHARMACIST_REVIEW",
        "A smaller quantity looks permissible. The dispensing pharmacist will make the final decision. "
        + COURSE_WARNING,
        allowed_quantities=allowed,
    )
