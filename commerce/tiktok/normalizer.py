from __future__ import annotations

from typing import Any

from ..models import ProductObservation


def _first(data: dict[str, Any], *keys: str, default=None):
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return default


def _number(value, default=None):
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        # TikTok price objects vary between page surfaces. Prefer the displayed
        # value before falling back to common amount/value aliases.
        value = _first(value, "display_price", "formatted_price", "amount", "value", "price")
        if value is None:
            return default
    text = str(value).replace("£", "").replace(",", "").strip()
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def _canonical_url(data: dict[str, Any]) -> str:
    direct = _first(data, "url", "product_url")
    if direct:
        return str(direct)
    seo = data.get("seo_url")
    if isinstance(seo, dict) and seo.get("canonical_url"):
        return str(seo["canonical_url"])
    product_id = _first(data, "product_id", "productId", "id")
    return f"https://shop.tiktok.com/gb/pdp/{product_id}" if product_id else ""


def normalize_product(data: dict[str, Any]) -> ProductObservation:
    """Normalize a TikTok Shop PDP or category/discovery product record."""
    product_id = str(_first(data, "product_id", "productId", "id", default=""))
    title = str(_first(data, "title", "product_name", "name", default="Unknown product"))
    price = _number(_first(data, "price", "sale_price", "current_price", "product_price"))
    if not product_id:
        raise ValueError("TikTok payload has no product id")
    if price is None:
        raise ValueError("TikTok payload has no usable price")

    specs = data.get("specs") or data.get("specifications") or {}
    if not isinstance(specs, dict):
        specs = {"description": str(specs)}

    sold_raw = _first(data, "sold_count", "sales", "sold", "product_sold_count")
    review_raw = _first(data, "review_count", "reviews", "product_review_count")
    stock_raw = _first(data, "stock", "inventory")

    return ProductObservation(
        source="tiktok_shop",
        product_id=product_id,
        title=title,
        price=price,
        original_price=_number(_first(data, "original_price", "list_price", "rrp", "market_price")),
        voucher_price=_number(_first(data, "voucher_price", "after_coupon_price")),
        currency=str(_first(data, "currency", "currency_code", default="GBP")),
        url=_canonical_url(data),
        seller_id=str(_first(data, "seller_id", "shop_id", default="")),
        seller_name=str(_first(data, "seller_name", "shop_name", default="")),
        sold_count=int(_number(sold_raw, 0)) if sold_raw is not None else None,
        rating=_number(_first(data, "rating", "seller_rating", "product_rating")),
        review_count=int(_number(review_raw, 0)) if review_raw is not None else None,
        category=str(_first(data, "category", "category_name", default="")),
        stock=int(_number(stock_raw, 0)) if stock_raw is not None else None,
        sku_id=str(_first(data, "sku_id", "skuId", default="")),
        variant=str(_first(data, "variant", "sku_name", default="")),
        specs=specs,
        raw=data,
    )
