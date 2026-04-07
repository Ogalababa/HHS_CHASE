"""
Maximo asset loader adapter (ADLS parquet -> bus asset DataFrame).

Rationale: Loading Maximo reference data is infrastructure (ADLS + pandas).
This module keeps those concerns out of the core and provides a clean, testable
API for obtaining the subset of asset fields needed to build domain `Bus`
entities (usually combined with live OMNIplus signals).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .datalake_helper import DataLakeConfig, read_parquet


@dataclass(frozen=True, slots=True)
class MaximoAssetQuery:
    """
    Query parameters for selecting bus assets.
    """

    assetnum_min: int = 1400
    assetnum_max: int = 1600


def filter_bus_assets(df: pd.DataFrame, *, query: MaximoAssetQuery) -> pd.DataFrame:
    """
    Filter raw Maximo assets into the subset needed for bus construction.

    Business rules:
    - `htm_vendor_serialnum` must start with 'WEB'
    - `assetnum` must be numeric and within (assetnum_min, assetnum_max)
    - return only required fields
    """
    required_columns = {
        "assetnum",
        "htm_tramtype",
        "htm_vendor_serialnum",
        "isrunning",
    }

    missing = required_columns - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns in asset data: {sorted(missing)}")

    out = df.copy()

    # Convert assetnum to numeric
    out["assetnum"] = pd.to_numeric(out["assetnum"], errors="coerce")
    out = out.dropna(subset=["assetnum"])
    out["assetnum"] = out["assetnum"].astype(int)

    # serialnum must start with WEB
    out = out.dropna(subset=["htm_vendor_serialnum"])
    out = out[out["htm_vendor_serialnum"].astype(str).str.startswith("WEB")]

    # filter range (exclusive, matching original code)
    out = out[(out["assetnum"] > query.assetnum_min) & (out["assetnum"] < query.assetnum_max)]

    return out[list(required_columns)].copy()


@dataclass(slots=True)
class MaximoAssetProvider:
    """
    Load and filter bus assets from Maximo parquet in ADLS.
    """

    datalake: DataLakeConfig | None = None
    parquet_filesystem: str = "maximo"
    parquet_path: str = "tables/asset/asset.parquet"

    def load_bus_assets(self, *, query: MaximoAssetQuery = MaximoAssetQuery()) -> pd.DataFrame:
        df = read_parquet(
            filesystem=self.parquet_filesystem,
            path=self.parquet_path,
            config=self.datalake,
        )
        return filter_bus_assets(df, query=query)

