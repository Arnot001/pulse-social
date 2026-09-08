"""TikTok Shop adapter boundary.

The collector deliberately consumes captured/approved payloads rather than
hard-coding private endpoints. PDH reconnaissance can feed payloads into this
adapter once their shape is known.
"""

from .normalizer import normalize_product

__all__ = ["normalize_product"]
