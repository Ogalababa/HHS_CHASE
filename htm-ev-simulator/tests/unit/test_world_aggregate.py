from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta

from tests.unit._src_path import ensure_backend_src_on_path

ensure_backend_src_on_path()

from backend.core.models.laad_infra.location import Location
from backend.core.models.planning.block import Block
from backend.core.models.planning.journey import Journey
from backend.core.models.planning.point_in_sequence import PointInSequence
from backend.core.models.transport.bus import Bus, BusState
from backend.core.models.world import DuplicateEntityIdError, EntityNotFoundError, World


def _dummy_point(pid: str = "30005") -> PointInSequence:
    t0 = datetime(2026, 1, 15, 6, 0, 0)
    return PointInSequence(
        point_id=pid,
        name="Stop",
        sequence_order=1,
        latitude=0.0,
        longitude=0.0,
        distance_to_next_m=1000.0,
        arrival_datetime=t0,
        departure_datetime=t0 + timedelta(minutes=1),
        wait_time=timedelta(0),
        is_wait_point=False,
    )


class TestWorldAggregate(unittest.TestCase):
    """Tests for aggregate registration and point–location linking."""

    def test_duplicate_bus_raises(self) -> None:
        world = World()
        b = Bus(
            vehicle_number=10,
            vin_number="VX",
            vehicle_type="E-BUS",
            state=BusState.AVAILABLE,
            energy_consumption_per_km=1.0,
            soc_percent=80.0,
            battery_capacity_kwh=100.0,
        )
        world.add_bus(b)
        b2 = Bus(
            vehicle_number=10,
            vin_number="VY",
            vehicle_type="E-BUS",
            state=BusState.AVAILABLE,
            energy_consumption_per_km=1.0,
            soc_percent=80.0,
            battery_capacity_kwh=100.0,
        )
        with self.assertRaises(DuplicateEntityIdError):
            world.add_bus(b2)

    def test_get_bus_raises_entity_not_found(self) -> None:
        world = World()
        with self.assertRaises(EntityNotFoundError):
            world.get_bus(999)

    def test_attach_locations_to_points_sets_charging_location(self) -> None:
        world = World()
        loc = Location(location_id="L1", latitude=1.0, longitude=2.0, point_id="30005")
        world.add_location(loc)

        jour = Journey(
            journey_id="J1",
            journey_ref="R1",
            journey_type="Dienst",
            vehicle_type="E-BUS",
            public_line_number="22",
            version_type="A",
        )
        pt = _dummy_point("30005")
        jour.add_point(pt)
        blk = Block("BLK1", date(2026, 1, 15))
        blk.journeys.append(jour)
        world.add_block(blk)

        world.attach_locations_to_points([pt])
        self.assertIs(pt.charging_location, loc)


if __name__ == "__main__":
    unittest.main()
