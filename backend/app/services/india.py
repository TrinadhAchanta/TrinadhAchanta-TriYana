"""India launch rules: drug schedules under the Drugs and Cosmetics Rules, 1945.

The schedule given to each demo medicine is an illustrative DEMO classification.
Before launch, load schedules from a maintained source (CDSCO) and have them
reviewed by a registered pharmacist and legal counsel.
"""
from __future__ import annotations

from ..models import Medication
from .dispensing_rules import policy_for

SCHEDULES = {
    "OTC": ("Over the counter", "No prescription needed."),
    "G": ("Schedule G", "Use under medical supervision."),
    "H": ("Schedule H", "Prescription medicine. Sold only against a valid prescription from a registered doctor."),
    "H1": ("Schedule H1", "Prescription medicine with extra controls. The pharmacist records the sale in the "
                          "Schedule H1 register (patient, doctor, medicine and quantity) and keeps it for 3 years."),
    "X": ("Schedule X", "Can't be sold online. Take your doctor's original prescription to a licensed pharmacy in "
                        "person; the pharmacy keeps a copy of the prescription."),
}
ONLINE_BLOCKED = {"X"}
REGISTER_REQUIRED = {"H1"}
SCHEDULE_X_NOTE = ("Schedule X medicine: this can't be bought online in India. It stays on your prescription. "
                   "Take your doctor's original prescription to a licensed pharmacy in person.")


def applies(jurisdiction: str) -> bool:
    return policy_for(jurisdiction).india_schedules


def schedule_info(med: Medication, jurisdiction: str) -> dict | None:
    if not applies(jurisdiction):
        return None
    code = med.india_schedule or "H"
    label, note = SCHEDULES.get(code, SCHEDULES["H"])
    return {"code": code, "label": label, "note": note,
            "online_sale_blocked": code in ONLINE_BLOCKED, "register_required": code in REGISTER_REQUIRED}


def online_blocked(med: Medication, jurisdiction: str) -> bool:
    return applies(jurisdiction) and (med.india_schedule or "H") in ONLINE_BLOCKED


def needs_h1_register(med: Medication, jurisdiction: str) -> bool:
    return applies(jurisdiction) and (med.india_schedule or "H") in REGISTER_REQUIRED
