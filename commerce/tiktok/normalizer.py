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
        value = _first(
            value,
            "sale_price_decimal",
            "single_product_price_decimal",
            "display_price",
            "formatted_price",
            "amount",
            "value",
            "price",
        )
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
    """Normalize TikTok Shop PDP and live category/discovery product records."""
    product_id = str(_first(data, "product_id", "productId", "id", default=""))
    title = str(_first(data, "title", "product_name", "name", default="Unknown product"))

    price_info = data.get("product_price_info")
    if not isinstance(price_info, dict):
        price_info = {}

    price = _number(_first(data, "price", "sale_price", "current_price", "product_price"))
    if price is None:
        price = _number(_first(price_info, "sale_price_decimal", "single_product_price_decimal", "sale_price_format"))

    if not product_id:
        raise ValueError("TikTok payload has no product id")
    if price is None:
        raise ValueError("TikTok payload has no usable price")

    specs = data.get("specs") or data.get("specifications") or {}
    if not isinstance(specs, dict):
        specs = {"description": str(specs)}

    sold_info = data.get("sold_info") if isinstance(data.get("sold_info"), dict) else {}
    rate_info = data.get("rate_info") if isinstance(data.get("rate_info"), dict) else {}
    seller_info = data.get("seller_info") if isinstance(data.get("seller_info"), dict) else {}

    sold_raw = _first(data, "sold_count", "sales", "sold", "product_sold_count")
    if sold_raw is None:
        sold_raw = sold_info.get("sold_count")

    review_raw = _first(data, "review_count", "reviews", "product_review_count")
    if review_raw is None:
        review_raw = rate_info.get("review_count")

    rating_raw = _first(data, "rating", "seller_rating", "product_rating")
    if rating_raw is None:
        rating_raw = rate_info.get("score")

    stock_raw = _first(data, "stock", "inventory")
    sku_id = _first(data, "sku_id", "skuId") or price_info.get("sku_id") or ""

    currency = _first(data, "currency", "currency_code")
    if not currency:
        currency = price_info.get("currency_name") or "GBP"

    original_price = _number(_first(data, "original_price", "list_price", "rrp", "market_price"))
    if original_price is None:
        original_price = _number(_first(price_info, "origin_price_decimal", "origin_price_format"))

    seller_id = str(_first(data, "seller_id", "shop_id", default=""))
    if not seller_id:
        seller_id = str(seller_info.get("seller_id") or "")

    seller_name = str(_first(data, "seller_name", "shop_name", default=""))
    if not seller_name:
        seller_name = str(seller_info.get("shop_name") or "")

    return ProductObservation(
        source="tiktok_shop",
        product_id=product_id,
        title=title,
        price=price,
        original_price=original_price,
        voucher_price=_number(_first(data, "voucher_price", "after_coupon_price")),
        currency=str(currency),
        url=_canonical_url(data),
        seller_id=seller_id,
        seller_name=seller_name,
        sold_count=int(_number(sold_raw, 0)) if sold_raw is not None else None,
        rating=_number(rating_raw),
        review_count=int(_number(review_raw, 0)) if review_raw is not None else None,
        category=str(_first(data, "category", "category_name", default="")),
        stock=int(_number(stock_raw, 0)) if stock_raw is not None else None,
        sku_id=str(sku_id),
        variant=str(_first(data, "variant", "sku_name", default="")),
        specs=specs,
        raw=data,
    )
