"""
Infrastructure adapters package.

Rationale: Adapters live outside the core to avoid leaking external dependencies
into the domain. Declaring this package supports clean imports and testing.
"""

from __future__ import annotations

from .bus_planning_parquet_provider import BusPlanningParquetProvider
from .maximo_asset_provider import MaximoAssetProvider, MaximoAssetQuery
from .omniplus_bus_provider import OmniplusBusProvider

__all__ = [
    "BusPlanningParquetProvider",
    "MaximoAssetProvider",
    "MaximoAssetQuery",
    "OmniplusBusProvider",
]

