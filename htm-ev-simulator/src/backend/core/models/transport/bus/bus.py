# -*- coding: utf-8 -*-
# /models/transport/bus.py

"""
Electric bus domain model.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional, TYPE_CHECKING

from .charging_curve import DEFAULT_CHARGING_CURVE, ChargingCurve

# Use TYPE_CHECKING to avoid circular import for type hinting
if TYPE_CHECKING:
    from ...planning.block import Block
    from ...planning.point_in_sequence import PointInSequence
    from ...laad_infra.charge_point import ChargePoint


class BusState(str, Enum):
    """Represents the operational state of a bus."""

    AVAILABLE = "AVAILABLE"
    RUNNING = "RUNNING"
    CHARGING = "CHARGING"
    MAINTENANCE = "MAINTENANCE"


class Bus:
    """
    Electric bus model with battery, SOC and range logic.

    Attributes:
        vehicle_number (int): The unique identifier for the vehicle.
        vin_number (str): The Vehicle Identification Number.

        vehicle_type (str): The type of vehicle.
        state (BusState): The current operational state of the bus.
        battery_capacity_kwh (float): The total capacity of the battery in kilowatt-hours.
        energy_consumption_per_km (float): The energy consumption rate in kilowatt-hours per kilometer.
        soc_percent (float): The current state of charge of the battery as a percentage.
        total_driven_distance_km (float): The total distance driven by the bus in kilometers.
        assigned_blocks (List[Block]): A list of blocks assigned to this bus.
        average_energy_consumption (Optional[float]): The average energy consumption in kWh/km.
        location (Optional[PointInSequence]): The current location of the bus (the point it is at or last visited).
        connected_charge_point (Optional[ChargePoint]): The charge point currently connected to this bus (if any).
    """

    def __init__(
        self,
        vehicle_number: int,
        vin_number: str,
        vehicle_type: str,
        state: BusState,
        energy_consumption_per_km: float,
        soc_percent: float,
        battery_capacity_kwh: Optional[float] = None,
        mom_charge_energy: Optional[float] = None,
        mom_discharge_energy: Optional[float] = None,
        soc_disp_cval: Optional[float] = None,
        average_energy_consumption: Optional[float] = None,
        charging_loss_kw: float = 4.0,
        charging_curve: ChargingCurve | None = None,
        max_charging_power_kw: float | None = 282.0,
    ):
        """
        Initializes a new Bus instance.

        Args:
            vehicle_number (int): The unique identifier for the vehicle.
            vin_number (str): The Vehicle Identification Number.
            vehicle_type (str): The type of vehicle.
            state (BusState): The current operational state of the bus.
            energy_consumption_per_km (float): The energy consumption rate in kilowatt-hours per kilometer.
            soc_percent (float): The initial state of charge of the battery as a percentage.
            battery_capacity_kwh (Optional[float]): The total capacity of the battery in kilowatt-hours.
                                                    If provided, this value is used directly.
            mom_charge_energy (Optional[float]): Momentary charge energy from API.
            mom_discharge_energy (Optional[float]): Momentary discharge energy from API.
            soc_disp_cval (Optional[float]): SOC display value from API.
                                              Used with mom_discharge_energy to calculate capacity.
            average_energy_consumption (Optional[float]): The average energy consumption in kWh/km from API.

        Raises:
            ValueError: If battery capacity cannot be determined from the provided arguments.
        """
        self.vehicle_number = vehicle_number
        self.vin_number = vin_number

        self.vehicle_type = vehicle_type

        # ✅ private backing fields
        self._state = state
        self._soc_percent = soc_percent

        self.energy_consumption_per_km = energy_consumption_per_km
        self.average_energy_consumption = average_energy_consumption

        # Determine battery_capacity_kwh
        if battery_capacity_kwh is not None:
            self.battery_capacity_kwh = battery_capacity_kwh
        elif mom_charge_energy is not None and mom_discharge_energy is not None:
            self.battery_capacity_kwh = mom_charge_energy + mom_discharge_energy
        elif (
            mom_discharge_energy is not None
            and soc_disp_cval is not None
            and soc_disp_cval > 0
        ):
            # Assuming soc_disp_cval is a percentage (0-100)
            self.battery_capacity_kwh = mom_discharge_energy / (soc_disp_cval / 100.0)
        else:
            raise ValueError(
                "Battery capacity (battery_capacity_kwh) could not be determined. "
                "Provide either battery_capacity_kwh directly, "
                "or mom_charge_energy and mom_discharge_energy, "
                "or mom_discharge_energy and soc_disp_cval."
            )

        self.total_driven_distance_km = 0.0
        self.assigned_blocks: List["Block"] = []  # Use string literal for type hinting
        self.location: Optional["PointInSequence"] = None  # Current location of the bus
        self.connected_charge_point: Optional["ChargePoint"] = None  # Currently connected charge point (if any)
        # Charging characteristics (dynamic charging envelope)
        self.charging_loss_kw = max(0.0, float(charging_loss_kw))
        self.charging_curve: ChargingCurve = charging_curve or DEFAULT_CHARGING_CURVE
        self.max_charging_power_kw: float | None = (
            None if max_charging_power_kw is None else max(0.0, float(max_charging_power_kw))
        )

    def __repr__(self) -> str:
        """Returns a developer-friendly string representation of the Bus."""
        return (
            f"Bus(vehicle_number={self.vehicle_number}, "
            f"vin_number='{self.vin_number}', "
            f"type='{self.vehicle_type}', "
            f"state={self.state.value}, "
            f"soc={self.soc_percent:.1f}%, "
            f"battery_capacity={self.battery_capacity_kwh:.1f}kWh, "
            f"consumption={self.energy_consumption_per_km:.2f}kWh/km, "
            f"range={self.remaining_range_km():.1f}km)"
        )

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    @property
    def state(self) -> BusState:
        """
        Gets the current state of the bus.
        """
        return self._state

    @state.setter
    def state(self, new_state: BusState):
        """
        Sets the state of the bus.
        Args:
            new_state (BusState): The new state to set for the bus.
        """
        self._state = new_state

    # ------------------------------------------------------------------
    # SOC
    # ------------------------------------------------------------------
    @property
    def soc_percent(self) -> float:
        """
        Gets the current SOC percentage of the bus battery.
        """
        return self._soc_percent

    @soc_percent.setter
    def soc_percent(self, value: float):
        """
        Sets the SOC percentage of the bus, ensuring it's within valid bounds.
        Args:
            value (float): The new SOC percentage to set. Must be between 0 and 100.
        """
        if not 0.0 <= value <= 100.0:
            raise ValueError("SOC must be between 0 and 100")
        self._soc_percent = value

    # ------------------------------------------------------------------
    # Energy
    # ------------------------------------------------------------------
    @property
    def current_energy_kwh(self) -> float:
        """
        Calculates the current energy in the battery in kWh.
        """
        return (self._soc_percent / 100.0) * self.battery_capacity_kwh

    def update_soc(self, delta_kwh: float):
        """
        Apply energy delta (positive = charging, negative = discharging).

        Args:
            delta_kwh (float): The change in energy in kWh.
        """
        if delta_kwh == 0:
            # No change in energy

            return

        new_energy = self.current_energy_kwh + delta_kwh
        new_energy = max(0.0, min(new_energy, self.battery_capacity_kwh))

        if self.battery_capacity_kwh == 0:
            self._soc_percent = 0.0
            return

        # Calculate SOC
        calculated_soc = (new_energy / self.battery_capacity_kwh) * 100.0
        
        # FIX: If energy is at or very close to battery capacity (within 0.01 kWh), set SOC to exactly 100%
        # This handles floating point precision issues where energy might be 384.99... instead of exactly 385.0
        if new_energy >= self.battery_capacity_kwh - 0.01:
            self._soc_percent = 100.0
        else:
            self._soc_percent = calculated_soc

    # ------------------------------------------------------------------
    # Driving logic
    # ------------------------------------------------------------------
    def remaining_range_km(self) -> float:
        if self.energy_consumption_per_km <= 0:
            # Avoid division by zero
            return 0.0
        return self.current_energy_kwh / self.energy_consumption_per_km

    def has_low_soc(self, threshold_percent: float) -> bool:
        """
        Checks if the current SOC is below a specified threshold.

        Args:
            threshold_percent (float): The SOC percentage threshold to check against.

        """
        return self._soc_percent <= threshold_percent

    # ------------------------------------------------------------------
    # Charging envelope / dynamic charging power
    # ------------------------------------------------------------------
    @staticmethod
    def _clamp_soc_percent(value: float) -> float:
        """Clamp SOC to [0, 100] for envelope calculation."""
        return ChargingCurve.clamp_soc_percent(value)

    @classmethod
    def charging_power_cap_kw(cls, soc_percent: float) -> float:
        """
        Vehicle charging power acceptance limit P_cap(SoC) in kW.

        Piecewise envelope (SoC in %):
        - Stage A: 0 <= SoC < 87:  P_cap = 250 + 0.368 * SoC
        - Stage B: 87 <= SoC < 97: P_cap = 282 - 5.2 * (SoC - 87)
        - Stage C: 97 <= SoC <= 100: P_cap = 230 * (100 - SoC) / 3
        """
        return DEFAULT_CHARGING_CURVE.power_cap_kw(soc_percent)

    def calculate_actual_charging_power_kw(self, charger_offered_power_kw: float) -> float:
        """
        Calculate actual charging power into the battery (kW), given charger offered power.

        Core model (wooden-barrel principle):
            P_actual(SoC, P_charger) = min(P_charger - P_loss, P_cap(SoC))

        Notes:
        - SoC is the bus SOC in percent (0..100).
        - P_loss is modeled as a constant auxiliary + conversion loss (default 4kW).
        - Result is clamped to >= 0.
        """
        p_actual = self.charging_curve.actual_battery_power_kw(
            soc_percent=self.soc_percent,
            charger_offered_power_kw=charger_offered_power_kw,
            charging_loss_kw=self.charging_loss_kw,
        )
        if self.max_charging_power_kw is not None:
            return min(float(p_actual), float(self.max_charging_power_kw))
        return float(p_actual)
