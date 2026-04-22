"""
SimPy-only visualization simulation service.

Rationale: This is the new single runtime engine for the refactor project.
The service keeps the frontend result contract unchanged while moving the core
execution to a SimPy-based scheduler in hexagonal architecture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..models.world import World
from .strategies.loader import build_enabled_strategies
from .visualization_simulation import (
    ClassifiedLogger,
    VisualizationSimulationResult,
    VisualizationSimulationService as LegacyVisualizationService,
)
from .simpy_engine.event_log import InternalEventLog
from .simpy_engine.resource_allocator import LocationPowerAllocator
from .simpy_engine.scheduler import SimpyScheduler


@dataclass(slots=True)
class VisualizationSimulationService:
    """
    SimPy-based service preserving legacy DTO contract.
    """

    low_soc_alert_threshold_percent: float = 14.0
    charging_target_soc_percent: float = 85.0
    charging_step_seconds: int = 300
    enable_precheck_replacement_strategy: bool = False
    enable_opportunity_charging_strategy: bool = False
    enable_start_full_soc_strategy: bool = False
    enable_power_limit_strategy: bool = False
    opportunity_charging_soc_threshold_percent: float = 80.0
    opportunity_charging_min_gap_seconds: int = 1800
    strategy_flags: dict[str, bool] = field(default_factory=dict)
    simulation_start_timestamp: float | None = None
    simulation_end_timestamp: float | None = None

    def __post_init__(self) -> None:
        merged = {
            "precheck_replacement": self.enable_precheck_replacement_strategy,
            "opportunity_charging": self.enable_opportunity_charging_strategy,
            "start_full_soc": self.enable_start_full_soc_strategy,
            "power_limit": self.enable_power_limit_strategy,
        }
        merged.update(self.strategy_flags or {})
        self.strategy_flags = merged

    def run(self, world: World) -> VisualizationSimulationResult:
        try:
            import simpy  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("simpy is required in the refactor project") from exc

        blocks = sorted(
            world.blocks_by_id.values(),
            key=lambda blk: blk.journeys[0].first_departure_datetime if blk.journeys and blk.journeys[0].first_departure_datetime else datetime.min,
        )
        buses = sorted(world.buses_by_vehicle_number.values(), key=lambda b: b.vehicle_number)
        start_ts = self.simulation_start_timestamp
        end_ts = self.simulation_end_timestamp
        if start_ts is None and blocks:
            first_block = next((b for b in blocks if b.journeys and b.journeys[0].first_departure_datetime), None)
            start_ts = first_block.journeys[0].first_departure_datetime.timestamp() if first_block else 0.0
        if start_ts is None:
            start_ts = 0.0

        if self.strategy_flags.get("start_full_soc", False):
            for bus in buses:
                bus.soc_percent = 100.0

        internal_log = InternalEventLog()
        allocator = LocationPowerAllocator(power_limit_enabled=bool(self.strategy_flags.get("power_limit", False)))
        strategies = build_enabled_strategies(self.strategy_flags)
        scheduler = SimpyScheduler(
            world=world,
            logger=internal_log,
            allocator=allocator,
            low_soc_alert_threshold_percent=self.low_soc_alert_threshold_percent,
            charging_target_soc_percent=self.charging_target_soc_percent,
            charging_step_seconds=self.charging_step_seconds,
            simulation_start_timestamp=float(start_ts),
            simulation_end_timestamp=float(end_ts) if end_ts is not None else None,
            strategies=strategies,
            opportunity_charging_soc_threshold_percent=self.opportunity_charging_soc_threshold_percent,
            opportunity_charging_min_gap_seconds=self.opportunity_charging_min_gap_seconds,
        )
        env = simpy.Environment(initial_time=float(start_ts))
        env.process(scheduler.run(env, blocks, buses))
        if end_ts is not None:
            env.run(until=float(end_ts))
        else:
            env.run()

        legacy_helper = LegacyVisualizationService()
        logger = ClassifiedLogger(
            bus_log=list(internal_log.bus_log),
            planning_log=list(internal_log.planning_log),
            laadinfra_log=list(internal_log.laadinfra_log),
        )
        return VisualizationSimulationResult(
            world=legacy_helper._to_world_view(world),
            classified_logger=logger,
            current_time=float(end_ts) if end_ts is not None else float(env.now),
            simulation_start_time=float(start_ts),
            simulation_end_time=float(end_ts) if end_ts is not None else None,
            completed_journeys=set(),
            skipped_journeys=set(),
            skipped_blocks=set(),
        )

