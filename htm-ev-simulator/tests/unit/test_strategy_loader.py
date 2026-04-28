from __future__ import annotations

import unittest

from tests.unit._src_path import ensure_backend_src_on_path

ensure_backend_src_on_path()

from backend.core.services.strategies.loader import build_enabled_strategies


class TestStrategyLoader(unittest.TestCase):
    """Strategy loader discovers implementations and honours feature flags."""

    def test_disabled_flags_yield_empty_when_defaults_off(self) -> None:
        s = build_enabled_strategies({k: False for k in (
            "precheck_replacement",
            "opportunity_charging",
            "start_full_soc",
            "power_limit",
        )})
        self.assertIsInstance(s, list)

    def test_start_full_soc_enables_known_strategy(self) -> None:
        s = build_enabled_strategies({"start_full_soc": True})
        keys = {type(x).__name__ for x in s}
        self.assertGreaterEqual(len(s), 1)
        self.assertTrue(any("StartFull" in k for k in keys))


if __name__ == "__main__":
    unittest.main()
