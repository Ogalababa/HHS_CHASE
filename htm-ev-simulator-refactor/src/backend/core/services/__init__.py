"""
Core services (use-cases / simulation engine).

Rationale: Services orchestrate domain models and ports; separating them from
models keeps entities lightweight and improves testability.
"""

from __future__ import annotations

from .minimal_charging_simulation import ChargingTrace, simulate_charging_soc_trace
from .simpy_charging_simulation import (
    ChargingTrace as SimpyChargingTrace,
    simulate_charging_soc_trace_simpy,
)
from .simpy_visualization_service import VisualizationSimulationService
from .visualization_simulation import (
    ClassifiedLogger,
    VisualizationSimulationResult,
    VisualizationWorldView,
)
from .world_builder import WorldBuildResult, WorldBuilder

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

