"""
Charging-infrastructure provider adapter (JSON -> domain models).

This adapter reads `processed_laadpalen_data.json` (connector-level records) and
builds a domain object graph:
- Location (physical place) with point_id link to planning
- Grid (LVI) objects
- Charger objects containing Connector objects

Rationale: JSON parsing and file IO are infrastructure concerns. Mapping raw
connector records into domain entities is an adapter responsibility so that
core services (WorldBuilder/Engine) can work with pure domain models.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..core.models.laad_infra.charger import Charger
from ..core.models.laad_infra.connector import Connector
from ..core.models.laad_infra.grid import Grid
from ..core.models.laad_infra.location import Location
from ..core.ports.infra_port import InfrastructureProviderPort

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover (Python < 3.9)
    ZoneInfo = None  # type: ignore[assignment]


class InfraJsonAdapterError(RuntimeError):
    """Raised when connector JSON cannot be mapped into domain infrastructure."""


def _parse_kw(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    s = str(value).strip().lower()
    if s.endswith("kw"):
        s = s[:-2].strip()
    try:
        return max(0.0, float(s))
    except ValueError:
        return 0.0


@dataclass(slots=True)
class ConnectorJsonInfrastructureProvider(InfrastructureProviderPort):
    """
    Provide grids and locations by reading connector-level JSON records.
    """

    json_path: Path
    power_limits_path: Optional[Path] = None

    def get_grids(self) -> list[Grid]:
        grids, _locations, _links = self._build()
        return list(grids.values())

    def get_locations(self) -> list[Location]:
        _grids, locations, _links = self._build()
        return list(locations.values())

    def get_location_grid_links(self) -> list[tuple[str, str]]:
        _grids, _locations, links = self._build()
        return links

    def _build(self) -> tuple[dict[str, Grid], dict[str, Location], list[tuple[str, str]]]:
        raw = self._read_json()

        grids_by_id: dict[str, Grid] = {}
        locations_by_id: dict[str, Location] = {}
        links: list[tuple[str, str]] = []

        # Index chargers by (location_id, charger_id)
        chargers_by_key: dict[tuple[str, str], Charger] = {}

        for rec in raw:
            location_name = str(rec.get("Location") or "").strip()
            if not location_name:
                raise InfraJsonAdapterError("Record missing Location.")

            point_id = rec.get("Point_Id")
            point_id_str: Optional[str] = None
            if point_id is not None:
                point_id_str = str(point_id)

            lat = rec.get("Latitude")
            lon = rec.get("Longitude")
            latitude = float(lat) if lat is not None else 0.0
            longitude = float(lon) if lon is not None else 0.0

            # Location id: stable, human-readable; can be replaced later by a true id.
            location_id = location_name
            loc = locations_by_id.get(location_id)
            if loc is None:
                loc = Location(
                    location_id=location_id,
                    latitude=latitude,
                    longitude=longitude,
                    point_id=point_id_str,
                )
                locations_by_id[location_id] = loc

            # Grid (LVI) is used as grid_id (may be null for some records)
            grid_id_raw = rec.get("LaagSpanningsVerdeelInstallatie")
            if grid_id_raw is not None and str(grid_id_raw).lower() != "null":
                grid_id = str(grid_id_raw).strip()
                if grid_id:
                    grid = grids_by_id.get(grid_id)
                    if grid is None:
                        grid = Grid(grid_id=grid_id, name=grid_id)
                        grids_by_id[grid_id] = grid
                    links.append((loc.location_id, grid.grid_id))

            charger_id = str(rec.get("Laadpaal") or "").strip()
            if not charger_id:
                raise InfraJsonAdapterError(f"Record missing Laadpaal (charger id): {rec}")

            charger_key = (loc.location_id, charger_id)
            charger = chargers_by_key.get(charger_key)
            if charger is None:
                charger = Charger(
                    charger_id=charger_id,
                    serial_number=_null_to_none(rec.get("Serienummer")),
                    software_version=_null_to_none(rec.get("Software")),
                )
                chargers_by_key[charger_key] = charger
                loc.chargers[charger_id] = charger

            connector = Connector(
                connector_id=str(rec.get("uniqueConnId") or "").strip() or f"{charger_id}-unknown",
                max_power_kw=_parse_kw(rec.get("MaxPower")),
                connector_type=str(rec.get("LaderType") or "").strip() or "unknown",
                raster_code=_null_to_none(rec.get("RasterCode")),
                connection_name=_null_to_none(rec.get("Connection_Name")),
            )
            charger.add_connector(connector)

        # De-duplicate links while preserving order
        seen: set[tuple[str, str]] = set()
        deduped_links: list[tuple[str, str]] = []
        for link in links:
            if link not in seen:
                seen.add(link)
                deduped_links.append(link)

        # Apply optional grid power limits (location-scoped configuration).
        if self.power_limits_path is not None:
            self._apply_power_limits(
                grids_by_id=grids_by_id,
                locations_by_id=locations_by_id,
                links=deduped_links,
            )

        return grids_by_id, locations_by_id, deduped_links

    def _apply_power_limits(
        self,
        *,
        grids_by_id: dict[str, Grid],
        locations_by_id: dict[str, Location],
        links: list[tuple[str, str]],
    ) -> None:
        cfg = self._read_power_limits()
        location_cfg: dict[str, dict] = {}
        for entry in cfg.get("location_power_limits", []):
            if isinstance(entry, dict) and entry.get("location_id"):
                location_cfg[str(entry["location_id"])] = entry

        for location_id, entry in location_cfg.items():
            # Only apply to grids linked to this location
            grid_ids = [gid for (lid, gid) in links if lid == location_id]
            if not grid_ids:
                continue

            if entry.get("time_window_type") != "daily":
                raise InfraJsonAdapterError(f"Unsupported time_window_type: {entry.get('time_window_type')}")

            tzname = str(entry.get("timezone") or "Europe/Amsterdam")
            limits = entry.get("limits")
            if not isinstance(limits, list):
                raise InfraJsonAdapterError(f"Invalid limits for location {location_id}")

            profile = _build_daily_power_profile(limits=limits, tzname=tzname)
            location = locations_by_id.get(location_id)
            if location is not None:
                # Also bind profile on location level to avoid relying solely on
                # optional grid linkage during simulation.
                location.max_power_profile = profile
            for gid in grid_ids:
                grid = grids_by_id.get(gid)
                if grid is not None:
                    grid.available_power_profile = profile

    def _read_power_limits(self) -> dict:
        if self.power_limits_path is None:
            return {}
        if not self.power_limits_path.exists():
            raise InfraJsonAdapterError(f"Power limits JSON not found: {self.power_limits_path}")
        data = json.loads(self.power_limits_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise InfraJsonAdapterError("Expected power limits JSON object.")
        return data

    def _read_json(self) -> list[dict]:
        if not self.json_path.exists():
            raise InfraJsonAdapterError(f"JSON file not found: {self.json_path}")
        data = json.loads(self.json_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise InfraJsonAdapterError("Expected top-level JSON array.")
        # Ensure all items are dict-like
        out: list[dict] = []
        for item in data:
            if isinstance(item, dict):
                out.append(item)
            else:
                raise InfraJsonAdapterError(f"Expected object items, got: {type(item)}")
        return out


def _null_to_none(value: object) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() == "null":
        return None
    return s


def _parse_hhmm(value: object) -> int:
    """
    Parse "HH:MM" into minutes since midnight. Allows "24:00" as 1440.
    """
    s = str(value).strip()
    if s == "24:00":
        return 24 * 60
    parts = s.split(":")
    if len(parts) != 2:
        raise InfraJsonAdapterError(f"Invalid time format: {value!r}")
    h = int(parts[0])
    m = int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise InfraJsonAdapterError(f"Invalid time: {value!r}")
    return h * 60 + m


def _build_daily_power_profile(*, limits: list[dict], tzname: str):
    """
    Build a callable(datetime)->float for a daily schedule.
    """
    if ZoneInfo is None:  # pragma: no cover
        raise InfraJsonAdapterError("zoneinfo not available; requires Python 3.9+")

    tz = ZoneInfo(tzname)
    windows: list[tuple[int, int, float]] = []
    for w in limits:
        if not isinstance(w, dict):
            continue
        start = _parse_hhmm(w.get("start"))
        end = _parse_hhmm(w.get("end"))
        p = w.get("max_power_kw")
        try:
            power = float(p)
        except (TypeError, ValueError):
            raise InfraJsonAdapterError(f"Invalid max_power_kw: {p!r}")
        windows.append((start, end, power))

    def profile(dt: datetime) -> float:
        if dt.tzinfo is None:
            local = dt.replace(tzinfo=tz)
        else:
            local = dt.astimezone(tz)
        minute = local.hour * 60 + local.minute

        for start, end, power in windows:
            if start <= minute < end:
                return power
        # If schedule doesn't cover a time, treat as unlimited.
        return float("inf")

    return profile

