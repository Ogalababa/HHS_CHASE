"""
Azure Data Lake helper (infrastructure).

Rationale: Accessing ADLS, authentication (DefaultAzureCredential) and parquet
IO (pandas) are infrastructure concerns. This module encapsulates those details
so core/domain stays independent from Azure SDKs and storage layouts.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from .env_loader import get_env


ENV_STORAGE_ACCOUNT = "DATALAKE_STORAGE_ACCOUNT"
ENV_DEFAULT_FILESYSTEM = "DATALAKE_FILESYSTEM"


@dataclass(frozen=True, slots=True)
class DataLakeConfig:
    """
    Configuration for connecting to ADLS.

    Rationale: Keeping config in a small object makes it easy to inject different
    accounts/filesystems in tests or environments without scattering constants.
    """

    storage_account: Optional[str] = None
    filesystem: Optional[str] = None

    def __post_init__(self) -> None:
        # Pull defaults from env/.env to avoid leaking account names in git.
        if self.storage_account is None:
            object.__setattr__(self, "storage_account", get_env(ENV_STORAGE_ACCOUNT))
        if self.filesystem is None:
            object.__setattr__(self, "filesystem", get_env(ENV_DEFAULT_FILESYSTEM))

        if not self.storage_account:
            raise RuntimeError(
                f"Missing ADLS storage account. Set {ENV_STORAGE_ACCOUNT} in your environment (.env)."
            )
        if not self.filesystem:
            raise RuntimeError(
                f"Missing ADLS filesystem. Set {ENV_DEFAULT_FILESYSTEM} in your environment (.env)."
            )

    @property
    def account_url(self) -> str:
        return f"https://{self.storage_account}.dfs.core.windows.net"


def _get_service_client(config: DataLakeConfig):
    """
    Create a DataLakeServiceClient lazily.

    Rationale: Azure SDK imports are kept inside the function so unit tests that
    mock `load_parquet_range` don't require Azure packages to be installed.
    """

    try:
        from azure.identity import DefaultAzureCredential
        from azure.storage.filedatalake import DataLakeServiceClient
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "Azure packages are required to read from ADLS. "
            "Install `azure-identity` and `azure-storage-file-datalake`."
        ) from e

    credential = DefaultAzureCredential()
    return DataLakeServiceClient(config.account_url, credential)


def _iter_dates(start: date, end: date):
    if end < start:
        raise ValueError(f"end_date {end} < start_date {start}")
    cur = start
    one = timedelta(days=1)
    while cur <= end:
        yield cur
        cur += one


def _read_parquet_file(*, service, filesystem: str, path: str) -> pd.DataFrame:
    fs = service.get_file_system_client(filesystem)
    file_client = fs.get_file_client(path)
    data = file_client.download_file().readall()
    return pd.read_parquet(io.BytesIO(data))


def read_parquet(
    *,
    filesystem: str,
    path: str,
    config: Optional[DataLakeConfig] = None,
) -> pd.DataFrame:
    """
    Read a single parquet file from ADLS.

    Rationale: Many reference datasets (e.g., Maximo assets) are stored as a
    single parquet file rather than daily partitions. This helper keeps the
    calling adapters simple and keeps ADLS details encapsulated.
    """
    cfg = config or DataLakeConfig()
    service = _get_service_client(cfg)
    return _read_parquet_file(service=service, filesystem=filesystem, path=path)


def load_parquet_range(
    *,
    start: date,
    end: date,
    base_path: str,
    config: Optional[DataLakeConfig] = None,
) -> pd.DataFrame:
    """
    Load partitioned parquet files in date range:

        {base_path}/year=YYYY/month=MM/day=DD/*.parquet
    """
    cfg = config or DataLakeConfig()
    service = _get_service_client(cfg)
    fs = service.get_file_system_client(cfg.filesystem)

    dfs: list[pd.DataFrame] = []

    for d in _iter_dates(start, end):
        partition = f"{base_path}/year={d.year}/month={d.month:02d}/day={d.day:02d}"
        paths = [
            p.name
            for p in fs.get_paths(path=partition)
            if not p.is_directory and p.name.endswith(".parquet")
        ]
        for path in paths:
            print(f"[DATALAKE] {cfg.filesystem}/{path}")
            dfs.append(_read_parquet_file(service=service, filesystem=cfg.filesystem, path=path))

    if not dfs:
        raise FileNotFoundError(
            f"No parquet under {cfg.filesystem}/{base_path} between {start} and {end}"
        )

    return pd.concat(dfs, ignore_index=True)

