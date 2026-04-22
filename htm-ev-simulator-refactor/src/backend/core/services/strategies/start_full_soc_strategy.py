"""
Set all buses to full SOC at simulation start.

Rationale: Some scenarios require a normalized starting condition where every
bus begins with 100% SOC regardless of provider telemetry snapshots.
"""

from __future__ import annotations

from .base import StrategyRuntimeState


class StartFullSocStrategy:
    strategy_key = "start_full_soc"
    enabled_by_default = False

    def __init__(self) -> None:
        self._applied = False

    def before_journey(self, service, state: StrategyRuntimeState) -> None:
        if self._applied:
            return
        for bus in state.buses:
            bus.soc_percent = 100.0
        self._applied = True

    def after_journey(self, service, state: StrategyRuntimeState) -> None:
        return

