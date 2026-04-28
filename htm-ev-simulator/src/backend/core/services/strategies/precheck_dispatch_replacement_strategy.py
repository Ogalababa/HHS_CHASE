"""
Precheck replacement-dispatch strategy (9xxxxxx virtual dispatch journey).

Rationale: When the current bus cannot complete the journey, replace it with an
available bus of the same type/series and emit replacement dispatch evidence.
"""

from __future__ import annotations

from .base import StrategyRuntimeState


class PrecheckDispatchReplacementStrategy:
    strategy_key = "precheck_dispatch_replacement"
    enabled_by_default = False
    execution_priority = 20

    def __init__(self) -> None:
        self._replacement_counter = 0

    @staticmethod
    def _is_garage_return_journey(state: StrategyRuntimeState) -> bool:
        if not state.journey.points:
            return False
        last_point = state.journey.points[-1]
        return str(getattr(last_point, "point_id", "")) == "30002"

    @staticmethod
    def _same_vehicle_series(a_number: int, b_number: int) -> bool:
        return int(a_number) // 100 == int(b_number) // 100

    def before_journey(self, service, state: StrategyRuntimeState) -> None:
        if self._is_garage_return_journey(state):
            return
        if service._can_complete_journey(state.active_bus, state.journey):
            return

        candidates = [
            b
            for b in state.buses
            if b.vin_number != state.active_bus.vin_number
            and b.vehicle_type == state.active_bus.vehicle_type
            and self._same_vehicle_series(b.vehicle_number, state.active_bus.vehicle_number)
        ]
        if not candidates:
            return

        self._replacement_counter += 1
        replacement_bus = service._select_bus_for_time(
            candidates,
            state.bus_available_at,
            state.assign_time,
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
        state.active_bus = replacement_bus

    def after_journey(self, service, state: StrategyRuntimeState) -> None:
        return

