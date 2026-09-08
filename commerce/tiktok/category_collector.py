from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from ..batch import ingest_discovery_payload
from ..store import CommerceStore

_SCRIPT_RE = re.compile(r"<script[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)


def fetch_category_page(url: str, timeout: int = 30) -> str:
    """Fetch a public TikTok Shop category page without cookies or auth tokens."""
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/152.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-GB,en;q=0.9",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def extract_json_payloads(html: str) -> list[Any]:
    """Extract JSON-bearing script blocks from server-rendered Shop HTML."""
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


def collect_category(
    url: str,
    store: CommerceStore | None = None,
    html: str | None = None,
) -> list[dict]:
    """Fetch one category page and persist all product observations found."""
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


def watch_category(
    url: str,
    interval: int = 900,
    store: CommerceStore | None = None,
) -> None:
    """Repeatedly sweep a category URL, building price/sales history over time."""
    store = store or CommerceStore()
    while True:
        started = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            results = collect_category(url, store)
            recorded = [r for r in results if r.get("status") == "recorded"]
            print(f"[{started}] recorded {len(recorded)} products from {url}")
            for item in sorted(recorded, key=lambda r: r["deal_score"], reverse=True)[:10]:
                print(
                    f"  {item['deal_score']:>3}/100 | {item['currency']} "
                    f"{item['price']:.2f} | {item['title']}"
                )
        except Exception as exc:
            print(f"[{started}] category sweep failed: {exc}")
        time.sleep(max(60, interval))


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect a public TikTok Shop category page")
    parser.add_argument("url", help="TikTok Shop category URL")
    parser.add_argument("--watch", action="store_true", help="Repeat the category sweep")
    parser.add_argument("--interval", type=int, default=900, help="Watch interval in seconds (default 900)")
    args = parser.parse_args()

    if args.watch:
        watch_category(args.url, args.interval)
        return

    results = collect_category(args.url)
    recorded = [r for r in results if r.get("status") == "recorded"]
    skipped = [r for r in results if r.get("status") == "skipped"]
    print(f"Recorded: {len(recorded)} | Skipped: {len(skipped)}")
    for item in sorted(recorded, key=lambda r: r["deal_score"], reverse=True):
        print(
            f"{item['deal_score']:>3}/100 | {item['currency']} {item['price']:.2f} | "
            f"{item['title']} | {item['product_id']}"
        )


if __name__ == "__main__":
    main()
