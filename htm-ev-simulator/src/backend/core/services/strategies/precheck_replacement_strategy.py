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

    @staticmethod
    def _is_garage_return_journey(state: StrategyRuntimeState) -> bool:
        """
        True when journey destination is Garage Telexstraat (30002).

        Rationale: return-to-garage legs should not trigger replacement dispatch.
        This avoids unnecessary bus swaps near end-of-duty charging flows.
        """
        if not state.journey.points:
            return False
        last_point = state.journey.points[-1]
        return str(getattr(last_point, "point_id", "")) == "30002"

    @staticmethod
    def _same_vehicle_series(a_number: int, b_number: int) -> bool:
        """
        Enforce replacement inside same number series (e.g., 14xx -> 14xx).
        """
        return int(a_number) // 100 == int(b_number) // 100

    def before_journey(self, service, state: StrategyRuntimeState) -> None:
        # Rule 1: If journey ends at Garage Telexstraat (30002), skip replacement.
        if self._is_garage_return_journey(state):
            return

        if service._can_complete_journey(state.active_bus, state.journey):
            return

        # Rule 2: replacement must be same bus type and same series (14xx/15xx).
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
        service._maybe_charge(state.active_bus, state.assign_time, state.logger)
        state.bus_available_at[state.active_bus.vin_number] = (
            state.logger.laadinfra_log[-1]["time"] if state.logger.laadinfra_log else state.assign_time
        )
        state.active_bus = replacement_bus

    def after_journey(self, service, state: StrategyRuntimeState) -> None:
        return

