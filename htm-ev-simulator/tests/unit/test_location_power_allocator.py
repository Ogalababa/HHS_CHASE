from __future__ import annotations

import unittest
from datetime import datetime

from tests.unit._src_path import ensure_backend_src_on_path

ensure_backend_src_on_path()

from backend.core.models.laad_infra.charger import Charger
from backend.core.models.laad_infra.connector import Connector
from backend.core.models.laad_infra.location import Location
from backend.core.models.transport.bus import Bus, BusState
from backend.core.services.simpy_engine.resource_allocator import LocationPowerAllocator


class TestLocationPowerAllocator(unittest.TestCase):
    """Allocate power envelope under optional site budgets."""

    def _location_with_charger(self) -> tuple[Location, Connector]:
        loc = Location(location_id="T1", latitude=1.0, longitude=2.0, point_id="30002")
        ch = Charger(charger_id="C1", max_power_kw=400.0)
        conn = Connector(connector_id="K1", max_power_kw=300.0, connector_type="CCS")
        ch.add_connector(conn)
        loc.chargers[ch.charger_id] = ch
        return loc, conn

    def test_unlimited_allocation_returns_desired_kw(self) -> None:
        alloc = LocationPowerAllocator(power_limit_enabled=False)
        loc, conn = self._location_with_charger()
        out = alloc.allocate_power_kw(
            location=loc,
            connector_previous_kw=0.0,
            desired_kw=200.0,
            next_time_ts=datetime(2026, 1, 1, 12, 0, 0).timestamp(),
        )
        self.assertAlmostEqual(out, 200.0, places=6)

    def test_apply_energy_raises_soc_via_bus_update(self) -> None:
        bus = Bus(
            vehicle_number=1,
            vin_number="V1",
            vehicle_type="E-BUS",
            state=BusState.AVAILABLE,
            energy_consumption_per_km=1.0,
            soc_percent=50.0,
            battery_capacity_kwh=100.0,
        )
        LocationPowerAllocator.apply_energy(bus, power_kw=50.0, dt_seconds=3600)
        self.assertGreater(bus.soc_percent, 50.0)

    def test_reset_clears_slot_tracker(self) -> None:
        alloc = LocationPowerAllocator(power_limit_enabled=True)

        def fake_profile(dt: datetime) -> float:
            return 100.0

        loc = Location(location_id="G1", latitude=1.0, longitude=2.0, point_id="30002")
        loc.grid = None
        loc.max_power_profile = fake_profile
        conn = Connector(connector_id="K9", max_power_kw=120.0, connector_type="CCS")
        ch = Charger(charger_id="Cx", max_power_kw=300.0, connectors=[conn])
        loc.chargers[ch.charger_id] = ch
        conn.current_power_kw = 0.0

        ts = datetime(2026, 6, 1, 10, 0, 0).timestamp()
        a = alloc.allocate_power_kw(
            location=loc,
            connector_previous_kw=0.0,
            desired_kw=80.0,
            next_time_ts=ts,
        )
        self.assertGreaterEqual(a, 0.0)
        alloc.reset()
        self.assertEqual(len(alloc._allocated_by_slot), 0)


if __name__ == "__main__":
    unittest.main()
