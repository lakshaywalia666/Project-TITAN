"""Persistent order workflow with idempotency, price integrity and fraud checks."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, Mapping

from titan_control.domain import canonical_json, new_id, utc_now
from titan_workloads.fraud import FraudFeatures, FraudModel


class ShopError(RuntimeError):
    pass


class ProductNotFound(ShopError):
    pass


class OrderConflict(ShopError):
    pass


SHOP_SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    sku TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    price_paise INTEGER NOT NULL CHECK(price_paise >= 0),
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    state TEXT NOT NULL,
    total_paise INTEGER NOT NULL,
    fraud_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS order_items (
    order_id TEXT NOT NULL REFERENCES orders(id),
    sku TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price_paise INTEGER NOT NULL,
    PRIMARY KEY(order_id, sku)
);
CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL UNIQUE REFERENCES orders(id),
    amount_paise INTEGER NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS order_idempotency (
    customer_id TEXT NOT NULL,
    key TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    order_id TEXT NOT NULL REFERENCES orders(id),
    PRIMARY KEY(customer_id, key)
);
"""


class ShopStore:
    def __init__(self, path: str | Path, fraud_model: FraudModel | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fraud_model = fraud_model or FraudModel()
        with closing(self._connect()) as connection:
            connection.executescript(SHOP_SCHEMA)
            connection.executemany(
                "INSERT OR IGNORE INTO products(sku, name, price_paise) VALUES(?, ?, ?)",
                (
                    ("TITAN-TEE", "Titan systems tee", 149_900),
                    ("SRE-NOTE", "Incident notebook", 39_900),
                    ("GPU-MUG", "GPU queue mug", 59_900),
                ),
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_products(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT sku, name, price_paise FROM products WHERE active = 1 ORDER BY sku"
            ).fetchall()
        return [dict(row) for row in rows]

    def create_order(
        self,
        *,
        customer_id: str,
        project_id: str,
        items: tuple[Mapping[str, Any], ...],
        idempotency_key: str,
        account_age_days: int = 30,
        country_mismatch: bool = False,
    ) -> dict[str, Any]:
        if not customer_id or not project_id or not idempotency_key:
            raise ShopError("customer, project and idempotency key are required")
        if not items or len(items) > 50:
            raise ShopError("an order must contain between 1 and 50 items")
        normalized: list[dict[str, Any]] = []
        for item in items:
            sku = str(item.get("sku", ""))
            quantity = int(item.get("quantity", 0))
            if not sku or not 1 <= quantity <= 20:
                raise ShopError("each item requires a SKU and quantity from 1 to 20")
            normalized.append({"sku": sku, "quantity": quantity})
        normalized.sort(key=lambda item: item["sku"])
        if len({item["sku"] for item in normalized}) != len(normalized):
            raise ShopError("duplicate SKUs must be combined by the caller")
        request = {
            "project_id": project_id,
            "items": normalized,
            "account_age_days": account_age_days,
            "country_mismatch": country_mismatch,
        }
        fingerprint = hashlib.sha256(canonical_json(request).encode("utf-8")).hexdigest()

        with self.transaction() as connection:
            previous = connection.execute(
                "SELECT fingerprint, order_id FROM order_idempotency WHERE customer_id = ? AND key = ?",
                (customer_id, idempotency_key),
            ).fetchone()
            if previous is not None:
                if previous["fingerprint"] != fingerprint:
                    raise OrderConflict("idempotency key was reused with different order data")
                return self._get_order(connection, previous["order_id"])

            priced_items: list[dict[str, Any]] = []
            total_paise = 0
            for item in normalized:
                product = connection.execute(
                    "SELECT sku, name, price_paise FROM products WHERE sku = ? AND active = 1",
                    (item["sku"],),
                ).fetchone()
                if product is None:
                    raise ProductNotFound(f"active product not found: {item['sku']}")
                unit_price = int(product["price_paise"])
                total_paise += unit_price * item["quantity"]
                priced_items.append(
                    {
                        "sku": item["sku"],
                        "quantity": item["quantity"],
                        "unit_price_paise": unit_price,
                    }
                )

            velocity = connection.execute(
                "SELECT COUNT(*) FROM orders WHERE customer_id = ? AND created_at >= ?",
                (customer_id, (datetime.now(UTC) - timedelta(hours=1)).isoformat()),
            ).fetchone()[0]
            prediction = self.fraud_model.predict(
                FraudFeatures(
                    amount_paise=total_paise,
                    account_age_days=account_age_days,
                    orders_last_hour=int(velocity),
                    country_mismatch=country_mismatch,
                )
            )
            state = {"allow": "PAID", "review": "REVIEW", "deny": "REJECTED"}[
                prediction.decision
            ]
            order_id = new_id("ord")
            now = utc_now()
            connection.execute(
                "INSERT INTO orders VALUES(?, ?, ?, ?, ?, ?, ?)",
                (
                    order_id,
                    customer_id,
                    project_id,
                    state,
                    total_paise,
                    canonical_json(prediction.to_dict()),
                    now,
                ),
            )
            connection.executemany(
                "INSERT INTO order_items VALUES(?, ?, ?, ?)",
                (
                    (order_id, item["sku"], item["quantity"], item["unit_price_paise"])
                    for item in priced_items
                ),
            )
            if state == "PAID":
                connection.execute(
                    "INSERT INTO payments VALUES(?, ?, ?, 'CAPTURED', ?)",
                    (new_id("pay"), order_id, total_paise, now),
                )
            connection.execute(
                "INSERT INTO order_idempotency VALUES(?, ?, ?, ?)",
                (customer_id, idempotency_key, fingerprint, order_id),
            )
            return self._get_order(connection, order_id)

    def get_order(self, order_id: str, *, customer_id: str | None = None) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            order = self._get_order(connection, order_id)
        if customer_id is not None and order["customer_id"] != customer_id:
            raise ProductNotFound("order not found")
        return order

    @staticmethod
    def _get_order(connection: sqlite3.Connection, order_id: str) -> dict[str, Any]:
        row = connection.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if row is None:
            raise ProductNotFound("order not found")
        document = dict(row)
        document["fraud"] = json.loads(document.pop("fraud_json"))
        document["items"] = [
            dict(item)
            for item in connection.execute(
                "SELECT sku, quantity, unit_price_paise FROM order_items WHERE order_id = ? ORDER BY sku",
                (order_id,),
            ).fetchall()
        ]
        payment = connection.execute(
            "SELECT id, state, amount_paise FROM payments WHERE order_id = ?", (order_id,)
        ).fetchone()
        document["payment"] = dict(payment) if payment is not None else None
        return document
