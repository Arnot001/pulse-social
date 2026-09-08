from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .scoring import score_deal
from .store import CommerceStore
from .tiktok import discover_products, normalize_product


def ingest_discovery_payload(payload: Any, store: CommerceStore | None = None) -> list[dict]:
    """Discover, normalize, score and persist every usable TikTok product."""
    store = store or CommerceStore()
    results: list[dict] = []

    for raw_product in discover_products(payload):
        try:
            item = normalize_product(raw_product)
        except (TypeError, ValueError) as exc:
            results.append({
                "status": "skipped",
                "product_id": str(raw_product.get("product_id") or raw_product.get("productId") or ""),
                "error": str(exc),
            })
            continue

        history = store.price_history(item.source, item.product_id)
        score = score_deal(item, history)
        observation_id = store.record(item)
        results.append({
            "status": "recorded",
            "observation_id": observation_id,
            "product_id": item.product_id,
            "title": item.title,
            "price": item.effective_price,
            "currency": item.currency,
            "deal_score": score.total,
            "score": asdict(score),
            "url": item.url,
        })

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover and ingest TikTok Shop products from a PDH/category JSON capture"
    )
    parser.add_argument("json_file", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.json_file.read_text(encoding="utf-8"))
    results = ingest_discovery_payload(payload)
    recorded = [r for r in results if r["status"] == "recorded"]
    skipped = [r for r in results if r["status"] == "skipped"]

    print(f"Discovered: {len(results)} | Recorded: {len(recorded)} | Skipped: {len(skipped)}")
    for result in sorted(recorded, key=lambda r: r["deal_score"], reverse=True):
        print(
            f"{result['deal_score']:>3}/100 | {result['currency']} {result['price']:.2f} | "
            f"{result['title']} | {result['product_id']}"
        )
    for result in skipped:
        print(f"SKIP | {result['product_id']} | {result['error']}")


if __name__ == "__main__":
    main()
