"""
Core services (use-cases / simulation engine).

Rationale: Services orchestrate domain models and ports; separating them from
models keeps entities lightweight and improves testability.

Heavy modules (visualization façade) are lazily exported so submodules such as
``simpy_engine.resource_allocator`` remain import-safe in unit tests without
pulling strategy/scheduler transitive imports at package load time.

Rationale: Avoiding circular imports keeps ``pytest``/unittest discovery robust
when tests import granular engine helpers.
"""

from __future__ import annotations

from typing import Any

from .minimal_charging_simulation import ChargingTrace, simulate_charging_soc_trace
from .simpy_charging_simulation import (
    ChargingTrace as SimpyChargingTrace,
    simulate_charging_soc_trace_simpy,
)
from .world_builder import WorldBuildResult, WorldBuilder

_lazy_export: dict[str, tuple[str, str]] = {
    "VisualizationSimulationService": (".simpy_visualization_service", "VisualizationSimulationService"),
    "VisualizationSimulationResult": (".visualization_simulation", "VisualizationSimulationResult"),
    "VisualizationWorldView": (".visualization_simulation", "VisualizationWorldView"),
    "ClassifiedLogger": (".visualization_simulation", "ClassifiedLogger"),
}


def __getattr__(name: str) -> Any:
    if name in _lazy_export:
        mod_path, cls_name = _lazy_export[name]
        mod = __import__(f"{__name__}{mod_path}", fromlist=[cls_name])
        return getattr(mod, cls_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(__all__) | set(_lazy_export.keys()))


__all__ = [
    "simulate_charging_soc_trace",
    "ChargingTrace",
    "simulate_charging_soc_trace_simpy",
    "SimpyChargingTrace",
    "VisualizationSimulationService",
    "VisualizationSimulationResult",
    "VisualizationWorldView",
    "ClassifiedLogger",
    "WorldBuilder",
    "WorldBuildResult",
]
