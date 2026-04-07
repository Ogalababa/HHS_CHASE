from __future__ import annotations

import unittest


class TestLaadInfra(unittest.TestCase):
    def setUp(self) -> None:
        import sys

        if "htm-ev-simulator/src" not in sys.path:
            sys.path.insert(0, "htm-ev-simulator/src")

    def test_connector_occupied_error(self) -> None:
        from backend.core.models.laad_infra import Connector, ConnectorOccupiedError

        c = Connector(connector_id="K1", max_power_kw="150kW", connector_type="pantograph")
        self.assertTrue(c.is_available)

        c.connect_bus(object())  # type: ignore[arg-type]
        self.assertFalse(c.is_available)

        with self.assertRaises(ConnectorOccupiedError):
            c.connect_bus(object())  # type: ignore[arg-type]

    def test_charger_add_connector_sets_conservative_max(self) -> None:
        from backend.core.models.laad_infra import Charger, Connector

        ch = Charger(charger_id="P1", max_power_kw=0.0)
        ch.add_connector(Connector(connector_id="K1", max_power_kw=150, connector_type="pantograph"))
        ch.add_connector(Connector(connector_id="K2", max_power_kw=200, connector_type="pantograph"))

        self.assertAlmostEqual(ch.max_power_kw, 350.0, places=6)
        self.assertAlmostEqual(ch.current_load_kw, 0.0, places=6)
        self.assertAlmostEqual(ch.available_power_kw, 350.0, places=6)


if __name__ == "__main__":
    unittest.main()

