"""
SimPy scheduler for visualization workflow.

Rationale: Scheduler orchestrates journeys, charging, and strategy hooks while
staying independent from adapters and report rendering.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from ...models.laad_infra.connector import Connector
from ...models.planning.block import Block
from ...models.planning.journey import Journey
from ...models.planning.point_in_sequence import PointInSequence
from ...models.transport.bus.bus import Bus, BusState
from ...models.world import World
from ...services.strategies.base import StrategyRuntimeState
from ...services.strategies.loader import run_after_journey, run_before_journey
from .event_log import InternalEventLog
from .resource_allocator import LocationPowerAllocator


@dataclass(slots=True)
class SimpyScheduler:
    world: World
    logger: InternalEventLog
    allocator: LocationPowerAllocator
    low_soc_alert_threshold_percent: float
    charging_target_soc_percent: float
    charging_step_seconds: int
    simulation_start_timestamp: float
    simulation_end_timestamp: float | None
    strategies: list[Any]
    opportunity_charging_soc_threshold_percent: float = 80.0
    opportunity_charging_min_gap_seconds: int = 1800

    @staticmethod
    def _point_to_location(point: PointInSequence) -> dict[str, Any]:
        return {
            "latitude": point.latitude,
            "longitude": point.longitude,
            "name": point.name,
            "point_id": point.point_id,
        }

    @staticmethod
    def _connector_status(connector: Connector) -> str:
        """
        Return connector status as string for log compatibility.

        Rationale: Some model versions store connector status as enum, others as
        plain string. This normalizer keeps logs stable across both variants.
        """
        status = getattr(connector, "status", "available")
        return str(getattr(status, "value", status))

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
    def _release_bus_connector(bus: Bus) -> None:
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
    def _select_connector(location) -> tuple[str, str, float, Connector] | None:
        for charger in location.chargers.values():
            for connector in charger.connectors:
                if not connector.is_available:
                    continue
                offered = connector.max_power_kw if connector.max_power_kw > 0 else charger.max_power_kw
                return charger.charger_id, connector.connector_id, float(max(offered, 50.0)), connector
        return None

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
            typed = [b for b in candidates if b.vehicle_type == required_vehicle_type]
            if typed:
                candidates = typed
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
        logger: InternalEventLog,
        block: Block,
        original_bus: Bus,
        replacement_bus: Bus,
        journey: Journey,
        sequence: int,
    ) -> None:
        start_ts = journey.points[0].departure_datetime.timestamp() if journey.points else 0.0
        dispatch_journey_id = f"9{sequence:06d}_{block.operating_day.isoformat()}"
        target_point = journey.points[0] if journey.points else self._find_point_by_id(world, "30002")
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
                "event": "journey_point",
                "time": start_ts,
                "block_id": block.block_id,
                "journey_id": dispatch_journey_id,
                "point_id": target_point.point_id if target_point else "N/A",
                "point_name": target_point.name if target_point else "Dispatch Target",
                "bus_vin": replacement_bus.vin_number,
                "bus_number": replacement_bus.vehicle_number,
            }
        )

    def _charge_until(
        self,
        *,
        bus: Bus,
        start_ts: float,
        until_ts: float,
        target_soc_percent: float,
        strategy_name: str,
        logger: InternalEventLog,
    ) -> None:
        now_ts = start_ts
        if bus.location is None:
            garage = self._find_point_by_id(self.world, "30002") or self._build_virtual_garage_point(self.world)
            if garage is None:
                return
            bus.location = garage
        location = getattr(bus.location, "charging_location", None)
        if location is None:
            return
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
                "time": start_ts,
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
                "time": start_ts,
                "bus_vin": bus.vin_number,
                "bus_number": bus.vehicle_number,
                "location_id": location.location_id,
                "charger_id": charger_id,
                "connector_id": connector_id,
                "soc_percent": bus.soc_percent,
                "target_soc": target_soc_percent,
                "strategy_name": strategy_name,
                "power_kw": 0.0,
                "location_total_power_kw": self.allocator.location_current_load_kw(location),
                "connector_status": self._connector_status(connector),
            }
        )
        while now_ts < until_ts and bus.soc_percent < 100.0:
            next_ts = min(until_ts, now_ts + self.charging_step_seconds)
            desired_kw = float(bus.calculate_actual_charging_power_kw(offered_power_kw))
            allocated_kw = self.allocator.allocate_power_kw(
                location=location,
                connector_previous_kw=float(connector.current_power_kw),
                desired_kw=desired_kw,
                next_time_ts=next_ts,
            )
            connector.current_power_kw = float(max(0.0, allocated_kw))
            connector.offered_power_kw = float(max(0.0, offered_power_kw))
            if allocated_kw > 0.0:
                connector.set_charging()
            else:
                connector.set_connected()
            self.allocator.apply_energy(bus, allocated_kw, int(next_ts - now_ts))
            logger.laadinfra_log.append(
                {
                    "event": "charging_progress",
                    "time": next_ts,
                    "bus_vin": bus.vin_number,
                    "bus_number": bus.vehicle_number,
                    "location_id": location.location_id,
                    "charger_id": charger_id,
                    "connector_id": connector_id,
                    "power_kw": float(allocated_kw),
                    "location_total_power_kw": self.allocator.location_current_load_kw(location),
                    "connector_status": self._connector_status(connector),
                    "soc_percent": bus.soc_percent,
                    "strategy_name": strategy_name,
                }
            )
            logger.bus_log.append(
                {
                    "event": "soc_update",
                    "time": next_ts,
                    "bus_vin": bus.vin_number,
                    "bus_number": bus.vehicle_number,
                    "soc_percent": bus.soc_percent,
                }
            )
            now_ts = next_ts
        if connector.connected_bus is bus:
            connector.current_power_kw = 0.0
            connector.offered_power_kw = 0.0
            connector.set_connected()
            bus.state = BusState.AVAILABLE
            logger.bus_log.append(
                {
                    "event": "state_update",
                    "time": now_ts,
                    "bus_vin": bus.vin_number,
                    "bus_number": bus.vehicle_number,
                    "state": bus.state.value,
                    "soc_percent": bus.soc_percent,
                    "location": self._point_to_location(bus.location),
                }
            )
            logger.laadinfra_log.append(
                {
                    "event": "charging_stopped",
                    "time": now_ts,
                    "bus_vin": bus.vin_number,
                    "bus_number": bus.vehicle_number,
                    "location_id": location.location_id,
                    "charger_id": charger_id,
                    "connector_id": connector_id,
                    "power_kw": 0.0,
                    "location_total_power_kw": self.allocator.location_current_load_kw(location),
                    "connector_status": self._connector_status(connector),
                }
            )

    def _maybe_charge(
        self,
        bus: Bus,
        start_time_ts: float,
        logger: InternalEventLog,
        *,
        strategy_name: str = "SOC_THRESHOLD",
        deadline_time_ts: float | None = None,
        target_soc_percent: float | None = None,
    ) -> None:
        if bus.location is None or getattr(bus.location, "charging_location", None) is None:
            garage = self._find_point_by_id(self.world, "30002") or self._build_virtual_garage_point(self.world)
            if garage is not None:
                bus.location = garage
        end_ts = deadline_time_ts if deadline_time_ts is not None else (start_time_ts + 4 * 3600)
        target = self.charging_target_soc_percent if target_soc_percent is None else target_soc_percent
        self._charge_until(
            bus=bus,
            start_ts=start_time_ts,
            until_ts=end_ts,
            target_soc_percent=target,
            strategy_name=strategy_name,
            logger=logger,
        )

    def _simulate_journey(self, bus: Bus, block: Block, journey: Journey, completed_journeys: set[Journey]) -> tuple[float, bool]:
        if not journey.points:
            return 0.0, False
        first_point = journey.points[0]
        start_ts = first_point.departure_datetime.timestamp()
        self._release_bus_connector(bus)
        bus.state = BusState.RUNNING
        bus.location = first_point
        self.logger.planning_log.append(
            {
                "event": "journey_start",
                "time": start_ts,
                "block_id": block.block_id,
                "journey_id": journey.journey_id,
                "bus_vin": bus.vin_number,
                "bus_number": bus.vehicle_number,
            }
        )
        self.logger.bus_log.append(
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
            self.logger.planning_log.append(
                {
                    "event": "journey_point",
                    "time": arrival_ts,
                    "block_id": block.block_id,
                    "journey_id": journey.journey_id,
                    "bus_vin": bus.vin_number,
                    "bus_number": bus.vehicle_number,
                    "point_id": point.point_id,
                    "point_name": point.name,
                }
            )
            distance_km = (float(point.distance_to_next_m) / 1000.0) if point.distance_to_next_m else 0.0
            bus.update_soc(-(distance_km * float(bus.energy_consumption_per_km)))
            self.logger.planning_log.append(
                {
                    "event": "point_arrival",
                    "time": arrival_ts,
                    "block_id": block.block_id,
                    "journey_id": journey.journey_id,
                    "bus_vin": bus.vin_number,
                    "bus_number": bus.vehicle_number,
                    "point_id": point.point_id,
                    "point_name": point.name,
                    "soc_percent": bus.soc_percent,
                    "range_km": bus.remaining_range_km(),
                }
            )
            self.logger.bus_log.append(
                {
                    "event": "soc_update",
                    "time": arrival_ts,
                    "bus_vin": bus.vin_number,
                    "bus_number": bus.vehicle_number,
                    "soc_percent": bus.soc_percent,
                }
            )
            self.logger.bus_log.append(
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
            if bus.soc_percent < self.low_soc_alert_threshold_percent:
                self.logger.planning_log.append(
                    {
                        "event": "journey_skipped",
                        "time": arrival_ts,
                        "block_id": block.block_id,
                        "journey_id": journey.journey_id,
                        "bus_vin": bus.vin_number,
                        "bus_number": bus.vehicle_number,
                        "reason": f"SOC below threshold {self.low_soc_alert_threshold_percent:.1f}%",
                    }
                )
                bus.state = BusState.AVAILABLE
                return arrival_ts, True
        end_ts = journey.points[-1].arrival_datetime.timestamp()
        self.logger.planning_log.append(
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
        return end_ts, False

    def run(self, env, blocks: list[Block], buses: list[Bus]) -> dict[str, Any]:
        """
        Run full block/journey simulation in SimPy context.

        Rationale: We keep deterministic planning timestamps while still using
        SimPy as the universal runtime clock driver.
        """
        completed_journeys: set[Journey] = set()
        skipped_journeys: set[Journey] = set()
        skipped_blocks: set[Block] = set()
        bus_available_at: dict[str, float] = {b.vin_number: self.simulation_start_timestamp for b in buses}

        for bus in buses:
            bus.state = BusState.AVAILABLE
            self.logger.bus_log.append(
                {
                    "event": "state_update",
                    "time": self.simulation_start_timestamp,
                    "bus_vin": bus.vin_number,
                    "bus_number": bus.vehicle_number,
                    "state": bus.state.value,
                    "soc_percent": bus.soc_percent,
                    "location": {
                        "name": getattr(bus.location, "name", "Garage Telexstraat"),
                        "point_id": getattr(bus.location, "point_id", "30002"),
                    },
                }
            )

        for block in sorted(
            blocks,
            key=lambda b: b.journeys[0].first_departure_datetime if b.journeys and b.journeys[0].first_departure_datetime else datetime.min,
        ):
            block_start_dt = block.journeys[0].first_departure_datetime if block.journeys else None
            if block_start_dt is None:
                continue
            if self.simulation_end_timestamp is not None and block_start_dt.timestamp() > self.simulation_end_timestamp:
                continue
            current_bus: Bus | None = None
            block_assigned_time: float | None = None
            block_end_time: float | None = None
            for journey_index, journey in enumerate(
                sorted(block.journeys, key=lambda j: j.points[0].departure_datetime.timestamp() if j.points else 0.0)
            ):
                if not journey.points:
                    continue
                journey_start = journey.points[0].departure_datetime.timestamp()
                if self.simulation_end_timestamp is not None and journey_start > self.simulation_end_timestamp:
                    continue
                if current_bus is None:
                    current_bus = self._select_bus_for_time(
                        buses,
                        bus_available_at,
                        journey_start,
                        required_vehicle_type=getattr(block, "vehicle_type", None),
                    )
                    block_assigned_time = journey_start
                    self.logger.planning_log.append(
                        {
                            "event": "block_assigned",
                            "time": journey_start,
                            "block_id": block.block_id,
                            "bus_vin": current_bus.vin_number,
                            "bus_number": current_bus.vehicle_number,
                        }
                    )
                if bus_available_at.get(current_bus.vin_number, 0.0) < journey_start and current_bus.soc_percent < self.charging_target_soc_percent:
                    self._charge_until(
                        bus=current_bus,
                        start_ts=bus_available_at.get(current_bus.vin_number, self.simulation_start_timestamp),
                        until_ts=journey_start,
                        target_soc_percent=100.0,
                        strategy_name="CONNECTED_IDLE_TOP_OFF",
                        logger=self.logger,
                    )
                state = StrategyRuntimeState(
                    world=self.world,
                    block=block,
                    journey=journey,
                    journey_index=journey_index,
                    assign_time=journey_start,
                    active_bus=current_bus,
                    buses=buses,
                    bus_available_at=bus_available_at,
                    logger=self.logger,
                )
                run_before_journey(self.strategies, self, state)
                current_bus = state.active_bus
                journey_end, skipped = self._simulate_journey(current_bus, block, journey, completed_journeys)
                block_end_time = journey_end if block_end_time is None else max(block_end_time, journey_end)
                state.journey_end = journey_end
                state.journey_skipped = skipped
                bus_available_at[current_bus.vin_number] = max(bus_available_at.get(current_bus.vin_number, 0.0), journey_end)
                run_after_journey(self.strategies, self, state)
                current_bus = state.active_bus
                if skipped:
                    skipped_journeys.add(journey)
                    skipped_blocks.add(block)
                    break
            if current_bus is not None:
                current_bus.state = BusState.AVAILABLE
                if block_assigned_time is not None:
                    self.logger.planning_log.append(
                        {
                            "event": "block_completed",
                            "time": block_end_time if block_end_time is not None else block_assigned_time,
                            "block_id": block.block_id,
                            "bus_vin": current_bus.vin_number,
                            "bus_number": current_bus.vehicle_number,
                        }
                    )
                # After block completion, dispatch bus back to Garage Telexstraat
                # and perform charging there for report consistency.
                garage_point = self._find_point_by_id(self.world, "30002") or self._build_virtual_garage_point(self.world)
                if garage_point is not None:
                    current_bus.location = garage_point
                charge_start = block_end_time if block_end_time is not None else bus_available_at[current_bus.vin_number]
                self._maybe_charge(
                    current_bus,
                    charge_start,
                    self.logger,
                    strategy_name="SOC_THRESHOLD",
                    target_soc_percent=100.0,
                )
                if self.logger.laadinfra_log:
                    bus_available_at[current_bus.vin_number] = max(
                        bus_available_at[current_bus.vin_number],
                        float(self.logger.laadinfra_log[-1].get("time", bus_available_at[current_bus.vin_number])),
                    )
                self.logger.bus_log.append(
                    {
                        "event": "state_update",
                        "time": bus_available_at[current_bus.vin_number],
                        "bus_vin": current_bus.vin_number,
                        "bus_number": current_bus.vehicle_number,
                        "state": current_bus.state.value,
                        "soc_percent": current_bus.soc_percent,
                    }
                )
            yield env.timeout(0)

        return {
            "completed_journeys": completed_journeys,
            "skipped_journeys": skipped_journeys,
            "skipped_blocks": skipped_blocks,
        }

