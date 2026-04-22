"""
Precheck replacement strategy.

Rationale: before executing a journey, check if the active bus can complete it.
If not, create replacement workflow logs and hand over to a same-type bus.
"""

from __future__ import annotations

from .base import StrategyRuntimeState


class PrecheckReplacementStrategy:
    strategy_key = "precheck_replacement"
    enabled_by_default = False

    def __init__(self) -> None:
        self._replacement_counter = 0

    def before_journey(self, service, state: StrategyRuntimeState) -> None:
        if service._can_complete_journey(state.active_bus, state.journey):
            return
        self._replacement_counter += 1
        replacement_bus = service._select_bus_for_time(
            state.buses,
            state.bus_available_at,
            state.assign_time,
            exclude_vin=state.active_bus.vin_number,
            required_vehicle_type=state.active_bus.vehicle_type,
        )
        if replacement_bus.vin_number == state.active_bus.vin_number:
            return
        service._log_precheck_replacement(
            world=state.world,
            logger=state.logger,
            block=state.block,
            original_bus=state.active_bus,
            replacement_bus=replacement_bus,
            journey=state.journey,
            sequence=self._replacement_counter,
        )
        service._maybe_charge(state.active_bus, state.assign_time, state.logger)
        state.bus_available_at[state.active_bus.vin_number] = (
            state.logger.laadinfra_log[-1]["time"] if state.logger.laadinfra_log else state.assign_time
        )
        state.active_bus = replacement_bus

    def after_journey(self, service, state: StrategyRuntimeState) -> None:
        return

