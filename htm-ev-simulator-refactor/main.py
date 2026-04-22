from __future__ import annotations

"""
Minimal runnable entrypoint for building a World.

Rationale: This script provides the smallest end-to-end "smoke test" for the
hexagonal core: adapters implement ports, WorldBuilder assembles the World, and
we verify that linking works (planning point -> charging Location, Location -> Grid).
It intentionally avoids ADLS/OMNIplus network calls and uses local JSON + in-memory stubs.
"""

import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path


def _ensure_src_on_path() -> None:
    src = Path(__file__).resolve().parent / "src"
    sys.path.insert(0, str(src))


_ensure_src_on_path()

from backend.core.models.planning.block import Block
from backend.core.models.planning.journey import Journey
from backend.core.models.planning.point_in_sequence import PointInSequence
from backend.core.models.transport.bus import Bus, BusState
from backend.core.ports.bus_port import BusProviderPort
from backend.core.ports.planning_port import PlanningProviderPort
from backend.core.services.world_builder import WorldBuilder
from backend.infrastructure.connector_json_infra_provider import ConnectorJsonInfrastructureProvider


@dataclass(slots=True)
class StubBusProvider(BusProviderPort):
    n_buses: int = 2

    def get_buses(self) -> list[Bus]:
        buses: list[Bus] = []
        for i in range(1, self.n_buses + 1):
            buses.append(
                Bus(
                    vehicle_number=i,
                    vin_number=f"VIN{i}",
                    vehicle_type="E-BUS",
                    state=BusState.AVAILABLE,
                    energy_consumption_per_km=1.0,
                    soc_percent=80.0,
                    battery_capacity_kwh=100.0,
                )
            )
        return buses


@dataclass(slots=True)
class StubPlanningProvider(PlanningProviderPort):
    point_ids: list[str]
    operating_day: date = date(2026, 1, 1)

    def get_blocks(self) -> list[Block]:
        blk = Block(block_id=f"B1_{self.operating_day.isoformat()}", operating_day=self.operating_day)

        j = Journey(
            journey_id=f"J1_{self.operating_day.isoformat()}",
            journey_ref="J1",
            journey_type="SERVICE",
            vehicle_type="E-BUS",
            public_line_number="1",
            version_type="A",
            block_id=blk.block_id,
        )

        # Make a point for each provided point_id (up to a small cap for readability)
        for idx, pid in enumerate(self.point_ids[:5], start=1):
            j.add_point(
                PointInSequence(
                    point_id=pid,
                    name=f"Stop {pid}",
                    sequence_order=idx,
                    latitude=0.0,
                    longitude=0.0,
                    distance_to_next_m=0.0,
                    arrival_datetime=datetime.combine(self.operating_day, datetime.min.time())
                    + timedelta(minutes=idx),
                    departure_datetime=datetime.combine(self.operating_day, datetime.min.time())
                    + timedelta(minutes=idx + 1),
                    wait_time=timedelta(0),
                    is_wait_point=False,
                )
            )

        blk.add_journey(j)
        return [blk]


def main() -> None:
    json_path = Path(__file__).resolve().parent / "src" / "backend" / "infrastructure" / "data" / "processed_laadpalen_data.json"
    power_limits_path = (
        Path(__file__).resolve().parent
        / "src"
        / "backend"
        / "infrastructure"
        / "data"
        / "grid_power_limits.json"
    )
    infra = ConnectorJsonInfrastructureProvider(json_path=json_path, power_limits_path=power_limits_path)

    # Collect point_ids from infra so we can create matching planning points.
    point_ids = sorted({str(loc.point_id) for loc in infra.get_locations() if loc.point_id})
    planning = StubPlanningProvider(point_ids=point_ids)
    buses = StubBusProvider(n_buses=2)

    wb = WorldBuilder(planning=planning, infrastructure=infra, buses=buses)
    result = wb.build()

    print("WorldBuildResult")
    print(
        f"- buses={result.n_buses}, grids={result.n_grids}, locations={result.n_locations}, "
        f"blocks={result.n_blocks}, journeys={result.n_journeys}, points={result.n_points}"
    )

    # Show a sample linkage if available (prefer Telexstraat if present)
    blk = next(iter(result.world.blocks_by_id.values()))
    points = blk.journeys[0].points
    pt = next(
        (
            p
            for p in points
            if p.charging_location is not None and p.charging_location.location_id == "Telexstraat"
        ),
        points[0],
    )
    print(f"Sample point_id={pt.point_id} charging_linked={pt.is_charging_location}")
    if pt.charging_location:
        grid_id = getattr(pt.charging_location.grid, "grid_id", None)
        print(f"  -> Location={pt.charging_location.location_id} grid={grid_id}")
        if pt.charging_location.grid is not None:
            # Demonstrate the time-dependent limit if present
            dt_01 = datetime(2026, 1, 1, 1, 0, 0)
            dt_09 = datetime(2026, 1, 1, 9, 0, 0)
            print(f"  -> grid_available_kw@01:00={pt.charging_location.grid.get_available_power_at(dt_01)}")
            print(f"  -> grid_available_kw@09:00={pt.charging_location.grid.get_available_power_at(dt_09)}")


if __name__ == "__main__":
    main()

