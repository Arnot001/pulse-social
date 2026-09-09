from __future__ import annotations

import re
from urllib.parse import urlparse

from ..batch import ingest_products
from ..store import CommerceStore
from .category_collector import extract_json_payloads, fetch_category_page
from .discovery import discover_products
from .normalizer import normalize_product

_PRODUCT_ID_RE = re.compile(r"(?:/pdp/(?:[^/?#]+/)?|product_id=)(\d{8,})")


def product_id_from_url(url: str) -> str:
    match = _PRODUCT_ID_RE.search(url)
    if match:
        return match.group(1)
    parts = [part for part in urlparse(url).path.split("/") if part]
    for part in reversed(parts):
        if part.isdigit() and len(part) >= 8:
            return part
    return ""


def _priced_candidates(html: str, target_id: str) -> list[dict]:
    candidates: list[dict] = []
    for payload in extract_json_payloads(html):
        for product in discover_products(payload):
            pid = str(product.get("product_id") or product.get("productId") or product.get("id") or "")
            if target_id and pid != target_id:
                continue
            try:
                normalize_product(product)
            except (TypeError, ValueError):
                continue
            candidates.append(product)
    return candidates


def _stored_fallback(store: CommerceStore, product_id: str) -> dict | None:
    """Return the latest category observation when TikTok's PDP HTML is price-light.

    TikTok currently exposes usable prices on the category surface for some products while
    the direct PDP's embedded records omit them. The watch loop must not turn that into a
    false error. Category refreshes keep this observation current; watch results explicitly
    identify the fallback so the UI can distinguish it from a fresh PDP price.
    """
    if not product_id:
        return None
    try:
        latest = store.latest_observation("tiktok_shop", product_id)
    except Exception:
        return None
    if not latest or latest.get("effective_price") is None:
        return None
    price = float(latest.get("effective_price"))
    return {
        "status": "recorded",
        "source": "tiktok_shop",
        "product_id": product_id,
        "title": latest.get("title") or f"TikTok product {product_id}",
        "price": price,
        "currency": latest.get("currency") or "GBP",
        "url": latest.get("url") or f"https://shop.tiktok.com/gb/pdp/{product_id}",
        "sold_count": latest.get("sold_count"),
        "price_change": None,
        "price_change_pct": None,
        "sold_change": None,
        "is_new_low": False,
        "watch_price_source": "stored_category_observation",
        "watch_warning": "TikTok PDP omitted price; using latest collected category price",
    }


def collect_product(url: str, store: CommerceStore | None = None, html: str | None = None) -> dict:
    store = store or CommerceStore()
    target_id = product_id_from_url(url)
    html = html if html is not None else fetch_category_page(url)
    candidates = _priced_candidates(html, target_id)
    if candidates:
        # Prefer the richest priced record. TikTok can repeat the same product in loader state.
        product = max(candidates, key=lambda x: len(x) + sum(isinstance(v, dict) for v in x.values()))
        result = ingest_products([product], store)
        if result:
            return result[0]

    fallback = _stored_fallback(store, target_id)
    if fallback:
        return fallback
    raise RuntimeError("TikTok PDP contained product records but none had a usable price, and no stored category price is available")
