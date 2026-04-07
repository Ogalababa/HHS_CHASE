# /models/transport/block.py
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from .journey import Journey


class Block:
    """Represents a scheduled block containing one or more sequential journeys."""

    def __init__(self, block_id: str, operating_day: date):
        """
        Initialize a block with its unique identifier and operating day.

        Args:
            block_id: The unique identifier for the block (may include date suffix for multi-day simulations).
            operating_day: The operating day of the block.
        """
        self.block_id = block_id
        self.operating_day = operating_day
        self.journeys: list[Journey] = []
        
        # Extract original block_id (without date suffix) for display purposes
        # Format: "original_id_YYYY-MM-DD" -> "original_id"
        if "_" in block_id and block_id.count("_") >= 3:  # At least one underscore in original + date
            # Try to extract original ID by removing date suffix
            # Date format is YYYY-MM-DD (10 characters + 1 underscore = 11 chars from end)
            parts = block_id.rsplit("_", 1)
            if len(parts) == 2 and len(parts[1]) == 10:  # Date part is 10 chars (YYYY-MM-DD)
                try:
                    # Verify it's a valid date format
                    from datetime import datetime
                    datetime.strptime(parts[1], "%Y-%m-%d")
                    self.original_block_id = parts[0]
                except ValueError:
                    self.original_block_id = block_id
            else:
                self.original_block_id = block_id
        else:
            self.original_block_id = block_id

        # --- Simulation Results ---
        self.assigned_bus_vehicle_number: Optional[int] = None
        self.sim_start_time: Optional[datetime] = None
        self.sim_end_time: Optional[datetime] = None

    def __repr__(self):
        """
        Returns a developer-friendly string representation of the Block.

        Returns:
            A string representation of the Block.
        """
        return (
            f"Block(id={self.block_id}, day={self.operating_day}, "
            f"n_journeys={self.journey_count})"
        )

    @property
    def journey_count(self) -> int:
        """
        Gets the number of journeys in the block.

        Returns:
            The number of journeys.
        """
        return len(self.journeys)

    @property
    def total_distance_km(self) -> float:
        """
        Calculates the total distance of all journeys in the block.

        Returns:
            The total distance in kilometers.
        """
        return sum(j.total_distance_km for j in self.journeys)

    def add_journey(self, journey: Journey):
        """
        Adds a journey to the block.

        Args:
            journey: The Journey object to add.
        """
        self.journeys.append(journey)

    def sort_journeys(self):
        """
        Sorts the journeys in the block by their first departure time.
        This method also sorts the points within each journey.
        """
        for j in self.journeys:
            if j.points:
                j.sort_points()

        self.journeys.sort(key=lambda j: j.points[0].departure_datetime)
