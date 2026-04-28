from __future__ import annotations

import unittest

from tests.unit._src_path import ensure_backend_src_on_path

ensure_backend_src_on_path()

from backend.core.models.laad_infra.connector import Connector
from backend.core.models.laad_infra.exceptions import ConnectorOccupiedError
from backend.core.models.transport.bus import Bus, BusState


class TestConnectorOccupancy(unittest.TestCase):
    """Connector occupancy is the smallest allocatable charging resource."""

    def test_double_connect_raises(self) -> None:
        c = Connector(connector_id="C1", max_power_kw=150.0, connector_type="CCS")
        b1 = Bus(
            vehicle_number=1,
            vin_number="V1",
            vehicle_type="E-BUS",
            state=BusState.AVAILABLE,
            energy_consumption_per_km=1.0,
            soc_percent=70.0,
            battery_capacity_kwh=352.8,
        )
        b2 = Bus(
            vehicle_number=2,
            vin_number="V2",
            vehicle_type="E-BUS",
            state=BusState.AVAILABLE,
            energy_consumption_per_km=1.0,
            soc_percent=70.0,
            battery_capacity_kwh=352.8,
        )
        c.connect_bus(b1)
        with self.assertRaises(ConnectorOccupiedError):
            c.connect_bus(b2)


if __name__ == "__main__":
    unittest.main()
