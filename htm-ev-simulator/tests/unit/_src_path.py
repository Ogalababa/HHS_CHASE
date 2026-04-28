"""Prepend `htm-ev-simulator/src` so `import backend...` works in unit tests."""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_backend_src_on_path() -> None:
    """
    Resolve `htm-ev-simulator/` as parent of `tests/unit/` and add `src/`.

    Rationale: Tests run via `python -m unittest discover -s tests/unit -t .`
    without requiring `PYTHONPATH` to be set manually in shell or CI.
    """
    htm_ev_root = Path(__file__).resolve().parents[2]
    src = htm_ev_root / "src"
    s = str(src)
    if s not in sys.path:
        sys.path.insert(0, s)
