"""
Defines the Grid (electrical grid) domain model.

Rationale: Grid constraints are part of the domain vocabulary (they shape how
much charging power can be used over time) but they must remain independent
from infrastructure (SCADA/DB/APIs). A small domain model provides a single
place to encode time-dependent capacity and to aggregate load across connected
locations, while allowing adapters to supply the actual profile function.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .location import Location

AvailablePowerProfileKw = Callable[[datetime], float]


@dataclass(slots=True)
class Grid:
    """
    Represents an electrical grid that provides power to charging locations.

    The grid can have time-dependent available power limits that restrict the
    maximum aggregate power that can be drawn by all connected locations.
    """

    grid_id: str
    name: Optional[str] = None

    available_power_profile: Optional[AvailablePowerProfileKw] = None
    connected_locations: list["Location"] = field(default_factory=list, repr=False)

    def get_available_power_at(self, time: datetime) -> float:
        """
        Return the available power from the grid at a specific time.

        Returns:
            Available power in kW. Returns `inf` if no profile is set.
        """
        if self.available_power_profile is not None:
            return float(self.available_power_profile(time))
        return float("inf")

    def connect_location(self, location: "Location") -> None:
        """
        Connect a location to this grid (back-reference list).

        Rationale: World-building often happens in adapters/services. This
        helper keeps the domain relationship consistent without introducing
        external dependencies.
        """
        if location not in self.connected_locations:
            self.connected_locations.append(location)

    @property
    def current_total_load_kw(self) -> float:
        """Total power currently being drawn by all connected locations."""
        return float(sum(loc.current_load_kw for loc in self.connected_locations))

    def get_remaining_capacity_at(self, time: datetime) -> float:
        """
        Remaining grid capacity at a specific time.

        Remaining capacity = available_power - current_total_load
        """
        available = self.get_available_power_at(time)
        return max(0.0, float(available) - self.current_total_load_kw)

