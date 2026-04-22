"""
Internal event log structures for SimPy runtime.

Rationale: The engine emits internal classified logs first, then the
application service maps them to the existing visualization result contract.
This keeps the simulation core independent from rendering concerns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class InternalEventLog:
    """Classified event streams used by visualization mapping."""

    bus_log: list[dict[str, Any]] = field(default_factory=list)
    planning_log: list[dict[str, Any]] = field(default_factory=list)
    laadinfra_log: list[dict[str, Any]] = field(default_factory=list)

