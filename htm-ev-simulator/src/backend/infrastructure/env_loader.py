"""
Minimal .env loader (infrastructure).

Rationale: Environment variables and local `.env` files are runtime/config
concerns. This tiny loader avoids adding third-party dependencies while keeping
secrets and environment-specific values out of git. Core/domain must never
depend on this module.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def get_env(key: str, *, dotenv_path: Optional[Path] = None) -> Optional[str]:
    """
    Get a configuration value from the process environment or a local `.env`.

    Priority:
    1) `os.environ`
    2) `.env` file (if present)
    """
    if key in os.environ and os.environ[key] != "":
        return os.environ[key]

    path = dotenv_path or _default_dotenv_path()
    if path is None or not path.exists():
        return None

    values = _parse_dotenv(path)
    val = values.get(key)
    return val if val != "" else None


def _default_dotenv_path() -> Optional[Path]:
    # This file lives at: htm-ev-simulator/src/backend/infrastructure/env_loader.py
    # We want: htm-ev-simulator/.env
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / ".env"
        # stop after reaching htm-ev-simulator root if present
        if candidate.name == ".env" and candidate.exists():
            return candidate
    # Fallback: relative to CWD
    cwd_candidate = Path(".") / "htm-ev-simulator" / ".env"
    return cwd_candidate


def _parse_dotenv(path: Path) -> dict[str, str]:
    """
    Parse a simple .env file.

    Supported:
    - KEY=VALUE
    - KEY="VALUE" / KEY='VALUE'
    - Comments starting with '#'
    - Optional leading 'export '
    """
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = k.strip()
        val = v.strip()
        if val and (val[0] == val[-1]) and val[0] in ("'", '"'):
            val = val[1:-1]
        out[key] = val
    return out

