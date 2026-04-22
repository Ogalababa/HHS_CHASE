"""
Charging curve / acceptance envelope for vehicles.

This module provides a pure-domain representation of the vehicle-side charging
power acceptance limit as a function of SoC.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChargingCurve:
    """
    Vehicle charging power acceptance envelope (P_cap) as a function of SoC.

    Vehicle charging power acceptance envelope (P_cap) as a function of SoC.

    Default parameters are derived from the Daimler NMC3 5-HVBB simulation (300kW Panto):
    - **Stage A**: Linear increase until ~87% SoC, reaching max power of 282 kW.
    - **Stage B**: Power reduction from 87% to 97% SoC.
    - **Stage C**: Rapid tail-off to zero at 100% SoC.
    """

    # --- Default envelope parameters based on simulation data ---
    stage_a_end_soc: float = 87.0
    stage_b_end_soc: float = 97.0

    # Stage A: P = a_base + a_slope * SoC (Approx. 282 kW at 87% SoC)
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
        Charging power acceptance limit of the battery (P_cap(SoC)) in kW.
        At 100% SoC, this always returns 0.0.
        """
        soc = self.clamp_soc_percent(float(soc_percent))

        if soc < self.stage_a_end_soc:
            return self.a_base_kw + (self.a_slope_kw_per_soc * soc)
        
        if soc < self.stage_b_end_soc:
            return self.b_start_kw - self.b_slope_kw_per_soc * (soc - self.stage_a_end_soc)
        
        if soc < 100.0:
            return self.c_factor_kw * (100.0 - soc) / float(self.c_divisor_soc)
            
        return 0.0

    def actual_battery_power_kw(
        self, 
        *, 
        soc_percent: float, 
        charger_offered_power_kw: float, 
        aux_load_kw: float = 2.0, 
        transmission_loss_kw: float = 2.0
    ) -> float:
        """
        Compute actual charging power into the battery (kW).

        Logic:
        1. The charger must first cover the auxiliary loads (2kW per documentation) 
           and any transmission losses.
        2. The remaining power is available for the battery, but limited by the 
           battery's acceptance envelope (power_cap_kw).
        3. At 100% SoC, power_cap_kw is 0, so this returns 0.
        """
        offered = max(0.0, float(charger_offered_power_kw))
        
        # Power consumed by vehicle systems and losses before reaching the battery
        overhead = max(0.0, float(aux_load_kw) + float(transmission_loss_kw))
        
        # Power available from the charger after overhead
        p_available = max(0.0, offered - overhead)
        
        # Battery acceptance limit at current SoC
        p_cap = self.power_cap_kw(soc_percent)
        
        # The battery only takes what it can accept and what the charger can provide
        return min(p_available, p_cap)


DEFAULT_CHARGING_CURVE = ChargingCurve()


