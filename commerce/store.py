from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from .models import ProductObservation


DEFAULT_DB = Path(os.environ.get("LOCALAPPDATA", ".")) / "Pulse Social" / "commerce.db"


class CommerceStore:
    def __init__(self, path: str | Path = DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def _init_db(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    sku_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL,
                    seller_id TEXT NOT NULL DEFAULT '',
                    seller_name TEXT NOT NULL DEFAULT '',
                    price REAL NOT NULL,
                    effective_price REAL NOT NULL,
                    original_price REAL,
                    currency TEXT NOT NULL,
                    sold_count INTEGER,
                    rating REAL,
                    review_count INTEGER,
                    category TEXT NOT NULL DEFAULT '',
                    stock INTEGER,
                    variant TEXT NOT NULL DEFAULT '',
                    url TEXT NOT NULL DEFAULT '',
                    specs_json TEXT NOT NULL DEFAULT '{}',
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    observed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_observations_product
                    ON observations(source, product_id, sku_id, observed_at);
                """
            )

    def record(self, item: ProductObservation) -> int:
        with self.connect() as db:
            cur = db.execute(
                """
                INSERT INTO observations (
                    source, product_id, sku_id, title, seller_id, seller_name,
                    price, effective_price, original_price, currency, sold_count,
                    rating, review_count, category, stock, variant, url,
                    specs_json, raw_json, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.source, item.product_id, item.sku_id, item.title,
                    item.seller_id, item.seller_name, item.price,
                    item.effective_price, item.original_price, item.currency,
                    item.sold_count, item.rating, item.review_count,
                    item.category, item.stock, item.variant, item.url,
                    json.dumps(item.specs, ensure_ascii=False),
                    json.dumps(item.raw, ensure_ascii=False), item.observed_at,
                ),
            )
            return int(cur.lastrowid)

    def price_history(self, source: str, product_id: str, limit: int = 200) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT effective_price, price, original_price, sold_count, observed_at
                FROM observations
                WHERE source = ? AND product_id = ?
                ORDER BY observed_at DESC LIMIT ?
                """,
                (source, product_id, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]
