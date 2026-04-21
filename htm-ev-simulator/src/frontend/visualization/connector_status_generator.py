"""
Connector status generator for timeline playback.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List
import json


def generate_connector_status_section(sim: Any, laadinfra_log: List[Dict[str, Any]]) -> str:
    """
    Build a playable connector status table over time.

    Rationale: Connector-level visibility (status, connected bus, per-connector
    power) is needed to validate charging resource allocation behavior.
    """
    sim_start = getattr(sim, "simulation_start_time", None)
    sim_end = getattr(sim, "simulation_end_time", None)
    if sim_start is None:
        sim_start = min((e.get("time", 0.0) for e in laadinfra_log), default=0.0)
    if sim_end is None:
        sim_end = max((e.get("time", sim_start) for e in laadinfra_log), default=sim_start)

    timeline_points: List[float] = []
    t = float(sim_start)
    while t <= float(sim_end):
        timeline_points.append(t)
        t += 300.0

    connector_meta: dict[str, dict[str, str]] = {}
    connector_events: dict[str, list[dict[str, Any]]] = defaultdict(list)
    location_time_power_sum: dict[str, dict[float, float]] = defaultdict(dict)
    charger_time_power_sum: dict[str, dict[str, dict[float, float]]] = defaultdict(lambda: defaultdict(dict))

    for entry in laadinfra_log:
        event = entry.get("event")
        time = entry.get("time")
        loc = entry.get("location_id")
        charger = entry.get("charger_id")
        connector = entry.get("connector_id")
        if event not in {"charging_started", "charging_progress", "charging_stopped"}:
            continue
        if time is None or not loc or not charger or not connector:
            continue
        key = f"{loc}::{charger}::{connector}"
        connector_meta[key] = {
            "location_id": str(loc),
            "charger_id": str(charger),
            "connector_id": str(connector),
        }
        connector_events[key].append(
            {
                "time": float(time),
                "status": str(entry.get("connector_status") or "UNKNOWN").upper(),
                "bus_number": entry.get("bus_number"),
                "bus_vin": entry.get("bus_vin"),
                "power_kw": float(entry.get("power_kw") or 0.0),
            }
        )
        if event == "charging_progress":
            ts = float(time)
            p = float(entry.get("power_kw") or 0.0)
            location_time_power_sum[str(loc)][ts] = location_time_power_sum[str(loc)].get(ts, 0.0) + p
            charger_time_power_sum[str(loc)][str(charger)][ts] = charger_time_power_sum[str(loc)][str(charger)].get(ts, 0.0) + p

    for evs in connector_events.values():
        evs.sort(key=lambda x: x["time"])
    location_total_by_time: dict[str, dict[int, float]] = defaultdict(dict)
    charger_total_by_time: dict[str, dict[str, dict[int, float]]] = defaultdict(lambda: defaultdict(dict))
    for loc, tmap in location_time_power_sum.items():
        for idx, tp in enumerate(timeline_points):
            location_total_by_time[loc][idx] = float(tmap.get(tp, 0.0))
    for loc, c_map in charger_time_power_sum.items():
        for charger, tmap in c_map.items():
            for idx, tp in enumerate(timeline_points):
                charger_total_by_time[loc][charger][idx] = float(tmap.get(tp, 0.0))

    rows = sorted(connector_meta.keys(), key=lambda k: (connector_meta[k]["location_id"], connector_meta[k]["charger_id"], connector_meta[k]["connector_id"]))
    grouped: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for key in rows:
        meta = connector_meta[key]
        grouped[meta["location_id"]][meta["charger_id"]].append(key)

    state_by_connector: dict[str, dict[int, dict[str, Any]]] = {}
    for key in rows:
        state_by_connector[key] = {}
        evs = connector_events.get(key, [])
        for idx, tp in enumerate(timeline_points):
            latest = None
            for ev in evs:
                if ev["time"] <= tp:
                    latest = ev
                else:
                    break
            if latest is not None:
                state_by_connector[key][idx] = latest

    html = []
    html.append("""
<div class="connector-status-section">
  <h2>Connector Status Over Time</h2>
  <p>Time interval: 5 minutes</p>
  <div style="margin: 1rem 0; display:flex; gap:1rem; align-items:center; flex-wrap:wrap;">
    <label for="connector-time-slider">Time:</label>
    <input type="range" id="connector-time-slider" min="0" max=\"""")
    html.append(str(max(0, len(timeline_points) - 1)))
    html.append("""\" value="0" style="width: 55%;">
    <span id="connector-current-time"></span>
    <button id="connector-play-btn" onclick="toggleConnectorPlay()" style="padding:6px 14px; border:none; border-radius:4px; background:#007bff; color:#fff; cursor:pointer;">▶ Play</button>
  </div>
  <div style="overflow-x:auto; max-height:75vh; overflow-y:auto;">
    <table id="connector-status-table">
      <thead>
        <tr>
          <th>Location</th>
          <th>Charger</th>
          <th>Connector</th>
          <th>Status</th>
          <th>Charging Bus</th>
          <th>Connector Power (kW)</th>
          <th>Location Total Power (kW)</th>
        </tr>
      </thead>
      <tbody id="connector-status-tbody">
""")
    for loc_id in sorted(grouped.keys()):
        loc_row_id = f"loc::{loc_id}"
        html.append(
            f"<tr class=\"connector-location-row\" data-row-id=\"{loc_row_id}\" data-level=\"location\">"
            f"<td><button class=\"toggle-btn\" onclick=\"toggleConnectorGroup('{loc_row_id}')\">▶</button> {loc_id}</td>"
            "<td>-</td><td>-</td><td>LOCATION</td><td>-</td><td>-</td>"
            f"<td class=\"loc-total-cell\" data-location-id=\"{loc_id}\">-</td></tr>"
        )
        for charger_id in sorted(grouped[loc_id].keys()):
            charger_row_id = f"charger::{loc_id}::{charger_id}"
            html.append(
                f"<tr class=\"hidden-row\" data-parent-id=\"{loc_row_id}\" data-row-id=\"{charger_row_id}\" data-level=\"charger\">"
                f"<td></td><td><button class=\"toggle-btn\" onclick=\"toggleConnectorGroup('{charger_row_id}')\">▶</button> {charger_id}</td>"
                "<td>-</td><td>CHARGER</td><td>-</td>"
                f"<td class=\"charger-total-cell\" data-location-id=\"{loc_id}\" data-charger-id=\"{charger_id}\">-</td><td>-</td></tr>"
            )
            for key in sorted(grouped[loc_id][charger_id]):
                meta = connector_meta[key]
                html.append(
                    f"<tr class=\"hidden-row\" data-parent-id=\"{charger_row_id}\" data-connector-key=\"{key}\" data-level=\"connector\">"
                    f"<td></td><td></td><td>{meta['connector_id']}</td>"
                    "<td class=\"status-cell\">-</td><td class=\"bus-cell\">-</td><td class=\"power-cell\">-</td><td class=\"loc-power-cell\">-</td></tr>"
                )
    html.append("""
      </tbody>
    </table>
  </div>
</div>
<script>
const connectorStatusData = {
  timeline: """)
    html.append(json.dumps([datetime.fromtimestamp(x).strftime("%Y-%m-%d %H:%M") for x in timeline_points]))
    html.append(""",
  rows: """)
    html.append(json.dumps(rows))
    html.append(""",
  meta: """)
    html.append(json.dumps(connector_meta))
    html.append(""",
  states: """)
    html.append(json.dumps(state_by_connector))
    html.append(""",
  locationTotals: """)
    html.append(json.dumps(location_total_by_time))
    html.append(""",
  chargerTotals: """)
    html.append(json.dumps(charger_total_by_time))
    html.append("""
};
let connectorPlaying = false;
let connectorPlayTimer = null;
let connectorIndex = 0;
const expandedConnectorGroups = new Set();

function toggleConnectorGroup(rowId) {
  if (expandedConnectorGroups.has(rowId)) {
    expandedConnectorGroups.delete(rowId);
  } else {
    expandedConnectorGroups.add(rowId);
  }
  refreshConnectorVisibility();
}

function refreshConnectorVisibility() {
  const allRows = document.querySelectorAll('#connector-status-tbody tr');
  allRows.forEach((row) => {
    const parentId = row.getAttribute('data-parent-id');
    if (!parentId) return;
    const grandParent = document.querySelector(`#connector-status-tbody tr[data-row-id="${parentId}"]`);
    const parentVisible = !grandParent || !grandParent.classList.contains('hidden-row');
    const visible = parentVisible && expandedConnectorGroups.has(parentId);
    row.classList.toggle('hidden-row', !visible);
  });
  document.querySelectorAll('.toggle-btn').forEach((btn) => {
    const row = btn.closest('tr');
    const rowId = row ? row.getAttribute('data-row-id') : null;
    btn.textContent = rowId && expandedConnectorGroups.has(rowId) ? '▼' : '▶';
  });
}

function renderConnectorTable(index) {
  connectorIndex = index;
  document.getElementById('connector-current-time').textContent = connectorStatusData.timeline[index] || '-';
  const rows = document.querySelectorAll('#connector-status-tbody tr[data-connector-key]');
  rows.forEach((row) => {
    const key = row.getAttribute('data-connector-key');
    const state = connectorStatusData.states[key] && connectorStatusData.states[key][index];
    const meta = connectorStatusData.meta[key];
    const location = meta ? meta.location_id : '';
    const statusCell = row.querySelector('.status-cell');
    const busCell = row.querySelector('.bus-cell');
    const powerCell = row.querySelector('.power-cell');
    const locPowerCell = row.querySelector('.loc-power-cell');
    const status = state ? (state.status || '-') : '-';
    const power = state ? Number(state.power_kw || 0) : 0;
    const bus = state && state.bus_number !== null && state.bus_number !== undefined ? String(state.bus_number) : '-';
    const locPower = connectorStatusData.locationTotals[location] && connectorStatusData.locationTotals[location][index];
    statusCell.textContent = status;
    busCell.textContent = power > 0.001 ? bus : '-';
    powerCell.textContent = power > 0.001 ? power.toFixed(1) : '-';
    locPowerCell.textContent = locPower !== undefined ? Number(locPower).toFixed(1) : '-';
  });
  const locationRows = document.querySelectorAll('.loc-total-cell');
  locationRows.forEach((cell) => {
    const loc = cell.getAttribute('data-location-id');
    const v = connectorStatusData.locationTotals[loc] && connectorStatusData.locationTotals[loc][index];
    cell.textContent = v !== undefined ? Number(v).toFixed(1) : '-';
  });
  const chargerRows = document.querySelectorAll('.charger-total-cell');
  chargerRows.forEach((cell) => {
    const loc = cell.getAttribute('data-location-id');
    const charger = cell.getAttribute('data-charger-id');
    const v = connectorStatusData.chargerTotals[loc]
      && connectorStatusData.chargerTotals[loc][charger]
      && connectorStatusData.chargerTotals[loc][charger][index];
    cell.textContent = v !== undefined ? Number(v).toFixed(1) : '-';
  });
}

function toggleConnectorPlay() {
  const btn = document.getElementById('connector-play-btn');
  if (connectorPlaying) {
    clearInterval(connectorPlayTimer);
    connectorPlayTimer = null;
    connectorPlaying = false;
    btn.textContent = '▶ Play';
    btn.style.backgroundColor = '#007bff';
    return;
  }
  connectorPlaying = true;
  btn.textContent = '⏸ Pause';
  btn.style.backgroundColor = '#dc3545';
  connectorPlayTimer = setInterval(() => {
    if (connectorIndex >= connectorStatusData.timeline.length - 1) {
      toggleConnectorPlay();
      return;
    }
    connectorIndex += 1;
    const slider = document.getElementById('connector-time-slider');
    if (slider) slider.value = connectorIndex;
    renderConnectorTable(connectorIndex);
  }, 500);
}

(function initConnectorStatus() {
  const slider = document.getElementById('connector-time-slider');
  if (!slider) return;
  // Expand all location rows by default.
  document.querySelectorAll('#connector-status-tbody tr[data-level="location"]').forEach((row) => {
    const rowId = row.getAttribute('data-row-id');
    if (rowId) expandedConnectorGroups.add(rowId);
  });
  slider.addEventListener('input', (e) => {
    renderConnectorTable(parseInt(e.target.value, 10));
  });
  refreshConnectorVisibility();
  renderConnectorTable(0);
})();
</script>
<style>
  .hidden-row { display: none; }
  .toggle-btn {
    border: none;
    background: transparent;
    cursor: pointer;
    font-size: 12px;
    margin-right: 6px;
    color: #495057;
  }
  .connector-location-row td {
    background: #f1f3f5;
    font-weight: 600;
  }
</style>
""")
    return "".join(html)

