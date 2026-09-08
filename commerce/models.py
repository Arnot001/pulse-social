from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class ProductObservation:
    source: str
    product_id: str
    title: str
    price: float
    currency: str = "GBP"
    url: str = ""
    seller_id: str = ""
    seller_name: str = ""
    original_price: float | None = None
    voucher_price: float | None = None
    sold_count: int | None = None
    rating: float | None = None
    review_count: int | None = None
    category: str = ""
    stock: int | None = None
    sku_id: str = ""
    variant: str = ""
    specs: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def effective_price(self) -> float:
        return self.voucher_price if self.voucher_price is not None else self.price

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
