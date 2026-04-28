"""
Precheck forced-return strategy (8xxxxxx virtual return journey).

Rationale: When an assigned bus cannot complete the upcoming journey and no
planned return-to-garage record exists in the remaining block, force the bus
back to Garage Telexstraat and emit explicit explainability logs.
"""

from __future__ import annotations

from .base import StrategyRuntimeState


class PrecheckForceReturnStrategy:
    strategy_key = "precheck_force_return"
    enabled_by_default = False
    execution_priority = 10

    def __init__(self) -> None:
        self._return_counter = 0

    @staticmethod
    def _is_garage_return_journey(state: StrategyRuntimeState) -> bool:
        if not state.journey.points:
            return False
        last_point = state.journey.points[-1]
        return str(getattr(last_point, "point_id", "")) == "30002"

    @staticmethod
    def _has_remaining_planned_return_to_garage(state: StrategyRuntimeState) -> bool:
        for idx, journey in enumerate(getattr(state.block, "journeys", [])):
            if idx < state.journey_index:
                continue
            points = getattr(journey, "points", [])
            if not points:
                continue
            if str(getattr(points[-1], "point_id", "")) == "30002":
                return True
        return False

    def before_journey(self, service, state: StrategyRuntimeState) -> None:
        # Return legs themselves do not need forced return generation.
        if self._is_garage_return_journey(state):
            return
        if service._can_complete_journey(state.active_bus, state.journey):
            return
        if self._has_remaining_planned_return_to_garage(state):
            return

        self._return_counter += 1
        forced_return_journey_id = f"8{self._return_counter:06d}_{state.block.operating_day.isoformat()}"
        from_point_id = str(getattr(getattr(state.active_bus, "location", None), "point_id", "")) or "N/A"
        state.logger.planning_log.append(
            {
                "event": "precheck_forced_return",
                "time": state.assign_time,
                "block_id": state.block.block_id,
                "journey_id": state.journey.journey_id,
                "forced_return_journey_id": forced_return_journey_id,
                "bus_vin": state.active_bus.vin_number,
                "bus_number": state.active_bus.vehicle_number,
                "from_point_id": from_point_id,
                "to_point_id": "30002",
                "reason": "Precheck failed and no planned return record in remaining block",
                "strategy": self.strategy_key,
            }
        )
        # Force return by sending bus to charging flow at garage.
        service._maybe_charge(state.active_bus, state.assign_time, state.logger)
        state.bus_available_at[state.active_bus.vin_number] = (
            state.logger.laadinfra_log[-1]["time"] if state.logger.laadinfra_log else state.assign_time
        )

    def after_journey(self, service, state: StrategyRuntimeState) -> None:
        return

