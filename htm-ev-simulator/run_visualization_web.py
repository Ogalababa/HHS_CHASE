from __future__ import annotations

"""
Lightweight frontend for configurable simulation and report redirection.

Rationale: The project currently generates visualization reports through Python
scripts. This web entrypoint provides a simple UX for configuring simulation
mode and parameters, while reusing the existing application runner to preserve
hexagonal boundaries.
"""

import html
import subprocess
import sys
import urllib.parse
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parent
RUNNER_PATH = PROJECT_ROOT / "run_visualization_report_demo.py"
DEFAULT_REPORT_RELATIVE = "outputs/combined_visualization_report.html"
app = FastAPI(title="Simulation Configurator")


def _build_form_page(message: str = "", error: str = "") -> str:
    safe_message = html.escape(message)
    safe_error = html.escape(error)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Simulation Configurator</title>
  <style>
    body {{ font-family: Arial, sans-serif; max-width: 820px; margin: 24px auto; padding: 0 12px; }}
    h1 {{ margin-bottom: 8px; }}
    .hint {{ color: #444; margin-bottom: 16px; }}
    fieldset {{ border: 1px solid #ddd; border-radius: 8px; padding: 12px; margin: 12px 0; }}
    legend {{ padding: 0 8px; }}
    label {{ display: block; margin: 8px 0 4px; }}
    input, select {{ width: 100%; padding: 8px; box-sizing: border-box; }}
    .row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
    .row3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }}
    .actions {{ margin-top: 16px; }}
    button {{ padding: 10px 16px; cursor: pointer; }}
    .msg {{ background: #e7f5ff; border: 1px solid #b3e5fc; padding: 10px; border-radius: 6px; margin: 10px 0; }}
    .err {{ background: #ffebee; border: 1px solid #ffcdd2; padding: 10px; border-radius: 6px; margin: 10px 0; color: #b71c1c; white-space: pre-wrap; }}
  </style>
</head>
<body>
  <h1>Simulation Configurator</h1>
  <p class="hint">Configure mode and parameters, run simulation, then open visualization report automatically.</p>
  {"<div class='msg'>" + safe_message + "</div>" if safe_message else ""}
  {"<div class='err'>" + safe_error + "</div>" if safe_error else ""}

  <form method="post" action="/run">
    <fieldset>
      <legend>Simulation Horizon</legend>
      <div class="row3">
        <div>
          <label for="sim_date">Simulation Date</label>
          <input id="sim_date" name="sim_date" type="date" value="2026-02-02" required />
        </div>
        <div>
          <label for="sim_start">Start Time</label>
          <input id="sim_start" name="sim_start" type="time" value="06:00" required />
        </div>
        <div>
          <label for="sim_hours">Duration (hours)</label>
          <input id="sim_hours" name="sim_hours" type="number" value="12" min="1" max="72" required />
        </div>
      </div>
    </fieldset>

    <fieldset>
      <legend>Provider Modes</legend>
      <label><input type="checkbox" name="use_real_planning" /> Use Real Planning (ADLS)</label>
      <label for="use_real_buses">Bus Provider</label>
      <select id="use_real_buses" name="use_real_buses">
        <option value="stub" selected>Stub</option>
        <option value="maximo">Maximo</option>
        <option value="omniplus">OMNIplus</option>
      </select>
      <label><input type="checkbox" name="fallback_to_stub" checked /> Fallback to stub on provider failure</label>
      <label for="omniplus_vins">OMNIplus VINs (comma-separated, only for OMNIplus mode)</label>
      <input id="omniplus_vins" name="omniplus_vins" type="text" placeholder="VIN-1401,VIN-1402" />
    </fieldset>

    <fieldset>
      <legend>Simulation Strategy</legend>
      <div class="row3">
        <div>
          <label for="low_soc_threshold">Low SOC threshold (%)</label>
          <input id="low_soc_threshold" name="low_soc_threshold" type="number" value="14" step="0.1" min="0" max="100" />
        </div>
        <div>
          <label for="charge_target_soc">Charge target SOC (%)</label>
          <input id="charge_target_soc" name="charge_target_soc" type="number" value="85" step="0.1" min="1" max="100" />
        </div>
        <div>
          <label for="charge_step_seconds">Charge step (seconds)</label>
          <input id="charge_step_seconds" name="charge_step_seconds" type="number" value="300" min="30" />
        </div>
      </div>
    </fieldset>

    <fieldset>
      <legend>Output</legend>
      <label for="report_path">Report path (relative to project root)</label>
      <input id="report_path" name="report_path" type="text" value="{DEFAULT_REPORT_RELATIVE}" />
      <label for="map_path">Map path (relative to project root)</label>
      <input id="map_path" name="map_path" type="text" value="outputs/replay_map.html" />
    </fieldset>

    <div class="actions">
      <button type="submit">Run Simulation</button>
    </div>
  </form>
</body>
</html>"""


def _build_runner_args(form: dict[str, list[str]]) -> list[str]:
    def v(name: str, default: str) -> str:
        return form.get(name, [default])[0].strip()

    args = [
        sys.executable,
        str(RUNNER_PATH),
        "--sim-date",
        v("sim_date", "2026-02-02"),
        "--sim-start",
        v("sim_start", "06:00"),
        "--sim-hours",
        v("sim_hours", "12"),
        "--use-real-buses",
        v("use_real_buses", "stub"),
        "--low-soc-threshold",
        v("low_soc_threshold", "14"),
        "--charge-target-soc",
        v("charge_target_soc", "85"),
        "--charge-step-seconds",
        v("charge_step_seconds", "300"),
        "--report-path",
        v("report_path", DEFAULT_REPORT_RELATIVE),
        "--map-path",
        v("map_path", "outputs/replay_map.html"),
    ]

    if "use_real_planning" in form:
        args.append("--use-real-planning")
    if "fallback_to_stub" in form:
        args.append("--fallback-to-stub")

    vins = v("omniplus_vins", "")
    if vins:
        args.extend(["--omniplus-vins", vins])

    return args


def _read_report_file(relative_path: str) -> str:
    file_path = (PROJECT_ROOT / relative_path).resolve()
    if not str(file_path).startswith(str(PROJECT_ROOT.resolve())):
        raise ValueError("Invalid report path.")
    return file_path.read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    message = request.query_params.get("msg", "")
    return HTMLResponse(_build_form_page(message=message))


@app.post("/run", response_class=HTMLResponse)
async def run_simulation(request: Request):
    raw = (await request.body()).decode("utf-8", errors="ignore")
    form = urllib.parse.parse_qs(raw)
    args = _build_runner_args(form)

    completed = subprocess.run(
        args,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        error_text = (completed.stderr or completed.stdout or "Unknown error").strip()
        return HTMLResponse(_build_form_page(error=f"Simulation failed:\n{error_text}"), status_code=400)

    report_relative = form.get("report_path", [DEFAULT_REPORT_RELATIVE])[0]
    encoded = urllib.parse.quote(report_relative)
    return RedirectResponse(url=f"/report?path={encoded}", status_code=303)


@app.get("/report", response_class=HTMLResponse)
async def open_report(path: str = DEFAULT_REPORT_RELATIVE) -> HTMLResponse:
    try:
        content = _read_report_file(path)
        return HTMLResponse(content)
    except Exception as exc:
        return HTMLResponse(_build_form_page(error=f"Cannot open report: {exc}"), status_code=404)


def main() -> None:
    host = "127.0.0.1"
    port = 8765
    print(f"Simulation frontend running at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
