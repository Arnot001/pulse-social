from __future__ import annotations

import re
from urllib.parse import urlparse

from ..batch import ingest_products
from ..store import CommerceStore
from .category_collector import extract_json_payloads, fetch_category_page
from .discovery import discover_products

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


def collect_product(url: str, store: CommerceStore | None = None, html: str | None = None) -> dict:
    store = store or CommerceStore()
    html = html if html is not None else fetch_category_page(url)
    target_id = product_id_from_url(url)
    candidates: dict[str, dict] = {}
    for payload in extract_json_payloads(html):
        for product in discover_products(payload):
            pid = str(product.get("product_id") or product.get("productId") or product.get("id") or "")
            if pid:
                candidates[pid] = product
    if target_id and target_id in candidates:
        product = candidates[target_id]
    elif len(candidates) == 1:
        product = next(iter(candidates.values()))
    else:
        raise RuntimeError(f"Could not isolate product {target_id or 'from URL'} from TikTok PDP embedded data.")
    result = ingest_products([product], store)
    if not result:
        raise RuntimeError("TikTok product produced no observation.")
    return result[0]
