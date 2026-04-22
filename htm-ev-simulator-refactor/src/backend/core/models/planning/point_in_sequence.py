# -*- coding: utf-8 -*-
# /models/planning/point_in_sequence.py
"""
PointInSequence = one row in planning parquet:
- PointInSequenceId
- PointInSequenceName
- PointInSequenceOrder
- ArrivalTime / DepartureTime (+ OperatingDay)
- DistanceToNextPointInSequence
- IsWaitPoint
- etc.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Optional




class PointInSequence:
    """Represents a point (stop) within a journey sequence."""

    def __init__(
        self,
        point_id: int | str,
        name: str,
        sequence_order: int,
        latitude: float,
        longitude: float,
        distance_to_next_m: Optional[float],
        arrival_datetime: datetime,
        departure_datetime: datetime,
        wait_time: timedelta,
        is_wait_point: bool,
        stop_area: Optional[int] = None,
        tariff_zone: Optional[int] = None,
    ):
        """
        Initialize a point with location, timing and operational details.
        """
        self.point_id = str(point_id)
        self.name = name
        self.sequence_order = int(sequence_order)
        self.latitude = float(latitude)
        self.longitude = float(longitude)
        self.distance_to_next_m = distance_to_next_m
        self.arrival_datetime = arrival_datetime
        self.departure_datetime = departure_datetime
        self.wait_time = wait_time
        self.is_wait_point = is_wait_point
        self.stop_area = stop_area
        self.tariff_zone = tariff_zone

        # --- Linked Objects ---
        self.charging_location: Optional["Location"] = None

        # --- Simulation Results ---
        self.sim_bus_state_at_arrival: Optional["BusState"] = None
        self.sim_soc_at_arrival: Optional[float] = None
        self.sim_range_at_arrival: Optional[float] = None
        self.sim_bus_state_at_departure: Optional["BusState"] = None
        self.sim_soc_at_departure: Optional[float] = None
        self.sim_range_at_departure: Optional[float] = None

    @property
    def is_charging_location(self) -> bool:
        """Returns True if this point is linked to a charging location."""
        return self.charging_location is not None

    def __repr__(self) -> str:
        """Return a detailed string representation of the point object."""
        return (
            f"Point(id={self.point_id}, name='{self.name}', order={self.sequence_order}, "
            f"charging={self.is_charging_location})"
        )

    # ... (other properties remain the same)
    @property
    def gps(self) -> tuple[float, float]:
        return self.latitude, self.longitude

    @property
    def dwell_time(self) -> timedelta:
        if self.arrival_datetime and self.departure_datetime:
            return self.departure_datetime - self.arrival_datetime
        return timedelta(0)

    @property
    def total_stop_time(self) -> timedelta:
        return self.dwell_time + self.wait_time

    @property
    def distance_km(self) -> float:
        if self.distance_to_next_m is None or math.isnan(self.distance_to_next_m):
            return 0.0
        return self.distance_to_next_m / 1000.0
