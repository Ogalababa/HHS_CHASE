"""
Bus-fill assignment strategy.

Rationale: Build a global block assignment plan by filling one bus timeline at a
time, respecting origin-point continuity. This models an operational dispatcher
workflow: exhaust one vehicle's feasible chain, then move to the next bus.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .base import StrategyRuntimeState


@dataclass(slots=True)
class _BusPlanState:
    available_at: float
    point_id: str
    vehicle_type: str


class BusFillAssignmentStrategy:
    strategy_key = "bus_fill_assignment"
    enabled_by_default = False
    execution_priority = 5

    def __init__(self) -> None:
        self._planned_bus_by_block: dict[str, str] = {}
        self._plan_built = False

    @staticmethod
    def _journey_start_ts(block) -> float:
        for journey in getattr(block, "journeys", []):
            if journey.first_departure_datetime:
                return float(journey.first_departure_datetime.timestamp())
        return float("inf")

    @staticmethod
    def _journey_end_ts(block) -> float:
        end_ts = 0.0
        for journey in getattr(block, "journeys", []):
            if journey.last_arrival_datetime:
                end_ts = max(end_ts, float(journey.last_arrival_datetime.timestamp()))
        return end_ts

    @staticmethod
    def _block_origin_point_id(block) -> str:
        for journey in getattr(block, "journeys", []):
            if journey.points:
                return str(getattr(journey.points[0], "point_id", ""))
        return ""

    @staticmethod
    def _block_destination_point_id(block) -> str:
        dest = ""
        for journey in getattr(block, "journeys", []):
            if journey.points:
                dest = str(getattr(journey.points[-1], "point_id", ""))
        return dest

    @staticmethod
    def _block_vehicle_type(block) -> str:
        for journey in getattr(block, "journeys", []):
            vt = str(getattr(journey, "vehicle_type", "") or "")
            if vt:
                return vt
        return ""

    @staticmethod
    def _normalize_vehicle_type(value: str) -> str:
        return "".join(ch for ch in str(value).lower() if ch.isalnum())

    def _build_plan(self, state: StrategyRuntimeState) -> None:
        if self._plan_built:
            return

        blocks = sorted(
            state.world.blocks_by_id.values(),
            key=self._journey_start_ts,
        )
        buses = sorted(state.buses, key=lambda b: b.vehicle_number)

        bus_states: dict[str, _BusPlanState] = {}
        for bus in buses:
            point_id = str(getattr(getattr(bus, "location", None), "point_id", "")) or "30002"
            bus_states[bus.vin_number] = _BusPlanState(
                available_at=float(state.bus_available_at.get(bus.vin_number, state.assign_time)),
                point_id=point_id,
                vehicle_type=str(getattr(bus, "vehicle_type", "") or ""),
            )

        remaining: dict[str, object] = {blk.block_id: blk for blk in blocks}

        # Fill buses one by one, then continue rounds until no progress.
        while remaining:
            progressed = False
            for bus in buses:
                st = bus_states[bus.vin_number]
                while True:
                    match = None
                    for blk in sorted(remaining.values(), key=self._journey_start_ts):
                        blk_start = self._journey_start_ts(blk)
                        origin = self._block_origin_point_id(blk)
                        block_vehicle_type = self._block_vehicle_type(blk)
                        if blk_start < st.available_at:
                            continue
                        if origin != st.point_id:
                            continue
                        if (
                            block_vehicle_type
                            and st.vehicle_type
                            and self._normalize_vehicle_type(block_vehicle_type)
                            != self._normalize_vehicle_type(st.vehicle_type)
                        ):
                            continue
                        match = blk
                        break
                    if match is None:
                        break
                    self._planned_bus_by_block[match.block_id] = bus.vin_number
                    st.available_at = self._journey_end_ts(match)
                    st.point_id = self._block_destination_point_id(match) or st.point_id
                    remaining.pop(match.block_id, None)
                    progressed = True
            if not progressed:
                break

        self._plan_built = True

    def before_journey(self, service, state: StrategyRuntimeState) -> None:
        if state.journey_index != 0:
            return

        self._build_plan(state)
        planned_vin = self._planned_bus_by_block.get(state.block.block_id)
        if not planned_vin:
            return
        planned_bus = next((b for b in state.buses if b.vin_number == planned_vin), None)
        if planned_bus is None:
            return

        origin_point_id = self._block_origin_point_id(state.block)
        bus_point_id = str(getattr(getattr(planned_bus, "location", None), "point_id", ""))
        if origin_point_id and bus_point_id != origin_point_id:
            return
        if state.bus_available_at.get(planned_bus.vin_number, 0.0) > state.assign_time:
            return

        selected_changed = planned_bus.vin_number != state.active_bus.vin_number
        state.logger.planning_log.append(
            {
                "event": "strategy_block_assignment_explain",
                "time": state.assign_time,
                "block_id": state.block.block_id,
                "journey_id": state.journey.journey_id,
                "strategy": self.strategy_key,
                "assignment_mode": "bus_fill",
                "selected_bus_number": planned_bus.vehicle_number,
                "selected_bus_vin": planned_bus.vin_number,
                "selected_bus_point_id": bus_point_id or "N/A",
                "selected_bus_soc_percent": round(float(planned_bus.soc_percent), 2),
                "origin_point_id": origin_point_id or "N/A",
                "target_distance_km": 0.0,
                "changed_assignment": selected_changed,
                "candidates": [],
            }
        )
        if selected_changed:
            state.active_bus = planned_bus
        state.assignment_locked = True

    def after_journey(self, service, state: StrategyRuntimeState) -> None:
        return

