#!/usr/bin/env python3
"""
Validate simulation JSON artefacts (log-consistency checks).

Reads one or more JSON files whose top-level shape is::

    {"bus_log": [...], "planning_log": [...], ...}

or a list of such objects (first element used).

Checks:
- ``time`` fields are finite numbers when present.
- SOC-like fields whose key contains ``soc`` hold values in ``[soc_min_pct, soc_max_pct]``.

Typical invocation (from ``htm-ev-simulator`` root)::

    python scripts/validate_simulation_output.py outputs/json/bus_log.json
    python scripts/validate_simulation_output.py outputs/json/bus_log.json outputs/json/planning_log.json outputs/json/laadinfra_log.json

Merged export (``{"bus_log": [...], ...}``) also works.

If you run **without** path arguments and ``outputs/json/*.json`` exists, **all JSON files**
in ``outputs/json/`` are validated (covers the usual split bus/planning/laadinfra logs).

Otherwise the script prints a short usage hint.

Rationale:
Ondersteunt D-2 (Testen & Evalueren): reproduceerbare sanity checks naast
historische KPI-vergelijking — geen vervanging van regressietests maar wel
bewijslast voor consistentie reviews.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
from typing import Any


_STREAM_STEMS = frozenset(("bus_log", "planning_log", "laadinfra_log"))


def load_payload(path: pathlib.Path) -> dict[str, Any]:
    """Normalise merged dicts and per-stream array exports under ``outputs/json/``."""
    stem = path.stem.lower()
    raw: Any = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(raw, dict):
        return raw

    if isinstance(raw, list):
        # Legacy: ``[ {"bus_log": ..., "planning_log": ... } ]``
        if raw:
            head = raw[0]
            if isinstance(head, dict) and any(k in head for k in ("bus_log", "planning_log", "laadinfra_log")):
                return dict(head)
        # Per-stream export: ``[ {...}, {...} ]`` for ``bus_log.json``, etc.
        if stem in _STREAM_STEMS:
            return {stem: raw}
        if not raw:
            return {}

    raise ValueError(
        f"Unsupported JSON shape in {path}: expected object, merged list wrapper, or "
        f"named stream array ({', '.join(sorted(_STREAM_STEMS))}). Got {type(raw).__name__}."
    )


def validate_payload(
    data: dict[str, Any],
    *,
    soc_min_pct: float = 0.0,
    soc_max_pct: float = 100.0,
    label_prefix: str = "",
) -> list[str]:
    """Return human-readable violations; empty means OK."""
    issues: list[str] = []

    for stream in ("bus_log", "planning_log", "laadinfra_log"):
        rows = data.get(stream)
        if not isinstance(rows, list):
            if stream in data:
                issues.append(f"{label_prefix}{stream}: expected list, got {type(rows).__name__}")
            continue
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                issues.append(f"{label_prefix}{stream}[{i}]: expected object")
                continue
            t = row.get("time")
            if t is not None:
                try:
                    tf = float(t)
                    if not math.isfinite(tf):
                        issues.append(f"{label_prefix}{stream}[{i}]: non-finite time")
                except (TypeError, ValueError):
                    issues.append(f"{label_prefix}{stream}[{i}]: time not numeric")

            for k, v in row.items():
                lk = str(k).lower()
                if "soc" in lk and isinstance(v, (int, float)):
                    vf = float(v)
                    if vf < soc_min_pct - 1e-6 or vf > soc_max_pct + 1e-6:
                        issues.append(
                            f"{label_prefix}{stream}[{i}]: field {k!r}={vf} "
                            f"outside [{soc_min_pct}, {soc_max_pct}]"
                        )

    return issues


def _default_json_under_outputs(sim_root: pathlib.Path) -> list[pathlib.Path]:
    """Prefer ``outputs/json/*.json``, else ``outputs/*.json``."""
    jd = sim_root / "outputs" / "json"
    if jd.is_dir():
        return sorted(jd.glob("*.json"))
    od = sim_root / "outputs"
    if od.is_dir():
        return sorted(od.glob("*.json"))
    return []


def _hint_no_paths(script_path: pathlib.Path) -> None:
    """Print how to invoke when no paths and nothing to auto-validate."""
    sim_root = script_path.resolve().parent.parent
    example = ""

    jd = sim_root / "outputs" / "json"
    if jd.is_dir():
        names = sorted(p.name for p in jd.glob("*.json"))
        if names:
            rels = [pathlib.Path("outputs") / "json" / n for n in names]
            line = " ".join(str(r) for r in rels)
            from_scripts_parts = [pathlib.Path("..") / r for r in rels]
            line_scr = " ".join(str(fp) for fp in from_scripts_parts)
            example = (
                "\nExample — validate all split logs (from htm-ev-simulator root):\n"
                f"  py -3 scripts/validate_simulation_output.py {line}\n"
                "\nExample (cwd is scripts):\n"
                f"  py -3 validate_simulation_output.py {line_scr}\n"
            )

    if not example:
        out_dir = sim_root / "outputs"
        if out_dir.is_dir():
            found = sorted(out_dir.glob("*.json"))
            if found:
                rel = pathlib.Path("outputs") / found[0].name
                from_scripts = pathlib.Path("..") / rel
                example = (
                    "\nExample (from repo folder htm-ev-simulator):\n"
                    f"  py -3 scripts/validate_simulation_output.py {rel}\n"
                    "\nExample (cwd is scripts):\n"
                    f"  py -3 validate_simulation_output.py {from_scripts}"
                )

    print(
        "No JSON files given and outputs/json/*.json was not found. Pass paths, e.g.:\n"
        f"{example}"
        "\nUse --help for options (--soc-min / --soc-max).\n",
        file=sys.stderr,
        end="",
    )


def main(argv: list[str] | None = None) -> int:
    script_path = pathlib.Path(__file__)
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "json_files",
        nargs="*",
        type=pathlib.Path,
        help=(
            "JSON log(s): merged dict, or split stream arrays (outputs/json/bus_log.json …). "
            "If omitted, all outputs/json/*.json are used when present."
        ),
    )
    p.add_argument("--soc-min", type=float, default=0.0)
    p.add_argument("--soc-max", type=float, default=100.0)
    args = p.parse_args(argv)

    sim_root = script_path.resolve().parent.parent
    paths = list(args.json_files)
    if not paths:
        paths = _default_json_under_outputs(sim_root)
        if not paths:
            _hint_no_paths(script_path)
            return 2

    any_fail = False
    for path in paths:
        if not path.is_file():
            print(f"FAIL: missing file {path}", file=sys.stderr)
            any_fail = True
            continue
        try:
            payload = load_payload(path)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            print(f"FAIL: {path}: {e}", file=sys.stderr)
            any_fail = True
            continue
        issues = validate_payload(
            payload,
            soc_min_pct=args.soc_min,
            soc_max_pct=args.soc_max,
            label_prefix=f"{path.name}: ",
        )
        if issues:
            any_fail = True
            print(f"FAIL: {path}")
            for line in issues[:50]:
                print(f"  - {line}")
            if len(issues) > 50:
                print(f"  ... ({len(issues) - 50} more)")
        else:
            print(f"OK: {path}")

    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
