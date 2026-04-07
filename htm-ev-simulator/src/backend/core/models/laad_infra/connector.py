"""
Defines the Connector (Laadkap) domain model.

Rationale: A connector is the smallest allocatable charging resource: it can be
occupied by at most one bus at a time, has a device-side power limit, and
exposes the offered-vs-actual power distinction needed to combine charger-side
setpoints with vehicle-side acceptance curves. Keeping it in the domain layer
ensures simulation logic stays independent from how infrastructure data is
loaded (Excel/DB) or exposed (API/UI).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from .exceptions import ConnectorOccupiedError

if TYPE_CHECKING:
    from ..transport.bus.bus import Bus


@dataclass(slots=True)
class Connector:
    """
    Represents a single charging connector (Laadkap).
    """

    connector_id: str
    max_power_kw: float
    connector_type: str
    raster_code: Optional[str] = None
    connection_name: Optional[str] = None

    # Dynamic state
    connected_bus: Optional["Bus"] = field(default=None, repr=False)
    # Offered/setpoint power from charger side (kW). The bus may accept less due
    # to its own charging envelope.
    offered_power_kw: float = 0.0
    # Actual power used for charging the battery (kW, net into battery).
    current_power_kw: float = 0.0

    def __post_init__(self) -> None:
        # Normalize numeric fields defensively (adapters may pass strings).
        if self.max_power_kw is None:
            self.max_power_kw = 0.0
        elif isinstance(self.max_power_kw, str):
            try:
                self.max_power_kw = float(self.max_power_kw.lower().replace("kw", ""))
            except (ValueError, AttributeError):
                self.max_power_kw = 0.0
        else:
            self.max_power_kw = float(self.max_power_kw)
        self.max_power_kw = max(0.0, self.max_power_kw)

        self.offered_power_kw = max(0.0, float(self.offered_power_kw))
        self.current_power_kw = max(0.0, float(self.current_power_kw))

    @property
    def is_available(self) -> bool:
        return self.connected_bus is None

    def connect_bus(self, bus: "Bus") -> None:
        """
        Connect a bus to this connector.

        Rationale: The connector is responsible only for occupancy state. Power
        scheduling and charging physics are handled by domain services.
        """
        if not self.is_available:
            occupied_by = (
                getattr(self.connected_bus, "vehicle_number", None) if self.connected_bus else None
            )
            raise ConnectorOccupiedError(
                f"Connector {self.connector_id} is already occupied"
                + (f" by bus {occupied_by}." if occupied_by is not None else ".")
            )

        self.connected_bus = bus

    def disconnect_bus(self) -> None:
        """
        Disconnect the current bus from this connector and reset dynamic power state.
        """
        self.connected_bus = None
        self.offered_power_kw = 0.0
        self.current_power_kw = 0.0

