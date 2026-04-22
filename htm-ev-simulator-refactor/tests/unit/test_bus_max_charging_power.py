from __future__ import annotations

import unittest


class TestBusMaxChargingPower(unittest.TestCase):
    def setUp(self) -> None:
        import sys

        if "htm-ev-simulator/src" not in sys.path:
            sys.path.insert(0, "htm-ev-simulator/src")

    def test_bus_max_charging_power_caps_actual(self) -> None:
        from backend.core.models.transport.bus import Bus, BusState

        bus = Bus(
            vehicle_number=1,
            vin_number="VIN1",
            vehicle_type="E-BUS",
            state=BusState.AVAILABLE,
            energy_consumption_per_km=1.0,
            soc_percent=50.0,
            battery_capacity_kwh=100.0,
            charging_loss_kw=0.0,
            max_charging_power_kw=200.0,
        )

        # Offered power is high; curve cap at 50% would be >200kW. Ensure hard cap applies.
        p = bus.calculate_actual_charging_power_kw(1000.0)
        self.assertLessEqual(p, 200.0 + 1e-9)


if __name__ == "__main__":
    unittest.main()

