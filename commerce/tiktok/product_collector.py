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


def _usable(product: dict) -> bool:
    try:
        normalize_product(product)
        return True
    except (TypeError, ValueError):
        return False


def collect_product(url: str, store: CommerceStore | None = None, html: str | None = None) -> dict:
    """Collect one TikTok PDP, preferring the richest price-bearing record for its ID.

    A PDP commonly repeats the same product ID in several embedded structures. Some are
    lightweight identity records without price data, so keeping only the last record can
    poison a watch check. Retain every occurrence and select one the normalizer can price.
    """
    store = store or CommerceStore()
    html = html if html is not None else fetch_category_page(url)
    target_id = product_id_from_url(url)
    candidates: dict[str, list[dict]] = {}
    for payload in extract_json_payloads(html):
        for product in discover_products(payload):
            pid = str(product.get("product_id") or product.get("productId") or product.get("id") or "")
            if pid:
                candidates.setdefault(pid, []).append(product)

    pool: list[dict]
    if target_id and target_id in candidates:
        pool = candidates[target_id]
    elif len(candidates) == 1:
        pool = next(iter(candidates.values()))
    else:
        raise RuntimeError(f"Could not isolate product {target_id or 'from URL'} from TikTok PDP embedded data.")

    product = next((candidate for candidate in reversed(pool) if _usable(candidate)), None)
    if product is None:
        raise ValueError("TikTok PDP contained product records but none had a usable price")

    result = ingest_products([product], store)
    if not result:
        raise RuntimeError("TikTok product produced no observation.")
    return result[0]
