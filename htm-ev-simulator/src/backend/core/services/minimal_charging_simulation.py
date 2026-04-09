"""
Minimal charging simulation (1 Hz SoC trace).

Rationale: Before building the full discrete-event simulation, it is useful to
validate the charging physics in isolation. This service simulates charging a
single `Bus` from a start SoC to a target SoC in fixed time steps, using the
existing vehicle acceptance curve and loss model.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models.transport.bus.bus import Bus


@dataclass(frozen=True, slots=True)
class ChargingTrace:
    """
    Output trace for a minimal charging run.

    - `soc_per_second` includes the initial SoC at t=0 as the first element.
    - `duration_seconds` is the number of simulated seconds until the target is reached.
    """

    duration_seconds: int
    soc_per_second: list[float]


def simulate_charging_soc_trace(
    *,
    bus: Bus,
    charger_offered_power_kw: float,
    start_soc_percent: float = 10.0,
    target_soc_percent: float = 100.0,
    dt_seconds: int = 1,
    max_seconds: int = 48 * 3600,
) -> ChargingTrace:
    """
    Simulate charging a bus from `start_soc_percent` to `target_soc_percent`.

    The model uses:
    - `Bus.calculate_actual_charging_power_kw()` to compute net battery power (kW)
      limited by charger offered power, charging loss, and acceptance curve.
    - `Bus.update_soc(delta_kwh)` to update SoC based on energy added in each step.

    Rationale: Fixed-step simulation is sufficient for a first validation of the
    charging curve and time-to-charge calculations, and it produces a simple
    per-second SoC series for plotting/debugging.
    """
    if dt_seconds <= 0:
        raise ValueError("dt_seconds must be > 0")
    if max_seconds <= 0:
        raise ValueError("max_seconds must be > 0")

    # Initialize SoC
    bus.soc_percent = float(start_soc_percent)

    soc_trace: list[float] = [float(bus.soc_percent)]
    elapsed = 0

    target = float(target_soc_percent)

    while bus.soc_percent < target and elapsed < max_seconds:
        p_kw = bus.calculate_actual_charging_power_kw(float(charger_offered_power_kw))
        # Convert kW -> kWh over dt_seconds (net into battery)
        delta_kwh = p_kw * (dt_seconds / 3600.0)
        bus.update_soc(delta_kwh)

        elapsed += dt_seconds
        soc_trace.append(float(bus.soc_percent))

        # Defensive: break if no progress (avoids infinite loops).
        if len(soc_trace) >= 3 and soc_trace[-1] <= soc_trace[-2] <= soc_trace[-3]:
            if p_kw <= 0.0:
                break

    return ChargingTrace(duration_seconds=elapsed, soc_per_second=soc_trace)

