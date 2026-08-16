from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from titan_workloads.fraud import FraudFeatures, FraudModel
from titan_workloads.shop_api import ShopSettings
from titan_workloads.shop import OrderConflict, ShopStore


class FraudModelTests(unittest.TestCase):
    def test_high_risk_combination_is_denied_and_explained(self) -> None:
        prediction = FraudModel().predict(
            FraudFeatures(
                amount_paise=5_000_000,
                account_age_days=1,
                orders_last_hour=8,
                country_mismatch=True,
            )
        )
        self.assertEqual("deny", prediction.decision)
        self.assertIn("country_mismatch", prediction.reasons)


class ShopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = ShopStore(Path(self.temporary_directory.name) / "shop.db")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_price_comes_from_catalog_and_payment_is_idempotent(self) -> None:
        request = {
            "customer_id": "alice",
            "project_id": "local",
            "items": ({"sku": "SRE-NOTE", "quantity": 2},),
            "idempotency_key": "alice-order-1",
        }
        first = self.store.create_order(**request)
        second = self.store.create_order(**request)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(79_800, first["total_paise"])
        self.assertEqual("CAPTURED", first["payment"]["state"])

    def test_idempotency_key_cannot_hide_different_order(self) -> None:
        self.store.create_order(
            customer_id="alice",
            project_id="local",
            items=({"sku": "SRE-NOTE", "quantity": 1},),
            idempotency_key="stable-key",
        )
        with self.assertRaises(OrderConflict):
            self.store.create_order(
                customer_id="alice",
                project_id="local",
                items=({"sku": "GPU-MUG", "quantity": 1},),
                idempotency_key="stable-key",
            )

    def test_high_risk_order_is_not_charged(self) -> None:
        order = self.store.create_order(
            customer_id="new-account",
            project_id="local",
            items=({"sku": "TITAN-TEE", "quantity": 20},),
            idempotency_key="risky-order",
            account_age_days=0,
            country_mismatch=True,
        )
        self.assertEqual("REJECTED", order["state"])
        self.assertIsNone(order["payment"])


class ShopSettingsTests(unittest.TestCase):
    def test_environment_controls_bounded_http_settings(self) -> None:
        settings = ShopSettings.from_environ(
            {
                "TITAN_SHOP_HOST": "127.0.0.2",
                "TITAN_SHOP_PORT": "8300",
                "TITAN_SHOP_DATABASE": "var/custom-shop.db",
                "TITAN_SHOP_MAX_REQUEST_BYTES": "8192",
                "TITAN_CORS_ALLOWED_ORIGINS": "https://portal.example",
            }
        )
        self.assertEqual("127.0.0.2", settings.host)
        self.assertEqual(8_192, settings.max_request_bytes)
        self.assertEqual(("https://portal.example",), settings.allowed_origins)

    def test_empty_database_path_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ShopSettings.from_environ({"TITAN_SHOP_DATABASE": " "})


if __name__ == "__main__":
    unittest.main()
