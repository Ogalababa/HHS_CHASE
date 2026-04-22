# -*- coding: utf-8 -*-
# /models/transport/journey.py
"""
Journey = vehicle journey (one JourneyId) consisting of a sequence
of PointInSequence points from the planning parquet.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

from .point_in_sequence import PointInSequence


class Journey:
    """Represents a vehicle journey consisting of a sequence of points."""

    def __init__(
        self,
        journey_id: str,
        journey_ref: str,
        journey_type: str,
        vehicle_type: str,
        public_line_number: str,
        version_type: str,
        transport_mode: str | None = None,
        direction_type: str | None = None,
        internal_line_number: str | None = None,
        block_id: str | None = None,
    ):
        """
        Initialize a journey with identification, scheduling and vehicle details.

        Parameters
        ----------
        journey_id:
            Maps to `JourneyId` (int32) in planning parquet.
        journey_ref:
            Maps to `JourneyRef`.
        journey_type:
            Maps to `JourneyType`.
        vehicle_type:
            Maps to `VehicleType`.
        public_line_number:
            Maps to `PublicLineNumber`.
        version_type:
            Maps to `VersionType`.
        transport_mode:
            Maps to `TransportMode` (optional).
        direction_type:
            Maps to `DirectionType` (optional).
        internal_line_number:
            Maps to `InternalLineNumber` (optional).
        block_id:
            Optional reference to `BlockId` this journey belongs to.
        """
        self.journey_id = str(journey_id)
        self.journey_ref = journey_ref
        self.journey_type = journey_type
        self.vehicle_type = vehicle_type
        self.public_line_number = str(public_line_number)
        self.version_type = version_type
        self.transport_mode = transport_mode
        self.direction_type = direction_type
        self.internal_line_number = internal_line_number
        self.block_id = block_id
        
        # Extract original journey_id (without date suffix) for display purposes
        # Format: "original_id_YYYY-MM-DD" -> "original_id"
        journey_id_str = str(journey_id)
        if "_" in journey_id_str:
            parts = journey_id_str.rsplit("_", 1)
            if len(parts) == 2 and len(parts[1]) == 10:  # Date part is 10 chars (YYYY-MM-DD)
                try:
                    # Verify it's a valid date format
                    from datetime import datetime
                    datetime.strptime(parts[1], "%Y-%m-%d")
                    self.original_journey_id = parts[0]
                except ValueError:
                    self.original_journey_id = journey_id_str
            else:
                self.original_journey_id = journey_id_str
        else:
            self.original_journey_id = journey_id_str

        self.points: List[PointInSequence] = []

        # --- Simulation Results ---
        self.sim_start_time: Optional[datetime] = None
        self.sim_end_time: Optional[datetime] = None

    def __repr__(self) -> str:
        """Return a detailed string representation of the journey object."""
        return (
            "id = {}, ref = {}, type = {}, public_line = {}, "
            "vehicle_type = {}, n_points = {}".format(
                self.journey_id,
                self.journey_ref,
                self.journey_type,
                self.public_line_number,
                self.vehicle_type,
                len(self.points),
            )
        )

    # ----- Convenience properties -----

    @property
    def start_point(self) -> PointInSequence | None:
        """Return the first point based on sequence order."""
        return self.points[0] if self.points else None

    @property
    def end_point(self) -> PointInSequence | None:
        """Return the final point based on sequence order."""
        return self.points[-1] if self.points else None

    @property
    def last_arrival_datetime(self) -> datetime | None:
        """Return the arrival time at the final point."""
        return self.end_point.arrival_datetime if self.end_point else None

    @property
    def first_departure_datetime(self) -> datetime | None:
        """Return the departure time at the first point."""
        return self.start_point.departure_datetime if self.start_point else None

    @property
    def duration(self) -> timedelta:
        """Return the total journey duration as a timedelta object."""
        if not (self.start_point and self.end_point):
            return timedelta(0)
        return self.end_point.arrival_datetime - self.start_point.departure_datetime

    @property
    def duration_seconds(self) -> float:
        """Return the total journey duration in seconds."""
        return self.duration.total_seconds()

    @property
    def duration_minutes(self) -> float:
        """Return the total journey duration in minutes."""
        return self.duration.total_seconds() / 60

    @property
    def duration_hours(self) -> float:
        """Return the total journey duration in hours."""
        return self.duration.total_seconds() / 3600

    @property
    def duration_str(self) -> str:
        """Return the total journey duration as 'HH:MM:SS' string."""
        total_seconds = int(self.duration.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    @property
    def point_count(self) -> int:
        """Return the total number of points in the journey."""
        return len(self.points)

    @property
    def total_distance_km(self) -> float:
        """Return the total distance of the journey in kilometers."""
        return sum(p.distance_km for p in self.points)

    @property
    def charging_points(self) -> list[PointInSequence]:
        """
        Return a list of points where charging is available.

        (is_charging_location is not in planning parquet; you will likely set it
        from infrastructure data.)
        """
        return [p for p in self.points if p.is_charging_location]

    @property
    def wait_points(self) -> list[PointInSequence]:
        """Return a list of waiting points (IsWaitPoint = True)."""
        return [p for p in self.points if p.is_wait_point]

    # ----- Mutators -----

    def add_point(self, point: PointInSequence) -> None:
        """Add a point to the journey."""
        self.points.append(point)

    def sort_points(self) -> None:
        """Sort the points in the journey by their sequence order."""
        self.points.sort(key=lambda p: p.sequence_order)
