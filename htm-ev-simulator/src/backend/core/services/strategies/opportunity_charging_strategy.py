"""
Opportunity charging strategy.

Rationale: capture useful layovers without changing fixed charge policy.
When terminal has a charger, SOC is low, and layover is long enough, charge
within the allowed gap before the next journey starts.
"""

from __future__ import annotations

from .base import StrategyRuntimeState


class OpportunityChargingStrategy:
    strategy_key = "opportunity_charging"
    enabled_by_default = False

    def before_journey(self, service, state: StrategyRuntimeState) -> None:
        return

    def after_journey(self, service, state: StrategyRuntimeState) -> None:
        if state.journey_end is None:
            return
        if state.journey_index >= len(state.block.journeys) - 1:
            return
        next_journey = state.block.journeys[state.journey_index + 1]
        next_start_ts = next_journey.points[0].departure_datetime.timestamp() if next_journey.points else state.journey_end
        layover_seconds = max(0.0, next_start_ts - state.journey_end)
        end_point = state.journey.points[-1] if state.journey.points else None
        if (
            end_point is None
            or end_point.charging_location is None
            or state.active_bus.soc_percent >= service.opportunity_charging_soc_threshold_percent
            or layover_seconds <= float(service.opportunity_charging_min_gap_seconds)
        ):
            return
        service._maybe_charge(
            state.active_bus,
            state.journey_end,
            state.logger,
            strategy_name="OPPORTUNITY_CHARGING",
            deadline_time_ts=next_start_ts,
            target_soc_percent=service.opportunity_charging_soc_threshold_percent,
        )
        state.bus_available_at[state.active_bus.vin_number] = next_start_ts

