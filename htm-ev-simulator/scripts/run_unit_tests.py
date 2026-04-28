#!/usr/bin/env python3
"""
Run all unit tests for htm-ev-simulator.

Usage (from repository ``htm-ev-simulator`` root)::

    python scripts/run_unit_tests.py

Rationale: Central entrypoint voor D-2 rapportage en CI (exitcode =
unittest main).
"""

from __future__ import annotations

import pathlib
import sys
import unittest


def main() -> int:
    root = pathlib.Path(__file__).resolve().parents[1]
    src = root / "src"
    sys.path.insert(0, str(src))

    loader = unittest.TestLoader()
    suite = loader.discover(
        str(root / "tests" / "unit"),
        pattern="test_*.py",
        top_level_dir=str(root),
    )
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
