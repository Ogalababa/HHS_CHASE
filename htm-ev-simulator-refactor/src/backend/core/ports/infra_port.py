"""
Infrastructure (charging infra) provider port (contract).

Rationale: Charging infrastructure data (locations, chargers, connectors, grid
profiles) comes from external sources and must be adaptable. This port keeps
the core independent of the data source, while allowing the world builder to
assemble a consistent domain object graph.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models.laad_infra.grid import Grid
from ..models.laad_infra.location import Location


class InfrastructureProviderPort(ABC):
    """
    Provide charging-infrastructure domain objects to the core.
    """

    @abstractmethod
    def get_grids(self) -> list[Grid]:
        """Return all grids used in the simulation world."""

    @abstractmethod
    def get_locations(self) -> list[Location]:
        """
        Return all locations (with chargers/connectors populated as needed).

        Rationale: A location is the domain aggregate for physical charging
        infrastructure. Adapters should attach chargers/connectors to locations
        before returning them.
        """

    def get_location_grid_links(self) -> list[tuple[str, str]]:
        """
        Optional: return (location_id, grid_id) links.

        If adapters already set `Location.grid`, this method can return an empty list.
        """
        return []

