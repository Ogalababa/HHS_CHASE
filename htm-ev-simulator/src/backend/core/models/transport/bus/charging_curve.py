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


class ChargingCurve:
    """
    Vehicle charging power acceptance envelope (P_cap) as a function of SoC.

    The current implementation preserves the existing piecewise-linear envelope
    that was previously implemented on `Bus`.

    Rationale: A small, dependency-free class is sufficient here. We avoid
    introducing configuration frameworks or infrastructure concerns into the
    domain. If the curve needs calibration later, this class can be extended to
    accept parameters or be replaced via a port.
    """

    @staticmethod
    def clamp_soc_percent(value: float) -> float:
        """Clamp SoC to [0, 100] for envelope calculation."""
        if value < 0.0:
            return 0.0
        if value > 100.0:
            return 100.0
        return float(value)

    @classmethod
    def power_cap_kw(cls, soc_percent: float) -> float:
        """
        Charging power acceptance limit (P_cap(SoC)) in kW.

        Piecewise envelope (SoC in %):
        - Stage A: 0 <= SoC < 87:  P_cap = 250 + 0.368 * SoC
        - Stage B: 87 <= SoC < 97: P_cap = 282 - 5.2 * (SoC - 87)
        - Stage C: 97 <= SoC <= 100: P_cap = 230 * (100 - SoC) / 3
        """
        soc = cls.clamp_soc_percent(float(soc_percent))

        if soc < 87.0:
            return 250.0 + (0.368 * soc)
        if soc < 97.0:
            return 282.0 - 5.2 * (soc - 87.0)
        # 97% - 100% tail-off to zero
        if soc <= 100.0:
            return 230.0 * (100.0 - soc) / 3.0
        return 0.0

    @classmethod
    def actual_battery_power_kw(
        cls, *, soc_percent: float, charger_offered_power_kw: float, charging_loss_kw: float = 4.0
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
        p_cap = cls.power_cap_kw(soc_percent)
        return min(p_available, p_cap)

