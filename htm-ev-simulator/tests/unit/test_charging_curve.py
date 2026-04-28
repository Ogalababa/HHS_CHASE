from __future__ import annotations

import unittest

from tests.unit._src_path import ensure_backend_src_on_path

ensure_backend_src_on_path()

from backend.core.models.transport.bus.charging_curve import DEFAULT_CHARGING_CURVE, ChargingCurve


class TestChargingCurve(unittest.TestCase):
    """Unit tests for NMC3-style charging envelope (domain)."""

    def test_clamp_soc_bounds(self) -> None:
        self.assertEqual(ChargingCurve.clamp_soc_percent(-1.0), 0.0)
        self.assertEqual(ChargingCurve.clamp_soc_percent(101.0), 100.0)
        self.assertAlmostEqual(ChargingCurve.clamp_soc_percent(42.3), 42.3)

    def test_power_cap_zero_at_full_soc(self) -> None:
        c = ChargingCurve()
        self.assertAlmostEqual(c.power_cap_kw(100.0), 0.0, places=6)

    def test_default_curve_stage_b_reaches_282kw_at_87(self) -> None:
        p = DEFAULT_CHARGING_CURVE.power_cap_kw(87.0)
        self.assertAlmostEqual(p, 282.0, places=0)

    def test_actual_battery_power_respects_overhead_and_cap(self) -> None:
        c = ChargingCurve()
        # High offer, low SoC → limited by envelope cap, not offer
        actual = c.actual_battery_power_kw(
            soc_percent=10.0,
            charger_offered_power_kw=10000.0,
            aux_load_kw=2.0,
            transmission_loss_kw=2.0,
        )
        cap = c.power_cap_kw(10.0)
        self.assertLessEqual(actual, cap + 1e-3)

    def test_actual_battery_power_zero_when_soc_full(self) -> None:
        actual = DEFAULT_CHARGING_CURVE.actual_battery_power_kw(soc_percent=100.0, charger_offered_power_kw=500.0)
        self.assertAlmostEqual(actual, 0.0, places=6)


if __name__ == "__main__":
    unittest.main()
