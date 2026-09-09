from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from .scoring import score_deal
from .store import CommerceStore
from .tiktok import discover_products, normalize_product


def _change(current: float | int | None, previous: float | int | None):
    if current is None or previous is None:
        return None
    return current - previous


def _raw_product_id(raw_product: dict) -> str:
    return str(raw_product.get("product_id") or raw_product.get("productId") or "")


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _history_intelligence(item, history: list[dict], previous: dict | None) -> dict:
    prices = [float(row["effective_price"]) for row in history if row.get("effective_price") is not None]
    historical_low = min(prices) if prices else None
    historical_high = max(prices) if prices else None
    historical_median = median(prices) if prices else None
    is_new_low = historical_low is not None and item.effective_price < historical_low - 0.005

    elapsed_hours = None
    sales_velocity_per_day = None
    if previous:
        current_time = _parse_time(item.observed_at)
        previous_time = _parse_time(previous.get("observed_at"))
        if current_time and previous_time:
            seconds = (current_time - previous_time).total_seconds()
            if seconds > 0:
                elapsed_hours = seconds / 3600
                previous_sold = previous.get("sold_count")
                if item.sold_count is not None and previous_sold is not None:
                    sold_delta = item.sold_count - int(previous_sold)
                    sales_velocity_per_day = sold_delta / (seconds / 86400)

    return {
        "historical_low": historical_low,
        "historical_high": historical_high,
        "historical_median": historical_median,
        "is_new_low": is_new_low,
        "elapsed_hours": elapsed_hours,
        "sales_velocity_per_day": sales_velocity_per_day,
        "history_count": len(prices),
    }


def ingest_products(products: Iterable[dict], store: CommerceStore | None = None) -> list[dict]:
    """Normalize, compare, score and persist unique products once per sweep."""
    store = store or CommerceStore()
    results: list[dict] = []
    seen: set[str] = set()

    for raw_product in products:
        product_id = _raw_product_id(raw_product)
        if product_id and product_id in seen:
            continue
        if product_id:
            seen.add(product_id)

        try:
            item = normalize_product(raw_product)
        except (TypeError, ValueError) as exc:
            results.append({"status": "skipped", "product_id": product_id, "error": str(exc)})
            continue

        if item.product_id and item.product_id != product_id:
            if item.product_id in seen:
                continue
            seen.add(item.product_id)

        history = store.price_history(item.source, item.product_id)
        previous = store.latest_observation(item.source, item.product_id)
        intelligence = _history_intelligence(item, history, previous)
        score = score_deal(item, history)

        previous_price = previous.get("effective_price") if previous else None
        previous_sold = previous.get("sold_count") if previous else None
        price_change = _change(item.effective_price, previous_price)
        sold_change = _change(item.sold_count, previous_sold)
        price_change_pct = None
        if price_change is not None and previous_price:
            price_change_pct = (price_change / float(previous_price)) * 100

        observation_id = store.record(item)
        results.append({
            "status": "recorded",
            "observation_id": observation_id,
            "product_id": item.product_id,
            "title": item.title,
            "price": item.effective_price,
            "previous_price": previous_price,
            "price_change": price_change,
            "price_change_pct": price_change_pct,
            "sold_count": item.sold_count,
            "previous_sold_count": previous_sold,
            "sold_change": sold_change,
            "currency": item.currency,
            "deal_score": score.total,
            "score": asdict(score),
            "url": item.url,
            **intelligence,
        })

    return results


def ingest_discovery_payload(payload: Any, store: CommerceStore | None = None) -> list[dict]:
    """Discover and ingest every unique usable TikTok product in one payload."""
    return ingest_products(discover_products(payload), store)


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover and ingest TikTok Shop products from JSON")
    parser.add_argument("json_file", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.json_file.read_text(encoding="utf-8"))
    results = ingest_discovery_payload(payload)
    recorded = [r for r in results if r["status"] == "recorded"]
    skipped = [r for r in results if r["status"] == "skipped"]
    print(f"Discovered: {len(results)} | Recorded: {len(recorded)} | Skipped: {len(skipped)}")
    for result in sorted(recorded, key=lambda r: r["deal_score"], reverse=True):
        print(f"{result['deal_score']:>3}/100 | {result['currency']} {result['price']:.2f} | {result['title']} | {result['product_id']}")
    for result in skipped:
        print(f"SKIP | {result['product_id']} | {result['error']}")


if __name__ == "__main__":
    main()
