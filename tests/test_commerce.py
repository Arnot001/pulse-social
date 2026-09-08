from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from commerce.batch import ingest_discovery_payload
from commerce.store import CommerceStore
from commerce.tiktok import discover_products, normalize_product, product_urls


class TikTokCommerceTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "loaderData": {
                "page_config": {
                    "components_map": {
                        "gaming": {
                            "component_data": {
                                "categoryProductsData": {
                                    "productList": [
                                        {
                                            "product_id": "1729431846014848905",
                                            "product_name": "RTX 4060 Gaming PC",
                                            "price": "787.55",
                                            "sold_count": 2,
                                            "seo_url": {
                                                "canonical_url": "https://shop.tiktok.com/gb/pdp/1729431846014848905"
                                            },
                                        },
                                        {
                                            "product_id": "2002",
                                            "title": "Gaming controller",
                                            "sale_price": "23.95",
                                            "sold_count": 5,
                                        },
                                    ]
                                }
                            }
                        }
                    }
                }
            }
        }

    def test_discovers_unique_products(self):
        products = discover_products(self.payload)
        self.assertEqual([p["product_id"] for p in products], ["1729431846014848905", "2002"])

    def test_builds_canonical_urls(self):
        urls = product_urls(self.payload)
        self.assertEqual(urls[0], "https://shop.tiktok.com/gb/pdp/1729431846014848905")
        self.assertEqual(urls[1], "https://shop.tiktok.com/gb/pdp/2002")

    def test_normalizes_category_product(self):
        item = normalize_product(discover_products(self.payload)[0])
        self.assertEqual(item.product_id, "1729431846014848905")
        self.assertEqual(item.price, 787.55)
        self.assertEqual(item.sold_count, 2)

    def test_batch_ingest_records_all_products(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CommerceStore(Path(tmp) / "commerce.db")
            results = ingest_discovery_payload(self.payload, store)
            recorded = [r for r in results if r["status"] == "recorded"]
            self.assertEqual(len(recorded), 2)
            self.assertTrue(all(0 <= r["deal_score"] <= 100 for r in recorded))
            self.assertEqual(len(store.price_history("tiktok_shop", "1729431846014848905")), 1)


if __name__ == "__main__":
    unittest.main()
