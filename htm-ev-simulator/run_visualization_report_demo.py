from __future__ import annotations

"""
Generate a frontend visualization report from a backend simulation.

Rationale: This runner supports both stub data and real infrastructure adapters
(planning parquet, Maximo assets, OMNIplus bus signals). Keeping this orchestration
in an application script allows repeatable report generation while preserving
hexagonal boundaries: adapters fetch data, core services simulate, frontend
module only renders.
"""

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional


def _ensure_src_on_path() -> None:
    src = Path(__file__).resolve().parent / "src"
    sys.path.insert(0, str(src))


_ensure_src_on_path()

from backend.core.models.planning.block import Block
from backend.core.models.planning.journey import Journey
from backend.core.models.planning.point_in_sequence import PointInSequence
from backend.core.models.transport.bus import Bus, BusState
from backend.core.ports.bus_port import BusProviderPort
from backend.core.ports.planning_port import PlanningProviderPort
from backend.core.services.visualization_simulation import VisualizationSimulationService
from backend.core.services.world_builder import WorldBuilder
from backend.infrastructure.bus_planning_parquet_provider import BusPlanningParquetProvider
from backend.infrastructure.connector_json_infra_provider import ConnectorJsonInfrastructureProvider
from backend.infrastructure.datalake_helper import DataLakeConfig
from backend.infrastructure.env_loader import get_env
from backend.infrastructure.maximo_asset_provider import MaximoAssetProvider, MaximoAssetQuery
from backend.infrastructure.omniplus_bus_provider import OmniplusBusProvider
from backend.infrastructure.omniplus_on.client import OmniplusAuthConfig, OmniplusOnClient
from frontend.visualization.dynamic_report_generator import generate_dynamic_report


def _stage(message: str) -> None:
    """Print structured stage logs for web status page parsing."""
    safe_message = message.encode("ascii", errors="backslashreplace").decode("ascii")
    print(f"[STAGE] {safe_message}", flush=True)


@dataclass(slots=True)
class DemoSimulationConfig:
    """Minimal config shape consumed by frontend statistics generator."""

    sim_date: date
    sim_start_time: time
    sim_duration_hours: int
    extra_report_params: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class StubBusProvider(BusProviderPort):
    n_buses: int = 4

    def get_buses(self) -> list[Bus]:
        buses: list[Bus] = []
        for i in range(1, self.n_buses + 1):
            buses.append(
                Bus(
                    vehicle_number=1400 + i,
                    vin_number=f"VIN-{1400 + i}",
                    vehicle_type="E-BUS",
                    state=BusState.AVAILABLE,
                    energy_consumption_per_km=1.25,
                    soc_percent=45.0 + i * 5,
                    battery_capacity_kwh=352.8,
                )
            )
        return buses


@dataclass(slots=True)
class StubPlanningProvider(PlanningProviderPort):
    point_ids: list[str]
    operating_day: date = date(2026, 2, 2)

    def get_blocks(self) -> list[Block]:
        blocks: list[Block] = []
        base_dt = datetime.combine(self.operating_day, time(hour=6, minute=0))

        if not self.point_ids:
            return blocks

        for block_index in range(3):
            block_id = f"BLOCK_{block_index + 1}_{self.operating_day.isoformat()}"
            block = Block(block_id=block_id, operating_day=self.operating_day)
            for journey_index in range(2):
                journey_start = base_dt + timedelta(hours=block_index * 2 + journey_index)
                journey = Journey(
                    journey_id=f"{1000000 + block_index * 10 + journey_index}_{self.operating_day.isoformat()}",
                    journey_ref=f"JR-{block_index + 1}-{journey_index + 1}",
                    journey_type="SERVICE",
                    vehicle_type="E-BUS",
                    public_line_number=str(10 + block_index),
                    version_type="A",
                    block_id=block.block_id,
                )
                for point_offset in range(4):
                    pid = self.point_ids[(block_index + journey_index + point_offset) % len(self.point_ids)]
                    arrival = journey_start + timedelta(minutes=point_offset * 12)
                    departure = arrival + timedelta(minutes=2)
                    journey.add_point(
                        PointInSequence(
                            point_id=pid,
                            name=f"Stop {pid}",
                            sequence_order=point_offset + 1,
                            latitude=52.07 + 0.005 * point_offset,
                            longitude=4.29 + 0.004 * point_offset,
                            distance_to_next_m=3200.0 if point_offset < 3 else 0.0,
                            arrival_datetime=arrival,
                            departure_datetime=departure,
                            wait_time=timedelta(minutes=2),
                            is_wait_point=point_offset == 3,
                        )
                    )
                block.add_journey(journey)
            blocks.append(block)

        return blocks


@dataclass(slots=True)
class MaximoBusProvider(BusProviderPort):
    """
    Build domain buses from Maximo assets.

    Rationale: This is a lightweight adapter composition used by the application
    runner. It keeps Maximo IO in infrastructure (`MaximoAssetProvider`) and
    performs only mapping to domain entities.
    """

    assets_provider: MaximoAssetProvider
    query: MaximoAssetQuery
    default_soc_percent: float = 65.0
    default_capacity_kwh: float = 352.8
    default_consumption_kwh_per_km: float = 1.25

    def get_buses(self) -> list[Bus]:
        assets = self.assets_provider.load_bus_assets(query=self.query)
        buses: list[Bus] = []
        for _, row in assets.iterrows():
            vehicle_number = int(row["assetnum"])
            vin = str(row["htm_vendor_serialnum"])
            max_power = row.get("max_charging_power_kw")
            max_power_kw = float(max_power) if max_power is not None else 282.0
            buses.append(
                Bus(
                    vehicle_number=vehicle_number,
                    vin_number=vin,
                    vehicle_type=str(row.get("htm_tramtype", "E-BUS")),
                    state=BusState.AVAILABLE,
                    energy_consumption_per_km=self.default_consumption_kwh_per_km,
                    soc_percent=self.default_soc_percent,
                    battery_capacity_kwh=self.default_capacity_kwh,
                    max_charging_power_kw=max_power_kw,
                )
            )
        return buses


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate configurable visualization simulation report.")
    parser.add_argument("--sim-date", default="2026-02-02", help="Simulation date in YYYY-MM-DD.")
    parser.add_argument("--sim-start", default="06:00", help="Simulation start time in HH:MM.")
    parser.add_argument("--sim-hours", type=int, default=12, help="Simulation horizon in hours.")

    parser.add_argument("--use-real-planning", action="store_true", help="Load planning via ADLS parquet adapter.")
    parser.add_argument("--use-real-buses", choices=["stub", "maximo", "omniplus"], default="stub")
    parser.add_argument(
        "--simulate-all-vehicles",
        action="store_true",
        help="Use all available vehicles for selected provider where possible.",
    )
    parser.add_argument("--fallback-to-stub", action="store_true", help="Fallback to stub providers on adapter errors.")

    parser.add_argument("--planning-base-path", default="planning/bus", help="ADLS base path for planning parquet.")
    parser.add_argument("--assetnum-min", type=int, default=1400, help="Min asset number (exclusive) for Maximo bus query.")
    parser.add_argument("--assetnum-max", type=int, default=1600, help="Max asset number (exclusive) for Maximo bus query.")
    parser.add_argument(
        "--omniplus-vins",
        default="",
        help="Comma-separated VIN list for OMNIplus provider (required when --use-real-buses=omniplus).",
    )

    parser.add_argument("--stub-bus-count", type=int, default=4, help="Bus count for stub provider.")
    parser.add_argument("--low-soc-threshold", type=float, default=14.0, help="Low SOC threshold for warning events.")
    parser.add_argument("--charge-target-soc", type=float, default=85.0, help="Target SOC for charging sessions.")
    parser.add_argument("--charge-step-seconds", type=int, default=300, help="Charging simulation step in seconds.")
    parser.add_argument(
        "--enable-precheck-replacement-strategy",
        action="store_true",
        help="Before each journey, precheck SOC and trigger 8xxxxxx return + 9xxxxxx replacement dispatch when insufficient.",
    )
    parser.add_argument(
        "--enable-opportunity-charging-strategy",
        action="store_true",
        help="Enable opportunity charging when terminal has charger, SOC<80%%, and layover exceeds 30 minutes.",
    )
    parser.add_argument(
        "--enable-start-full-soc-strategy",
        action="store_true",
        help="Set all buses SOC to 100%% at simulation start.",
    )

    parser.add_argument(
        "--report-path",
        default="outputs/combined_visualization_report.html",
        help="Output HTML report path.",
    )
    parser.add_argument("--map-path", default="outputs/replay_map.html", help="Output map HTML path.")
    return parser


def _load_omniplus_client_from_env() -> OmniplusOnClient:
    client_id = os.getenv("CLIENT_ID") or get_env("CLIENT_ID")
    client_secret = os.getenv("CLIENT_SECRET") or get_env("CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("Missing CLIENT_ID/CLIENT_SECRET for OMNIplus provider.")
    config = OmniplusAuthConfig(client_id=client_id, client_secret=client_secret)
    return OmniplusOnClient(config=config)


def _build_planning_provider(
    *,
    use_real: bool,
    sim_date: date,
    sim_start_time: time,
    sim_hours: int,
    planning_base_path: str,
    point_ids: list[str],
) -> PlanningProviderPort:
    if not use_real:
        return StubPlanningProvider(point_ids=point_ids, operating_day=sim_date)

    sim_start_dt = datetime.combine(sim_date, sim_start_time)
    sim_end_dt = sim_start_dt + timedelta(hours=sim_hours)
    end_date = sim_date + timedelta(days=max(0, int(sim_hours / 24)))
    return BusPlanningParquetProvider(
        start_date=sim_date,
        end_date=end_date,
        base_path=planning_base_path,
        datalake=DataLakeConfig(),
        simulation_start=sim_start_dt,
        simulation_end=sim_end_dt,
    )


def _build_bus_provider(
    *,
    mode: str,
    stub_bus_count: int,
    assetnum_min: int,
    assetnum_max: int,
    omniplus_vins: list[str],
    simulate_all_vehicles: bool,
) -> BusProviderPort:
    if mode == "stub":
        return StubBusProvider(n_buses=stub_bus_count)
    if mode == "maximo":
        _stage("Fetching Maximo vehicle data")
        return MaximoBusProvider(
            assets_provider=MaximoAssetProvider(datalake=DataLakeConfig()),
            query=MaximoAssetQuery(assetnum_min=assetnum_min, assetnum_max=assetnum_max),
        )
    if mode == "omniplus":
        _stage("Fetching Maximo mapping data (wagon nr <-> VIN)")
        maximo_assets = MaximoAssetProvider(datalake=DataLakeConfig()).load_bus_assets(
            query=MaximoAssetQuery(assetnum_min=assetnum_min, assetnum_max=assetnum_max)
        )
        vin_to_vehicle_number = {
            str(row["htm_vendor_serialnum"]): int(row["assetnum"])
            for _, row in maximo_assets.iterrows()
        }
        if not omniplus_vins and simulate_all_vehicles:
            omniplus_vins = list(vin_to_vehicle_number.keys())
        if not omniplus_vins:
            raise RuntimeError("--omniplus-vins is required when --use-real-buses=omniplus and all-vehicles is off.")
        client = _load_omniplus_client_from_env()
        _stage("Fetching OMNIplus ON realtime bus data")
        return OmniplusBusProvider(
            client=client,
            vins=omniplus_vins,
            vin_to_vehicle_number=vin_to_vehicle_number,
        )
    raise RuntimeError(f"Unsupported bus provider mode: {mode}")


def _safe_build_provider_pair(
    *,
    use_real_planning: bool,
    use_real_buses: str,
    fallback_to_stub: bool,
    sim_date: date,
    sim_start_time: time,
    sim_hours: int,
    planning_base_path: str,
    point_ids: list[str],
    stub_bus_count: int,
    assetnum_min: int,
    assetnum_max: int,
    omniplus_vins: list[str],
    simulate_all_vehicles: bool,
) -> tuple[PlanningProviderPort, BusProviderPort]:
    try:
        planning_provider = _build_planning_provider(
            use_real=use_real_planning,
            sim_date=sim_date,
            sim_start_time=sim_start_time,
            sim_hours=sim_hours,
            planning_base_path=planning_base_path,
            point_ids=point_ids,
        )
        bus_provider = _build_bus_provider(
            mode=use_real_buses,
            stub_bus_count=stub_bus_count,
            assetnum_min=assetnum_min,
            assetnum_max=assetnum_max,
            omniplus_vins=omniplus_vins,
            simulate_all_vehicles=simulate_all_vehicles,
        )
        return planning_provider, bus_provider
    except Exception as exc:
        if not fallback_to_stub:
            raise
        print(f"[WARN] Real adapter setup failed, falling back to stubs: {exc}")
        return (
            StubPlanningProvider(point_ids=point_ids, operating_day=sim_date),
            StubBusProvider(n_buses=stub_bus_count),
        )


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    sim_date = datetime.strptime(args.sim_date, "%Y-%m-%d").date()
    sim_start_time = datetime.strptime(args.sim_start, "%H:%M").time()
    omniplus_vins = [v.strip() for v in args.omniplus_vins.split(",") if v.strip()]

    project_root = Path(__file__).resolve().parent
    json_path = project_root / "src" / "backend" / "infrastructure" / "data" / "processed_laadpalen_data.json"
    power_limits_path = project_root / "src" / "backend" / "infrastructure" / "data" / "grid_power_limits.json"

    infra = ConnectorJsonInfrastructureProvider(json_path=json_path, power_limits_path=power_limits_path)
    point_ids = sorted({str(loc.point_id) for loc in infra.get_locations() if loc.point_id})
    _stage("Building data providers")

    planning_provider, bus_provider = _safe_build_provider_pair(
        use_real_planning=args.use_real_planning,
        use_real_buses=args.use_real_buses,
        fallback_to_stub=args.fallback_to_stub,
        sim_date=sim_date,
        sim_start_time=sim_start_time,
        sim_hours=args.sim_hours,
        planning_base_path=args.planning_base_path,
        point_ids=point_ids,
        stub_bus_count=args.stub_bus_count,
        assetnum_min=args.assetnum_min,
        assetnum_max=args.assetnum_max,
        omniplus_vins=omniplus_vins,
        simulate_all_vehicles=args.simulate_all_vehicles,
    )

    _stage("Building world model")
    world_builder = WorldBuilder(
        planning=planning_provider,
        infrastructure=infra,
        buses=bus_provider,
    )
    world = world_builder.build().world

    _stage("Running simulation")
    sim_start_dt = datetime.combine(sim_date, sim_start_time)
    sim_end_dt = sim_start_dt + timedelta(hours=args.sim_hours)
    simulation_service = VisualizationSimulationService(
        low_soc_alert_threshold_percent=args.low_soc_threshold,
        charging_target_soc_percent=args.charge_target_soc,
        charging_step_seconds=args.charge_step_seconds,
        enable_precheck_replacement_strategy=args.enable_precheck_replacement_strategy,
        enable_opportunity_charging_strategy=args.enable_opportunity_charging_strategy,
        enable_start_full_soc_strategy=args.enable_start_full_soc_strategy,
        simulation_start_timestamp=sim_start_dt.timestamp(),
        simulation_end_timestamp=sim_end_dt.timestamp(),
    )
    simulation = simulation_service.run(world)
    config = DemoSimulationConfig(
        sim_date=sim_date,
        sim_start_time=sim_start_time,
        sim_duration_hours=args.sim_hours,
    )

    report_path = (project_root / args.report_path).resolve()
    map_path = (project_root / args.map_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    map_path.parent.mkdir(parents=True, exist_ok=True)

    _stage("Generating visualization report")
    generate_dynamic_report(
        sim=simulation,
        output_path=str(report_path),
        title="Visualization Demo Report",
        config=config,
    )

    _stage("Simulation and report generation completed")
    print(f"Report generated: {report_path}")
    print(f"Map placeholder path: {map_path}")
    print(f"Bus log JSON: {report_path.parent / 'json' / 'bus_log.json'}")
    print(f"Laadinfra log JSON: {report_path.parent / 'json' / 'laadinfra_log.json'}")
    print(f"Planning log JSON: {report_path.parent / 'json' / 'planning_log.json'}")
    print(f"Planning provider: {planning_provider.__class__.__name__}")
    print(f"Bus provider: {bus_provider.__class__.__name__}")


if __name__ == "__main__":
    main()
