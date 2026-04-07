from __future__ import annotations

import unittest
from datetime import datetime, timezone


class _FakeResponse:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, *, token_payload, latest_payload):
        self._token_payload = token_payload
        self._latest_payload = latest_payload
        self.post_calls = []
        self.get_calls = []

    def post(self, url, *, headers=None, data=None, timeout=None):
        self.post_calls.append({"url": url, "headers": headers, "data": data, "timeout": timeout})
        return _FakeResponse(self._token_payload)

    def get(self, url, *, headers=None, params=None, timeout=None):
        self.get_calls.append({"url": url, "headers": headers, "params": params, "timeout": timeout})
        return _FakeResponse(self._latest_payload)


class TestOmniplusOnClient(unittest.TestCase):
    def setUp(self) -> None:
        import sys

        if "htm-ev-simulator/src" not in sys.path:
            sys.path.insert(0, "htm-ev-simulator/src")

    def test_get_latest_signals_maps_ids_and_timestamps(self) -> None:
        from backend.infrastructure.omniplus_on.client import OmniplusAuthConfig, OmniplusOnClient

        vin = "VIN123"
        now_ms = 1_700_000_000_000
        later_ms = now_ms + 60_000

        token_payload = {"access_token": "token123", "expires_in": 3600}
        latest_payload = [
            # Known id -> mapped
            {"vin": vin, "id": 4157, "values": [{"timestamp": now_ms, "value": 81.5}]},
            {"vin": vin, "id": 264, "values": [{"timestamp": later_ms, "value": 10.0}]},
            # Unknown id -> ignored
            {"vin": vin, "id": 9999, "values": [{"timestamp": now_ms, "value": 123}]},
            # Missing values -> ignored
            {"vin": vin, "id": 261, "values": []},
        ]

        session = _FakeSession(token_payload=token_payload, latest_payload=latest_payload)
        client = OmniplusOnClient(
            config=OmniplusAuthConfig(client_id="id", client_secret="secret"),
            session=session,  # type: ignore[arg-type]
            auto_auth=False,
        )

        out = client.get_latest_signals([vin])
        self.assertIn(vin, out)
        self.assertEqual(out[vin]["vin"], vin)
        self.assertEqual(out[vin]["SOCdispCval"], 81.5)
        self.assertEqual(out[vin]["MomChargeEnergy"], 10.0)
        self.assertNotIn("9999", out[vin])

        self.assertIsInstance(out[vin]["first_update_dt"], datetime)
        self.assertIsInstance(out[vin]["last_update_dt"], datetime)
        self.assertEqual(out[vin]["first_update_dt"].tzinfo, timezone.utc)
        self.assertEqual(out[vin]["last_update_dt"].tzinfo, timezone.utc)
        self.assertLessEqual(out[vin]["first_update_dt"], out[vin]["last_update_dt"])

    def test_token_is_cached(self) -> None:
        from backend.infrastructure.omniplus_on.client import OmniplusAuthConfig, OmniplusOnClient

        session = _FakeSession(
            token_payload={"access_token": "token123", "expires_in": 3600},
            latest_payload=[],
        )
        client = OmniplusOnClient(
            config=OmniplusAuthConfig(client_id="id", client_secret="secret"),
            session=session,  # type: ignore[arg-type]
            auto_auth=False,
        )

        t1 = client.get_token()
        t2 = client.get_token()
        self.assertEqual(t1, t2)
        self.assertEqual(len(session.post_calls), 1)


class TestOmniplusBusProvider(unittest.TestCase):
    def setUp(self) -> None:
        import sys

        if "htm-ev-simulator/src" not in sys.path:
            sys.path.insert(0, "htm-ev-simulator/src")

    def test_bus_provider_maps_signals_to_bus(self) -> None:
        from backend.infrastructure.omniplus_bus_provider import OmniplusBusProvider
        from backend.infrastructure.omniplus_on.client import OmniplusAuthConfig, OmniplusOnClient

        vin = "VIN123"
        session = _FakeSession(
            token_payload={"access_token": "token123", "expires_in": 3600},
            latest_payload=[
                {"vin": vin, "id": 4157, "values": [{"timestamp": 1, "value": 80.0}]},  # SOCdispCval
                {"vin": vin, "id": 264, "values": [{"timestamp": 1, "value": 100.0}]},  # MomChargeEnergy
                {"vin": vin, "id": 265, "values": [{"timestamp": 1, "value": 200.0}]},  # MomDischargeEnergy
                {"vin": vin, "id": 261, "values": [{"timestamp": 1, "value": 1.2}]},  # AverageEnergyConsumption
            ],
        )
        client = OmniplusOnClient(
            config=OmniplusAuthConfig(client_id="id", client_secret="secret"),
            session=session,  # type: ignore[arg-type]
            auto_auth=False,
        )

        provider = OmniplusBusProvider(client=client, vins=[vin])
        buses = provider.get_buses()
        self.assertEqual(len(buses), 1)
        bus = buses[0]
        self.assertEqual(bus.vin_number, vin)
        self.assertAlmostEqual(bus.soc_percent, 80.0, places=6)
        # Inferred capacity = mom_charge + mom_discharge
        self.assertAlmostEqual(bus.battery_capacity_kwh, 300.0, places=6)


if __name__ == "__main__":
    unittest.main()

