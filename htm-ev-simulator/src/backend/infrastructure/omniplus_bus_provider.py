"""
OMNIplus ON bus provider adapter.

Rationale: This adapter implements the core `BusProviderPort` using the
OMNIplus ON HTTP API. It lives in the infrastructure layer because it depends
on external protocols (`requests`) and environment configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..core.models.transport.bus.bus import Bus, BusState
from ..core.ports.bus_port import BusProviderPort
from .omniplus_on.client import OmniplusOnClient


@dataclass(slots=True)
class OmniplusBusProvider(BusProviderPort):
    """
    Provide buses by fetching latest OMNIplus ON signals and mapping them to `Bus`.

    Rationale: The core wants domain entities; this adapter performs mapping
    from vendor-specific signal names/ids to domain constructor arguments.
    """

    client: OmniplusOnClient
    vins: list[str]
    vin_to_vehicle_number: Optional[dict[str, int]] = None

    def get_buses(self) -> list[Bus]:
        raw_by_vin = self.client.get_latest_signals(self.vins)
        buses: list[Bus] = []

        for idx, vin in enumerate(self.vins, start=1):
            raw = raw_by_vin.get(vin, {"vin": vin})
            vehicle_number = idx
            if self.vin_to_vehicle_number:
                vehicle_number = int(self.vin_to_vehicle_number.get(str(vin), idx))

            # These keys must match your SIGNAL_ID_TO_NAME mapping.
            soc_disp_cval = _to_float(raw.get("SOCdispCval"))
            mom_charge_energy = _to_float(raw.get("MomChargeEnergy"))
            mom_discharge_energy = _to_float(raw.get("MomDischargeEnergy"))
            avg_cons = _to_float(raw.get("AverageEnergyConsumption"))

            # Domain Bus requires either explicit capacity or enough fields to infer it.
            bus = Bus(
                vehicle_number=vehicle_number,
                vin_number=str(vin),
                vehicle_type=str(raw.get("VehicleType", "E-BUS")),
                state=BusState.AVAILABLE,
                energy_consumption_per_km=float(avg_cons) if avg_cons is not None else 1.0,
                soc_percent=float(soc_disp_cval) if soc_disp_cval is not None else 50.0,
                mom_charge_energy=mom_charge_energy,
                mom_discharge_energy=mom_discharge_energy,
                soc_disp_cval=soc_disp_cval,
                average_energy_consumption=avg_cons,
            )
            buses.append(bus)

        return buses


def _to_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

