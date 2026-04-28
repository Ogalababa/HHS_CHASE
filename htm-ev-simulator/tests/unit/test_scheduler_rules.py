from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from tests.unit._src_path import ensure_backend_src_on_path

ensure_backend_src_on_path()

from backend.core.models.planning.journey import Journey
from backend.core.models.planning.point_in_sequence import PointInSequence
from backend.core.models.transport.bus import Bus, BusState
from backend.core.models.world import World
from backend.core.services.simpy_engine.event_log import InternalEventLog
from backend.core.services.simpy_engine.resource_allocator import LocationPowerAllocator
from backend.core.services.simpy_engine.scheduler import SimpyScheduler


def _mk_point(
    *,
    pid: str,
    dist_m: float,
    departure: datetime,
) -> PointInSequence:
    return PointInSequence(
        point_id=pid,
        name="x",
        sequence_order=1,
        latitude=0.0,
        longitude=0.0,
        distance_to_next_m=dist_m,
        arrival_datetime=departure - timedelta(seconds=60),
        departure_datetime=departure,
        wait_time=timedelta(0),
        is_wait_point=False,
    )


class TestSchedulerBusinessRules(unittest.TestCase):
    """Static journey/business-rule hooks on ``SimpyScheduler``."""

    def _sched(self, low_soc: float = 14.0) -> SimpyScheduler:
        return SimpyScheduler(
            world=World(),
            logger=InternalEventLog(),
            allocator=LocationPowerAllocator(),
            low_soc_alert_threshold_percent=low_soc,
            charging_target_soc_percent=100.0,
            charging_step_seconds=60,
            simulation_start_timestamp=0.0,
            simulation_end_timestamp=None,
            strategies=[],
        )

    def test_garage_destination_journey_is_true(self) -> None:
        t0 = datetime(2026, 3, 1, 10, 0, 0)
        j = Journey("J_G", "rf", "Dienst", "E-BUS", "22", "A")
        j.add_point(
            PointInSequence(
                point_id="A1",
                name="a",
                sequence_order=1,
                latitude=0.0,
                longitude=0.0,
                distance_to_next_m=1000.0,
                arrival_datetime=t0,
                departure_datetime=t0,
                wait_time=timedelta(0),
                is_wait_point=False,
            )
        )
        j.add_point(_mk_point(pid="30002", dist_m=0.0, departure=t0 + timedelta(minutes=10)))
        self.assertTrue(SimpyScheduler._is_garage_destination_journey(j))

    def test_can_complete_garage_journey_even_if_soc_would_be_low(self) -> None:
        sched = self._sched()
        t0 = datetime(2026, 3, 1, 10, 0, 0)
        j = Journey("J_G2", "rf", "Dienst", "E-BUS", "22", "A")
        j.add_point(
            PointInSequence(
                point_id="A1",
                name="a",
                sequence_order=1,
                latitude=0.0,
                longitude=0.0,
                distance_to_next_m=5000.0,
                arrival_datetime=t0,
                departure_datetime=t0,
                wait_time=timedelta(0),
                is_wait_point=False,
            )
        )
        j.add_point(_mk_point(pid="30002", dist_m=0.0, departure=t0 + timedelta(minutes=20)))
        bus = Bus(
            vehicle_number=1,
            vin_number="VX",
            vehicle_type="E-BUS",
            state=BusState.AVAILABLE,
            energy_consumption_per_km=50.0,
            soc_percent=20.0,
            battery_capacity_kwh=80.0,
        )
        self.assertTrue(sched._can_complete_journey(bus, j))

    def test_can_complete_false_when_projected_below_threshold(self) -> None:
        sched = self._sched(low_soc=14.0)
        t0 = datetime(2026, 3, 1, 8, 0, 0)
        j = Journey("J_NR", "rf", "Dienst", "E-BUS", "22", "A")
        j.add_point(
            PointInSequence(
                point_id="A1",
                name="a",
                sequence_order=1,
                latitude=0.0,
                longitude=0.0,
                distance_to_next_m=100_000.0,
                arrival_datetime=t0,
                departure_datetime=t0,
                wait_time=timedelta(0),
                is_wait_point=False,
            )
        )
        j.add_point(
            _mk_point(
                pid="B3",
                dist_m=0.0,
                departure=t0 + timedelta(hours=1),
            )
        )
        bus = Bus(
            vehicle_number=2,
            vin_number="VY",
            vehicle_type="E-BUS",
            state=BusState.AVAILABLE,
            energy_consumption_per_km=5.0,
            soc_percent=18.0,
            battery_capacity_kwh=352.8,
        )
        self.assertFalse(sched._can_complete_journey(bus, j))


if __name__ == "__main__":
    unittest.main()
