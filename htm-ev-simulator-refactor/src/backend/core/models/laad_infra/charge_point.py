# -*- coding: utf-8 -*-
# /models/transport/charge_point.py
from __future__ import annotations

from ..transport.bus import Bus, BusState


class ChargePoint:
    """Represents a single charging point for a bus."""

    def __init__(self, id: int):
        """
        Initializes a new ChargePoint instance.

        Args:
            id: The unique identifier for the charge point.
        """
        self.id = id
        self.connected_bus: Bus | None = None

    def connect(self, bus: Bus):
        """
        Connects a bus to the charge point.

        Args:
            bus: The Bus object to connect.

        Raises:
            ValueError: If the charge point is already occupied.
        """
        if self.connected_bus is not None:
            raise ValueError("Charge point already occupied")

        self.connected_bus = bus
        bus.connected_charge_point = self

        # set bus state
        if bus.soc_percent >= 100:
            bus.state = BusState.AVAILABLE
        else:
            bus.state = BusState.CHARGING

    def disconnect(self):
        """
        Disconnects the currently connected bus from the charge point.
        """
        if self.connected_bus:
            self.connected_bus.connected_charge_point = None
            if self.connected_bus.state == BusState.CHARGING:
                self.connected_bus.state = BusState.AVAILABLE
        self.connected_bus = None
