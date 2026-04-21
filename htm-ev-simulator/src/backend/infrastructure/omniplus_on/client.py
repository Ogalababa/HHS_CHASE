"""
OMNIplus ON OAuth2 client + signal fetcher.

Rationale: HTTP + OAuth2 are infrastructure concerns. The domain/core must not
depend on `requests` or environment variables. This module encapsulates the API
protocol and exposes typed Python methods that adapters can use to map API data
into domain entities.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from requests import Session

from ..env_loader import get_env
from .constants import SIGNAL_ID_TO_NAME, SIGNAL_IDS_DEFAULT

DEFAULT_TOKEN_URL = "https://omniplus-on.com/oauth/token"
DEFAULT_DATA_BASE_URL = "https://omniplus-on.com/data"
DEFAULT_SCOPE = "historic diagnosis"


@dataclass(slots=True)
class OmniplusAuthConfig:
    """OAuth2 configuration for OMNIplus ON."""

    client_id: str
    client_secret: str
    scope: str = DEFAULT_SCOPE
    token_url: str = DEFAULT_TOKEN_URL
    data_base_url: str = DEFAULT_DATA_BASE_URL


def ts_ms_to_datetime(ts_ms: int) -> datetime:
    """Convert milliseconds since epoch to UTC datetime."""
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)


class OmniplusOnClient:
    """OAuth2 client + data helper for OMNIplus ON."""

    def __init__(
        self,
        *,
        config: Optional[OmniplusAuthConfig] = None,
        session: Session | None = None,
        timeout: float = 10.0,
        auto_auth: bool = True,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout = float(timeout)

        if config is None:
            # Keep same behavior as ADLS helpers: prefer process env, then `.env`.
            client_id = os.getenv("CLIENT_ID") or get_env("CLIENT_ID")
            client_secret = os.getenv("CLIENT_SECRET") or get_env("CLIENT_SECRET")
            if not client_id or not client_secret:
                raise RuntimeError("Missing CLIENT_ID or CLIENT_SECRET for OMNIplus ON.")
            config = OmniplusAuthConfig(client_id=client_id, client_secret=client_secret)

        self.config = config
        self.data_base_url = config.data_base_url.rstrip("/")

        self._access_token: str | None = None
        self._token_expiry: datetime | None = None

        if auto_auth:
            self.get_token()

    def get_token(self, *, force_refresh: bool = False) -> str:
        """Retrieve an OAuth2 access token (cached until expiry)."""
        now = datetime.now(timezone.utc)
        if (
            not force_refresh
            and self._access_token
            and self._token_expiry
            and now < self._token_expiry
        ):
            return self._access_token

        credentials = f"{self.config.client_id}:{self.config.client_secret}".encode("utf-8")
        basic_auth = base64.b64encode(credentials).decode("utf-8")

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "Authorization": f"Basic {basic_auth}",
        }
        data = {"grant_type": "client_credentials", "scope": self.config.scope}

        response = self.session.post(
            self.config.token_url,
            headers=headers,
            data=data,
            timeout=self.timeout,
        )
        response.raise_for_status()

        payload = response.json()
        access_token = payload.get("access_token")
        expires_in = payload.get("expires_in", 3600)
        if not access_token:
            raise RuntimeError(f"Token response missing access_token: {payload}")

        self._access_token = str(access_token)
        self._token_expiry = now + timedelta(seconds=int(expires_in) - 60)
        return self._access_token

    def get_latest_signals(self, vins: list[str], *, signal_ids: list[int] | None = None) -> dict[str, dict]:
        """Fetch latest signals for VINs; returns dict keyed by VIN."""
        params: list[tuple[str, str]] = []
        for vin in vins:
            params.append(("vins", vin))
        for sid in (signal_ids or SIGNAL_IDS_DEFAULT):
            params.append(("signals", str(sid)))

        headers = {"Accept": "application/json", "Authorization": f"Bearer {self.get_token()}"}
        resp = self.session.get(
            f"{self.data_base_url}/v2/signals/latest",
            headers=headers,
            params=params,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        raw = resp.json()

        result: dict[str, dict] = {}
        ts_buffer: dict[str, list[int]] = {}

        for entry in raw:
            vin = entry.get("vin")
            signal_id = entry.get("id")
            values = entry.get("values", [])
            if not vin or not values:
                continue

            signal_name = SIGNAL_ID_TO_NAME.get(signal_id)
            if not signal_name:
                continue

            latest = values[0]
            value = latest.get("value")
            ts = latest.get("timestamp")

            if vin not in result:
                result[vin] = {"vin": vin}
                ts_buffer[vin] = []

            result[vin][signal_name] = value
            if isinstance(ts, int):
                ts_buffer[vin].append(ts)

        for vin, timestamps in ts_buffer.items():
            result[vin]["first_update_dt"] = ts_ms_to_datetime(min(timestamps)) if timestamps else None
            result[vin]["last_update_dt"] = ts_ms_to_datetime(max(timestamps)) if timestamps else None

        return result

