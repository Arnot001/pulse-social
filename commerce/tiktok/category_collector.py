from __future__ import annotations

import argparse
import json
import math
import re
import time
from typing import Any
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

from platforms.pdh_bridge import pdh_request

from ..batch import ingest_products
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
    payloads = []
    for body in _SCRIPT_RE.findall(html):
        text = body.strip()
        if not text or text[0] not in "[{":
            continue
        try:
            payloads.append(json.loads(text))
        except json.JSONDecodeError:
            continue
    return payloads


def unique_products_from_payloads(payloads: list[Any]) -> list[dict]:
    """Aggregate a category sweep before any database writes occur."""
    products: list[dict] = []
    seen: set[str] = set()
    for payload in payloads:
        for product in discover_products(payload):
            product_id = str(product.get("product_id") or product.get("productId") or "")
            if product_id and product_id in seen:
                continue
            if product_id:
                seen.add(product_id)
            products.append(product)
    return products


class CategoryCollection(list):
    """List-compatible ingestion results plus browser collection completeness."""

    def __init__(self, results, metadata):
        super().__init__(results)
        self.complete = metadata.get("complete") is True
        self.stop_reason = metadata.get("stopReason", "UNVERIFIED")
        self.product_count = len(metadata.get("products", []))
        self.clicks = metadata.get("clicks", 0)
        self.duration_ms = metadata.get("durationMs", 0)
        self.data_complete = metadata.get("dataComplete") is True
        self.incomplete_product_count = metadata.get("incompleteProductCount", 0)
        self.rejected_product_count = metadata.get("rejectedProductCount", 0)
        self.ingestion_complete = metadata.get("ingestionComplete", True)
        self.skipped_product_count = metadata.get("skippedProductCount", 0)


def request_category(url: str | None = None) -> dict:
    """Ask PDH once. No TikTok HTTP fallback, browser launch, or auth handling."""
    payload = {}
    if url:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.netloc != "shop.tiktok.com"
                or parsed.query or parsed.fragment
                or not re.fullmatch(r"/gb/c/[^/]+/\d+/?", parsed.path)):
            raise ValueError("Use a plain https://shop.tiktok.com/gb/c/<slug>/<id> category URL.")
        payload["url"] = url.rstrip("/")
    result = pdh_request("tiktok.shop_category", payload, timeout=50.0)
    if not isinstance(result, dict):
        return {"products": [], "complete": False, "stopReason": "BRIDGE_NO_RESPONSE"}
    if not isinstance(result.get("products"), list):
        return {"products": [], "complete": False, "stopReason": "INVALID_PDH_RESULT"}
    # Defense in depth: persist only known commerce fields, never raw page payloads.
    products = {}
    rejected_count = 0
    for raw in result["products"]:
        if not isinstance(raw, dict):
            rejected_count += 1
            continue
        product_id = str(raw.get("product_id") or "")
        if not re.fullmatch(r"\d+", product_id):
            rejected_count += 1
            continue
        previous = products.get(product_id, {})
        price = raw.get("price")
        if type(price) not in (int, float) or not math.isfinite(price) or price < 0:
            price = previous.get("price")
        products[product_id] = {
            "product_id": product_id, "title": str(raw.get("title") or previous.get("title") or "")[:500],
            "price": price,
            "currency": "GBP", "url": f"https://shop.tiktok.com/gb/pdp/{product_id}",
        }
    reason = str(result.get("stopReason") or "UNVERIFIED")
    reason = reason if re.fullmatch(r"[A-Z_]{1,60}", reason) else "UNVERIFIED"

    local_incomplete_count = sum(
        not product["title"] or product["price"] is None
        for product in products.values()
    )
    pdh_incomplete_count = result.get("incompleteProductCount")
    if type(pdh_incomplete_count) is int and pdh_incomplete_count >= 0:
        incomplete_product_count = max(local_incomplete_count, pdh_incomplete_count)
    else:
        incomplete_product_count = local_incomplete_count

    pdh_data_complete = result.get("dataComplete")
    if type(pdh_data_complete) is bool:
        data_complete = (
            pdh_data_complete
            and incomplete_product_count == 0
            and rejected_count == 0
        )
    else:
        data_complete = incomplete_product_count == 0 and rejected_count == 0

    # Pagination completeness belongs to PDH. Missing/ambiguous product fields
    # are reported separately and must never rewrite a verified END_OF_LIST.
    complete = (
        result.get("complete") is True
        and reason == "END_OF_LIST"
        and bool(products)
    )

    return {"products": list(products.values()),
            "complete": complete,
            "dataComplete": data_complete,
            "incompleteProductCount": incomplete_product_count,
            "rejectedProductCount": rejected_count,
            "stopReason": reason,
            "clicks": result.get("clicks") if type(result.get("clicks")) is int else 0,
            "durationMs": result.get("durationMs") if type(result.get("durationMs")) in (int, float) else 0,
            "browserStage": str(result.get("browserStage") or "")[:80],
            "browserError": str(result.get("browserError") or "")[:300]}


def collect_category(url: str, store: CommerceStore | None = None, html: str | None = None) -> CategoryCollection:
    if html is not None:
        # Explicit offline fixtures/imports remain supported; never claim completeness.
        metadata = {"products": unique_products_from_payloads(extract_json_payloads(html)),
                    "complete": False, "stopReason": "STATIC_SNAPSHOT"}
    else:
        metadata = request_category(url)
    results = ingest_products(metadata["products"], store or CommerceStore()) if metadata["products"] else []
    skipped_count = sum(item.get("status") == "skipped" for item in results)
    metadata = {
        **metadata,
        "ingestionComplete": skipped_count == 0,
        "skippedProductCount": skipped_count,
    }
    return CategoryCollection(results, metadata)


def category_summary(results: CategoryCollection) -> str:
    recorded = sum(item.get("status") == "recorded" for item in results)
    skipped = sum(item.get("status") == "skipped" for item in results)
    state = "COMPLETE" if results.complete else "PARTIAL"
    return (f"{state} // {results.product_count} COLLECTED // {recorded} RECORDED // "
            f"{skipped} SKIPPED // {results.stop_reason}")


def diagnose_category(url: str) -> tuple[list[dict], list[dict]]:
    results = collect_category(url)
    diagnostics = [
        {k: product.get(k) for k in (
            "product_id", "title", "product_price_info", "sku_info", "sold_info",
            "rate_info", "seller_info", "product_marketing_info"
        )}
        for product in results
    ]
    return results, diagnostics


def _change_text(item: dict) -> str:
    bits = []
    price_change = item.get("price_change")
    pct = item.get("price_change_pct")
    if price_change is not None and abs(price_change) >= 0.005:
        arrow = "DROP" if price_change < 0 else "RISE"
        bits.append(f"{arrow} {price_change:+.2f} ({pct:+.1f}%)")
    sold_change = item.get("sold_change")
    if sold_change is not None and sold_change != 0:
        bits.append(f"SOLD {sold_change:+d}")
    return " | ".join(bits)


def _print_item(item: dict) -> None:
    change = _change_text(item)
    suffix = f" | {change}" if change else ""
    print(f"{item['deal_score']:>3}/100 | {item['currency']} {item['price']:.2f} | {item['title']} | {item['product_id']}{suffix}")


def watch_category(url: str, interval: int = 900, store: CommerceStore | None = None) -> None:
    store = store or CommerceStore()
    while True:
        started = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            results = collect_category(url, store)
            recorded = [r for r in results if r.get("status") == "recorded"]
            changed = [r for r in recorded if r.get("price_change") not in (None, 0) or r.get("sold_change") not in (None, 0)]
            print(f"[{started}] {category_summary(results)} | changed {len(changed)}")
            for item in sorted(changed, key=lambda r: (r.get("price_change_pct") or 0, -r["deal_score"])):
                _print_item(item)
        except Exception as exc:
            print(f"[{started}] category sweep failed: {exc}")
        time.sleep(max(60, interval))


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect TikTok Shop through PDH's browser-owned View more loop")
    parser.add_argument("url", nargs="?", help="Plain category URL; omitted uses the single open Shop category tab")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=int, default=900)
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--read-only", action="store_true", help="One browser collection; print counts only, with no database writes")
    args = parser.parse_args()
    if args.read_only:
        result = request_category(args.url)
        print(json.dumps({"complete": result["complete"], "stopReason": result["stopReason"],
                          "dataComplete": result.get("dataComplete", False),
                          "incompleteProductCount": result.get("incompleteProductCount", 0),
                          "rejectedProductCount": result.get("rejectedProductCount", 0),
                          "productCount": len(result["products"]), "clicks": result.get("clicks", 0),
                          "durationMs": result.get("durationMs", 0),
                          "browserStage": result.get("browserStage", ""),
                          "browserError": result.get("browserError", "")}, indent=2))
        return
    if not args.url:
        parser.error("url is required unless --read-only is used")
    if args.watch:
        watch_category(args.url, args.interval)
        return
    if args.diagnose:
        results, diagnostics = diagnose_category(args.url)
    else:
        results, diagnostics = collect_category(args.url), []
    recorded = [r for r in results if r.get("status") == "recorded"]
    skipped = [r for r in results if r.get("status") == "skipped"]
    changed = [r for r in recorded if r.get("price_change") not in (None, 0) or r.get("sold_change") not in (None, 0)]
    print(f"{category_summary(results)} | Changed: {len(changed)}")
    for item in sorted(recorded, key=lambda r: r["deal_score"], reverse=True):
        _print_item(item)
    for item in skipped[:10]:
        print(f"SKIP | {item.get('product_id', '')} | {item.get('error', 'unknown error')}")
    if diagnostics:
        print("\nNESTED PRODUCT DATA (first 3)")
        for item in diagnostics[:3]:
            print(json.dumps(item, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
