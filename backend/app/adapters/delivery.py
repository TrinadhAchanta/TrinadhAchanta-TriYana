"""Sandbox delivery provider (stands in for authorised courier integrations)."""
from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..models import utcnow

OPTION_INFO = {
    "standard": {"label": "Standard delivery", "minutes": 240, "fee_multiplier": 1.0},
    "same_day": {"label": "Same-day delivery", "minutes": 120, "fee_multiplier": 1.4},
    "scheduled": {"label": "Scheduled delivery", "minutes": None, "fee_multiplier": 1.0},
    "priority": {"label": "Priority delivery", "minutes": 45, "fee_multiplier": 2.0},
    "drone": {"label": "Drone delivery (approved zones)", "minutes": 30, "fee_multiplier": 2.5},
}

COURIERS = ["Asha R.", "Leo M.", "Priya K.", "Sam T.", "Noor H."]


@dataclass
class Booking:
    tracking_ref: str
    courier_name: str
    eta: datetime
    handover_code: str


class SandboxDeliveryProvider:
    name = "sandbox-courier"

    def eta_minutes(self, option: str, distance_km: float, prep_minutes: int) -> int:
        base = OPTION_INFO[option]["minutes"] or 240
        return int(prep_minutes + base * (0.6 if option in ("priority", "drone") else 1) + distance_km * 3)

    def book(self, option: str, distance_km: float, prep_minutes: int, scheduled_for: datetime | None) -> Booking:
        eta = scheduled_for or (utcnow() + timedelta(minutes=self.eta_minutes(option, distance_km, prep_minutes)))
        return Booking(
            tracking_ref=f"TRK-{uuid.uuid4().hex[:8].upper()}",
            courier_name=random.choice(COURIERS),
            eta=eta,
            handover_code=f"{random.randint(0, 9999):04d}",
        )
