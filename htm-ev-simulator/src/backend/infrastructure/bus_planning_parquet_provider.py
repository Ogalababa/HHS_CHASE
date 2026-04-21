"""
Bus planning provider adapter (ADLS parquet -> domain planning models).

Rationale: Reading parquet via pandas and Azure SDKs is infrastructure. This
adapter implements the core `PlanningProviderPort` by translating stop-level
planning rows into domain entities (`Block`, `Journey`, `PointInSequence`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

import pandas as pd

from ..core.models.planning.block import Block
from ..core.models.planning.journey import Journey
from ..core.models.planning.point_in_sequence import PointInSequence
from ..core.ports.planning_port import PlanningProviderPort
from .datalake_helper import DataLakeConfig, load_parquet_range


class PlanningAdapterError(RuntimeError):
    """Raised when planning data cannot be mapped into domain models."""


@dataclass(slots=True)
class BusPlanningParquetProvider(PlanningProviderPort):
    """
    Load stop-level planning parquet and build Blocks/Journeys/Points.
    """

    start_date: date
    end_date: date
    base_path: str = "planning/bus"
    datalake: Optional[DataLakeConfig] = None
    columns: Optional[Iterable[str]] = None
    simulation_start: Optional[datetime] = None
    simulation_end: Optional[datetime] = None

    def get_blocks(self) -> list[Block]:
        df = load_parquet_range(
            start=self.start_date,
            end=self.end_date,
            base_path=self.base_path,
            config=self.datalake,
        )

        if self.columns is not None:
            df = _restrict_columns(df, self.columns)

        blocks = _df_to_blocks(df)
        if self.simulation_start is not None and self.simulation_end is not None:
            blocks = _filter_blocks_by_window(
                blocks,
                window_start=self.simulation_start,
                window_end=self.simulation_end,
            )
        return blocks


def _restrict_columns(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    cols = list(columns)
    missing = set(cols) - set(df.columns)
    if missing:
        raise PlanningAdapterError(f"Missing requested columns: {sorted(missing)}")
    return df[cols].copy()


def _require_columns(df: pd.DataFrame, required: Iterable[str]) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise PlanningAdapterError(f"Planning parquet missing required columns: {missing}")


def _parse_dt(operating_day: date, time_like: object) -> datetime:
    """
    Parse a parquet time column into a datetime.

    Accepts:
    - datetime already
    - ISO string ("HH:MM:SS" or full ISO datetime)
    """
    if isinstance(time_like, datetime):
        return time_like
    if time_like is None or (isinstance(time_like, float) and pd.isna(time_like)):
        # Default to start of operating day if missing.
        return datetime.combine(operating_day, datetime.min.time())

    s = str(time_like)
    try:
        # Full ISO
        dt = datetime.fromisoformat(s)
        return dt
    except ValueError:
        pass

    # Time-of-day
    try:
        t = datetime.strptime(s, "%H:%M:%S").time()
        return datetime.combine(operating_day, t)
    except ValueError as e:
        raise PlanningAdapterError(f"Cannot parse datetime/time value: {time_like!r}") from e


def _df_to_blocks(df: pd.DataFrame) -> list[Block]:
    required = [
        "BlockId",
        "OperatingDay",
        "JourneyId",
        "JourneyRef",
        "JourneyType",
        "VehicleType",
        "PublicLineNumber",
        "VersionType",
        "PointInSequenceId",
        "PointInSequenceName",
        "PointInSequenceOrder",
        "ArrivalTime",
        "DepartureTime",
        "DistanceToNextPointInSequence",
        "IsWaitPoint",
    ]
    _require_columns(df, required)

    # Normalize OperatingDay to python date
    op_day_series = df["OperatingDay"]
    if pd.api.types.is_datetime64_any_dtype(op_day_series):
        df = df.copy()
        df["OperatingDay"] = op_day_series.dt.date

    blocks: dict[tuple[str, date], Block] = {}
    journeys: dict[tuple[str, str, date], Journey] = {}

    # Stable ordering: block -> journey -> point order
    df_sorted = df.sort_values(["OperatingDay", "BlockId", "JourneyId", "PointInSequenceOrder"])

    for _, row in df_sorted.iterrows():
        operating_day = row["OperatingDay"]
        if not isinstance(operating_day, date):
            raise PlanningAdapterError(f"OperatingDay must be date, got {type(operating_day)}")

        block_id = str(row["BlockId"])
        block_key = (block_id, operating_day)
        block = blocks.get(block_key)
        if block is None:
            # Encode multi-day uniqueness by suffixing the day (keeps your display logic working)
            block_unique_id = f"{block_id}_{operating_day.isoformat()}"
            block = Block(block_id=block_unique_id, operating_day=operating_day)
            blocks[block_key] = block

        journey_id = str(row["JourneyId"])
        journey_key = (block.block_id, journey_id, operating_day)
        journey = journeys.get(journey_key)
        if journey is None:
            journey_unique_id = f"{journey_id}_{operating_day.isoformat()}"
            journey = Journey(
                journey_id=journey_unique_id,
                journey_ref=str(row["JourneyRef"]),
                journey_type=str(row["JourneyType"]),
                vehicle_type=str(row["VehicleType"]),
                public_line_number=str(row["PublicLineNumber"]),
                version_type=str(row["VersionType"]),
                block_id=block.block_id,
            )
            journeys[journey_key] = journey
            block.add_journey(journey)

        point = PointInSequence(
            point_id=row["PointInSequenceId"],
            name=str(row["PointInSequenceName"]),
            sequence_order=int(row["PointInSequenceOrder"]),
            latitude=float(row.get("Latitude", 0.0) or 0.0),
            longitude=float(row.get("Longitude", 0.0) or 0.0),
            distance_to_next_m=None
            if pd.isna(row["DistanceToNextPointInSequence"])
            else float(row["DistanceToNextPointInSequence"]),
            arrival_datetime=_parse_dt(operating_day, row["ArrivalTime"]),
            departure_datetime=_parse_dt(operating_day, row["DepartureTime"]),
            wait_time=timedelta(0),
            is_wait_point=bool(row["IsWaitPoint"]),
        )
        journey.add_point(point)

    # Sort points inside each journey for safety
    for j in journeys.values():
        j.sort_points()

    # Return blocks sorted by (day, id) for deterministic behavior
    return [b for (_, _), b in sorted(blocks.items(), key=lambda kv: (kv[0][1], kv[0][0]))]


def _filter_blocks_by_window(
    blocks: list[Block],
    *,
    window_start: datetime,
    window_end: datetime,
) -> list[Block]:
    """
    Keep only journeys overlapping with simulation window.

    Rationale: ADLS parquet is loaded per date partition; we must further filter
    by configured simulation time (including cross-day windows) before running
    the simulation to avoid irrelevant early/late journeys.
    """
    if window_end <= window_start:
        return []
    filtered_blocks: list[Block] = []
    for block in blocks:
        keep_journeys: list[Journey] = []
        for journey in block.journeys:
            j_start = journey.first_departure_datetime
            j_end = journey.last_arrival_datetime
            if j_start is None or j_end is None:
                continue
            # Keep only journeys that START within configured simulation window.
            # Rationale: for visualization simulation we should not include
            # pre-start journeys that only overlap the boundary; they create
            # empty rows (not simulated) in detailed reports.
            if j_start < window_start or j_start >= window_end:
                continue
            keep_journeys.append(journey)
        if keep_journeys:
            block.journeys = keep_journeys
            block.sort_journeys()
            filtered_blocks.append(block)
    return filtered_blocks

