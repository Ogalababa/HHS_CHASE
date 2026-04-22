"""
Location-level charging resource allocation.

Rationale: Power-budget logic should be isolated from scheduler flow so it
remains reusable and testable, especially for Telexstraat time-window caps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ...models.laad_infra.location import Location
from ...models.transport.bus.bus import Bus


@dataclass(slots=True)
class LocationPowerAllocator:
    """Allocate connector power under optional location-level limits."""

    power_limit_enabled: bool = False
    _allocated_by_slot: dict[tuple[str, float], float] = field(default_factory=dict)

    def reset(self) -> None:
        self._allocated_by_slot.clear()

    def _location_power_limit_kw(self, location: Location, time_ts: float) -> float:
        if not self.power_limit_enabled:
            return float("inf")
        loc_id = str(getattr(location, "location_id", "")).lower()
        point_id = str(getattr(location, "point_id", ""))
        if point_id not in {"30002", "3002"} and "telexstraat" not in loc_id:
            return float("inf")
        profile = getattr(location, "max_power_profile", None)
        if callable(profile):
            return float(profile(datetime.fromtimestamp(time_ts)))
        grid = getattr(location, "grid", None)
        if grid is not None:
            return float(grid.get_available_power_at(datetime.fromtimestamp(time_ts)))
        return float("inf")

    @staticmethod
    def location_current_load_kw(location: Location) -> float:
        return float(sum(ch.current_load_kw for ch in location.chargers.values()))

    def allocate_power_kw(
        self,
        *,
        location: Location,
        connector_previous_kw: float,
        desired_kw: float,
        next_time_ts: float,
    ) -> float:
        """
        Return allocated power for one connector at one timestep.

        Rationale: Enforce both per-connector remaining headroom and a global
        per-(location,timestamp) budget so concurrent charging loops cannot
        violate location limits.
        """
        limit_kw = self._location_power_limit_kw(location, next_time_ts)
        if limit_kw == float("inf"):
            return max(0.0, float(desired_kw))

        current_load = self.location_current_load_kw(location)
        other_load = max(0.0, current_load - max(0.0, float(connector_previous_kw)))
        remaining_for_connector = max(0.0, float(limit_kw) - other_load)
        candidate = min(max(0.0, float(desired_kw)), remaining_for_connector)

        slot_key = (str(location.location_id), float(next_time_ts))
        allocated = float(self._allocated_by_slot.get(slot_key, 0.0))
        remaining_slot = max(0.0, float(limit_kw) - allocated)
        actual = min(candidate, remaining_slot)
        self._allocated_by_slot[slot_key] = allocated + actual
        return actual

    @staticmethod
    def apply_energy(bus: Bus, power_kw: float, dt_seconds: int) -> None:
        if power_kw <= 0.0:
            return
        delta_kwh = float(power_kw) * (float(dt_seconds) / 3600.0)
        bus.update_soc(delta_kwh)

