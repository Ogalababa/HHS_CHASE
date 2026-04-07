"""
Core services (use-cases / simulation engine).

Rationale: Services orchestrate domain models and ports; separating them from
models keeps entities lightweight and improves testability.
"""

from __future__ import annotations

from .world_builder import WorldBuildResult, WorldBuilder

__all__ = [
    "WorldBuilder",
    "WorldBuildResult",
]

