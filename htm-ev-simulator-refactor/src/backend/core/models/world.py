"""
Simulation World (domain aggregate root).

The World is an in-memory aggregate that groups domain entities needed to run a
simulation: vehicles, planning, and charging infrastructure.

Rationale: In hexagonal architecture, the core must stay independent from how
data is loaded (Excel/DB/API). A World aggregate provides a stable, explicit
domain object graph that can be constructed by a world-builder service using
ports. This keeps the simulation engine focused on behavior (use-cases) rather
than wiring and lookup logic, and makes tests deterministic and lightweight.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, TYPE_CHECKING

from .laad_infra.grid import Grid
from .laad_infra.location import Location
from .planning.block import Block
from .transport.bus.bus import Bus

if TYPE_CHECKING:
    from .planning.point_in_sequence import PointInSequence


class WorldDomainError(Exception):
    """Base class for world/aggregate consistency errors."""


class DuplicateEntityIdError(WorldDomainError):
    """Raised when attempting to register an entity with a duplicate id."""


class EntityNotFoundError(WorldDomainError):
    """Raised when an entity cannot be found in the world indexes."""


@dataclass(slots=True)
class World:
    """
    Aggregate root that holds entities and provides indexing/linking helpers.

    Notes:
    - This class intentionally does NOT load data from external sources.
    - It also avoids simulation-time behavior; those belong in services.
    """

    buses_by_vehicle_number: dict[int, Bus] = field(default_factory=dict)
    locations_by_id: dict[str, Location] = field(default_factory=dict)
    grids_by_id: dict[str, Grid] = field(default_factory=dict)
    blocks_by_id: dict[str, Block] = field(default_factory=dict)

    # --- Registration helpers -------------------------------------------------
    def add_bus(self, bus: Bus) -> None:
        key = int(bus.vehicle_number)
        if key in self.buses_by_vehicle_number:
            raise DuplicateEntityIdError(f"Duplicate bus vehicle_number: {key}")
        self.buses_by_vehicle_number[key] = bus

    def add_location(self, location: Location) -> None:
        key = str(location.location_id)
        if key in self.locations_by_id:
            raise DuplicateEntityIdError(f"Duplicate location_id: {key}")
        self.locations_by_id[key] = location

    def add_grid(self, grid: Grid) -> None:
        key = str(grid.grid_id)
        if key in self.grids_by_id:
            raise DuplicateEntityIdError(f"Duplicate grid_id: {key}")
        self.grids_by_id[key] = grid

    def add_block(self, block: Block) -> None:
        key = str(block.block_id)
        if key in self.blocks_by_id:
            raise DuplicateEntityIdError(f"Duplicate block_id: {key}")
        self.blocks_by_id[key] = block

    # --- Lookup helpers -------------------------------------------------------
    def get_bus(self, vehicle_number: int) -> Bus:
        try:
            return self.buses_by_vehicle_number[int(vehicle_number)]
        except KeyError as e:
            raise EntityNotFoundError(f"Bus not found: vehicle_number={vehicle_number}") from e

    def get_location(self, location_id: str) -> Location:
        key = str(location_id)
        try:
            return self.locations_by_id[key]
        except KeyError as e:
            raise EntityNotFoundError(f"Location not found: location_id={key}") from e

    def get_grid(self, grid_id: str) -> Grid:
        key = str(grid_id)
        try:
            return self.grids_by_id[key]
        except KeyError as e:
            raise EntityNotFoundError(f"Grid not found: grid_id={key}") from e

    def get_block(self, block_id: str) -> Block:
        key = str(block_id)
        try:
            return self.blocks_by_id[key]
        except KeyError as e:
            raise EntityNotFoundError(f"Block not found: block_id={key}") from e

    # --- Linking helpers ------------------------------------------------------
    def connect_location_to_grid(self, *, location_id: str, grid_id: str) -> None:
        """
        Connect a location to a grid and set back-references.

        Rationale: Object-graph wiring should be explicit and centralized to
        avoid scattered mutation across adapters and services.
        """
        location = self.get_location(location_id)
        grid = self.get_grid(grid_id)
        location.grid = grid
        grid.connect_location(location)

    def attach_locations_to_points(self, points: Iterable["PointInSequence"]) -> None:
        """
        Attach `Location` objects to planning points using `point_id` matching.

        A point is considered a charging location if a `Location` exists with
        `Location.point_id == PointInSequence.point_id`.

        Rationale: Planning models should not import laad-infra models directly.
        This linking step keeps the dependency direction clean while still
        building a usable world graph for simulation.
        """
        # Build index: point_id -> Location
        point_to_location: dict[str, Location] = {}
        for loc in self.locations_by_id.values():
            if loc.point_id:
                point_to_location[str(loc.point_id)] = loc

        for p in points:
            pid = str(p.point_id)
            loc: Optional[Location] = point_to_location.get(pid)
            if loc is not None:
                p.charging_location = loc

