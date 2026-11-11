"""Pharmacy integration adapter.

`MockPharmacyNetwork` stands in for real pharmacy-system / e-prescription
network integrations. It reads the demo inventory tables and reports whether
stock is *live-verified* or only a catalogue estimate. Swap it for a real
adapter implementing the same methods.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Pharmacy, PharmacyInventory, utcnow

LIVE_FRESHNESS = timedelta(minutes=15)


@dataclass
class StockInfo:
    medication_id: int
    units_in_stock: int | None
    unit_price: float | None
    verified: bool          # True only when confirmed by a live integration recently
    carried: bool


class MockPharmacyNetwork:
    name = "mock-pharmacy-network"

    def __init__(self, db: Session):
        self.db = db

    def stock(self, pharmacy: Pharmacy, medication_id: int) -> StockInfo:
        row = self.db.scalars(
            select(PharmacyInventory).where(
                PharmacyInventory.pharmacy_id == pharmacy.id,
                PharmacyInventory.medication_id == medication_id,
            )
        ).first()
        if row is None:
            return StockInfo(medication_id, None, None, False, False)
        verified = (
            pharmacy.integration == "mock-live"
            and row.verified_at is not None
            and utcnow() - row.verified_at <= LIVE_FRESHNESS
        )
        return StockInfo(medication_id, row.units_in_stock, row.unit_price, verified, True)

    def refresh_live_stock(self, pharmacy: Pharmacy) -> None:
        """Simulates a live inventory sync: live-integrated pharmacies get fresh timestamps."""
        if pharmacy.integration != "mock-live":
            return
        for row in self.db.scalars(select(PharmacyInventory).where(PharmacyInventory.pharmacy_id == pharmacy.id)):
            row.verified_at = utcnow()

    def reserve(self, pharmacy: Pharmacy, medication_id: int, units: int) -> bool:
        row = self.db.scalars(
            select(PharmacyInventory).where(
                PharmacyInventory.pharmacy_id == pharmacy.id,
                PharmacyInventory.medication_id == medication_id,
            ).with_for_update()
        ).first()
        if row is None or row.units_in_stock < units:
            return False
        row.units_in_stock -= units
        return True

    def release(self, pharmacy: Pharmacy, medication_id: int, units: int) -> None:
        row = self.db.scalars(
            select(PharmacyInventory).where(
                PharmacyInventory.pharmacy_id == pharmacy.id,
                PharmacyInventory.medication_id == medication_id,
            )
        ).first()
        if row is not None:
            row.units_in_stock += units
