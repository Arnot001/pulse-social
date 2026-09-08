"""TikTok Shop commerce adapter.

PDH-confirmed browser payloads are parsed here without persisting browser
session tokens or hard-coding transient signed request parameters.
"""

from .discovery import discover_products, product_urls
from .normalizer import normalize_product

__all__ = ["discover_products", "product_urls", "normalize_product"]
