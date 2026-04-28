from __future__ import annotations

import unittest

from tests.unit._src_path import ensure_backend_src_on_path

ensure_backend_src_on_path()

from backend.core.models.transport.bus import Bus, BusState


class TestBusDomain(unittest.TestCase):
    """Domain tests for SOC, charging power, capacity derivation."""

    def _minimal_bus(self, **kwargs: object) -> Bus:
        base = dict(
            vehicle_number=1,
            vin_number="VIN1",
            vehicle_type="E-BUS",
            state=BusState.AVAILABLE,
            energy_consumption_per_km=1.0,
            soc_percent=50.0,
            battery_capacity_kwh=352.8,
            charging_loss_kw=4.0,
            max_charging_power_kw=282.0,
        )
        base.update(kwargs)
        return Bus(**base)  # type: ignore[arg-type]

    def test_battery_capacity_from_mom_attributes(self) -> None:
        b = Bus(
            vehicle_number=2,
            vin_number="VIN2",
            vehicle_type="E-BUS",
            state=BusState.AVAILABLE,
            energy_consumption_per_km=1.0,
            soc_percent=90.0,
            mom_charge_energy=100.0,
            mom_discharge_energy=290.8,
        )
        self.assertAlmostEqual(b.battery_capacity_kwh, 390.8, places=3)

    def test_update_soc_clamps_and_full_soc_precision(self) -> None:
        bus = self._minimal_bus(battery_capacity_kwh=100.0, soc_percent=99.9)
        bus.update_soc(1.0)
        self.assertAlmostEqual(bus.soc_percent, 100.0, places=2)

        bus.update_soc(-500.0)
        self.assertAlmostEqual(bus.soc_percent, 0.0, places=6)

    def test_has_low_soc_14pct_rule(self) -> None:
        bus = self._minimal_bus(soc_percent=14.0)
        self.assertTrue(bus.has_low_soc(14.0))
        bus.soc_percent = 14.1
        self.assertFalse(bus.has_low_soc(14.0))

    def test_calculate_actual_charging_power_respects_max_kw(self) -> None:
        bus = self._minimal_bus(max_charging_power_kw=150.0, soc_percent=30.0)
        p = bus.calculate_actual_charging_power_kw(500.0)
        self.assertLessEqual(p, 150.0 + 1e-9)

    def test_soc_setter_raises_out_of_bounds(self) -> None:
        bus = self._minimal_bus()
        with self.assertRaises(ValueError):
            bus.soc_percent = -1.0
        with self.assertRaises(ValueError):
            bus.soc_percent = 101.0


if __name__ == "__main__":
    unittest.main()
