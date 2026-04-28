#!/usr/bin/env python3
"""
Inspect planning parquet in ADLS and check journey/block origin records.

What this script validates:
1) Journey-level origin record exists (minimum PointInSequenceOrder row).
2) Origin key fields are present (point id/name, departure time).
3) Block-level first journey has an origin record.

Typical usage (from htm-ev-simulator root):
    python scripts/check_planning_origin_records.py --start-date 2026-02-02 --end-date 2026-02-04
    python scripts/check_planning_origin_records.py --start-date 2026-02-02 --end-date 2026-02-02 --base-path planning/bus --max-samples 20

Environment:
- DATALAKE_STORAGE_ACCOUNT
- DATALAKE_FILESYSTEM
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from src.backend.infrastructure.datalake_helper import DataLakeConfig, load_parquet_range


@dataclass(slots=True)
class OriginIssue:
    level: str  # journey | block
    operating_day: str
    block_id: str
    journey_id: str | None
    reason: str
    point_id: str | None = None
    point_name: str | None = None
    point_order: Any = None
    departure_time: Any = None


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date: {value!r}, expected YYYY-MM-DD") from exc


def _ensure_required_columns(df: pd.DataFrame) -> None:
    required = {
        "OperatingDay",
        "BlockId",
        "JourneyId",
        "PointInSequenceId",
        "PointInSequenceName",
        "PointInSequenceOrder",
        "DepartureTime",
    }
    missing = sorted(required - set(df.columns))
    if missing:
        raise RuntimeError(f"Planning parquet missing required columns: {missing}")


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except Exception:
        return False


def analyze_origins(df: pd.DataFrame) -> tuple[dict[str, Any], list[OriginIssue]]:
    _ensure_required_columns(df)

    rows = df.copy()
    if pd.api.types.is_datetime64_any_dtype(rows["OperatingDay"]):
        rows["OperatingDay"] = rows["OperatingDay"].dt.date

    # Stable sorting ensures deterministic "first point" selection.
    rows = rows.sort_values(["OperatingDay", "BlockId", "JourneyId", "PointInSequenceOrder"])

    issues: list[OriginIssue] = []

    grouped = rows.groupby(["OperatingDay", "BlockId", "JourneyId"], sort=False)
    total_journeys = 0
    journeys_with_origin = 0

    journey_origin_index: dict[tuple[date, str], list[tuple[str, Any]]] = {}

    for (op_day, block_id, journey_id), g in grouped:
        total_journeys += 1
        first = g.iloc[0] if len(g.index) > 0 else None
        if first is None:
            issues.append(
                OriginIssue(
                    level="journey",
                    operating_day=str(op_day),
                    block_id=_to_str(block_id),
                    journey_id=_to_str(journey_id),
                    reason="journey has no rows",
                )
            )
            continue

        point_id = first.get("PointInSequenceId")
        point_name = first.get("PointInSequenceName")
        point_order = first.get("PointInSequenceOrder")
        departure_time = first.get("DepartureTime")

        missing_fields: list[str] = []
        if _is_missing(point_id):
            missing_fields.append("PointInSequenceId")
        if _is_missing(point_name):
            missing_fields.append("PointInSequenceName")
        if _is_missing(point_order):
            missing_fields.append("PointInSequenceOrder")
        if _is_missing(departure_time):
            missing_fields.append("DepartureTime")

        if missing_fields:
            issues.append(
                OriginIssue(
                    level="journey",
                    operating_day=str(op_day),
                    block_id=_to_str(block_id),
                    journey_id=_to_str(journey_id),
                    reason=f"origin row has missing fields: {', '.join(missing_fields)}",
                    point_id=None if _is_missing(point_id) else _to_str(point_id),
                    point_name=None if _is_missing(point_name) else _to_str(point_name),
                    point_order=point_order,
                    departure_time=departure_time,
                )
            )
        else:
            journeys_with_origin += 1

        key = (op_day, _to_str(block_id))
        journey_origin_index.setdefault(key, []).append((_to_str(journey_id), point_order))

    # Block-level: verify a block has at least one journey and first journey has an origin.
    total_blocks = 0
    blocks_with_origin = 0
    for (op_day, block_id), journey_items in sorted(journey_origin_index.items(), key=lambda x: (x[0][0], x[0][1])):
        total_blocks += 1
        if not journey_items:
            issues.append(
                OriginIssue(
                    level="block",
                    operating_day=str(op_day),
                    block_id=_to_str(block_id),
                    journey_id=None,
                    reason="block has no journey rows",
                )
            )
            continue
        # sort by journey id then point order as fallback
        journey_items_sorted = sorted(journey_items, key=lambda it: (it[0], it[1]))
        first_journey_id = journey_items_sorted[0][0]
        # If journey had missing fields, it is already in journey issues; we still flag block summary.
        has_journey_issue = any(
            i.level == "journey"
            and i.operating_day == str(op_day)
            and i.block_id == _to_str(block_id)
            and i.journey_id == first_journey_id
            for i in issues
        )
        if has_journey_issue:
            issues.append(
                OriginIssue(
                    level="block",
                    operating_day=str(op_day),
                    block_id=_to_str(block_id),
                    journey_id=first_journey_id,
                    reason="first journey origin record incomplete",
                )
            )
        else:
            blocks_with_origin += 1

    summary = {
        "rows": len(rows.index),
        "journeys_total": total_journeys,
        "journeys_with_valid_origin": journeys_with_origin,
        "journeys_missing_or_invalid_origin": total_journeys - journeys_with_origin,
        "blocks_total": total_blocks,
        "blocks_with_valid_first_origin": blocks_with_origin,
        "blocks_missing_or_invalid_first_origin": total_blocks - blocks_with_origin,
    }
    return summary, issues


def main() -> None:
    parser = argparse.ArgumentParser(description="Check planning origin records from ADLS parquet.")
    parser.add_argument("--start-date", type=_parse_date, required=True, help="YYYY-MM-DD")
    parser.add_argument("--end-date", type=_parse_date, required=True, help="YYYY-MM-DD")
    parser.add_argument("--base-path", default="planning/bus", help="Parquet base path in ADLS")
    parser.add_argument("--max-samples", type=int, default=15, help="How many issues to print")
    args = parser.parse_args()

    if args.end_date < args.start_date:
        raise SystemExit("--end-date must be >= --start-date")

    cfg = DataLakeConfig()
    print(f"[INFO] ADLS account={cfg.storage_account}, filesystem={cfg.filesystem}")
    print(f"[INFO] Loading planning parquet from {args.base_path} between {args.start_date} and {args.end_date}")
    df = load_parquet_range(
        start=args.start_date,
        end=args.end_date,
        base_path=args.base_path,
        config=cfg,
    )

    summary, issues = analyze_origins(df)
    print("\n=== Origin Record Summary ===")
    for k, v in summary.items():
        print(f"- {k}: {v}")

    if not issues:
        print("\n[OK] No missing/incomplete origin records found.")
        return

    print(f"\n[WARN] Found {len(issues)} issues. Showing up to {max(0, args.max_samples)} samples:")
    for i, issue in enumerate(issues[: max(0, args.max_samples)], start=1):
        print(
            f"{i:02d}. [{issue.level}] day={issue.operating_day} block={issue.block_id} "
            f"journey={issue.journey_id or '-'} reason={issue.reason} "
            f"point_id={issue.point_id or '-'} point_name={issue.point_name or '-'} "
            f"order={issue.point_order} departure={issue.departure_time}"
        )


if __name__ == "__main__":
    main()

