"""
Bus fleet provider port (contract).

Rationale: Vehicle/fleet data can come from multiple sources (API snapshots,
configuration files, databases). The simulation core should consume a stable
domain representation (`Bus`) without depending on those sources.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models.transport.bus.bus import Bus


class BusProviderPort(ABC):
    """Provide the bus fleet to the core."""

    @abstractmethod
    def get_buses(self) -> list[Bus]:
        """
        Return all buses to include in the simulation.

        Implementations should ensure `vehicle_number` is unique per bus.
        """

