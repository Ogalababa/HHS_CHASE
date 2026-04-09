from __future__ import annotations

"""
Runnable SimPy charging demo.

Usage (PowerShell):
    py htm-ev-simulator/run_simpy_charge_demo.py

Optional:
    py htm-ev-simulator/run_simpy_charge_demo.py --capacity-kwh 352.8 --charger-kw 360 --start-soc 10 --target-soc 100 --out soc_trace.csv
"""

import argparse
import csv
import sys
from pathlib import Path


def _ensure_src_on_path() -> None:
    src = Path(__file__).resolve().parent / "src"
    sys.path.insert(0, str(src))


def main() -> int:
    _ensure_src_on_path()

    parser = argparse.ArgumentParser(description="SimPy charging simulation demo (1Hz SoC trace).")
    parser.add_argument("--capacity-kwh", type=float, default=100.0, help="Battery capacity (kWh).")
    parser.add_argument("--charger-kw", type=float, default=360.0, help="Charger offered power (kW).")
    parser.add_argument("--start-soc", type=float, default=10.0, help="Start SoC (%).")
    parser.add_argument("--target-soc", type=float, default=100.0, help="Target SoC (%).")
    parser.add_argument("--dt", type=int, default=1, help="Time step (seconds).")
    parser.add_argument("--out", type=str, default="", help="Optional CSV output path.")
    args = parser.parse_args()

    from backend.core.models.transport.bus import Bus, BusState
    from backend.core.services import simulate_charging_soc_trace_simpy

    bus = Bus(
        vehicle_number=1,
        vin_number="DEMO",
        vehicle_type="E-BUS",
        state=BusState.CHARGING,
        energy_consumption_per_km=1.0,
        soc_percent=float(args.start_soc),
        battery_capacity_kwh=float(args.capacity_kwh),
    )

    trace = simulate_charging_soc_trace_simpy(
        bus=bus,
        charger_offered_power_kw=float(args.charger_kw),
        start_soc_percent=float(args.start_soc),
        target_soc_percent=float(args.target_soc),
        dt_seconds=int(args.dt),
    )

    print(f"duration_seconds={trace.duration_seconds}")
    print(f"duration_minutes={trace.duration_seconds/60:.2f}")
    print(f"samples={len(trace.soc_per_second)} (includes t=0)")
    print(f"start_soc={trace.soc_per_second[0]:.3f}  end_soc={trace.soc_per_second[-1]:.3f}")

    if args.out:
        out_path = Path(args.out)
        with out_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["t_seconds", "soc_percent"])
            for i, soc in enumerate(trace.soc_per_second):
                w.writerow([i * int(args.dt), soc])
        print(f"wrote_csv={out_path.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

