"""
SimPy runtime components for refactor project.

Heavy modules (scheduler) are lazily resolved so importing
``backend.core.services.simpy_engine.resource_allocator`` does not execute the
strategy/scheduler circular import chain during test collection.

Rationale: Package-level eager imports amplified ``StrategyRuntimeState``
partial-init errors under ``unittest`` discovery (see scheduler ↔ base).
"""

from __future__ import annotations

from typing import Any


def __getattr__(name: str) -> Any:
    if name == "InternalEventLog":
        from .event_log import InternalEventLog

        return InternalEventLog
    if name == "LocationPowerAllocator":
        from .resource_allocator import LocationPowerAllocator

        return LocationPowerAllocator
    if name == "SimpyScheduler":
        from .scheduler import SimpyScheduler

        return SimpyScheduler
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)


__all__ = ["InternalEventLog", "LocationPowerAllocator", "SimpyScheduler"]
