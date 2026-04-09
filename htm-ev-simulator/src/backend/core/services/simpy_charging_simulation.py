"""
SimPy-based minimal charging simulation (1 Hz SoC trace).

Rationale: The project uses SimPy as the discrete-event simulation driver.
Even for a "minimal" charging-only scenario, using SimPy keeps the execution
model consistent with the full simulator: a process yields timeouts and updates
domain state. The charging physics remains inside domain models (`Bus` +
`ChargingCurve`); SimPy is only the scheduler/clock.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models.transport.bus.bus import Bus


@dataclass(frozen=True, slots=True)
class ChargingTrace:
    """
    Output trace for a charging run.

    - `soc_per_second` includes the initial SoC at t=0 as the first element.
    - `duration_seconds` is the number of simulated seconds until the target is reached.
    """

    duration_seconds: int
    soc_per_second: list[float]


def simulate_charging_soc_trace_simpy(
    *,
    bus: Bus,
    charger_offered_power_kw: float,
    start_soc_percent: float = 10.0,
    target_soc_percent: float = 100.0,
    dt_seconds: int = 1,
    max_seconds: int = 48 * 3600,
) -> ChargingTrace:
    """
    Simulate charging with SimPy from start SoC to target SoC.
    """
    if dt_seconds <= 0:
        raise ValueError("dt_seconds must be > 0")
    if max_seconds <= 0:
        raise ValueError("max_seconds must be > 0")

    try:
        import simpy  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("simpy is required for this simulation. Install `simpy`.") from e

    bus.soc_percent = float(start_soc_percent)
    target = float(target_soc_percent)

    env = simpy.Environment()
    soc_trace: list[float] = [float(bus.soc_percent)]

    def charging_process():
        elapsed = 0
        while bus.soc_percent < target and elapsed < max_seconds:
            p_kw = bus.calculate_actual_charging_power_kw(float(charger_offered_power_kw))
            delta_kwh = p_kw * (dt_seconds / 3600.0)
            bus.update_soc(delta_kwh)

            yield env.timeout(dt_seconds)
            elapsed += dt_seconds
            soc_trace.append(float(bus.soc_percent))

            # Defensive: break if no progress (avoids infinite loops).
            if len(soc_trace) >= 3 and soc_trace[-1] <= soc_trace[-2] <= soc_trace[-3]:
                if p_kw <= 0.0:
                    break

    env.process(charging_process())
    env.run(until=max_seconds)

    # env.now may exceed the actual time to reach target if target is reached early;
    # compute duration based on trace length.
    duration = (len(soc_trace) - 1) * dt_seconds
    return ChargingTrace(duration_seconds=int(duration), soc_per_second=soc_trace)

