from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _walk(value: Any) -> Iterable[Any]:
    """Yield every node in a captured TikTok JSON/embedded-state payload."""
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _looks_like_product(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    keys = set(value)
    has_id = bool(keys & {"product_id", "productId"})
    has_product_signal = bool(
        keys
        & {
            "product_name",
            "title",
            "seo_url",
            "price",
            "sale_price",
            "current_price",
            "sold_count",
        }
    )
    return has_id and has_product_signal


def discover_products(payload: Any) -> list[dict[str, Any]]:
    """Extract unique product-like records from TikTok Shop captures.

    PDH confirmed category pages expose embedded loaderData under the category
    page route, including page_config.components_map[*].component_data
    .categoryProductsData.productList.  We intentionally walk the complete
    payload as a fallback because TikTok can move a component without changing
    the useful product record itself.
    """
    products: list[dict[str, Any]] = []
    seen: set[str] = set()

    for node in _walk(payload):
        if not _looks_like_product(node):
            continue
        product_id = str(node.get("product_id") or node.get("productId") or "")
        if not product_id or product_id in seen:
            continue
        seen.add(product_id)
        products.append(node)

    return products


def product_urls(payload: Any, region: str = "gb") -> list[str]:
    """Return canonical TikTok Shop PDP URLs for discovered products."""
    urls: list[str] = []
    for product in discover_products(payload):
        seo = product.get("seo_url")
        if isinstance(seo, dict):
            canonical = seo.get("canonical_url")
            if canonical:
                urls.append(str(canonical))
                continue
        product_id = str(product.get("product_id") or product.get("productId"))
        urls.append(f"https://shop.tiktok.com/{region}/pdp/{product_id}")
    return urls
