# D-2 Testen & evaluatie — Validatierapport

**Project:** HTM Electric Bus Visualization Simulator (`htm-ev-simulator`)  
**Doelactiviteit:** Unit tests, testscripts, log-consistentiechecks en kader voor historische KPI-vergelijking (D-2).  
**Versie:** concept — te koppelen aan je afstudeerdocument (Datum: 28-04-2026).

**Zh:** Volledige verificatie in het Chinees: [`verification_report_zh.md`](verification_report_zh.md).

---

## 1. Scope en kwaliteitscriteria

| Criterium | Toelichting |
|-----------|-------------|
| **Nauwkeurigheid** | Vergelijking simulatie-output met planning/historie (bijv. vertrek-/aankomsttijden per rit, SoC-verloop). In je narratief: gemiddelde afwijking **3–6 minuten per rit** is acceptabel voor **trendanalyse** (geen seconde-realtime). |
| **Betrouwbaarheid** | Geen crashes; voorspelbare eventvolgorde; SoC binnen [0,100] % in gelogde velden; beleidsregels (o.a. **lage SoC 14%**, garage-rit uitzondering, NMC3-curve) gedekt door regressietests waar mogelijk. |
| **Consistentie** | Logs (`bus_log`, `planning_log`, `laadinfra_log`) doorlopen op eindige timestamps en interne consistentie (script `scripts/validate_simulation_output.py`). |

---

## 2. Bewijslast — artefacten

| Artefact | Locatie | Doel |
|---------|---------|------|
| **Unit tests** | `tests/unit/test_*.py` | Per laag: domein (`Bus`, `ChargingCurve`, `World`, connector), services (`LocationPowerAllocator`, `SimpyScheduler` business rules, `WorldBuilder`, strategy loader), infra (`maximo` filter), SimPy/minimal charging. |
| **Testrunner** | `scripts/run_unit_tests.py` | Eén exitcode (`0`/`1`) voor rapportage en CI. |
| **Logvalidatie** | `scripts/validate_simulation_output.py` | Post-run sanity checks op JSON-export (tijdvelden, SOC-velden). |
| **Architectuur** | `README.md`, `PROJECT_ARCHITECTURE.md` | Toelichting Hexagonal / SimPy-scheduler. |

---

## 3. Uitvoering (reproduceerbaar)

Vanaf de map `htm-ev-simulator`:

```powershell
py -3 scripts/run_unit_tests.py
```

Na een simulatierun (bijv. `run_visualization_report_demo.py`), output valideren.

**Gesplitste logs** (`outputs/json/bus_log.json`, `planning_log.json`, `laadinfra_log.json`): voer vanaf `htm-ev-simulator` uit zonder argumenten — alle `outputs/json/*.json` worden gevalideerd — of geef de drie paden expliciet mee.

```powershell
py -3 scripts/validate_simulation_output.py
py -3 scripts/validate_simulation_output.py outputs\json\bus_log.json outputs\json\planning_log.json outputs\json\laadinfra_log.json
```

Gecombineerde export (één JSON met `bus_log` / `planning_log` / `laadinfra_log` keys) kan ook als enkel bestand worden doorgegeven.

> **Afhankelijkheid:** `pandas` is nodig voor `test_maximo_asset_provider` indien die test meedraait (`pip install pandas`).

---

## 4. Interpretatie t.o.v. besluitvorming (jouw D-2-tekst)

- **Impact van 3–6 min afwijking:** beïnvloedt vooral **timing van vervanging/omruil** en **optreden van strategie-hooks** (substitutie, buffermarges), niet automatisch “volledige uitval” van exploitatie in het model.
- **SoC-bufferanalyse (18–20%):** wordt ondersteund doordat de scheduler expliciet **`low_soc_alert_threshold_percent`** (standaard **14%**) en projectie vóór ritstart hanteert (`_can_complete_journey`); unit tests documenteren **garage-bestemming (30002)** als uitzondering op de lage-SoC-grens.

---

## 5. Beperkingen en vervolg

- **Historische vergelijking** (parquet/OTP) zit niet in deze repo als vaste pipeline; exporteer tijdreeksen en vergelijk KPI’s (MAE/MAPE minuten, dekking) in notebook of script — voeg tabellen/plots toe als bijlage in je scriptie.
- **End-to-end GUI** (FastAPI) wordt aanbevolen handmatig of met lichte integratietests; niet alle paden zijn in deze suite geautomatiseerd.

---

## 6. Referenties in code (samenvatting)

| Module | Geteste gedragingen |
|--------|---------------------|
| `charging_curve` / `Bus` | Enveloppe 282 kW, vermogensdak, SoC-clamp, 14%-drempel. |
| `World` | Duplicate ID’s, `attach_locations_to_points`. |
| `LocationPowerAllocator` | Allocatie, reset slot-state, `apply_energy`. |
| `SimpyScheduler` | Garage-rit vs. lage-SoC-projectie. |
| `WorldBuilder` | Port-samenvoeging zonder I/O. |
| `strategies/loader` | Feature flags / `start_full_soc`. |
| `Connector` | `ConnectorOccupiedError` bij dubbele bezetting. |

---

*Dit document dient als bewijsstuk voor **D-2: Testen & evalueren** naast de testscripts en eventuele Jupyter-/exportbijlagen.*
