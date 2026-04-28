# HTM Electric Bus Visualization Simulator (`htm-ev-simulator`)

A visualization-oriented discrete-event simulation for HTM operational planning: it replays journeys, SOC evolution, and charging-asset usage on **planning timestamps**, and emits classified logs plus HTML reports. The main execution path is the **SimPy-driven `SimpyScheduler`**, with ports/adapters and domain models kept separate (see [`PROJECT_ARCHITECTURE.md`](PROJECT_ARCHITECTURE.md)).

**Strategy host API (allowlist + types):** [`docs/STRATEGY_HOST_API.md`](docs/STRATEGY_HOST_API.md)  
**Protocol source:** `src/backend/core/services/strategies/simulation_strategy_host.py` (`SimulationStrategyHost`)

---

## 1. Stack and dependencies

| Component | Notes |
|-----------|--------|
| Python 3.10+ | Type hints, `dataclass`, `Protocol` |
| SimPy | Unified simulation clock; block-level loop uses `yield env.timeout(0)` inside the process |
| FastAPI / Uvicorn | Optional web entry |
| Domain core | `src/backend/core/models/`, `ports/`, `services/` |
| Infrastructure | `src/backend/infrastructure/` (Parquet/JSON/OMNIplus adapters, etc.) |

Install dependencies from the `htm-ev-simulator` directory:

```bash
pip install -r requirements.txt
```

`requirements.txt` currently lists: `simpy`, `fastapi`, `uvicorn`.

---

## 2. Quick start

From the **`htm-ev-simulator`** root, add `src` to `PYTHONPATH`, then run a script (PowerShell example):

```powershell
$env:PYTHONPATH = "$PWD\src"
python run_visualization_report_demo.py
```

Other entrypoints:

| Script | Role |
|--------|------|
| `run_visualization_report_demo.py` | Offline combined visualization report (JSON/HTML) |
| `run_visualization_web.py` | FastAPI + configurator flow |
| `run_simpy_charge_demo.py` | SimPy charging demo |

Default outputs live under `outputs/` (JSON logs, `report_parts/`, combined reports, etc.).

---

## 3. SimPy engine behaviour (detailed)

This section maps to `VisualizationSimulationService.run` (`simpy_visualization_service.py`) and `SimpyScheduler.run` (`simpy_engine/scheduler.py`).

### 3.1 Clock and wiring

- `simpy.Environment(initial_time=simulation_start_timestamp)`.
- Register the scheduler: `env.process(scheduler.run(env, blocks, buses))`.
- If `simulation_end_timestamp` is set, `env.run(until=end)`; otherwise `env.run()` until the event queue is exhausted.
- **Business times still follow `datetime` timestamps from planning data**; `env.now` stays aligned with journey/charging steps for a single driver and future extensions (the main loop currently advances per block with `yield env.timeout(0)` so it stays consistent with planning time).

### 3.2 Ordering and initialization

- **Blocks:** ascending by **first departure time of the first journey’s first point** in each block.
- **Buses:** ascending by `vehicle_number`.
- Optional **`start_full_soc` strategy:** set every bus to 100% SOC before the run.
- Each bus: `bus_available_at[VIN]` starts at `simulation_start_timestamp`; an initial `bus_log` state row is written.

### 3.3 Block / journey main loop (per block)

Journeys inside a block are sorted by **first-point departure time**, then processed in order:

1. **Skip:** empty point list; or block/journey start after `simulation_end_timestamp` (when set).
2. **First journey assignment:** if there is no `current_bus` yet, `_select_bus_for_time` (optionally filtered by block `vehicle_type`) and append `planning_log` → `block_assigned`.
3. **Pre-journey top-up:** if `bus_available_at < journey_start` and SOC is below `charging_target_soc_percent`, run `_charge_until` on `[available_time, journey_start)` (strategy name `CONNECTED_IDLE_TOP_OFF`, target SOC 100%).
4. **Strategy hooks (before):** `run_before_journey(strategies, scheduler, state)`; strategies may swap `state.active_bus`, update `bus_available_at`, etc. (see the strategy API doc).
5. **Journey simulation:** `_simulate_journey` (next subsection).
6. **Strategy hooks (after):** `run_after_journey`; `bus_available_at[current_vin] = max(…, journey_end)`.
7. **If this journey is skipped:** record the journey and block as skipped and **stop further journeys in this block**.
8. **End of block:** write `block_completed`; associate the bus with **30002 (Garage Telexstraat)**; call `_maybe_charge` up to **100% SOC** (matches report “return to depot and charge” narrative); refresh `bus_available_at` from the last charging log timestamp.
9. `yield env.timeout(0)` for the next SimPy scheduling tick.

### 3.4 Journey simulation `_simulate_journey` (energy and low SOC)

- Release any occupied connector; set state to running; log `journey_start` and first-point `state_update`.
- For each point: log `journey_point` / `point_arrival` at arrival time; reduce SOC from `distance_to_next_m` and `energy_consumption_per_km`; emit `soc_update` / `state_update`.
- **Low-SOC cut-off:** if SOC **falls below** `low_soc_alert_threshold_percent` and the journey is **not** a “return to garage” leg (final point not 30002), append `journey_skipped` (reason mentions the threshold), set bus to available, **abort the journey**, return `skipped=True`.
- **Return-to-garage:** when the last `point_id == "30002"`, the journey is **not** skipped for low SOC (matches `_can_complete_journey` always returning `True` for 30002 destinations).

### 3.5 Charging and power

- `_maybe_charge` delegates to `_charge_until`: attach at a chargeable location, step in `charging_step_seconds`; power is limited by the **NMC3 non-linear curve** (`Bus.calculate_actual_charging_power_kw`) and **`LocationPowerAllocator`** (site budget / strategy flag).
- Log events: `charging_started` / `charging_progress` / `charging_stopped` plus matching `bus_log` state/SOC rows.

### 3.6 Strategy flags (service layer)

`VisualizationSimulationService.strategy_flags` merges boolean switches; keys include `precheck_replacement`, `opportunity_charging`, `start_full_soc`, `power_limit`, etc. `strategies/loader.py` builds the list and passes it into `SimpyScheduler`.

---

## 4. Repository layout (compact)

```
htm-ev-simulator/
├── docs/
│   └── STRATEGY_HOST_API.md    # Allowlisted strategy host API
├── src/
│   ├── backend/
│   │   ├── core/
│   │   │   ├── models/         # Buses, planning, charging domain
│   │   │   ├── ports/          # Bus / planning / infra ports
│   │   │   └── services/       # WorldBuilder, SimPy viz service, strategies, scheduler
│   │   └── infrastructure/     # Parquet/JSON adapters, etc.
│   └── frontend/
│       └── visualization/      # Report generators and HTML templates
├── outputs/                    # Default run artefacts
├── requirements.txt
├── PROJECT_ARCHITECTURE.md      # Hexagonal layers and modules
└── README.md
```

---

## 5. Business and reporting notes

- **SOC floor:** default **14%** (tunable on the service); below threshold on **non-return** journeys drives skip/alarm semantics.
- **Charging curve:** high-SOC taper rules live in `models/transport/bus/charging_curve.py` and `bus.py`.
- **Report semantics:** classified reports align `NOT_STARTED`, skipped journeys, `charging_stopped`, etc. with log events—see `frontend/visualization/classified_report_generator.py` and related modules.

---

## 6. Further reading

- Architecture: [`PROJECT_ARCHITECTURE.md`](PROJECT_ARCHITECTURE.md)
- **Stable surface exposed from `SimpyScheduler` to strategies:** [`docs/STRATEGY_HOST_API.md`](docs/STRATEGY_HOST_API.md)
- **PlantUML class diagrams** (overview + detailed, multi-page): [`docs/plantuml/README.md`](docs/plantuml/README.md)
