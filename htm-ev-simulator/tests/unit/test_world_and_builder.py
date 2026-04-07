from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta


class TestWorldAndWorldBuilder(unittest.TestCase):
    def setUp(self) -> None:
        import sys

        if "htm-ev-simulator/src" not in sys.path:
            sys.path.insert(0, "htm-ev-simulator/src")

    def test_world_duplicate_ids_raise(self) -> None:
        from backend.core.models import DuplicateEntityIdError, World
        from backend.core.models.laad_infra import Grid

        w = World()
        w.add_grid(Grid(grid_id="G1"))
        with self.assertRaises(DuplicateEntityIdError):
            w.add_grid(Grid(grid_id="G1"))

    def test_world_attach_locations_to_points_by_point_id(self) -> None:
        from backend.core.models import World
        from backend.core.models.laad_infra import Location
        from backend.core.models.planning.point_in_sequence import PointInSequence

        w = World()
        w.add_location(Location(location_id="L1", latitude=52.0, longitude=4.3, point_id="42"))

        p = PointInSequence(
            point_id="42",
            name="Stop A",
            sequence_order=1,
            latitude=52.0,
            longitude=4.3,
            distance_to_next_m=1000.0,
            arrival_datetime=datetime(2026, 1, 1, 8, 0, 0),
            departure_datetime=datetime(2026, 1, 1, 8, 5, 0),
            wait_time=timedelta(minutes=0),
            is_wait_point=False,
        )
        self.assertFalse(p.is_charging_location)

        w.attach_locations_to_points([p])
        self.assertTrue(p.is_charging_location)
        self.assertIsNotNone(p.charging_location)
        self.assertEqual(p.charging_location.location_id, "L1")

    def test_world_builder_builds_and_links(self) -> None:
        from backend.core.models.laad_infra import Grid, Location
        from backend.core.models.planning.block import Block
        from backend.core.models.planning.journey import Journey
        from backend.core.models.planning.point_in_sequence import PointInSequence
        from backend.core.models.transport.bus import Bus, BusState
        from backend.core.services.world_builder import WorldBuilder

        class FakePlanning:
            def get_blocks(self) -> list[Block]:
                blk = Block(block_id="B1", operating_day=date(2026, 1, 1))
                j = Journey(
                    journey_id="J1",
                    journey_ref="J1",
                    journey_type="SERVICE",
                    vehicle_type="E-BUS",
                    public_line_number="1",
                    version_type="A",
                )
                j.add_point(
                    PointInSequence(
                        point_id="P1",
                        name="Depot",
                        sequence_order=1,
                        latitude=52.0,
                        longitude=4.3,
                        distance_to_next_m=0.0,
                        arrival_datetime=datetime(2026, 1, 1, 8, 0, 0),
                        departure_datetime=datetime(2026, 1, 1, 8, 0, 0),
                        wait_time=timedelta(minutes=0),
                        is_wait_point=False,
                    )
                )
                blk.add_journey(j)
                return [blk]

        class FakeInfra:
            def get_grids(self) -> list[Grid]:
                return [Grid(grid_id="G1")]

            def get_locations(self) -> list[Location]:
                return [Location(location_id="L1", latitude=52.0, longitude=4.3, point_id="P1")]

            def get_location_grid_links(self) -> list[tuple[str, str]]:
                return [("L1", "G1")]

        class FakeBuses:
            def get_buses(self) -> list[Bus]:
                return [
                    Bus(
                        1,
                        "VIN",
                        "E-BUS",
                        BusState.AVAILABLE,
                        1.0,
                        50.0,
                        battery_capacity_kwh=100.0,
                    )
                ]

        wb = WorldBuilder(planning=FakePlanning(), infrastructure=FakeInfra(), buses=FakeBuses())
        result = wb.build()

        self.assertEqual(result.n_buses, 1)
        self.assertEqual(result.n_grids, 1)
        self.assertEqual(result.n_locations, 1)
        self.assertEqual(result.n_blocks, 1)
        self.assertEqual(result.n_journeys, 1)
        self.assertEqual(result.n_points, 1)

        # Cross-links: location -> grid
        loc = result.world.get_location("L1")
        self.assertIsNotNone(loc.grid)
        self.assertEqual(loc.grid.grid_id, "G1")

        # Cross-links: point -> location
        blk = result.world.get_block("B1")
        pt = blk.journeys[0].points[0]
        self.assertTrue(pt.is_charging_location)
        self.assertEqual(pt.charging_location.location_id, "L1")


if __name__ == "__main__":
    unittest.main()

