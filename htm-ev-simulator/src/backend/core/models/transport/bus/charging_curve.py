"""
Charging curve / acceptance envelope for vehicles.

This module provides a pure-domain representation of the vehicle-side charging
power acceptance limit as a function of SoC.

Rationale: The charging envelope is a cross-cutting physical rule that should
not be embedded in the `Bus` entity itself. Extracting it into an isolated
domain module improves testability, reuse (other vehicle models), and makes it
explicit which assumptions drive the simulation results, while keeping the
domain layer free of external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChargingCurve:
    """
    Vehicle charging power acceptance envelope (P_cap) as a function of SoC.

    Default parameters preserve the existing piecewise-linear envelope that was
    previously implemented on `Bus`, with the default stage thresholds:
    - **Stage A end**: 87%
    - **Stage B end**: 97%

    Rationale: Making the curve parameterizable keeps the physical assumptions
    explicit and calibratable without changing the `Bus` entity. This aligns
    with hexagonal architecture by keeping core domain logic deterministic and
    free of infrastructure dependencies.
    """

    # --- Default envelope parameters (match previous behavior) ---
    stage_a_end_soc: float = 87.0
    stage_b_end_soc: float = 97.0

    # Stage A: P = a_base + a_slope * SoC
    a_base_kw: float = 250.0
    a_slope_kw_per_soc: float = 0.368

    # Stage B: P = b_start_kw - b_slope * (SoC - stage_a_end_soc)
    b_start_kw: float = 282.0
    b_slope_kw_per_soc: float = 5.2

    # Stage C tail: P = c_factor_kw * (100 - SoC) / c_divisor_soc
    c_factor_kw: float = 230.0
    c_divisor_soc: float = 3.0

    @staticmethod
    def clamp_soc_percent(value: float) -> float:
        """Clamp SoC to [0, 100] for envelope calculation."""
        if value < 0.0:
            return 0.0
        if value > 100.0:
            return 100.0
        return float(value)

    def power_cap_kw(self, soc_percent: float) -> float:
        """
        Charging power acceptance limit (P_cap(SoC)) in kW.

        Piecewise envelope (SoC in %):
        - Stage A: 0 <= SoC < stage_a_end_soc:  P_cap = a_base_kw + a_slope_kw_per_soc * SoC
        - Stage B: stage_a_end_soc <= SoC < stage_b_end_soc:
                   P_cap = b_start_kw - b_slope_kw_per_soc * (SoC - stage_a_end_soc)
        - Stage C: stage_b_end_soc <= SoC <= 100:
                   P_cap = c_factor_kw * (100 - SoC) / c_divisor_soc
        """
        soc = self.clamp_soc_percent(float(soc_percent))

        if soc < self.stage_a_end_soc:
            return self.a_base_kw + (self.a_slope_kw_per_soc * soc)
        if soc < self.stage_b_end_soc:
            return self.b_start_kw - self.b_slope_kw_per_soc * (soc - self.stage_a_end_soc)
        # Tail-off to zero
        if soc <= 100.0:
            return self.c_factor_kw * (100.0 - soc) / float(self.c_divisor_soc)
        return 0.0

    def actual_battery_power_kw(
        self, *, soc_percent: float, charger_offered_power_kw: float, charging_loss_kw: float = 4.0
    ) -> float:
        """
        Compute actual charging power into the battery (kW).

        Core model (wooden-barrel principle):
            P_actual = min(P_charger - P_loss, P_cap(SoC))

        Rationale: The simulation needs a single, deterministic place to compute
        battery-side power. By locating it here, we keep `Bus` focused on state
        and invariants, while the physical acceptance model remains reusable.
        """
        offered = max(0.0, float(charger_offered_power_kw))
        loss = max(0.0, float(charging_loss_kw))
        p_available = max(0.0, offered - loss)
        p_cap = self.power_cap_kw(soc_percent)
        return min(p_available, p_cap)


DEFAULT_CHARGING_CURVE = ChargingCurve()


