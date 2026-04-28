"""
Dynamic report generator with external JSON payload.

Rationale: Previous combined reports embed very large HTML tables and inline
JavaScript data, which creates multi-megabyte HTML files and causes browser
performance issues. This generator writes a compact HTML shell and moves report
data into a separate JSON file loaded at runtime.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
import json
import bisect

from .bus_status_generator import generate_bus_status_section
from .connector_status_generator import generate_connector_status_section
from .classified_report_generator import (
    generate_breakdown_table_body,
    generate_laadinfra_detailed_section,
    generate_summary_section,
)
from .statistics_generator import analyze_planning_statistics
from .statistics_generator import generate_statistics_section


@dataclass(slots=True)
class DynamicBusSnapshot:
    time: float
    bus_vin: str
    bus_number: int
    state: str
    soc_percent: Optional[float]
    block_id: Optional[str]
    location: Optional[str]


def _build_bus_snapshots(
    sim: Any,
    bus_log: list[dict[str, Any]],
    planning_log: list[dict[str, Any]],
    sample_interval_seconds: int = 300,
) -> dict[str, Any]:
    buses = sorted(sim.world.buses, key=lambda b: b.vehicle_number)
    if not buses:
        return {"timeline": [], "rows": []}

    start_time = min((x.get("time", 0.0) for x in bus_log), default=0.0)
    end_time = max((x.get("time", start_time) for x in bus_log), default=start_time)
    timeline: list[float] = []
    t = start_time
    while t <= end_time:
        timeline.append(t)
        t += sample_interval_seconds

    state_events: dict[str, list[dict[str, Any]]] = {}
    soc_events: dict[str, list[dict[str, Any]]] = {}
    for entry in bus_log:
        vin = entry.get("bus_vin")
        if not vin:
            continue
        if entry.get("event") == "state_update":
            state_events.setdefault(vin, []).append(entry)
        if entry.get("event") in {"state_update", "soc_update"}:
            soc_events.setdefault(vin, []).append(entry)

    block_events: dict[str, list[dict[str, Any]]] = {}
    for entry in planning_log:
        vin = entry.get("bus_vin")
        if not vin:
            continue
        if entry.get("event") in {"block_assigned", "block_completed"}:
            block_events.setdefault(vin, []).append(entry)

    for events in state_events.values():
        events.sort(key=lambda x: x.get("time", 0.0))
    for events in soc_events.values():
        events.sort(key=lambda x: x.get("time", 0.0))
    for events in block_events.values():
        events.sort(key=lambda x: x.get("time", 0.0))

    rows: list[dict[str, Any]] = []
    for time_point in timeline:
        for bus in buses:
            vin = bus.vin_number
            bus_state = None
            location = None
            for ev in state_events.get(vin, []):
                if ev.get("time", 0.0) <= time_point:
                    bus_state = ev.get("state")
                    loc = ev.get("location")
                    if isinstance(loc, dict):
                        location = loc.get("name")
                else:
                    break

            bus_soc = None
            for ev in soc_events.get(vin, []):
                if ev.get("time", 0.0) <= time_point:
                    bus_soc = ev.get("soc_percent")
                else:
                    break

            assigned_block = None
            for ev in block_events.get(vin, []):
                if ev.get("time", 0.0) <= time_point:
                    if ev.get("event") == "block_assigned":
                        assigned_block = ev.get("block_id")
                    elif ev.get("event") == "block_completed":
                        assigned_block = None
                else:
                    break

            rows.append(
                asdict(DynamicBusSnapshot(
                    time=time_point,
                    bus_vin=vin,
                    bus_number=bus.vehicle_number,
                    state=bus_state or "UNKNOWN",
                    soc_percent=bus_soc,
                    block_id=assigned_block,
                    location=location,
                ))
            )
    return {"timeline": timeline, "rows": rows}


def _build_summary(sim: Any, planning_log: list[dict[str, Any]], laadinfra_log: list[dict[str, Any]]) -> dict[str, Any]:
    journeys_total = len([x for x in planning_log if x.get("event") == "journey_start"])
    blocks_total = len({x.get("block_id") for x in planning_log if x.get("event") == "block_assigned" and x.get("block_id")})
    skipped_journey_ids = {
        (x.get("block_id"), x.get("journey_id"))
        for x in planning_log
        if x.get("event") == "journey_skipped_low_soc" and x.get("journey_id")
    }
    skipped_journeys_count = len(skipped_journey_ids) if skipped_journey_ids else len(sim.skipped_journeys)
    return {
        "simulation_stop_time": datetime.fromtimestamp(sim.current_time).strftime("%Y-%m-%d %H:%M:%S") if sim.current_time else "N/A",
        "journeys_total": journeys_total,
        "journeys_completed": len(sim.completed_journeys),
        "journeys_skipped": skipped_journeys_count,
        "blocks_total": blocks_total,
        "blocks_skipped": len(sim.skipped_blocks),
        "charging_sessions": len([x for x in laadinfra_log if x.get("event") == "charging_started"]),
    }


def _enrich_planning_log_with_soc(
    planning_log: list[dict[str, Any]],
    bus_log: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Backfill missing SOC values in planning events from bus timeline.

    Rationale: `generate_breakdown_table_body` renders SOC from planning events,
    but current simulation events often omit `soc_percent` on point/journey/block
    events. This preserves existing report logic while restoring SOC visibility.
    """
    soc_timeline: dict[str, list[tuple[float, float]]] = {}
    for entry in bus_log:
        event = entry.get("event")
        if event not in {"state_update", "soc_update"}:
            continue
        vin = entry.get("bus_vin")
        t = entry.get("time")
        soc = entry.get("soc_percent")
        if not vin or t is None or soc is None:
            continue
        soc_timeline.setdefault(vin, []).append((float(t), float(soc)))

    for vin in list(soc_timeline.keys()):
        soc_timeline[vin].sort(key=lambda x: x[0])

    result: list[dict[str, Any]] = []
    for entry in planning_log:
        new_entry = dict(entry)
        if new_entry.get("soc_percent") is not None:
            result.append(new_entry)
            continue
        vin = new_entry.get("bus_vin")
        t = new_entry.get("time")
        if not vin or t is None or vin not in soc_timeline:
            result.append(new_entry)
            continue
        times = [x[0] for x in soc_timeline[vin]]
        idx = bisect.bisect_right(times, float(t)) - 1
        if idx >= 0:
            new_entry["soc_percent"] = soc_timeline[vin][idx][1]
        result.append(new_entry)
    return result


def generate_dynamic_report(
    *,
    sim: Any,
    output_path: str,
    title: str = "Dynamic Simulation Report",
    config: Optional[Any] = None,
) -> None:
    """
    Generate compact HTML + JSON dynamic report.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload_path = out.with_name(f"{out.stem}.data.json")
    logs_dir = out.parent / "json"
    logs_dir.mkdir(parents=True, exist_ok=True)

    bus_log = sim.classified_logger.bus_log
    planning_log = sim.classified_logger.planning_log
    laadinfra_log = sim.classified_logger.laadinfra_log

    enriched_planning_log = _enrich_planning_log_with_soc(planning_log, bus_log)

    statistics = None
    if config is not None:
        statistics = analyze_planning_statistics(
            sim.world,
            config,
            bus_log=bus_log,
            skipped_blocks=sim.skipped_blocks,
            skipped_journeys=sim.skipped_journeys,
            planning_log=enriched_planning_log,
        )

    payload = {
        "title": title,
        "summary": _build_summary(sim, planning_log, laadinfra_log),
        "statistics": statistics,
        "bus_status": _build_bus_snapshots(sim, bus_log, planning_log),
    }
    payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (logs_dir / "bus_log.json").write_text(json.dumps(bus_log, ensure_ascii=False), encoding="utf-8")
    (logs_dir / "laadinfra_log.json").write_text(json.dumps(laadinfra_log, ensure_ascii=False), encoding="utf-8")
    (logs_dir / "planning_log.json").write_text(json.dumps(planning_log, ensure_ascii=False), encoding="utf-8")

    # Build full legacy-compatible sections, but persist them as separate HTML parts.
    report_parts_dir = out.parent / "report_parts"
    report_parts_dir.mkdir(parents=True, exist_ok=True)

    statistics_html = (
        generate_statistics_section(statistics)
        if statistics is not None
        else "<p>Statistics not available (config missing)</p>"
    )
    summary_html = generate_summary_section(sim, planning_log, laadinfra_log)
    breakdown_rows_html = generate_breakdown_table_body(enriched_planning_log, sim.world, laadinfra_log)
    laadinfra_html = generate_laadinfra_detailed_section(
        laadinfra_log,
        sim.world.locations,
        planning_log,
    )
    bus_status_html = generate_bus_status_section(sim, bus_log, planning_log, laadinfra_log)
    connector_status_html = generate_connector_status_section(sim, laadinfra_log)

    (report_parts_dir / "statistics.html").write_text(statistics_html, encoding="utf-8")
    (report_parts_dir / "summary.html").write_text(summary_html, encoding="utf-8")
    (report_parts_dir / "breakdown_rows.html").write_text(breakdown_rows_html, encoding="utf-8")
    (report_parts_dir / "laadinfra.html").write_text(laadinfra_html, encoding="utf-8")
    (report_parts_dir / "bus_status.html").write_text(bus_status_html, encoding="utf-8")
    (report_parts_dir / "connector_status.html").write_text(connector_status_html, encoding="utf-8")

    template_path = Path(__file__).parent / "templates" / "combined_report.html"
    template_html = template_path.read_text(encoding="utf-8")
    simulation_window_text = _build_summary(sim, planning_log, laadinfra_log).get("simulation_stop_time", "N/A")
    if config is not None:
        start_dt = datetime.combine(config.sim_date, config.sim_start_time)
        end_dt = start_dt + timedelta(hours=config.sim_duration_hours)
        simulation_window_text = f"{start_dt.strftime('%Y-%m-%d %H:%M:%S')} - {end_dt.strftime('%Y-%m-%d %H:%M:%S')}"

    dynamic_statistics = '<div id="dyn-statistics-slot"></div>'
    dynamic_summary = '<div id="dyn-summary-slot"></div>'
    dynamic_breakdown_rows = '<tr id="dyn-breakdown-loading"><td colspan="7">Loading simulation breakdown...</td></tr>'
    dynamic_laadinfra = '<div id="dyn-laadinfra-slot"></div>'
    dynamic_bus_status = '<div id="dyn-busstatus-slot"></div>'
    dynamic_connector_status = '<div id="dyn-connector-slot"></div>'

    script = """
<script>
(() => {
  const partsBase = "outputs/report_parts/";
  const loaded = new Set();
  const loadedScripts = new Set();

  const loadExternalScript = (src) => {
    if (!src || loadedScripts.has(src)) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src;
      s.async = false;
      s.onload = () => {
        loadedScripts.add(src);
        resolve();
      };
      s.onerror = () => reject(new Error("Failed to load script: " + src));
      document.head.appendChild(s);
    });
  };

  const injectHtmlWithScripts = async (target, htmlText) => {
    if (!target) return;
    target.innerHTML = htmlText;
    const scripts = Array.from(target.querySelectorAll("script"));
    for (const oldScript of scripts) {
      const newScript = document.createElement("script");
      for (const attr of oldScript.attributes) {
        newScript.setAttribute(attr.name, attr.value);
      }
      if (oldScript.src) {
        await loadExternalScript(oldScript.src);
      } else {
        newScript.text = oldScript.text || "";
        oldScript.parentNode && oldScript.parentNode.replaceChild(newScript, oldScript);
      }
    }
  };

  const fetchPart = async (file) => {
    const url = "/report-part?path=" + encodeURIComponent(partsBase + file);
    const res = await fetch(url);
    if (!res.ok) {
      throw new Error("Failed to load " + file + " (" + res.status + ")");
    }
    return await res.text();
  };

  const loadStatistics = async () => {
    if (loaded.has("statistics")) return;
    const slot = document.getElementById("dyn-statistics-slot");
    if (!slot) return;
    await injectHtmlWithScripts(slot, await fetchPart("statistics.html"));
    loaded.add("statistics");
  };

  const loadReport = async () => {
    if (loaded.has("report")) return;
    const summarySlot = document.getElementById("dyn-summary-slot");
    if (summarySlot) {
      await injectHtmlWithScripts(summarySlot, await fetchPart("summary.html"));
    }
    const tbody = document.querySelector("#Report tbody");
    if (tbody) {
      tbody.innerHTML = await fetchPart("breakdown_rows.html");
      if (typeof window.refreshAssignedBusFilter === "function") {
        window.refreshAssignedBusFilter();
      }
    }
    loaded.add("report");
  };

  const loadLaadinfra = async () => {
    if (loaded.has("laadinfra")) return;
    const slot = document.getElementById("dyn-laadinfra-slot");
    if (!slot) return;
    await injectHtmlWithScripts(slot, await fetchPart("laadinfra.html"));
    loaded.add("laadinfra");
  };

  const loadBusStatus = async () => {
    if (loaded.has("busstatus")) return;
    const slot = document.getElementById("dyn-busstatus-slot");
    if (!slot) return;
    await injectHtmlWithScripts(slot, await fetchPart("bus_status.html"));
    loaded.add("busstatus");
  };

  const loadConnectorStatus = async () => {
    if (loaded.has("connectorstatus")) return;
    const slot = document.getElementById("dyn-connector-slot");
    if (!slot) return;
    await injectHtmlWithScripts(slot, await fetchPart("connector_status.html"));
    loaded.add("connectorstatus");
  };

  const wireTabLazyLoad = () => {
    const links = Array.from(document.querySelectorAll(".tab-link"));
    const plan = [
      { keyword: "Planning Statistics", loader: loadStatistics },
      { keyword: "Planning Detailed Report", loader: loadReport },
      { keyword: "LaadInfra Detailed Report", loader: loadLaadinfra },
      { keyword: "Bus Status", loader: loadBusStatus },
      { keyword: "Connector Status", loader: loadConnectorStatus },
    ];
    for (const link of links) {
      const text = (link.textContent || "").trim();
      const matched = plan.find((x) => text.includes(x.keyword));
      if (!matched) continue;
      link.addEventListener("click", () => {
        matched.loader().catch((err) => console.error(err));
      });
    }
  };

  // Initial tab is Statistics in template, preload only this tab for exact first-paint behavior.
  loadStatistics().catch((err) => console.error(err));
  wireTabLazyLoad();
})();
</script>
"""

    html_out = template_html.replace("{{ title }}", title)
    html_out = html_out.replace("Simulation stopped at:", "Simulation window:")
    html_out = html_out.replace("{{ sim_stop_time }}", simulation_window_text)
    html_out = html_out.replace("{{ statistics_section }}", dynamic_statistics)
    html_out = html_out.replace("{{ summary_section }}", dynamic_summary)
    html_out = html_out.replace("{{ breakdown_table_body }}", dynamic_breakdown_rows)
    html_out = html_out.replace("{{ laadinfra_section }}", dynamic_laadinfra)
    html_out = html_out.replace("{{ bus_status_section }}", dynamic_bus_status + script)
    html_out = html_out.replace("{{ connector_status_section }}", dynamic_connector_status)
    out.write_text(html_out, encoding="utf-8")
