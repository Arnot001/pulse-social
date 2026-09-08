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
    text = str(value).replace("£", "").replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return default


def normalize_product(data: dict[str, Any]) -> ProductObservation:
    """Normalize a captured TikTok Shop product-like payload.

    This is intentionally tolerant while PDH reconnaissance establishes the
    stable payload schema. Once confirmed, replace aliases with explicit paths.
    """
    product_id = str(_first(data, "product_id", "productId", "id", default=""))
    title = str(_first(data, "title", "product_name", "name", default="Unknown product"))
    price = _number(_first(data, "price", "sale_price", "current_price"))
    if not product_id:
        raise ValueError("TikTok payload has no product id")
    if price is None:
        raise ValueError("TikTok payload has no usable price")

    specs = data.get("specs") or data.get("specifications") or {}
    if not isinstance(specs, dict):
        specs = {"description": str(specs)}

    return ProductObservation(
        source="tiktok_shop",
        product_id=product_id,
        title=title,
        price=price,
        original_price=_number(_first(data, "original_price", "list_price", "rrp")),
        voucher_price=_number(_first(data, "voucher_price", "after_coupon_price")),
        currency=str(_first(data, "currency", "currency_code", default="GBP")),
        url=str(_first(data, "url", "product_url", default="")),
        seller_id=str(_first(data, "seller_id", "shop_id", default="")),
        seller_name=str(_first(data, "seller_name", "shop_name", default="")),
        sold_count=int(_number(_first(data, "sold_count", "sales", "sold"), 0)) if _first(data, "sold_count", "sales", "sold") is not None else None,
        rating=_number(_first(data, "rating", "seller_rating", "product_rating")),
        review_count=int(_number(_first(data, "review_count", "reviews"), 0)) if _first(data, "review_count", "reviews") is not None else None,
        category=str(_first(data, "category", "category_name", default="")),
        stock=int(_number(_first(data, "stock", "inventory"), 0)) if _first(data, "stock", "inventory") is not None else None,
        sku_id=str(_first(data, "sku_id", "skuId", default="")),
        variant=str(_first(data, "variant", "sku_name", default="")),
        specs=specs,
        raw=data,
    )
