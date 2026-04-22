"""
Automatic strategy discovery and lifecycle helpers.

Rationale: New strategy files should be picked up without service changes.
This loader discovers strategy classes from the strategies package by
convention and instantiates enabled strategies.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Any

from .base import SimulationStrategy


def _iter_strategy_classes() -> list[type]:
    package = importlib.import_module(__package__)
    classes: list[type] = []
    for module_info in pkgutil.iter_modules(package.__path__):
        if module_info.name in {"base", "loader"}:
            continue
        module = importlib.import_module(f"{package.__name__}.{module_info.name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if not hasattr(obj, "strategy_key"):
                continue
            if obj.__module__ != module.__name__:
                continue
            if callable(getattr(obj, "before_journey", None)) and callable(getattr(obj, "after_journey", None)):
                classes.append(obj)
    return classes


def build_enabled_strategies(flags: dict[str, bool] | None = None) -> list[SimulationStrategy]:
    flags = flags or {}
    strategies: list[SimulationStrategy] = []
    for cls in _iter_strategy_classes():
        key = getattr(cls, "strategy_key", "")
        enabled_default = bool(getattr(cls, "enabled_by_default", False))
        enabled = flags.get(key, enabled_default)
        if enabled:
            strategies.append(cls())
    return strategies


def run_before_journey(strategies: list[SimulationStrategy], service: Any, state: Any) -> None:
    for strategy in strategies:
        strategy.before_journey(service, state)


def run_after_journey(strategies: list[SimulationStrategy], service: Any, state: Any) -> None:
    for strategy in strategies:
        strategy.after_journey(service, state)

