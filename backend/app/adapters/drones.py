"""Sandbox drone-logistics provider and road courier fallback.

Stands in for a real Indian medical-drone operator API (operators such as
TSAW Drones, Skye Air or Redwing run this kind of service). No real operator is
integrated or implied: every UIN, permission number and pilot below is
fictional. A real integration would swap this class for the operator's API
client and pull airspace permissions from the DGCA Digital Sky platform.
"""
from __future__ import annotations

import random
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..models import utcnow
from .delivery import COURIERS


@dataclass(frozen=True)
class DroneModel:
    model: str
    uin: str                    # Unique Identification Number issued on Digital Sky
    category: str               # Drone Rules 2021 weight category (all-up weight)
    max_payload_kg: float
    cold_box_payload_kg: float  # payload left when the active 2–8 °C box is fitted
    range_km: float             # one-way range with reserve
    cruise_kmh: float
    cold_box_hold_minutes: int


FLEET = [
    DroneModel("Demo VTOL-5 (fictional)", "UA-DEMO-0042", "Small (2–25 kg)", 5.0, 3.0, 30.0, 90.0, 120),
    DroneModel("Demo Quad-3 (fictional)", "UA-DEMO-0107", "Small (2–25 kg)", 3.0, 1.8, 15.0, 60.0, 90),
]
REMOTE_PILOTS = ["K. Varma (RPC DEMO-RPC-2231)", "S. Iyer (RPC DEMO-RPC-1874)", "A. Khan (RPC DEMO-RPC-3310)"]
MAX_WIND_KMH = 30.0
CRUISE_ALTITUDE_M = 100  # below the 120 m (400 ft) green-zone ceiling


@dataclass
class DroneBooking:
    provider_ref: str
    drone: DroneModel
    remote_pilot: str
    duration_minutes: int
    eta: datetime
    permission_ref: str | None
    handover_code: str
    extras: dict = field(default_factory=dict)


class SandboxDroneProvider:
    name = "Sandbox Drone Network (demo operator)"
    operating_jurisdictions = {"DEMO-IN"}

    def __init__(self, wind_kmh: float = 12.0):
        self.wind_kmh_now = wind_kmh

    def wind_kmh(self, lat: float, lng: float) -> float:
        """Mock weather feed at the launch point."""
        return self.wind_kmh_now

    def pick_drone(self, distance_km: float, weight_kg: float, cold_chain: bool) -> DroneModel | None:
        for d in sorted(FLEET, key=lambda d: d.max_payload_kg):
            cap = d.cold_box_payload_kg if cold_chain else d.max_payload_kg
            if weight_kg <= cap and distance_km <= d.range_km:
                return d
        return None

    def flight_minutes(self, drone: DroneModel, distance_km: float) -> int:
        return max(4, round(distance_km / drone.cruise_kmh * 60 + 4))  # +4 min climb, descent, winch

    def request_yellow_zone_permission(self, corridor: str) -> str:
        """Demo stand-in for an ATC/airport-operator permission via Digital Sky."""
        return f"DS-PERM-DEMO-{zlib.crc32(corridor.encode()) % 100000:05d}"

    def book(self, drone: DroneModel, distance_km: float, needs_permission: bool, corridor: str,
             prep_minutes: int = 5) -> DroneBooking:
        dur = self.flight_minutes(drone, distance_km)
        permission = self.request_yellow_zone_permission(corridor) if needs_permission else None
        delay = 15 if needs_permission else 0  # ATC slot
        return DroneBooking(
            provider_ref=f"DRN-{random.randint(0, 0xFFFFFF):06X}",
            drone=drone, remote_pilot=random.choice(REMOTE_PILOTS), duration_minutes=dur,
            eta=utcnow() + timedelta(minutes=prep_minutes + delay + dur), permission_ref=permission,
            handover_code=f"{random.randint(0, 9999):04d}",
        )


@dataclass
class RoadBooking:
    provider_ref: str
    courier: str
    vehicle: str
    duration_minutes: int
    eta: datetime
    handover_code: str


class SandboxRoadCourier:
    """Bike/van medical courier used whenever a drone can't fly the route."""

    name = "Sandbox Medical Courier (road)"

    def duration_minutes(self, distance_km: float, urgency: str = "routine") -> int:
        speed = 28.0 if urgency in ("urgent", "emergency") else 22.0  # city traffic, km/h
        return round(distance_km * 1.3 / speed * 60 + 10)  # 1.3 road-winding factor, 10 min pickup

    def book(self, distance_km: float, cold_chain: bool, urgency: str = "routine") -> RoadBooking:
        dur = self.duration_minutes(distance_km, urgency)
        return RoadBooking(
            provider_ref=f"RD-{random.randint(0, 0xFFFFFF):06X}", courier=random.choice(COURIERS),
            vehicle="Van with 2–8 °C box" if cold_chain or distance_km > 15 else "Bike with insulated bag",
            duration_minutes=dur, eta=utcnow() + timedelta(minutes=dur), handover_code=f"{random.randint(0, 9999):04d}",
        )


drone_provider = SandboxDroneProvider()
road_courier = SandboxRoadCourier()
