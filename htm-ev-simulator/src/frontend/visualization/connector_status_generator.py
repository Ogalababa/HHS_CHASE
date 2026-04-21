"""
Connector status generator for timeline playback.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List
import json


def _safe_id(value: str) -> str:
    return value.replace(" ", "-").replace(":", "-").replace("/", "-")


def _latest_at_or_before(events: List[dict[str, Any]], ts: float) -> dict[str, Any] | None:
    latest = None
    for ev in events:
        if ev["time"] <= ts:
            latest = ev
        else:
            break
    return latest


def generate_connector_status_section(sim: Any, laadinfra_log: List[Dict[str, Any]]) -> str:
    """
    Build a playable connector-status view with collapsible sections.

    Rationale: mimic LaadInfra section folding style while focusing each
    hierarchy header on total-power visibility at current time.
    """
    sim_start = getattr(sim, "simulation_start_time", None)
    sim_end = getattr(sim, "simulation_end_time", None)
    if sim_start is None:
        sim_start = min((e.get("time", 0.0) for e in laadinfra_log), default=0.0)
    if sim_end is None:
        sim_end = max((e.get("time", sim_start) for e in laadinfra_log), default=sim_start)

    # Use exact charging-progress timestamps for truthful "same-time" totals.
    # Rationale: fixed 5-minute bins can merge events from different seconds and
    # inflate apparent concurrent power.
    progress_times = sorted(
        {
            float(e.get("time"))
            for e in laadinfra_log
            if e.get("event") == "charging_progress"
            and e.get("time") is not None
            and float(sim_start) <= float(e.get("time")) <= float(sim_end)
        }
    )
    timeline_points: List[float] = progress_times if progress_times else [float(sim_start)]

    connector_events: dict[str, List[dict[str, Any]]] = defaultdict(list)
    connector_meta: dict[str, dict[str, str]] = {}
    grouped: dict[str, dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))

    for entry in laadinfra_log:
        event = entry.get("event")
        if event not in {"charging_started", "charging_progress", "charging_stopped"}:
            continue
        ts = entry.get("time")
        loc = entry.get("location_id")
        charger = entry.get("charger_id")
        connector = entry.get("connector_id")
        if ts is None or not loc or not charger or not connector:
            continue
        key = f"{loc}::{charger}::{connector}"
        if key not in connector_meta:
            connector_meta[key] = {
                "location_id": str(loc),
                "charger_id": str(charger),
                "connector_id": str(connector),
            }
            grouped[str(loc)][str(charger)].append(key)
        connector_events[key].append(
            {
                "event": event,
                "time": float(ts),
                "status": str(entry.get("connector_status") or "UNKNOWN").upper(),
                "bus_number": entry.get("bus_number"),
                "power_kw": float(entry.get("power_kw") or 0.0),
            }
        )

    for key in connector_events:
        connector_events[key].sort(key=lambda x: x["time"])
    for loc in grouped:
        for charger in grouped[loc]:
            grouped[loc][charger].sort(key=lambda k: connector_meta[k]["connector_id"])

    state_by_connector: dict[str, dict[int, dict[str, Any]]] = {}
    for key, evs in connector_events.items():
        state_by_connector[key] = {}
        for idx, ts in enumerate(timeline_points):
            latest = _latest_at_or_before(evs, ts)
            if latest is not None:
                normalized = dict(latest)
                # Use only exact timestamp power to avoid cross-second aggregation.
                in_bin = [
                    ev for ev in evs
                    if abs(float(ev["time"]) - float(ts)) < 1e-6 and ev.get("event") == "charging_progress"
                ]
                if in_bin:
                    latest_bin = in_bin[-1]
                    normalized["power_kw"] = float(latest_bin.get("power_kw") or 0.0)
                    normalized["bus_number"] = latest_bin.get("bus_number")
                    normalized["status"] = str(latest_bin.get("status") or normalized.get("status") or "UNKNOWN").upper()
                else:
                    normalized["power_kw"] = 0.0
                    if str(normalized.get("status") or "").upper() == "CHARGING":
                        normalized["status"] = "CONNECTED"
                state_by_connector[key][idx] = normalized

    location_total: dict[str, dict[int, float]] = defaultdict(dict)
    charger_total: dict[str, dict[str, dict[int, float]]] = defaultdict(lambda: defaultdict(dict))
    connector_total: dict[str, dict[int, float]] = defaultdict(dict)
    for idx, _ in enumerate(timeline_points):
        for loc, charger_map in grouped.items():
            loc_sum = 0.0
            for charger, keys in charger_map.items():
                ch_sum = 0.0
                for key in keys:
                    st = state_by_connector.get(key, {}).get(idx)
                    p = float(st.get("power_kw") or 0.0) if st else 0.0
                    connector_total[key][idx] = p
                    ch_sum += p
                charger_total[loc][charger][idx] = ch_sum
                loc_sum += ch_sum
            location_total[loc][idx] = loc_sum

    html: List[str] = []
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
""")

    for loc in sorted(grouped.keys()):
        loc_safe = _safe_id(loc)
        html.append(
            f"""
  <div class="location-section">
    <div class="location-header collapsed" id="connector-loc-header-{loc_safe}" onclick="toggleConnectorLocation('{loc_safe}')">
      <span class="toggle-icon">▶</span>
      <strong>Location: {loc}</strong>
      <span class="session-count">Total Power: <span id="connector-loc-power-{loc_safe}">0.0</span> kW</span>
    </div>
    <div class="location-content hidden" id="connector-loc-content-{loc_safe}">
"""
        )
        for charger in sorted(grouped[loc].keys()):
            charger_safe = _safe_id(f"{loc}::{charger}")
            html.append(
                f"""
      <div class="charger-section">
        <div class="charger-header collapsed" id="connector-charger-header-{charger_safe}" onclick="toggleConnectorCharger('{charger_safe}')">
          <span class="toggle-icon">▶</span>
          <strong>Charger: {charger}</strong>
          <span class="session-count">Total Power: <span id="connector-charger-power-{charger_safe}">0.0</span> kW</span>
        </div>
        <div class="charger-content hidden" id="connector-charger-content-{charger_safe}">
          <table>
            <thead>
              <tr>
                <th>Connector</th>
                <th>Status</th>
                <th>Charging Bus</th>
                <th>Connector Power (kW)</th>
                <th>Charger Total Power (kW)</th>
                <th>Location Total Power (kW)</th>
              </tr>
            </thead>
            <tbody>
"""
            )
            for key in grouped[loc][charger]:
                meta = connector_meta[key]
                conn_id = meta["connector_id"]
                html.append(
                    f"""
              <tr data-connector-key="{key}">
                <td>{conn_id}</td>
                <td class="status-cell">-</td>
                <td class="bus-cell">-</td>
                <td class="power-cell">-</td>
                <td class="charger-total-cell">-</td>
                <td class="location-total-cell">-</td>
              </tr>
"""
                )
            html.append(
                """
            </tbody>
          </table>
        </div>
      </div>
"""
            )
        html.append("""
    </div>
  </div>
""")

    html.append("""
</div>
<script>
const connectorStatusData = {
  timeline: """)
    html.append(json.dumps([datetime.fromtimestamp(x).strftime("%Y-%m-%d %H:%M") for x in timeline_points]))
    html.append(""",
  stateByConnector: """)
    html.append(json.dumps(state_by_connector))
    html.append(""",
  connectorMeta: """)
    html.append(json.dumps(connector_meta))
    html.append(""",
  connectorTotal: """)
    html.append(json.dumps(connector_total))
    html.append(""",
  chargerTotal: """)
    html.append(json.dumps(charger_total))
    html.append(""",
  locationTotal: """)
    html.append(json.dumps(location_total))
    html.append("""
};

let connectorPlaying = false;
let connectorPlayTimer = null;
let connectorIndex = 0;

function toggleConnectorLocation(locSafe) {
  const header = document.getElementById('connector-loc-header-' + locSafe);
  const content = document.getElementById('connector-loc-content-' + locSafe);
  if (!header || !content) return;
  header.classList.toggle('collapsed');
  content.classList.toggle('hidden');
}

function toggleConnectorCharger(chargerSafe) {
  const header = document.getElementById('connector-charger-header-' + chargerSafe);
  const content = document.getElementById('connector-charger-content-' + chargerSafe);
  if (!header || !content) return;
  header.classList.toggle('collapsed');
  content.classList.toggle('hidden');
}

function renderConnectorStatus(index) {
  connectorIndex = index;
  const timelineLabel = document.getElementById('connector-current-time');
  if (timelineLabel) timelineLabel.textContent = connectorStatusData.timeline[index] || '-';

  // Update header total power values
  Object.entries(connectorStatusData.locationTotal).forEach(([locId, byIdx]) => {
    const id = 'connector-loc-power-' + locId.replaceAll(' ', '-').replaceAll(':', '-').replaceAll('/', '-');
    const el = document.getElementById(id);
    if (el) {
      const v = byIdx[index] !== undefined ? Number(byIdx[index]) : 0.0;
      el.textContent = v.toFixed(1);
    }
  });
  Object.entries(connectorStatusData.chargerTotal).forEach(([locId, byCharger]) => {
    Object.entries(byCharger).forEach(([chargerId, byIdx]) => {
      const id = 'connector-charger-power-' + (locId + '::' + chargerId).replaceAll(' ', '-').replaceAll(':', '-').replaceAll('/', '-');
      const el = document.getElementById(id);
      if (el) {
        const v = byIdx[index] !== undefined ? Number(byIdx[index]) : 0.0;
        el.textContent = v.toFixed(1);
      }
    });
  });
  Object.entries(connectorStatusData.connectorTotal).forEach(([key, byIdx]) => {
    // Keep connector total in data model; table rows already show this value.
    const id = 'connector-power-' + key.replaceAll(' ', '-').replaceAll(':', '-').replaceAll('/', '-');
    const el = document.getElementById(id);
    if (el) {
      const v = byIdx[index] !== undefined ? Number(byIdx[index]) : 0.0;
      el.textContent = v.toFixed(1);
    }
  });

  // Update connector detail rows
  const rows = document.querySelectorAll('tr[data-connector-key]');
  rows.forEach((row) => {
    const key = row.getAttribute('data-connector-key');
    const meta = connectorStatusData.connectorMeta[key];
    if (!meta) return;
    const state = connectorStatusData.stateByConnector[key] && connectorStatusData.stateByConnector[key][index];
    const status = state ? (state.status || '-') : '-';
    const bus = state && state.bus_number !== null && state.bus_number !== undefined ? String(state.bus_number) : '-';
    const power = state ? Number(state.power_kw || 0.0) : 0.0;
    const chargerTotal = connectorStatusData.chargerTotal[meta.location_id]
      && connectorStatusData.chargerTotal[meta.location_id][meta.charger_id]
      && connectorStatusData.chargerTotal[meta.location_id][meta.charger_id][index];
    const locationTotal = connectorStatusData.locationTotal[meta.location_id]
      && connectorStatusData.locationTotal[meta.location_id][index];

    row.querySelector('.status-cell').textContent = status;
    row.querySelector('.bus-cell').textContent = power > 0.001 ? bus : '-';
    row.querySelector('.power-cell').textContent = power.toFixed(1);
    row.querySelector('.charger-total-cell').textContent = Number(chargerTotal || 0.0).toFixed(1);
    row.querySelector('.location-total-cell').textContent = Number(locationTotal || 0.0).toFixed(1);
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
    renderConnectorStatus(connectorIndex);
  }, 500);
}

(function initConnectorStatus() {
  const slider = document.getElementById('connector-time-slider');
  if (!slider) return;
  slider.addEventListener('input', (e) => {
    renderConnectorStatus(parseInt(e.target.value, 10));
  });
  renderConnectorStatus(0);
})();
</script>
""")
    return "".join(html)

