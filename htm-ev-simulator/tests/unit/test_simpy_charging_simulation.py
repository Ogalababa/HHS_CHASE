from __future__ import annotations

import unittest


class TestSimpyChargingSimulation(unittest.TestCase):
    def setUp(self) -> None:
        import sys

        if "htm-ev-simulator/src" not in sys.path:
            sys.path.insert(0, "htm-ev-simulator/src")

    def test_simpy_simulates_from_10_to_100_and_soc_is_monotonic(self) -> None:
        try:
            import simpy  # noqa: F401
        except ImportError:
            self.skipTest("simpy not installed")

        from backend.core.models.transport.bus import Bus, BusState
        from backend.core.services import simulate_charging_soc_trace_simpy

        bus = Bus(
            vehicle_number=1,
            vin_number="VIN1",
            vehicle_type="E-BUS",
            state=BusState.AVAILABLE,
            energy_consumption_per_km=1.0,
            soc_percent=10.0,
            battery_capacity_kwh=100.0,
            max_charging_power_kw=282.0,
        )

        trace = simulate_charging_soc_trace_simpy(
            bus=bus,
            charger_offered_power_kw=360.0,
            start_soc_percent=10.0,
            target_soc_percent=100.0,
            dt_seconds=1,
            max_seconds=24 * 3600,
        )

        self.assertGreater(trace.duration_seconds, 0)
        self.assertAlmostEqual(trace.soc_per_second[0], 10.0, places=6)
        self.assertAlmostEqual(trace.soc_per_second[-1], 100.0, places=6)

        for a, b in zip(trace.soc_per_second, trace.soc_per_second[1:]):
            self.assertGreaterEqual(b + 1e-12, a)


if __name__ == "__main__":
    unittest.main()

