"""
Visualization-oriented simulation service.

Rationale: The visualization layer expects a legacy simulation object with
classified logs (`bus_log`, `planning_log`, `laadinfra_log`) and convenience
fields (`world.buses`, `world.blocks`, etc.). Instead of coupling frontend code
to adapters directly, this service builds a small application-facing simulation
result from pure domain models so the same output contract can be reused by
different data providers in hexagonal architecture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from ..models.laad_infra.location import Location
from ..models.laad_infra.connector import Connector
from ..models.planning.block import Block
from ..models.planning.journey import Journey
from ..models.planning.point_in_sequence import PointInSequence
from ..models.transport.bus.bus import Bus, BusState
from ..models.world import World
from .strategies.base import StrategyRuntimeState
from .strategies.loader import build_enabled_strategies, run_after_journey, run_before_journey


@dataclass(slots=True)
class ClassifiedLogger:
    """Container for visualization-classified event streams."""

    bus_log: list[dict[str, Any]] = field(default_factory=list)
    planning_log: list[dict[str, Any]] = field(default_factory=list)
    laadinfra_log: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class VisualizationWorldView:
    """
    Compatibility view required by frontend visualization code.

    Rationale: The frontend report generator accesses `world.blocks`,
    `world.locations` and `world.buses` as if they are simple collections.
    The core domain uses explicit indexed fields (`*_by_id`), so we expose a
    read-oriented view instead of modifying domain entities.
    """

    blocks: dict[str, Block]
    locations: dict[str, Location]
    buses: list[Bus]


@dataclass(slots=True)
class VisualizationSimulationResult:
    """
    Simulation output contract consumed by `frontend.visualization`.

    Rationale: The existing frontend report API expects a simulation-engine-like
    object. This lightweight DTO preserves that contract while keeping the core
    simulation logic in the backend service layer.
    """

    world: VisualizationWorldView
    classified_logger: ClassifiedLogger
    current_time: float
    simulation_start_time: float | None = None
    simulation_end_time: float | None = None
    completed_journeys: set[Journey] = field(default_factory=set)
    skipped_journeys: set[Journey] = field(default_factory=set)
    skipped_blocks: set[Block] = field(default_factory=set)


@dataclass(slots=True)
class VisualizationSimulationService:
    """
    Run a deterministic lightweight simulation for report generation.

    Rationale: This service focuses on producing the event vocabulary required
    by the current visualization templates, not on full operational optimization.
    It enables quick end-to-end validation of reports while the advanced engine
    evolves independently.
    """

    low_soc_alert_threshold_percent: float = 14.0
    charging_target_soc_percent: float = 85.0
    default_charger_power_kw: float = 282.0
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
    _garage_point: PointInSequence | None = field(default=None, init=False, repr=False)
    _location_time_power_allocations: dict[tuple[str, float], float] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        """
        Normalize strategy flag aliases into unified dynamic strategy flags.

        Rationale: preserve backward compatibility with existing config fields
        while enabling pluggable strategy discovery without editing this service.
        """
        merged = {
            "precheck_replacement": self.enable_precheck_replacement_strategy,
            "opportunity_charging": self.enable_opportunity_charging_strategy,
            "start_full_soc": self.enable_start_full_soc_strategy,
            "power_limit": self.enable_power_limit_strategy,
        }
        merged.update(self.strategy_flags or {})
        self.strategy_flags = merged

    def run(self, world: World) -> VisualizationSimulationResult:
        self._location_time_power_allocations = {}
        buses = sorted(world.buses_by_vehicle_number.values(), key=lambda b: b.vehicle_number)
        all_blocks = sorted(
            world.blocks_by_id.values(),
            key=lambda blk: blk.journeys[0].first_departure_datetime if blk.journeys else datetime.min,
        )

        logger = ClassifiedLogger()
        completed_journeys: set[Journey] = set()
        skipped_journeys: set[Journey] = set()
        skipped_blocks: set[Block] = set()
        start_ts = self.simulation_start_timestamp
        end_ts = self.simulation_end_timestamp
        if start_ts is None and all_blocks:
            first_block = next((b for b in all_blocks if b.journeys and b.journeys[0].first_departure_datetime), None)
            start_ts = first_block.journeys[0].first_departure_datetime.timestamp() if first_block else 0.0
        if start_ts is None:
            start_ts = 0.0
        current_time = float(start_ts)
        bus_available_at: dict[str, float] = {b.vin_number: float(start_ts) for b in buses}
        strategies = build_enabled_strategies(self.strategy_flags)
        self._garage_point = self._find_point_by_id(world, "30002")
        if self._garage_point is None:
            self._garage_point = self._build_virtual_garage_point(world)
        blocks = []
        for block in all_blocks:
            if not block.journeys or not block.journeys[0].first_departure_datetime:
                continue
            block_start = block.journeys[0].first_departure_datetime.timestamp()
            if block_start < float(start_ts):
                continue
            if end_ts is not None and block_start >= float(end_ts):
                continue
            blocks.append(block)

        if not buses or not blocks:
            return VisualizationSimulationResult(
                world=self._to_world_view(world),
                classified_logger=logger,
                current_time=current_time,
                simulation_start_time=float(start_ts),
                simulation_end_time=float(end_ts) if end_ts is not None else None,
                completed_journeys=completed_journeys,
                skipped_journeys=skipped_journeys,
                skipped_blocks=skipped_blocks,
            )

        garage_point = self._garage_point
        if bool(self.strategy_flags.get("start_full_soc", False)):
            for bus in buses:
                bus.soc_percent = 100.0
        for bus in buses:
            bus.state = BusState.AVAILABLE
            if garage_point is not None:
                bus.location = garage_point
            logger.bus_log.append(
                {
                    "event": "state_update",
                    "time": float(start_ts),
                    "bus_vin": bus.vin_number,
                    "bus_number": bus.vehicle_number,
                    "state": bus.state.value,
                    "soc_percent": bus.soc_percent,
                    "location": self._point_to_location(bus.location) if bus.location else {"name": "Garage Telexstraat", "point_id": "30002"},
                }
            )

        for idx, block in enumerate(blocks):
            if not block.journeys:
                skipped_blocks.add(block)
                continue

            assign_time = max(float(start_ts), block.journeys[0].first_departure_datetime.timestamp())
            bus = self._select_bus_for_time(buses, bus_available_at, assign_time)
            # If a bus remains connected to a connector while idle, keep charging
            # with the charging curve until the next assignment time.
            if self._is_bus_connected_to_connector(bus) and bus.soc_percent < 100.0:
                idle_charge_start = min(bus_available_at.get(bus.vin_number, assign_time), assign_time)
                self._maybe_charge(
                    bus,
                    idle_charge_start,
                    logger,
                    strategy_name="CONNECTED_IDLE_TOP_OFF",
                    deadline_time_ts=assign_time,
                    target_soc_percent=100.0,
                )
                if logger.laadinfra_log:
                    bus_available_at[bus.vin_number] = logger.laadinfra_log[-1]["time"]
            block_end_time = assign_time
            logger.planning_log.append(
                {
                    "event": "block_assigned",
                    "time": assign_time,
                    "block_id": block.block_id,
                    "bus_vin": bus.vin_number,
                    "bus_number": bus.vehicle_number,
                }
            )

            active_bus = bus
            for journey_index, journey in enumerate(block.journeys):
                state = StrategyRuntimeState(
                    world=world,
                    block=block,
                    journey=journey,
                    journey_index=journey_index,
                    assign_time=assign_time,
                    active_bus=active_bus,
                    buses=buses,
                    bus_available_at=bus_available_at,
                    logger=logger,
                )
                run_before_journey(strategies, self, state)
                active_bus = state.active_bus

                journey_end, journey_skipped = self._simulate_journey(
                    active_bus,
                    block,
                    journey,
                    logger,
                    completed_journeys,
                )
                block_end_time = max(block_end_time, journey_end)
                if journey_skipped:
                    skipped_journeys.add(journey)
                    skipped_blocks.add(block)
                    break
                state.journey_end = journey_end
                state.journey_skipped = journey_skipped
                run_after_journey(strategies, self, state)
                active_bus = state.active_bus

            logger.planning_log.append(
                {
                    "event": "block_completed",
                    "time": block_end_time,
                    "block_id": block.block_id,
                    "bus_vin": active_bus.vin_number,
                    "bus_number": active_bus.vehicle_number,
                }
            )

            self._maybe_charge(active_bus, block_end_time, logger, strategy_name="SOC_THRESHOLD")
            bus_available_at[active_bus.vin_number] = logger.laadinfra_log[-1]["time"] if logger.laadinfra_log else block_end_time
            current_time = max(current_time, block_end_time)
            current_time = max(current_time, logger.laadinfra_log[-1]["time"] if logger.laadinfra_log else current_time)

        return VisualizationSimulationResult(
            world=self._to_world_view(world),
            classified_logger=logger,
            current_time=current_time,
            simulation_start_time=float(start_ts),
            simulation_end_time=float(end_ts) if end_ts is not None else None,
            completed_journeys=completed_journeys,
            skipped_journeys=skipped_journeys,
            skipped_blocks=skipped_blocks,
        )

    def _simulate_journey(
        self,
        bus: Bus,
        block: Block,
        journey: Journey,
        logger: ClassifiedLogger,
        completed_journeys: set[Journey],
    ) -> tuple[float, bool]:
        if not journey.points:
            return 0.0, False

        first_point = journey.points[0]
        start_ts = first_point.departure_datetime.timestamp()
        self._release_bus_connector(bus)
        bus.state = BusState.RUNNING
        bus.location = first_point

        logger.planning_log.append(
            {
                "event": "journey_start",
                "time": start_ts,
                "block_id": block.block_id,
                "journey_id": journey.journey_id,
                "bus_vin": bus.vin_number,
                "bus_number": bus.vehicle_number,
            }
        )
        logger.bus_log.append(
            {
                "event": "state_update",
                "time": start_ts,
                "bus_vin": bus.vin_number,
                "bus_number": bus.vehicle_number,
                "state": bus.state.value,
                "soc_percent": bus.soc_percent,
                "location": self._point_to_location(first_point),
            }
        )

        for point in journey.points:
            arrival_ts = point.arrival_datetime.timestamp()
            bus.location = point

            logger.planning_log.append(
                {
                    "event": "point_arrival",
                    "time": arrival_ts,
                    "block_id": block.block_id,
                    "journey_id": journey.journey_id,
                    "point_id": point.point_id,
                    "point_name": point.name,
                    "bus_vin": bus.vin_number,
                    "bus_number": bus.vehicle_number,
                }
            )

            distance_km = point.distance_km
            if distance_km > 0:
                bus.update_soc(-(distance_km * bus.energy_consumption_per_km))

            logger.bus_log.append(
                {
                    "event": "soc_update",
                    "time": arrival_ts,
                    "bus_vin": bus.vin_number,
                    "bus_number": bus.vehicle_number,
                    "soc_percent": bus.soc_percent,
                }
            )
            logger.bus_log.append(
                {
                    "event": "state_update",
                    "time": arrival_ts,
                    "bus_vin": bus.vin_number,
                    "bus_number": bus.vehicle_number,
                    "state": bus.state.value,
                    "soc_percent": bus.soc_percent,
                    "location": self._point_to_location(point),
                }
            )

            if bus.has_low_soc(self.low_soc_alert_threshold_percent):
                already_marked_low_soc = any(
                    e.get("event") == "journey_skipped_low_soc"
                    and e.get("block_id") == block.block_id
                    and e.get("journey_id") == journey.journey_id
                    for e in logger.planning_log
                )
                if already_marked_low_soc:
                    return arrival_ts, True
                logger.planning_log.append(
                    {
                        "event": "journey_skipped_low_soc",
                        "time": arrival_ts,
                        "block_id": block.block_id,
                        "journey_id": journey.journey_id,
                        "bus_vin": bus.vin_number,
                        "bus_number": bus.vehicle_number,
                        "soc_percent": bus.soc_percent,
                        "reason": f"SOC below threshold {self.low_soc_alert_threshold_percent:.1f}%",
                    }
                )
                # Stop the journey immediately when low-SOC skip is triggered.
                bus.state = BusState.AVAILABLE
                logger.bus_log.append(
                    {
                        "event": "state_update",
                        "time": arrival_ts,
                        "bus_vin": bus.vin_number,
                        "bus_number": bus.vehicle_number,
                        "state": bus.state.value,
                        "soc_percent": bus.soc_percent,
                        "location": self._point_to_location(point),
                    }
                )
                return arrival_ts, True

        end_ts = journey.points[-1].arrival_datetime.timestamp()
        logger.planning_log.append(
            {
                "event": "journey_end",
                "time": end_ts,
                "block_id": block.block_id,
                "journey_id": journey.journey_id,
                "bus_vin": bus.vin_number,
                "bus_number": bus.vehicle_number,
            }
        )
        completed_journeys.add(journey)
        bus.state = BusState.AVAILABLE
        logger.bus_log.append(
            {
                "event": "state_update",
                "time": end_ts,
                "bus_vin": bus.vin_number,
                "bus_number": bus.vehicle_number,
                "state": bus.state.value,
                "soc_percent": bus.soc_percent,
                "location": self._point_to_location(journey.points[-1]),
            }
        )
        return end_ts, False

    def _maybe_charge(
        self,
        bus: Bus,
        start_time_ts: float,
        logger: ClassifiedLogger,
        *,
        strategy_name: str = "SOC_THRESHOLD",
        deadline_time_ts: float | None = None,
        target_soc_percent: float | None = None,
    ) -> None:
        if bus.location is None or bus.location.charging_location is None:
            if self._garage_point is None or self._garage_point.charging_location is None:
                return
            bus.location = self._garage_point
        effective_target_soc = self.charging_target_soc_percent if target_soc_percent is None else target_soc_percent
        if bus.soc_percent >= effective_target_soc:
            return

        location = bus.location.charging_location
        selected = self._select_connector(location)
        if selected is None:
            return
        charger_id, connector_id, offered_power_kw, connector = selected
        connector.connect_bus(bus)
        connector.set_charging()

        bus.state = BusState.CHARGING
        logger.bus_log.append(
            {
                "event": "state_update",
                "time": start_time_ts,
                "bus_vin": bus.vin_number,
                "bus_number": bus.vehicle_number,
                "state": bus.state.value,
                "soc_percent": bus.soc_percent,
                "location": self._point_to_location(bus.location),
            }
        )

        logger.laadinfra_log.append(
            {
                "event": "charging_started",
                "time": start_time_ts,
                "bus_vin": bus.vin_number,
                "bus_number": bus.vehicle_number,
                "location_id": location.location_id,
                "charger_id": charger_id,
                "connector_id": connector_id,
                "soc_percent": bus.soc_percent,
                "target_soc": effective_target_soc,
                "strategy_name": strategy_name,
                "power_kw": 0.0,
                "location_total_power_kw": self._location_current_load_kw(location),
                "connector_status": connector.status,
            }
        )

        current_time = start_time_ts
        reached_target_soc = bus.soc_percent >= effective_target_soc
        while True:
            if deadline_time_ts is not None and current_time + self.charging_step_seconds > deadline_time_ts:
                break
            if bus.soc_percent >= 100.0:
                break
            desired_kw = bus.calculate_actual_charging_power_kw(offered_power_kw)
            if desired_kw <= 0.0:
                connector.current_power_kw = 0.0
                connector.set_connected()
                break

            next_time = current_time + self.charging_step_seconds
            power_limit_kw = self._location_power_limit_kw(location, next_time)
            if power_limit_kw == float("inf"):
                actual_power_kw = desired_kw
            else:
                # Location-level hard cap: remaining capacity after all *other* connectors.
                current_load_kw = self._location_current_load_kw(location)
                own_prev_kw = float(connector.current_power_kw)
                other_load_kw = max(0.0, current_load_kw - own_prev_kw)
                remaining_for_this_connector_kw = max(0.0, float(power_limit_kw) - other_load_kw)
                actual_power_kw = min(desired_kw, remaining_for_this_connector_kw)

            if power_limit_kw != float("inf"):
                # Global per-location per-timestamp budget guard to prevent
                # multiple charging loops from exceeding the same time-slot cap.
                budget_key = (str(location.location_id), float(next_time))
                already_allocated = float(self._location_time_power_allocations.get(budget_key, 0.0))
                remaining_budget_kw = max(0.0, float(power_limit_kw) - already_allocated)
                actual_power_kw = min(actual_power_kw, remaining_budget_kw)
                self._location_time_power_allocations[budget_key] = already_allocated + actual_power_kw

            connector.current_power_kw = actual_power_kw
            connector.offered_power_kw = offered_power_kw
            if actual_power_kw > 0.0:
                connector.set_charging()
                delta_kwh = actual_power_kw * (self.charging_step_seconds / 3600.0)
                bus.update_soc(delta_kwh)
            else:
                # Stays connected but receives no power (queue/wait).
                connector.set_connected()

            current_time = next_time
            location_total_power_kw = self._location_current_load_kw(location)
            logger.laadinfra_log.append(
                {
                    "event": "charging_progress",
                    "time": current_time,
                    "bus_vin": bus.vin_number,
                    "bus_number": bus.vehicle_number,
                    "location_id": location.location_id,
                    "charger_id": charger_id,
                    "connector_id": connector_id,
                    "soc_percent": bus.soc_percent,
                    "power_kw": actual_power_kw,
                    "location_total_power_kw": location_total_power_kw,
                    "strategy_name": strategy_name,
                    "connector_status": connector.status,
                }
            )
            logger.bus_log.append(
                {
                    "event": "soc_update",
                    "time": current_time,
                    "bus_vin": bus.vin_number,
                    "bus_number": bus.vehicle_number,
                    "soc_percent": bus.soc_percent,
                }
            )

            if (not reached_target_soc) and bus.soc_percent >= effective_target_soc:
                reached_target_soc = True
                bus.state = BusState.AVAILABLE
                logger.bus_log.append(
                    {
                        "event": "state_update",
                        "time": current_time,
                        "bus_vin": bus.vin_number,
                        "bus_number": bus.vehicle_number,
                        "state": bus.state.value,
                        "soc_percent": bus.soc_percent,
                        "location": self._point_to_location(bus.location),
                    }
                )

            if current_time - start_time_ts > 4 * 3600:
                break

        # Charging ended; bus may remain physically connected.
        connector.current_power_kw = 0.0
        connector.offered_power_kw = 0.0
        connector.set_connected()
        logger.laadinfra_log.append(
            {
                "event": "charging_stopped",
                "time": current_time,
                "bus_vin": bus.vin_number,
                "bus_number": bus.vehicle_number,
                "location_id": location.location_id,
                "charger_id": charger_id,
                "connector_id": connector_id,
                "soc_percent": bus.soc_percent,
                "power_kw": 0.0,
                "location_total_power_kw": self._location_current_load_kw(location),
                "connector_status": connector.status,
            }
        )
        if bus.state != BusState.AVAILABLE:
            bus.state = BusState.AVAILABLE
            logger.bus_log.append(
                {
                    "event": "state_update",
                    "time": current_time,
                    "bus_vin": bus.vin_number,
                    "bus_number": bus.vehicle_number,
                    "state": bus.state.value,
                    "soc_percent": bus.soc_percent,
                    "location": self._point_to_location(bus.location),
                }
            )

    @staticmethod
    def _select_bus_for_time(
        buses: list[Bus],
        bus_available_at: dict[str, float],
        target_time: float,
        exclude_vin: str | None = None,
        required_vehicle_type: str | None = None,
    ) -> Bus:
        candidates = [b for b in buses if b.vin_number != exclude_vin]
        if required_vehicle_type:
            typed_candidates = [b for b in candidates if b.vehicle_type == required_vehicle_type]
            if typed_candidates:
                candidates = typed_candidates
        if not candidates:
            return buses[0]
        available = [b for b in candidates if bus_available_at.get(b.vin_number, 0.0) <= target_time]
        if available:
            return sorted(available, key=lambda b: (-b.soc_percent, b.vehicle_number))[0]
        return sorted(candidates, key=lambda b: (bus_available_at.get(b.vin_number, 0.0), b.vehicle_number))[0]

    def _can_complete_journey(self, bus: Bus, journey: Journey) -> bool:
        required_kwh = 0.0
        for point in journey.points:
            if point.distance_to_next_m:
                required_kwh += (point.distance_to_next_m / 1000.0) * bus.energy_consumption_per_km
        required_soc_percent = (required_kwh / bus.battery_capacity_kwh) * 100.0 if bus.battery_capacity_kwh > 0 else 100.0
        projected_soc = bus.soc_percent - required_soc_percent
        return projected_soc >= self.low_soc_alert_threshold_percent

    def _log_precheck_replacement(
        self,
        *,
        world: World,
        logger: ClassifiedLogger,
        block: Block,
        original_bus: Bus,
        replacement_bus: Bus,
        journey: Journey,
        sequence: int,
    ) -> None:
        start_ts = journey.points[0].departure_datetime.timestamp() if journey.points else 0.0
        return_journey_id = f"8{sequence:06d}_{block.operating_day.isoformat()}"
        dispatch_journey_id = f"9{sequence:06d}_{block.operating_day.isoformat()}"
        garage_point = self._find_point_by_id(world, "30002")
        fallback_point = journey.points[0] if journey.points else original_bus.location
        target_point = fallback_point
        if not garage_point:
            garage_point = fallback_point
        # Return trip log (8xxxxxx)
        logger.planning_log.append(
            {
                "event": "return_journey_created",
                "time": start_ts - 1,
                "block_id": block.block_id,
                "return_journey_id": return_journey_id,
                "original_journey_id": journey.journey_id,
                "bus_vin": original_bus.vin_number,
                "bus_number": original_bus.vehicle_number,
                "reason": "Precheck SOC insufficient for next journey",
            }
        )
        logger.planning_log.append(
            {
                "event": "journey_replacement",
                "time": start_ts,
                "block_id": block.block_id,
                "journey_id": journey.journey_id,
                "bus_vin": original_bus.vin_number,
                "bus_number": original_bus.vehicle_number,
                "replacement_bus_vin": replacement_bus.vin_number,
                "replacement_bus_number": replacement_bus.vehicle_number,
                "reason": "Precheck SOC insufficient; replacement dispatched",
            }
        )
        logger.planning_log.append(
            {
                "event": "block_end_return_journey_created",
                "time": start_ts,
                "block_id": block.block_id,
                "return_journey_id": return_journey_id,
                "bus_vin": original_bus.vin_number,
                "bus_number": original_bus.vehicle_number,
                "reason": "Return to Garage Telexstraat (30002) for charging",
            }
        )
        # Dispatch trip log (9xxxxxx)
        logger.planning_log.append(
            {
                "event": "journey_start",
                "time": max(0.0, start_ts - 600),
                "block_id": block.block_id,
                "journey_id": dispatch_journey_id,
                "bus_vin": replacement_bus.vin_number,
                "bus_number": replacement_bus.vehicle_number,
            }
        )
        logger.planning_log.append(
            {
                "event": "point_arrival",
                "time": start_ts,
                "block_id": block.block_id,
                "journey_id": dispatch_journey_id,
                "point_id": target_point.point_id if target_point else "N/A",
                "point_name": target_point.name if target_point else "Dispatch Target",
                "bus_vin": replacement_bus.vin_number,
                "bus_number": replacement_bus.vehicle_number,
            }
        )
        logger.planning_log.append(
            {
                "event": "journey_end",
                "time": start_ts,
                "block_id": block.block_id,
                "journey_id": dispatch_journey_id,
                "bus_vin": replacement_bus.vin_number,
                "bus_number": replacement_bus.vehicle_number,
            }
        )

    @staticmethod
    def _find_point_by_id(world: World, point_id: str) -> PointInSequence | None:
        for block in world.blocks_by_id.values():
            for journey in block.journeys:
                for point in journey.points:
                    if str(point.point_id) == str(point_id):
                        return point
        return None

    @staticmethod
    def _build_virtual_garage_point(world: World) -> PointInSequence | None:
        """
        Build a synthetic planning point for garage charger fallback.

        Rationale: Some simulation windows may not include any planning points
        with charger linkage. To keep charging simulation realistic and produce
        laadinfra logs, we create a virtual Telexstraat point from infra data.
        """
        garage_location = None
        for loc in world.locations_by_id.values():
            if str(getattr(loc, "point_id", "")) == "30002":
                garage_location = loc
                break
        if garage_location is None:
            return None
        now = datetime.combine(date.today(), datetime.min.time())
        point = PointInSequence(
            point_id="30002",
            name="Garage Telexstraat",
            sequence_order=1,
            latitude=0.0,
            longitude=0.0,
            distance_to_next_m=0.0,
            arrival_datetime=now,
            departure_datetime=now,
            wait_time=timedelta(0),
            is_wait_point=True,
        )
        point.charging_location = garage_location
        return point

    @staticmethod
    def _select_connector(location: Location) -> tuple[str, str, float, Connector] | None:
        for charger in location.chargers.values():
            for connector in charger.connectors:
                if not connector.is_available:
                    continue
                offered = connector.max_power_kw if connector.max_power_kw > 0 else charger.max_power_kw
                return charger.charger_id, connector.connector_id, float(max(offered, 50.0)), connector
        return None

    @staticmethod
    def _release_bus_connector(bus: Bus) -> None:
        """
        Release any connector currently occupied by this bus.

        Rationale: A connector should return to AVAILABLE only when no bus is
        physically connected. We release it when the bus departs for a journey.
        """
        loc = getattr(bus, "location", None)
        charging_loc = getattr(loc, "charging_location", None) if loc is not None else None
        if charging_loc is None:
            return
        for charger in charging_loc.chargers.values():
            for connector in charger.connectors:
                if connector.connected_bus is bus:
                    connector.disconnect_bus()
                    return

    @staticmethod
    def _is_bus_connected_to_connector(bus: Bus) -> bool:
        """
        Check whether the bus is still physically connected to any connector.

        Rationale: charging behavior is connector-driven. If the bus remains
        connected during idle time, simulation should keep applying the charging
        curve until departure or a stopping condition.
        """
        loc = getattr(bus, "location", None)
        charging_loc = getattr(loc, "charging_location", None) if loc is not None else None
        if charging_loc is None:
            return False
        for charger in charging_loc.chargers.values():
            for connector in charger.connectors:
                if connector.connected_bus is bus:
                    return True
        return False

    @staticmethod
    def _location_current_load_kw(location: Location) -> float:
        """
        Calculate aggregate charging power for an entire location.

        Rationale: report-level `location_total_power_kw` must represent site
        total load across all chargers/connectors, not the current bus only.
        """
        return float(sum(ch.current_load_kw for ch in location.chargers.values()))

    @staticmethod
    def _find_charger_id_for_connector(location: Location, connector: Connector) -> str | None:
        for charger in location.chargers.values():
            if connector in charger.connectors:
                return charger.charger_id
        return None

    @staticmethod
    def _collect_connected_buses_at_location(location: Location) -> list[tuple[Bus, Connector, float]]:
        """
        Collect all buses currently connected at a location with their connector power offer.

        Rationale: parallel charging model requires stepping all connected buses
        in the same time slice, not only the bus that initiated the charge call.
        """
        pairs: list[tuple[Bus, Connector, float]] = []
        for charger in location.chargers.values():
            for conn in charger.connectors:
                connected_bus = conn.connected_bus
                if connected_bus is None:
                    continue
                offered = conn.max_power_kw if conn.max_power_kw > 0 else charger.max_power_kw
                pairs.append((connected_bus, conn, float(max(offered, 50.0))))
        return pairs

    def _location_power_limit_kw(self, location: Location, current_time_ts: float) -> float:
        """
        Return location power cap (kW) for current time when enabled.

        Rationale: only Telexstraat (point_id 30002) applies configured grid
        limits. Other locations stay unconstrained to preserve current behavior.
        """
        if not bool(self.strategy_flags.get("power_limit", False)):
            return float("inf")
        loc_id = str(getattr(location, "location_id", "")).lower()
        point_id = str(getattr(location, "point_id", ""))
        if point_id not in {"30002", "3002"} and "telexstraat" not in loc_id:
            return float("inf")
        location_profile = getattr(location, "max_power_profile", None)
        if callable(location_profile):
            return float(location_profile(datetime.fromtimestamp(current_time_ts)))
        grid = getattr(location, "grid", None)
        if grid is None:
            return float("inf")
        return float(grid.get_available_power_at(datetime.fromtimestamp(current_time_ts)))

    @staticmethod
    def _to_world_view(world: World) -> VisualizationWorldView:
        return VisualizationWorldView(
            blocks=dict(world.blocks_by_id),
            locations=dict(world.locations_by_id),
            buses=list(world.buses_by_vehicle_number.values()),
        )

    @staticmethod
    def _point_to_location(point: PointInSequence) -> dict[str, Any]:
        return {
            "latitude": point.latitude,
            "longitude": point.longitude,
            "name": point.name,
            "point_id": point.point_id,
        }
