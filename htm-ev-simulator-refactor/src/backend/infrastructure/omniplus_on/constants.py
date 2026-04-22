"""
OMNIplus ON signal constants.

Rationale: Signal IDs and their semantic names are infrastructure concerns: they
are defined by an external API. Keeping them in the infrastructure layer avoids
leaking vendor-specific details into the domain/core.
"""

from __future__ import annotations

SIGNAL_ID_TO_NAME: dict[int, str] = {
    256: "RemainingVehRange",
    261: "AverageEnergyConsumption",
    264: "MomChargeEnergy",
    265: "MomDischargeEnergy",
    271: "BatPow",
    4157: "SOCdispCval",
}

# Default list of signal IDs to request.
SIGNAL_IDS_DEFAULT: list[int] = list(SIGNAL_ID_TO_NAME.keys())

