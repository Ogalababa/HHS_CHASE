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
from datetime import datetime
from typing import Any

from ..models.laad_infra.location import Location
from ..models.planning.block import Block
from ..models.planning.journey import Journey
from ..models.planning.point_in_sequence import PointInSequence
from ..models.transport.bus.bus import Bus, BusState
from ..models.world import World


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

    def run(self, world: World) -> VisualizationSimulationResult:
        buses = sorted(world.buses_by_vehicle_number.values(), key=lambda b: b.vehicle_number)
        blocks = sorted(
            world.blocks_by_id.values(),
            key=lambda blk: blk.journeys[0].first_departure_datetime if blk.journeys else datetime.min,
        )

        logger = ClassifiedLogger()
        completed_journeys: set[Journey] = set()
        skipped_blocks: set[Block] = set()
        current_time = 0.0

        if not buses or not blocks:
            return VisualizationSimulationResult(
                world=self._to_world_view(world),
                classified_logger=logger,
                current_time=current_time,
                completed_journeys=completed_journeys,
                skipped_blocks=skipped_blocks,
            )

        for idx, block in enumerate(blocks):
            if not block.journeys:
                skipped_blocks.add(block)
                continue

            bus = buses[idx % len(buses)]
            assign_time = block.journeys[0].first_departure_datetime.timestamp()
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

            for journey in block.journeys:
                self._simulate_journey(bus, block, journey, logger, completed_journeys)
                journey_end = journey.points[-1].arrival_datetime.timestamp() if journey.points else assign_time
                block_end_time = max(block_end_time, journey_end)

            logger.planning_log.append(
                {
                    "event": "block_completed",
                    "time": block_end_time,
                    "block_id": block.block_id,
                    "bus_vin": bus.vin_number,
                    "bus_number": bus.vehicle_number,
                }
            )

            self._maybe_charge(bus, block_end_time, logger)
            current_time = max(current_time, block_end_time)
            current_time = max(current_time, logger.laadinfra_log[-1]["time"] if logger.laadinfra_log else current_time)

        return VisualizationSimulationResult(
            world=self._to_world_view(world),
            classified_logger=logger,
            current_time=current_time,
            completed_journeys=completed_journeys,
            skipped_blocks=skipped_blocks,
        )

    def _simulate_journey(
        self,
        bus: Bus,
        block: Block,
        journey: Journey,
        logger: ClassifiedLogger,
        completed_journeys: set[Journey],
    ) -> None:
        if not journey.points:
            return

        first_point = journey.points[0]
        start_ts = first_point.departure_datetime.timestamp()
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
                    continue
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

    def _maybe_charge(self, bus: Bus, start_time_ts: float, logger: ClassifiedLogger) -> None:
        if bus.location is None or bus.location.charging_location is None:
            return
        if bus.soc_percent >= self.charging_target_soc_percent:
            return

        location = bus.location.charging_location
        charger_id, connector_id, offered_power_kw = self._select_connector(location)

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
                "target_soc": self.charging_target_soc_percent,
                "strategy_name": "SOC_THRESHOLD",
                "power_kw": 0.0,
                "location_total_power_kw": 0.0,
            }
        )

        current_time = start_time_ts
        while bus.soc_percent < self.charging_target_soc_percent:
            actual_power_kw = bus.calculate_actual_charging_power_kw(offered_power_kw)
            delta_kwh = actual_power_kw * (self.charging_step_seconds / 3600.0)
            bus.update_soc(delta_kwh)
            current_time += self.charging_step_seconds

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
                    "location_total_power_kw": actual_power_kw,
                    "strategy_name": "SOC_THRESHOLD",
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

            if current_time - start_time_ts > 4 * 3600:
                break

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
            }
        )
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
    def _select_connector(location: Location) -> tuple[str, str, float]:
        for charger in location.chargers.values():
            if charger.connectors:
                connector = charger.connectors[0]
                offered = connector.max_power_kw if connector.max_power_kw > 0 else charger.max_power_kw
                return charger.charger_id, connector.connector_id, float(max(offered, 50.0))
        return "N/A", "N/A", 150.0

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
