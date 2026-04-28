"""
Block assignment strategy for all blocks (with depot-return optimization).

Rationale: The default scheduler assignment is SOC/availability oriented, but
it does not explicitly optimize operational plausibility of where buses are
currently waiting. This strategy becomes the main assignment policy:

- It handles assignment for *all* blocks at the first journey.
- It prefers buses already at the journey origin stop.
- For single-journey return-to-depot blocks, it strongly prefers non-depot idle
  buses that plausibly need to return.

This keeps assignments realistic while still preserving deterministic fallback
behavior via scheduler helper methods.
"""

from __future__ import annotations

from datetime import datetime

from .base import StrategyRuntimeState


class DepotReturnDispatchStrategy:
    strategy_key = "depot_return_dispatch"
    enabled_by_default = False

    # Distance matching tolerance (km) for inferred origin stop.
    _distance_tolerance_km = 0.15

    def __init__(self) -> None:
        self._origin_by_distance_km: dict[float, set[str]] | None = None
        self._distance_by_origin_point: dict[str, float] | None = None

    @staticmethod
    def _is_depot_return_journey(state: StrategyRuntimeState) -> bool:
        if not state.journey.points:
            return False
        return str(getattr(state.journey.points[-1], "point_id", "")) == "30002"

    @staticmethod
    def _journey_distance_km(state: StrategyRuntimeState) -> float:
        distance_m = 0.0
        for point in state.journey.points:
            distance_m += float(getattr(point, "distance_to_next_m", 0.0) or 0.0)
        return distance_m / 1000.0

    @staticmethod
    def _is_single_journey_block(state: StrategyRuntimeState) -> bool:
        return len(getattr(state.block, "journeys", [])) == 1

    @staticmethod
    def _journey_origin_point_id(state: StrategyRuntimeState) -> str | None:
        if not state.journey.points:
            return None
        pid = str(getattr(state.journey.points[0], "point_id", ""))
        return pid if pid else None

    def _build_distance_origin_index(self, state: StrategyRuntimeState) -> None:
        if self._origin_by_distance_km is not None:
            return
        index: dict[float, set[str]] = {}
        distance_by_origin: dict[str, float] = {}
        for block in state.world.blocks_by_id.values():
            for journey in getattr(block, "journeys", []):
                points = getattr(journey, "points", [])
                if len(points) < 2:
                    continue
                if str(getattr(points[-1], "point_id", "")) != "30002":
                    continue
                origin_pid = str(getattr(points[0], "point_id", ""))
                if not origin_pid or origin_pid == "30002":
                    continue
                distance_m = 0.0
                for point in points:
                    distance_m += float(getattr(point, "distance_to_next_m", 0.0) or 0.0)
                key = round(distance_m / 1000.0, 2)
                index.setdefault(key, set()).add(origin_pid)
                # Keep shortest observed distance for this origin as baseline.
                prev = distance_by_origin.get(origin_pid)
                if prev is None or key < prev:
                    distance_by_origin[origin_pid] = key
        self._origin_by_distance_km = index
        self._distance_by_origin_point = distance_by_origin

    def _infer_origin_point_id(self, state: StrategyRuntimeState) -> str | None:
        # If planning already includes a non-depot first point, use it directly.
        if state.journey.points:
            first_pid = str(getattr(state.journey.points[0], "point_id", ""))
            if first_pid and first_pid != "30002":
                return first_pid

        self._build_distance_origin_index(state)
        if not self._origin_by_distance_km:
            return None

        journey_distance = self._journey_distance_km(state)
        best_key: float | None = None
        best_delta = float("inf")
        for known_distance in self._origin_by_distance_km.keys():
            delta = abs(known_distance - journey_distance)
            if delta < best_delta:
                best_delta = delta
                best_key = known_distance
        if best_key is None or best_delta > self._distance_tolerance_km:
            return None

        origins = sorted(self._origin_by_distance_km.get(best_key, set()))
        return origins[0] if origins else None

    @staticmethod
    def _is_bus_waiting_at_point(bus, point_id: str) -> bool:
        bus_point_id = str(getattr(getattr(bus, "location", None), "point_id", ""))
        return bus_point_id == str(point_id)

    @staticmethod
    def _bus_point_id(bus) -> str:
        return str(getattr(getattr(bus, "location", None), "point_id", ""))

    @staticmethod
    def _is_bus_available_for_assignment(state: StrategyRuntimeState, bus) -> bool:
        return state.bus_available_at.get(bus.vin_number, 0.0) <= state.assign_time

    def _available_non_depot_candidates(self, state: StrategyRuntimeState) -> list:
        return [
            bus
            for bus in state.buses
            if self._is_bus_available_for_assignment(state, bus)
            and self._bus_point_id(bus)
            and self._bus_point_id(bus) != "30002"
        ]

    def _eligible_candidates(self, state: StrategyRuntimeState) -> list:
        required_vehicle_type = getattr(state.active_bus, "vehicle_type", None)
        origin_pid = self._journey_origin_point_id(state)
        candidates = [bus for bus in state.buses if self._is_bus_available_for_assignment(state, bus)]
        # Hard constraint: only buses currently waiting at journey origin may be assigned.
        if origin_pid:
            candidates = [bus for bus in candidates if self._bus_point_id(bus) == origin_pid]
        if required_vehicle_type:
            typed = [bus for bus in candidates if bus.vehicle_type == required_vehicle_type]
            if typed:
                candidates = typed
        return candidates

    def _score_generic_assignment(self, service, state: StrategyRuntimeState, bus) -> float:
        """
        Lower score = better candidate.

        Heuristic order:
        1) exact origin match
        2) can complete journey
        3) avoid dispatching from depot for non-depot origins
        4) prefer higher SOC as tie-breaker
        """
        origin_pid = self._journey_origin_point_id(state)
        bus_pid = self._bus_point_id(bus)
        score = 0.0

        if origin_pid and bus_pid == origin_pid:
            score -= 50.0
        elif origin_pid and bus_pid != origin_pid:
            score += 10.0

        if not service._can_complete_journey(bus, state.journey):
            score += 1000.0

        if origin_pid and origin_pid != "30002" and bus_pid == "30002":
            score += 20.0

        score -= float(bus.soc_percent) / 100.0
        return score

    def _select_generic_best_bus(self, service, state: StrategyRuntimeState):
        candidates = self._eligible_candidates(state)
        if not candidates:
            return None
        scored = sorted(candidates, key=lambda bus: (self._score_generic_assignment(service, state, bus), bus.vehicle_number))
        return scored[0]

    def _top_generic_candidates(self, service, state: StrategyRuntimeState, top_n: int = 5) -> list[dict]:
        candidates = self._eligible_candidates(state)
        scored = sorted(
            candidates,
            key=lambda bus: (self._score_generic_assignment(service, state, bus), bus.vehicle_number),
        )
        out: list[dict] = []
        for bus in scored[:top_n]:
            out.append(
                {
                    "bus_number": bus.vehicle_number,
                    "bus_vin": bus.vin_number,
                    "point_id": self._bus_point_id(bus) or "N/A",
                    "soc_percent": round(float(bus.soc_percent), 2),
                    "score": round(float(self._score_generic_assignment(service, state, bus)), 4),
                    "can_complete": bool(service._can_complete_journey(bus, state.journey)),
                }
            )
        return out

    def _select_depot_return_best_bus(self, service, state: StrategyRuntimeState):
        """
        Special path for single journey ending at depot:
        prefer non-depot idle buses and, when possible, match inferred origin.
        """
        origin_point_id = self._infer_origin_point_id(state)
        target_distance_km = round(self._journey_distance_km(state), 2)
        base_candidates = self._available_non_depot_candidates(state)
        if not base_candidates:
            return None

        if origin_point_id:
            exact_origin_candidates = [bus for bus in base_candidates if self._is_bus_waiting_at_point(bus, origin_point_id)]
            if exact_origin_candidates:
                return service._select_bus_for_time(
                    exact_origin_candidates,
                    state.bus_available_at,
                    state.assign_time,
                    required_vehicle_type=getattr(state.active_bus, "vehicle_type", None),
                )

        self._build_distance_origin_index(state)
        distance_by_origin = self._distance_by_origin_point or {}
        scored: list[tuple[float, object]] = []
        for bus in base_candidates:
            bus_pid = self._bus_point_id(bus)
            baseline = distance_by_origin.get(bus_pid)
            if baseline is None:
                continue
            scored.append((abs(baseline - target_distance_km), bus))
        if not scored:
            return None
        best_delta = min(delta for delta, _ in scored)
        near = [bus for delta, bus in scored if delta == best_delta]
        return service._select_bus_for_time(
            near,
            state.bus_available_at,
            state.assign_time,
            required_vehicle_type=getattr(state.active_bus, "vehicle_type", None),
        )

    def _top_depot_return_candidates(self, service, state: StrategyRuntimeState, top_n: int = 5) -> list[dict]:
        self._build_distance_origin_index(state)
        distance_by_origin = self._distance_by_origin_point or {}
        target_distance_km = round(self._journey_distance_km(state), 2)
        out: list[dict] = []
        for bus in self._available_non_depot_candidates(state):
            bus_pid = self._bus_point_id(bus)
            baseline = distance_by_origin.get(bus_pid)
            if baseline is None:
                continue
            out.append(
                {
                    "bus_number": bus.vehicle_number,
                    "bus_vin": bus.vin_number,
                    "point_id": bus_pid or "N/A",
                    "soc_percent": round(float(bus.soc_percent), 2),
                    "distance_delta_km": round(abs(float(baseline) - target_distance_km), 4),
                    "baseline_distance_km": round(float(baseline), 2),
                }
            )
        out.sort(key=lambda x: (x["distance_delta_km"], x["bus_number"]))
        return out[:top_n]

    def before_journey(self, service, state: StrategyRuntimeState) -> None:
        # This strategy owns block assignment. Only act at first journey.
        if state.journey_index != 0:
            return

        is_single_depot_return = self._is_single_journey_block(state) and self._is_depot_return_journey(state)
        assign_dt = datetime.fromtimestamp(state.assign_time) if isinstance(state.assign_time, (int, float)) else None
        in_midnight_window = bool(assign_dt and 0 <= assign_dt.hour < 6)
        if is_single_depot_return and in_midnight_window:
            assignment_mode = "midnight_depot_return_priority"
        elif is_single_depot_return:
            assignment_mode = "depot_return"
        else:
            assignment_mode = "general"
        explain_candidates: list[dict] = []
        selected = None
        if assignment_mode in {"depot_return", "midnight_depot_return_priority"}:
            explain_candidates = self._top_depot_return_candidates(service, state)
            selected = self._select_depot_return_best_bus(service, state)

        if selected is None:
            if assignment_mode == "general":
                explain_candidates = self._top_generic_candidates(service, state)
            selected = self._select_generic_best_bus(service, state)
        if selected is None:
            return

        selected_changed = selected.vin_number != state.active_bus.vin_number

        origin_point_id = self._infer_origin_point_id(state) or self._journey_origin_point_id(state) or self._bus_point_id(selected)
        state.logger.planning_log.append(
            {
                "event": "strategy_block_assignment_explain",
                "time": state.assign_time,
                "block_id": state.block.block_id,
                "journey_id": state.journey.journey_id,
                "strategy": self.strategy_key,
                "assignment_mode": assignment_mode,
                "selected_bus_number": selected.vehicle_number,
                "selected_bus_vin": selected.vin_number,
                "selected_bus_point_id": self._bus_point_id(selected) or "N/A",
                "selected_bus_soc_percent": round(float(selected.soc_percent), 2),
                "origin_point_id": origin_point_id,
                "target_distance_km": round(self._journey_distance_km(state), 2),
                "changed_assignment": selected_changed,
                "candidates": explain_candidates,
            }
        )

        if not selected_changed:
            return

        state.active_bus = selected
        state.logger.planning_log.append(
            {
                "event": "strategy_block_reassignment",
                "time": state.assign_time,
                "block_id": state.block.block_id,
                "journey_id": state.journey.journey_id,
                "origin_point_id": origin_point_id,
                "predicted_distance_km": round(self._journey_distance_km(state), 2),
                "bus_vin": selected.vin_number,
                "bus_number": selected.vehicle_number,
                "strategy": self.strategy_key,
                "assignment_mode": assignment_mode,
                "reason": "Block assignment optimized by location/availability/SOC heuristic",
            }
        )

    def after_journey(self, service, state: StrategyRuntimeState) -> None:
        return

