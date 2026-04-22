"""
Defines the Charger (Laadpaal) domain model.

Rationale: The simulation needs a domain representation of a charger that is
free of infrastructure dependencies (databases, APIs). A charger aggregates one
or more connectors (laadkappen) and provides a clear domain boundary for
reasoning about device limits vs. per-connector setpoints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .connector import Connector


@dataclass(slots=True)
class Charger:
    """
    Represents a physical charging station (Laadpaal), which can have multiple connectors.

    Rationale: Connectors carry the "one bus per plug" occupancy state, while
    the charger represents the shared power budget across connectors. Keeping
    this aggregation in the domain layer allows the simulation engine to apply
    policies without embedding assumptions in adapters.
    """

    charger_id: str
    serial_number: Optional[str] = None
    software_version: Optional[str] = None
    connectors: list[Connector] = field(default_factory=list)

    # Physical max power across all connectors (can be overridden by adapter data)
    max_power_kw: float = 0.0

    def __post_init__(self) -> None:
        self.max_power_kw = max(0.0, float(self.max_power_kw))

    def add_connector(self, connector: Connector) -> None:
        """
        Add a connector to this charger.

        Rationale: Adapters often build the charger from multiple rows. We keep
        an imperative helper to make world-building straightforward while
        preserving a consistent max-power interpretation.
        """
        self.connectors.append(connector)

        # Conservative default: ensure charger max power is at least the sum of
        # connector device limits. This avoids accidental under-capacity when
        # adapter data omits charger-level limits.
        summed = sum(c.max_power_kw for c in self.connectors)
        if summed > self.max_power_kw:
            self.max_power_kw = float(summed)

    @property
    def current_load_kw(self) -> float:
        """Current total power being drawn from all connectors."""
        return float(sum(c.current_power_kw for c in self.connectors))

    @property
    def available_power_kw(self) -> float:
        """Remaining power capacity of the charger (device-side)."""
        return max(0.0, float(self.max_power_kw) - self.current_load_kw)

