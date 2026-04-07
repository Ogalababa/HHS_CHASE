from __future__ import annotations

import unittest
from datetime import date


class TestBusPlanningParquetProvider(unittest.TestCase):
    def setUp(self) -> None:
        import sys

        if "htm-ev-simulator/src" not in sys.path:
            sys.path.insert(0, "htm-ev-simulator/src")

    def test_df_to_blocks_basic_mapping(self) -> None:
        import pandas as pd

        from backend.infrastructure.bus_planning_parquet_provider import _df_to_blocks

        df = pd.DataFrame(
            [
                {
                    "BlockId": "B1",
                    "OperatingDay": date(2026, 1, 1),
                    "JourneyId": "J1",
                    "JourneyRef": "J1",
                    "JourneyType": "SERVICE",
                    "VehicleType": "E-BUS",
                    "PublicLineNumber": "1",
                    "VersionType": "A",
                    "PointInSequenceId": 10,
                    "PointInSequenceName": "Stop A",
                    "PointInSequenceOrder": 1,
                    "ArrivalTime": "08:00:00",
                    "DepartureTime": "08:05:00",
                    "DistanceToNextPointInSequence": 1000,
                    "IsWaitPoint": False,
                },
                {
                    "BlockId": "B1",
                    "OperatingDay": date(2026, 1, 1),
                    "JourneyId": "J1",
                    "JourneyRef": "J1",
                    "JourneyType": "SERVICE",
                    "VehicleType": "E-BUS",
                    "PublicLineNumber": "1",
                    "VersionType": "A",
                    "PointInSequenceId": 11,
                    "PointInSequenceName": "Stop B",
                    "PointInSequenceOrder": 2,
                    "ArrivalTime": "08:10:00",
                    "DepartureTime": "08:11:00",
                    "DistanceToNextPointInSequence": 0,
                    "IsWaitPoint": True,
                },
            ]
        )

        blocks = _df_to_blocks(df)
        self.assertEqual(len(blocks), 1)
        blk = blocks[0]
        self.assertEqual(blk.operating_day, date(2026, 1, 1))
        self.assertEqual(len(blk.journeys), 1)

        j = blk.journeys[0]
        self.assertEqual(j.point_count, 2)
        self.assertEqual(j.points[0].name, "Stop A")
        self.assertEqual(j.points[1].name, "Stop B")
        self.assertTrue(j.points[1].is_wait_point)


if __name__ == "__main__":
    unittest.main()

