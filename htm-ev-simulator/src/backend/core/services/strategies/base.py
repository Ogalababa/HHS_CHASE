"""
Strategy contracts for visualization simulation runtime hooks.

Rationale: Strategies should be independently extensible without changing the
simulation service. A small hook contract allows new behaviors to be plugged in
as separate modules and discovered automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .simulation_strategy_host import SimulationStrategyHost

from ...models.planning.block import Block
from ...models.planning.journey import Journey
from ...models.transport.bus.bus import Bus


@dataclass(slots=True)
class StrategyRuntimeState:
    """
    Mutable state shared with strategy hooks for one journey step.

    Rationale: Passing a state object avoids tight coupling between strategies
    and service internals while still allowing safe, intentional mutation (e.g.
    swapping `active_bus` for replacement scenarios).
    """

    world: Any
    block: Block
    journey: Journey
    journey_index: int
    assign_time: float
    active_bus: Bus
    buses: list[Bus]
    bus_available_at: dict[str, float]
    logger: Any
    journey_end: float | None = None
    journey_skipped: bool = False


class SimulationStrategy(Protocol):
    """
    Strategy hook protocol.

    Rationale: a narrow protocol keeps the host service stable; future
    strategies can be added as standalone files implementing these hooks.
    """

    strategy_key: str

    def before_journey(self, service: SimulationStrategyHost, state: StrategyRuntimeState) -> None:
        """Executed before journey simulation."""

    def after_journey(self, service: SimulationStrategyHost, state: StrategyRuntimeState) -> None:
        """Executed after journey simulation."""

