from __future__ import annotations

import unittest


class TestChargingCurve(unittest.TestCase):
    def setUp(self) -> None:
        # Ensure we can import from the src/ root without installing a package.
        import sys

        if "htm-ev-simulator/src" not in sys.path:
            sys.path.insert(0, "htm-ev-simulator/src")

    def test_default_thresholds_are_87_97(self) -> None:
        from backend.core.models.transport.bus import DEFAULT_CHARGING_CURVE

        self.assertEqual(DEFAULT_CHARGING_CURVE.stage_a_end_soc, 87.0)
        self.assertEqual(DEFAULT_CHARGING_CURVE.stage_b_end_soc, 97.0)

    def test_power_cap_is_non_negative_and_clamped(self) -> None:
        from backend.core.models.transport.bus import DEFAULT_CHARGING_CURVE

        self.assertGreaterEqual(DEFAULT_CHARGING_CURVE.power_cap_kw(-10.0), 0.0)
        self.assertGreaterEqual(DEFAULT_CHARGING_CURVE.power_cap_kw(50.0), 0.0)
        self.assertGreaterEqual(DEFAULT_CHARGING_CURVE.power_cap_kw(150.0), 0.0)

        # At 100%, tail should be 0.
        self.assertAlmostEqual(DEFAULT_CHARGING_CURVE.power_cap_kw(100.0), 0.0, places=6)

    def test_actual_power_is_limited_by_offered_minus_loss_and_cap(self) -> None:
        from backend.core.models.transport.bus import DEFAULT_CHARGING_CURVE

        soc = 50.0
        cap = DEFAULT_CHARGING_CURVE.power_cap_kw(soc)

        # If offered is huge, actual equals cap (after loss).
        self.assertAlmostEqual(
            DEFAULT_CHARGING_CURVE.actual_battery_power_kw(
                soc_percent=soc,
                charger_offered_power_kw=10_000.0,
                charging_loss_kw=0.0,
            ),
            cap,
            places=6,
        )

        # If offered is small, actual equals offered-loss.
        self.assertAlmostEqual(
            DEFAULT_CHARGING_CURVE.actual_battery_power_kw(
                soc_percent=soc,
                charger_offered_power_kw=100.0,
                charging_loss_kw=4.0,
            ),
            96.0,
            places=6,
        )


if __name__ == "__main__":
    unittest.main()

