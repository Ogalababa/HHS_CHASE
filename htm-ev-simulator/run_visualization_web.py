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
import threading
import uuid
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parent
RUNNER_PATH = PROJECT_ROOT / "run_visualization_report_demo.py"
DEFAULT_REPORT_RELATIVE = "outputs/combined_visualization_report.html"
app = FastAPI(title="Simulation Configurator")
_jobs_lock = threading.Lock()


@dataclass
class SimulationJob:
    job_id: str
    status: str  # queued | running | success | failed
    report_relative_path: str
    stdout: str = ""
    stderr: str = ""
    return_code: int | None = None


_jobs: dict[str, SimulationJob] = {}


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
    :root {{
      --bg: #f8f9fa;
      --card-bg: #ffffff;
      --text: #212529;
      --border: #dee2e6;
      --accent: #007bff;
      --accent-hover: #0056b3;
      --header-bg: #343a40;
      --header-text: #ffffff;
    }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      margin: 0;
      background: var(--bg);
      color: var(--text);
    }}
    .page {{
      max-width: 980px;
      margin: 20px auto;
      padding: 0 16px 20px;
    }}
    .page-header {{
      background: var(--header-bg);
      color: var(--header-text);
      border-radius: 10px;
      padding: 16px 20px;
      margin-bottom: 16px;
      box-shadow: 0 2px 4px rgba(0, 0, 0, 0.08);
    }}
    h1 {{ margin: 0; font-size: 1.4rem; }}
    .hint {{ margin-top: 8px; margin-bottom: 0; color: #cfd4da; }}
    form {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 16px;
      box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
    }}
    fieldset {{
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 14px;
      margin: 12px 0;
      background: #fcfcfd;
    }}
    legend {{
      padding: 0 8px;
      font-weight: 600;
      color: #495057;
    }}
    label {{ display: block; margin: 10px 0 4px; font-size: 0.95rem; }}
    input, select {{
      width: 100%;
      padding: 9px 10px;
      box-sizing: border-box;
      border: 1px solid #ced4da;
      border-radius: 6px;
      background: #fff;
      color: var(--text);
    }}
    input:focus, select:focus {{
      outline: none;
      border-color: #86b7fe;
      box-shadow: 0 0 0 0.18rem rgba(13, 110, 253, 0.15);
    }}
    input[type="checkbox"] {{
      width: auto;
      margin-right: 8px;
      transform: translateY(1px);
    }}
    .row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .row3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; }}
    .actions {{ margin-top: 18px; }}
    button {{
      background: var(--accent);
      color: white;
      border: none;
      border-radius: 8px;
      padding: 10px 18px;
      font-weight: 600;
      cursor: pointer;
    }}
    button:hover {{ background: var(--accent-hover); }}
    .msg {{ background: #e7f5ff; border: 1px solid #b3e5fc; padding: 10px; border-radius: 6px; margin: 10px 0; }}
    .err {{ background: #ffebee; border: 1px solid #ffcdd2; padding: 10px; border-radius: 6px; margin: 10px 0; color: #b71c1c; white-space: pre-wrap; }}
  </style>
</head>
<body>
  <div class="page">
  <div class="page-header">
    <h1>Simulation Configurator</h1>
    <p class="hint">Configure mode and parameters, run simulation, then open visualization report automatically.</p>
  </div>
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
          <input id="sim_hours" name="sim_hours" type="number" value="24" min="1" max="72" required />
        </div>
      </div>
    </fieldset>

    <fieldset>
      <legend>Provider Modes</legend>
      <label><input type="checkbox" name="use_real_planning" checked /> Use Real Planning (ADLS)</label>
      <label for="use_real_buses">Bus Provider</label>
      <select id="use_real_buses" name="use_real_buses">
        <option value="stub">Stub</option>
        <option value="omniplus" selected>OMNIplus</option>
      </select>
      <label><input type="checkbox" name="simulate_all_vehicles" checked /> Simulate all vehicles (default)</label>
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
      <label>
        <input type="checkbox" name="enable_precheck_force_return_strategy" checked />
        Enable precheck force-return strategy (generate 8xxxxxx forced return when no planned return is matched)
      </label>
      <label>
        <input type="checkbox" name="enable_precheck_dispatch_replacement_strategy" checked />
        Enable precheck replacement-dispatch strategy (generate 9xxxxxx replacement dispatch)
      </label>
      <label>
        <input type="checkbox" name="enable_opportunity_charging_strategy" checked />
        Enable opportunity charging (terminal has charger, SOC&lt;80%, gap&gt;30 min)
      </label>
      <label>
        <input type="checkbox" name="enable_start_full_soc_strategy" checked />
        Enable full SOC start strategy (set all buses SOC=100% at simulation start)
      </label>
      <label>
        <input type="checkbox" name="enable_power_limit_strategy" checked />
        Enable power limit strategy (apply grid cap at Telexstraat / point 30002 only)
      </label>
      <label>
        <input type="checkbox" name="enable_depot_return_dispatch_strategy" checked />
        Enable smart block assignment strategy (optimize first-journey assignment for all blocks with depot-return optimization)
      </label>
      <label>
        <input type="checkbox" name="enable_bus_fill_assignment_strategy" checked />
        Enable bus-fill assignment strategy (fill one bus timeline by origin continuity, then proceed to next bus)
      </label>
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
  </div>
</body>
</html>"""


def _extract_current_stage(stdout_text: str) -> str:
    stage_lines = []
    for line in stdout_text.splitlines():
        if line.startswith("[STAGE] "):
            stage_lines.append(line.replace("[STAGE] ", "", 1).strip())
    return stage_lines[-1] if stage_lines else "Initializing"


def _build_status_page(job: SimulationJob) -> str:
    safe_stdout = html.escape(job.stdout[-12000:])
    safe_stderr = html.escape(job.stderr[-12000:])
    current_stage = html.escape(_extract_current_stage(job.stdout))
    status_color = "#0b5ed7"
    if job.status == "success":
        status_color = "#198754"
    elif job.status == "failed":
        status_color = "#dc3545"

    auto_refresh = ""
    if job.status in {"queued", "running"}:
        auto_refresh = '<meta http-equiv="refresh" content="1">'

    action_html = ""
    if job.status == "success":
        encoded = urllib.parse.quote(job.report_relative_path)
        action_html = f'<p><a href="/report?path={encoded}">Open Report</a></p>'
    elif job.status == "failed":
        action_html = '<p><a href="/">Back to config</a></p>'

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  {auto_refresh}
  <title>Simulation Status</title>
  <style>
    body {{ font-family: Arial, sans-serif; max-width: 900px; margin: 24px auto; padding: 0 12px; }}
    .badge {{ display: inline-block; padding: 6px 10px; border-radius: 999px; color: white; background: {status_color}; }}
    pre {{ background: #0f172a; color: #e2e8f0; padding: 12px; border-radius: 8px; overflow-x: auto; white-space: pre-wrap; }}
    .hint {{ color: #64748b; }}
  </style>
</head>
<body>
  <h1>Simulation Status</h1>
  <p>Job: <code>{job.job_id}</code></p>
  <p>Status: <span class="badge">{job.status.upper()}</span></p>
  <p>Current Stage: <strong>{current_stage}</strong></p>
  <p class="hint">Page refreshes automatically every 2 seconds while running.</p>
  {action_html}
  <h3>Stdout</h3>
  <pre>{safe_stdout or "(no output yet)"}</pre>
  <h3>Stderr</h3>
  <pre>{safe_stderr or "(no errors)"}</pre>
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
        v("sim_hours", "24"),
        "--use-real-buses",
        v("use_real_buses", "omniplus"),
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
    if "simulate_all_vehicles" in form:
        args.append("--simulate-all-vehicles")
    if "enable_precheck_force_return_strategy" in form:
        args.append("--enable-precheck-force-return-strategy")
    if "enable_precheck_dispatch_replacement_strategy" in form:
        args.append("--enable-precheck-dispatch-replacement-strategy")
    if "enable_opportunity_charging_strategy" in form:
        args.append("--enable-opportunity-charging-strategy")
    if "enable_start_full_soc_strategy" in form:
        args.append("--enable-start-full-soc-strategy")
    if "enable_power_limit_strategy" in form:
        args.append("--enable-power-limit-strategy")
    if "enable_depot_return_dispatch_strategy" in form:
        args.append("--enable-depot-return-dispatch-strategy")
    if "enable_bus_fill_assignment_strategy" in form:
        args.append("--enable-bus-fill-assignment-strategy")

    vins = v("omniplus_vins", "")
    if vins:
        args.extend(["--omniplus-vins", vins])

    return args


def _read_report_file(relative_path: str) -> str:
    file_path = (PROJECT_ROOT / relative_path).resolve()
    if not str(file_path).startswith(str(PROJECT_ROOT.resolve())):
        raise ValueError("Invalid report path.")
    return file_path.read_text(encoding="utf-8")


def _read_json_file(relative_path: str) -> dict:
    file_path = (PROJECT_ROOT / relative_path).resolve()
    if not str(file_path).startswith(str(PROJECT_ROOT.resolve())):
        raise ValueError("Invalid report data path.")
    import json
    return json.loads(file_path.read_text(encoding="utf-8"))


def _read_html_file(relative_path: str) -> str:
    file_path = (PROJECT_ROOT / relative_path).resolve()
    if not str(file_path).startswith(str(PROJECT_ROOT.resolve())):
        raise ValueError("Invalid report part path.")
    return file_path.read_text(encoding="utf-8")


def _run_job(job_id: str, args: list[str]) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job.status = "running"

    process = subprocess.Popen(
        args,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )

    def _append_stream(stream: TextIO | None, attr_name: str) -> None:
        if stream is None:
            return
        for line in iter(stream.readline, ""):
            with _jobs_lock:
                live_job = _jobs.get(job_id)
                if not live_job:
                    break
                current_value = getattr(live_job, attr_name, "")
                setattr(live_job, attr_name, current_value + line)
        stream.close()

    stdout_thread = threading.Thread(
        target=_append_stream, args=(process.stdout, "stdout"), daemon=True
    )
    stderr_thread = threading.Thread(
        target=_append_stream, args=(process.stderr, "stderr"), daemon=True
    )
    stdout_thread.start()
    stderr_thread.start()
    return_code = process.wait()
    stdout_thread.join(timeout=2)
    stderr_thread.join(timeout=2)

    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job.return_code = return_code
        job.status = "success" if return_code == 0 else "failed"


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    message = request.query_params.get("msg", "")
    return HTMLResponse(_build_form_page(message=message))


@app.post("/run", response_class=HTMLResponse)
async def run_simulation(request: Request):
    raw = (await request.body()).decode("utf-8", errors="ignore")
    form = urllib.parse.parse_qs(raw)
    args = _build_runner_args(form)
    report_relative = form.get("report_path", [DEFAULT_REPORT_RELATIVE])[0]

    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = SimulationJob(
            job_id=job_id,
            status="queued",
            report_relative_path=report_relative,
        )

    t = threading.Thread(target=_run_job, args=(job_id, args), daemon=True)
    t.start()
    return RedirectResponse(url=f"/run-status?id={job_id}", status_code=303)


@app.get("/run-status", response_class=HTMLResponse)
async def run_status(id: str) -> HTMLResponse:
    with _jobs_lock:
        job = _jobs.get(id)
    if not job:
        return HTMLResponse(_build_form_page(error=f"Unknown job id: {id}"), status_code=404)
    return HTMLResponse(_build_status_page(job))


@app.get("/report", response_class=HTMLResponse)
async def open_report(path: str = DEFAULT_REPORT_RELATIVE) -> HTMLResponse:
    try:
        content = _read_report_file(path)
        return HTMLResponse(content)
    except Exception as exc:
        return HTMLResponse(_build_form_page(error=f"Cannot open report: {exc}"), status_code=404)


@app.get("/report-data")
async def open_report_data(path: str) -> JSONResponse:
    try:
        payload = _read_json_file(path)
        return JSONResponse(payload)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)


@app.get("/report-part", response_class=HTMLResponse)
async def open_report_part(path: str) -> HTMLResponse:
    try:
        content = _read_html_file(path)
        return HTMLResponse(content)
    except Exception as exc:
        return HTMLResponse(f"<h2>Failed to open report part</h2><pre>{html.escape(str(exc))}</pre>", status_code=404)


def main() -> None:
    host = "127.0.0.1"
    port = 8765
    print(f"Simulation frontend running at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
