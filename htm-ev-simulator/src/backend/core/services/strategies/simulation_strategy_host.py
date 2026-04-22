"""
Protocol for the object passed as `service` into strategy hooks.

Rationale: Strategies are invoked with `run_before_journey(strategies, self, state)`
where `self` is `SimpyScheduler`. This module documents the **supported public
surface** (methods and attributes) strategies may rely on, so new strategies do
not call undefined APIs. Python structural typing (`Protocol`) enables static
checkers to validate usage without forcing inheritance on the scheduler.
"""

from __future__ import annotations

from typing import Protocol

from ...models.planning.block import Block
from ...models.planning.journey import Journey
from ...models.transport.bus.bus import Bus
from ...models.world import World
from ..simpy_engine.event_log import InternalEventLog


class SimulationStrategyHost(Protocol):
    """
    Host surface exposed to `SimulationStrategy.before_journey/after_journey`.

    Implemented by: `SimpyScheduler` (see `simpy_engine/scheduler.py`).

    Note: Method names starting with `_` are intentionally the legacy hook
    contract; prefer not renaming them without updating all strategies.
    """

    # --- Configuration mirrored from VisualizationSimulationService -----------
    opportunity_charging_soc_threshold_percent: float
    opportunity_charging_min_gap_seconds: int
    charging_target_soc_percent: float
    low_soc_alert_threshold_percent: float
    charging_step_seconds: int

    # --- Precheck / replacement helpers ---------------------------------------
    def _can_complete_journey(self, bus: Bus, journey: Journey) -> bool:
        """Return True if projected SOC after journey stays above low-SOC gate (with garage exemptions)."""

    def _select_bus_for_time(
        self,
        buses: list[Bus],
        bus_available_at: dict[str, float],
        target_time: float,
        exclude_vin: str | None = None,
        required_vehicle_type: str | None = None,
    ) -> Bus:
        """Pick a replacement/standby bus by availability time and SOC heuristic."""

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
        """Append planning log entries for a precheck replacement workflow."""

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
        """Start a bounded charging session; writes bus + laadinfra classified logs."""
