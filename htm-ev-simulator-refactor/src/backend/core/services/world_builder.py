"""
World builder service.

This service assembles a `World` aggregate from port-provided domain objects.

Rationale: The WorldBuilder belongs in the core service/use-case layer because
it performs orchestration (wiring and consistency) rather than representing a
business entity. By consuming ports, it keeps the core independent from data
sources (Excel/DB/API) and concentrates graph-building logic in one place,
making the simulation engine simpler and easier to test.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..models.world import World
from ..ports.bus_port import BusProviderPort
from ..ports.infra_port import InfrastructureProviderPort
from ..ports.planning_port import PlanningProviderPort


@dataclass(slots=True)
class WorldBuildResult:
    """
    Result of building a world.

    Rationale: Returning a small report alongside the world helps debugging and
    makes it easier to validate input coverage in tests and notebooks without
    coupling to logging infrastructure.
    """

    world: World
    n_buses: int
    n_grids: int
    n_locations: int
    n_blocks: int
    n_journeys: int
    n_points: int


class WorldBuilder:
    """
    Build a `World` aggregate using core ports.
    """

    def __init__(
        self,
        *,
        planning: PlanningProviderPort,
        infrastructure: InfrastructureProviderPort,
        buses: BusProviderPort,
    ) -> None:
        self._planning = planning
        self._infrastructure = infrastructure
        self._buses = buses

    def build(self) -> WorldBuildResult:
        """
        Build a world and wire cross-aggregate references.

        Steps (high level):
        - Register buses, grids, locations, blocks into the World indexes
        - Connect `Location` objects to `Grid` objects (if provided)
        - Attach `Location` objects to planning points by `point_id`
        """
        world = World()

        buses = self._buses.get_buses()
        for b in buses:
            world.add_bus(b)

        grids = self._infrastructure.get_grids()
        for g in grids:
            world.add_grid(g)

        locations = self._infrastructure.get_locations()
        for loc in locations:
            world.add_location(loc)

        # Wiring Location <-> Grid: prefer explicit links from port; otherwise
        # respect adapter-populated Location.grid (if present).
        for location_id, grid_id in self._infrastructure.get_location_grid_links():
            world.connect_location_to_grid(location_id=location_id, grid_id=grid_id)

        for loc in world.locations_by_id.values():
            if loc.grid is not None:
                gid = getattr(loc.grid, "grid_id", None)
                if gid is not None and str(gid) in world.grids_by_id:
                    world.connect_location_to_grid(location_id=loc.location_id, grid_id=str(gid))

        blocks = self._planning.get_blocks()
        for blk in blocks:
            world.add_block(blk)

        journeys = list(_iter_journeys(blocks))
        points = list(_iter_points(journeys))
        world.attach_locations_to_points(points)

        return WorldBuildResult(
            world=world,
            n_buses=len(buses),
            n_grids=len(grids),
            n_locations=len(locations),
            n_blocks=len(blocks),
            n_journeys=len(journeys),
            n_points=len(points),
        )


def _iter_journeys(blocks: Iterable) -> Iterable:
    for blk in blocks:
        for j in getattr(blk, "journeys", []):
            yield j


def _iter_points(journeys: Iterable) -> Iterable:
    for j in journeys:
        for p in getattr(j, "points", []):
            yield p

