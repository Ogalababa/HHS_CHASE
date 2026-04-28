from __future__ import annotations

import unittest
from datetime import date

from tests.unit._src_path import ensure_backend_src_on_path

ensure_backend_src_on_path()

from backend.core.models.planning.block import Block
from backend.core.models.transport.bus import Bus, BusState
from backend.core.ports.bus_port import BusProviderPort
from backend.core.ports.infra_port import InfrastructureProviderPort
from backend.core.ports.planning_port import PlanningProviderPort
from backend.core.services.world_builder import WorldBuilder


class _FakeBuses(BusProviderPort):
    def __init__(self, buses: list[Bus]) -> None:
        self._buses = buses

    def get_buses(self) -> list[Bus]:
        return list(self._buses)


class _FakePlanning(PlanningProviderPort):
    def __init__(self, blocks: list[Block]) -> None:
        self._blocks = blocks

    def get_blocks(self) -> list[Block]:
        return list(self._blocks)


class _FakeInfra(InfrastructureProviderPort):
    def get_grids(self):
        return []

    def get_locations(self):
        return []


class TestWorldBuilder(unittest.TestCase):
    """WorldBuilder wires ports without external I/O."""

    def test_build_counts_entities(self) -> None:
        bus = Bus(
            vehicle_number=5,
            vin_number="BV",
            vehicle_type="E-BUS",
            state=BusState.AVAILABLE,
            energy_consumption_per_km=1.0,
            soc_percent=66.0,
            battery_capacity_kwh=352.8,
        )
        blk = Block("BLK_WB", date(2026, 4, 1))
        planning = _FakePlanning([blk])
        infra = _FakeInfra()
        buses = _FakeBuses([bus])
        res = WorldBuilder(planning=planning, infrastructure=infra, buses=buses).build()
        self.assertEqual(res.n_buses, 1)
        self.assertEqual(res.n_blocks, 1)
        self.assertEqual(res.n_locations, 0)
        self.assertIs(res.world.get_bus(5), bus)


if __name__ == "__main__":
    unittest.main()
