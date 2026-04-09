from __future__ import annotations

import unittest


class TestMaximoAssetProvider(unittest.TestCase):
    def setUp(self) -> None:
        import sys

        if "htm-ev-simulator/src" not in sys.path:
            sys.path.insert(0, "htm-ev-simulator/src")

    def test_filter_bus_assets_rules(self) -> None:
        import pandas as pd

        from backend.infrastructure.maximo_asset_provider import MaximoAssetQuery, filter_bus_assets

        df = pd.DataFrame(
            [
                # valid
                {
                    "assetnum": "1500",
                    "htm_tramtype": "E-BUS",
                    "htm_vendor_serialnum": "WEB2863141M144820",
                    "isrunning": 1,
                    "max_charging_power_kw": 250.0,
                },
                # invalid serial prefix
                {
                    "assetnum": "1501",
                    "htm_tramtype": "E-BUS",
                    "htm_vendor_serialnum": "ABC123",
                    "isrunning": 1,
                },
                # non-numeric assetnum
                {
                    "assetnum": "not-a-number",
                    "htm_tramtype": "E-BUS",
                    "htm_vendor_serialnum": "WEBXXX",
                    "isrunning": 1,
                },
                # out of range
                {
                    "assetnum": "1700",
                    "htm_tramtype": "E-BUS",
                    "htm_vendor_serialnum": "WEBYYY",
                    "isrunning": 1,
                },
            ]
        )

        out = filter_bus_assets(df, query=MaximoAssetQuery(assetnum_min=1400, assetnum_max=1600))
        self.assertEqual(len(out), 1)
        self.assertEqual(int(out.iloc[0]["assetnum"]), 1500)
        self.assertTrue(str(out.iloc[0]["htm_vendor_serialnum"]).startswith("WEB"))
        self.assertIn("max_charging_power_kw", out.columns)
        self.assertAlmostEqual(float(out.iloc[0]["max_charging_power_kw"]), 250.0, places=6)


if __name__ == "__main__":
    unittest.main()

