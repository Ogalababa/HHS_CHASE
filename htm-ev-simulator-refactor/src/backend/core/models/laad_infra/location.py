"""
Defines the Location domain model for charging infrastructure.

Rationale: A `Location` groups chargers at a physical place and provides domain
queries such as "how much power is available here right now?". Keeping this
logic in the domain layer makes the simulation engine independent from how
locations/chargers are loaded (Excel/API/DB) and how results are persisted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from .charger import Charger
from .grid import Grid


PowerProfileKw = Callable[[datetime], float]


@dataclass(slots=True)
class Location:
    """
    Represents a physical location that contains charging infrastructure.

    Notes:
    - `point_id` can be used to link this location to planning data
      (`PointInSequence.point_id`) without importing planning models here.
    - `physical_max_power_profile` models device-side site capability independent
      from grid constraints.
    """

    location_id: str
    latitude: float
    longitude: float
    point_id: str | None = None  # Link with a planning PointInSequence (by id)
    chargers: dict[str, Charger] = field(default_factory=dict)

    grid: Grid | None = None

    physical_max_power_profile: PowerProfileKw | None = None
    max_power_profile: PowerProfileKw | None = None  # Backward compatibility

    def get_or_create_charger(self, charger_id: str, **kwargs) -> Charger:
        """
        Retrieve an existing charger or create a new one.

        Rationale: This convenience keeps adapter code simple when constructing
        the domain model from tabular sources (e.g., Excel rows).
        """
        if charger_id not in self.chargers:
            self.chargers[charger_id] = Charger(charger_id=charger_id, **kwargs)
        return self.chargers[charger_id]

    def get_max_power_at(self, time: datetime) -> float:
        """
        Backward-compatible alias for `get_available_power_at()`.
        """
        return self.get_available_power_at(time)

    def get_available_power_at(self, time: datetime) -> float:
        """
        Return the maximum power available at this location at a specific time.

        Current behavior: returns unlimited power.

        Rationale: Grid constraints are not yet modeled in the current core
        simulation. Returning `inf` preserves previous behavior while keeping a
        dedicated domain method that can be upgraded later to incorporate grid
        limits (potentially via a port/service).
        """
        _ = time  # kept for signature stability
        return float("inf")

    def get_physical_max_power_at(self, time: datetime) -> float:
        """
        Return the physical maximum power capability of the infrastructure.
        This does not consider grid limits.
        """
        if self.physical_max_power_profile is not None:
            return float(self.physical_max_power_profile(time))
        if self.max_power_profile is not None:
            return float(self.max_power_profile(time))

        total = sum(charger.max_power_kw for charger in self.chargers.values())
        return float(total) if total > 0.0 else float("inf")

    @property
    def current_load_kw(self) -> float:
        """Current total power being drawn from all chargers."""
        return float(sum(c.current_load_kw for c in self.chargers.values()))

    @property
    def remaining_capacity_kw(self) -> float:
        """
        Remaining capacity considering available power and current load.
        """
        available = self.get_available_power_at(datetime.now())
        return max(0.0, float(available) - self.current_load_kw)

