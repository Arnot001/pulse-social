from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from .models import ProductObservation


@dataclass(slots=True)
class DealScore:
    total: int
    price_anomaly: int
    seller_confidence: int
    specification_confidence: int
    sales_momentum: int
    reasons: list[str]


def _clamp(value: float, low: float = 0, high: float = 100) -> int:
    return round(max(low, min(high, value)))


def score_deal(item: ProductObservation, history: list[dict]) -> DealScore:
    reasons: list[str] = []
    historical = [float(x["effective_price"]) for x in history if x.get("effective_price")]
    baseline = median(historical) if historical else item.original_price

    if baseline and baseline > 0:
        discount = (baseline - item.effective_price) / baseline
        price_score = _clamp(50 + discount * 180)
        if discount >= 0.20:
            reasons.append(f"Price is {discount:.0%} below observed baseline")
    else:
        price_score = 45
        reasons.append("Not enough price history yet")

    seller_score = 50
    if item.rating is not None:
        seller_score += (item.rating - 4.0) * 35
    if item.review_count is not None and item.review_count >= 100:
        seller_score += 10
    seller_score = _clamp(seller_score)

    spec_score = 70
    title = item.title.lower()
    if "gaming pc" in title or item.category.lower() in {"pc", "computer", "gaming pc"}:
        important = ("cpu", "gpu", "ram", "storage")
        present = sum(bool(item.specs.get(k)) for k in important)
        spec_score = _clamp(20 + present * 20)
        if present < 3:
            reasons.append("Important PC specifications are missing")

    momentum_score = 50
    sold = [x.get("sold_count") for x in history if x.get("sold_count") is not None]
    if len(sold) >= 2:
        growth = sold[-1] - sold[0]
        momentum_score = _clamp(50 + growth * 2)
        if growth > 0:
            reasons.append(f"Sales count increased by {growth}")

    total = _clamp(
        price_score * 0.45
        + seller_score * 0.20
        + spec_score * 0.20
        + momentum_score * 0.15
    )
    return DealScore(total, price_score, seller_score, spec_score, momentum_score, reasons)
