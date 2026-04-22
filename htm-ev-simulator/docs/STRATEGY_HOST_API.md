# Strategy host API (`SimpyScheduler` / `SimulationStrategyHost`)

This document defines the **supported host surface** that strategy modules may rely on inside the `before_journey` / `after_journey` hooks of the visualization discrete-event simulation. At runtime the `service` argument is a `SimpyScheduler` instance; for typing it should be treated as `SimulationStrategyHost` (`typing.Protocol`) so static checkers and refactors preserve a stable contract.

**Where it lives**

- Protocol: `src/backend/core/services/strategies/simulation_strategy_host.py` → `SimulationStrategyHost`
- Implementation: `src/backend/core/services/simpy_engine/scheduler.py` → `SimpyScheduler`
- Strategy contracts: `src/backend/core/services/strategies/base.py` → `SimulationStrategy`, `StrategyRuntimeState`

---

## 1. Callable methods and attributes (allowlist)

The APIs below are used by **built-in strategies** (e.g. `precheck_replacement`, `opportunity_charging`) and are treated as a **stable outward contract**. Other `SimpyScheduler` members (such as `_simulate_journey`, `_charge_until`) **must not** be called from strategies.

### 1.1 Configuration attributes (read-only for strategies)

| Member | Type | Description |
|--------|------|-------------|
| `opportunity_charging_soc_threshold_percent` | `float` | Opportunity charging: only considered when SOC is below this value |
| `opportunity_charging_min_gap_seconds` | `int` | Opportunity charging: minimum seconds until the next journey departure |
| `charging_target_soc_percent` | `float` | Default charge target when `_maybe_charge` omits `target_soc_percent` |
| `low_soc_alert_threshold_percent` | `float` | In-journey SOC floor; consistent with `_can_complete_journey` |
| `charging_step_seconds` | `int` | Charging time step (seconds), used internally; strategies typically only read it |

### 1.2 `_can_complete_journey(bus, journey) -> bool`

- **Purpose:** Whether, after completing the full `journey`, projected SOC would still be at or above `low_soc_alert_threshold_percent`.
- **Special case:** If the journey **ends** at depot point **30002** (Garage Telexstraat), **always returns `True`** (return-to-depot legs are never classified as “cannot complete” at the strategy layer due to the SOC gate).

### 1.3 `_select_bus_for_time(buses, bus_available_at, target_time, exclude_vin=None, required_vehicle_type=None) -> Bus`

- **Purpose:** Pick one bus from candidates using availability time and a SOC heuristic (shared by precheck replacement and first-block dispatch, etc.).
- **Note:** Implemented as `@staticmethod` on the class; call as `service._select_bus_for_time(...)` (same call shape as an instance method).

### 1.4 `_log_precheck_replacement(*, world, logger, block, original_bus, replacement_bus, journey, sequence) -> None`

- **Purpose:** Append precheck replacement events to `planning_log` (`journey_replacement`, `journey_point`, …) with fields agreed with the report classifier.

### 1.5 `_maybe_charge(bus, start_time_ts, logger, *, strategy_name="SOC_THRESHOLD", deadline_time_ts=None, target_soc_percent=None) -> None`

- **Purpose:** Start a **bounded** charging session at the bus’s current or fallback (30002) location; writes `bus_log` / `laadinfra_log`.
- **Keyword args:**
  - `strategy_name`: label in logs (e.g. `OPPORTUNITY_CHARGING`).
  - `deadline_time_ts`: upper bound timestamp for the charge simulation; `None` uses an internal default window.
  - `target_soc_percent`: target SOC; `None` falls back to `charging_target_soc_percent`.

---

## 2. `StrategyRuntimeState` fields strategies may mutate safely

| Field | Type | Convention |
|-------|------|--------------|
| `active_bus` | `Bus` | Precheck replacement: may switch to the replacement bus |
| `bus_available_at` | `dict[str, float]` | May update per-VIN next-dispatch time (should stay consistent with log timestamps) |

Other fields (`world`, `block`, `journey`, `logger`, …) should be treated read-only; `journey_end` and `journey_skipped` are filled by the scheduler after `_simulate_journey` and are readable in `after_journey`.

---

## 3. Python typing (kept in sync with code)

Authoritative signatures are in `SimulationStrategyHost` inside `simulation_strategy_host.py`; `SimulationStrategy.before_journey` / `after_journey` annotate `service` with that type.

When adding a new strategy:

1. Use only this allowlist and the `StrategyRuntimeState` conventions above.
2. If you need new host capabilities, extend `SimulationStrategyHost` and this document first, then implement on `SimpyScheduler`—avoid coupling strategies to private implementation details.
