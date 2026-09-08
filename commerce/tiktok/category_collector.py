from __future__ import annotations

import argparse
import json
import re
import time
from typing import Any
from urllib.request import Request, urlopen

from ..batch import ingest_discovery_payload
from ..store import CommerceStore
from .discovery import discover_products

_SCRIPT_RE = re.compile(r"<script[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)


def fetch_category_page(url: str, timeout: int = 30) -> str:
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
        "Accept-Language": "en-GB,en;q=0.9",
    })
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def extract_json_payloads(html: str) -> list[Any]:
    payloads: list[Any] = []
    for body in _SCRIPT_RE.findall(html):
        text = body.strip()
        if not text or text[0] not in "[{":
            continue
        try:
            payloads.append(json.loads(text))
        except json.JSONDecodeError:
            continue
    return payloads


def collect_category(url: str, store: CommerceStore | None = None, html: str | None = None) -> list[dict]:
    store = store or CommerceStore()
    html = html if html is not None else fetch_category_page(url)
    results: list[dict] = []
    seen: set[str] = set()
    for payload in extract_json_payloads(html):
        for result in ingest_discovery_payload(payload, store):
            product_id = result.get("product_id", "")
            if product_id and product_id in seen:
                continue
            if product_id:
                seen.add(product_id)
            results.append(result)
    return results


def diagnose_category(url: str) -> tuple[list[dict], list[dict]]:
    html = fetch_category_page(url)
    payloads = extract_json_payloads(html)
    results = collect_category(url, html=html)
    diagnostics: list[dict] = []
    seen: set[str] = set()
    for payload in payloads:
        for product in discover_products(payload):
            product_id = str(product.get("product_id") or product.get("productId") or "")
            if not product_id or product_id in seen:
                continue
            seen.add(product_id)
            diagnostics.append({
                "product_id": product_id,
                "title": product.get("title"),
                "product_price_info": product.get("product_price_info"),
                "sku_info": product.get("sku_info"),
                "sold_info": product.get("sold_info"),
                "rate_info": product.get("rate_info"),
                "seller_info": product.get("seller_info"),
                "product_marketing_info": product.get("product_marketing_info"),
            })
    return results, diagnostics


def watch_category(url: str, interval: int = 900, store: CommerceStore | None = None) -> None:
    store = store or CommerceStore()
    while True:
        started = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            results = collect_category(url, store)
            recorded = [r for r in results if r.get("status") == "recorded"]
            print(f"[{started}] recorded {len(recorded)} products from {url}")
            for item in sorted(recorded, key=lambda r: r["deal_score"], reverse=True)[:10]:
                print(f"  {item['deal_score']:>3}/100 | {item['currency']} {item['price']:.2f} | {item['title']}")
        except Exception as exc:
            print(f"[{started}] category sweep failed: {exc}")
        time.sleep(max(60, interval))


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect a public TikTok Shop category page")
    parser.add_argument("url")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=int, default=900)
    parser.add_argument("--diagnose", action="store_true")
    args = parser.parse_args()
    if args.watch:
        watch_category(args.url, args.interval)
        return
    if args.diagnose:
        results, diagnostics = diagnose_category(args.url)
    else:
        results, diagnostics = collect_category(args.url), []
    recorded = [r for r in results if r.get("status") == "recorded"]
    skipped = [r for r in results if r.get("status") == "skipped"]
    print(f"Recorded: {len(recorded)} | Skipped: {len(skipped)}")
    for item in sorted(recorded, key=lambda r: r["deal_score"], reverse=True):
        print(f"{item['deal_score']:>3}/100 | {item['currency']} {item['price']:.2f} | {item['title']} | {item['product_id']}")
    for item in skipped[:10]:
        print(f"SKIP | {item.get('product_id', '')} | {item.get('error', 'unknown error')}")
    if diagnostics:
        print("\nNESTED PRODUCT DATA (first 3)")
        for item in diagnostics[:3]:
            print(json.dumps(item, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
