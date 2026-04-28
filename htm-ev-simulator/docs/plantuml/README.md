# PlantUML diagrams

## Overview class diagram

- **File:** [`class_diagram.puml`](class_diagram.puml)
- **Scope:** Compact view of main types under `src/backend/core` (domain, ports, services, strategies), key infrastructure adapters, and one frontend DTO. Omits script-only entrypoints and function-only report helpers.

## Detailed class diagram

- **File:** [`class_diagram_detailed.puml`](class_diagram_detailed.puml)
- **Single canvas (one big diagram, no `newpage`):** [`class_diagram_detailed_single.puml`](class_diagram_detailed_single.puml) — same packages/classes/relations; use when you want one SVG/PNG. Very large: increase Java heap if PlantUML errors (`java -Xmx4096m -jar ...`).
- **Scope:** Richer view with:
  - **Page 1 — Domain:** exceptions, `World`, planning (`Block`, `Journey`, `PointInSequence`), `Bus` / `BusState` / `ChargingCurve`, laad-infra (`Grid`, `Location`, `Charger`, `Connector`, `ChargePoint`), and aggregate wiring.
  - **Page 2 — Application:** ports (`BusProviderPort`, `PlanningProviderPort`, `InfrastructureProviderPort`), `WorldBuilder` / `WorldBuildResult`, visualization DTOs (`ClassifiedLogger`, `VisualizationWorldView`, `VisualizationSimulationResult`, legacy `VisualizationSimulationService` helper), `InternalEventLog`.
  - **Page 3 — SimPy engine:** `LocationPowerAllocator` (fields + `allocate_power_kw` / `apply_energy` / Telexstraat limit logic), `SimpyScheduler` (dataclass fields + main private/public methods used in the journey/charge loop).
  - **Page 4 — Strategies & infra:** `StrategyRuntimeState`, `SimulationStrategy` / `SimulationStrategyHost`, concrete strategies, loader artifact note, SimPy `VisualizationSimulationService`, adapters (`OmniplusBusProvider`, `BusPlanningParquetProvider`, `ConnectorJsonInfrastructureProvider`), `OmniplusOnClient`, `DataLakeConfig`, `MaximoAssetProvider`, `DynamicBusSnapshot`.

Use **`newpage`** so multi-page exports (PDF or multi-page PNG) stay readable; for a single huge PNG, you can temporarily comment out `newpage` lines.

### How to render

1. Install [PlantUML](https://plantuml.com/download) (needs Java) or use the [PlantUML extension](https://marketplace.visualstudio.com/items?itemName=jebbs.plantuml) in VS Code / Cursor.
2. From this directory:

```bash
plantuml class_diagram.puml
plantuml class_diagram_detailed.puml
```

This produces `class_diagram.png` and `class_diagram_detailed.png` (and/or SVG depending on your PlantUML setup).

3. Or use the [PlantUML Web Server](https://www.plantuml.com/plantuml/uml/) and paste the `.puml` contents (very large diagrams may hit size limits).

### Notation

- Packages follow **architectural roles**, not always 1:1 with Python import paths.
- `..|>` = structural implementation (`Protocol` / ABC in code).
- `..>` = dependency / use.
- `*--` / `o--` = composition / aggregation style ownership.
- `{static}` = `@staticmethod` in Python.

---

## Pyreverse (auto-generated from code)

From `htm-ev-simulator` root, after `pip install pylint` and with Java available:

```powershell
.\scripts\run_pyreverse.ps1
```

This writes:

- `out/pyreverse/classes_htm_ev_simulator.puml` — class diagram
- `out/pyreverse/packages_htm_ev_simulator.puml` — package diagram
- matching `.svg` files (uses `tools/plantuml.jar`, downloaded on first run; jar is gitignored).

Set `PYTHONPATH=src` is handled inside the script. Pyreverse may print one-off astroid warnings; output files are still produced if exit code is 0.
