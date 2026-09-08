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
            "loaderData": {"page_config": {"components_map": {"gaming": {"component_data": {
                "categoryProductsData": {"productList": [
                    {"product_id": "1729431846014848905", "product_name": "RTX 4060 Gaming PC", "price": "787.55", "sold_count": 2, "seo_url": {"canonical_url": "https://shop.tiktok.com/gb/pdp/1729431846014848905"}},
                    {"product_id": "2002", "title": "Gaming controller", "sale_price": "23.95", "sold_count": 5},
                ]}
            }}}}}
        }
        self.live_product = {
            "product_id": "1729553894309993373",
            "title": "FIFINE D6 Macro Keyboard",
            "product_price_info": {
                "sku_id": "1729553894310058909",
                "currency_name": "GBP",
                "currency_symbol": "£",
                "sale_price_decimal": "72.99",
                "origin_price_decimal": "89.99",
                "discount_decimal": "0.19",
            },
            "sold_info": {"sold_count": 469},
            "rate_info": {"score": 4.9, "review_count": "37"},
            "seller_info": {"seller_id": "7496151571180456861", "shop_name": "Fifine Shop"},
            "seo_url": {"canonical_url": "https://shop.tiktok.com/gb/pdp/1729553894309993373"},
            "sku_info": [{"SkuId": "1729553894310058909", "PriceInfo": {"sale_price_decimal": "72.99"}}],
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

    def test_normalizes_live_nested_category_product(self):
        item = normalize_product(self.live_product)
        self.assertEqual(item.price, 72.99)
        self.assertEqual(item.original_price, 89.99)
        self.assertEqual(item.currency, "GBP")
        self.assertEqual(item.sku_id, "1729553894310058909")
        self.assertEqual(item.sold_count, 469)
        self.assertEqual(item.rating, 4.9)
        self.assertEqual(item.review_count, 37)
        self.assertEqual(item.seller_id, "7496151571180456861")
        self.assertEqual(item.seller_name, "Fifine Shop")

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
