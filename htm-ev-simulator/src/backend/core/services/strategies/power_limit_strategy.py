"""
Power limit strategy toggle.

Rationale: Keep grid-power-limit behavior as an explicitly named strategy so it
can be enabled/disabled from configuration without changing simulation service
or strategy loader wiring.
"""

from __future__ import annotations

from .base import StrategyRuntimeState


class PowerLimitStrategy:
    """
    Marker strategy for enabling location power-limit behavior.

    Rationale: The actual cap enforcement happens inside charging service logic
    because it is time-step based and affects all connected buses in parallel.
    This strategy exists as a pluggable switch in the strategy system.
    """

    strategy_key = "power_limit"
    enabled_by_default = False

    def before_journey(self, service, state: StrategyRuntimeState) -> None:
        return None

    def after_journey(self, service, state: StrategyRuntimeState) -> None:
        return None

