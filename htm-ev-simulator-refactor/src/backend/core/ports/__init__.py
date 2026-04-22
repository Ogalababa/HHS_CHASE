"""
Core ports (interfaces / contracts).

Rationale: Ports define the only way core logic talks to the outside world.
Keeping them in `core` prevents infrastructure concerns from creeping into
domain logic while still allowing adapters to implement these interfaces.
"""

from __future__ import annotations

from .bus_port import BusProviderPort
from .infra_port import InfrastructureProviderPort
from .planning_port import PlanningProviderPort

__all__ = [
    "PlanningProviderPort",
    "InfrastructureProviderPort",
    "BusProviderPort",
]

