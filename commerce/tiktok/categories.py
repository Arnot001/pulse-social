from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .category_collector import extract_json_payloads, fetch_category_page

ALL_CATEGORIES_URL = "https://shop.tiktok.com/gb/c"


@dataclass(frozen=True)
class TikTokCategory:
    category_id: str
    name: str
    slug: str
    level: int
    parent_id: str
    is_leaf: bool

    @property
    def url(self) -> str:
        return f"https://shop.tiktok.com/gb/c/{self.slug}/{self.category_id}"


def _walk(value: Any) -> Iterable[dict]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def categories_from_payloads(payloads: list[Any]) -> list[TikTokCategory]:
    """Extract TikTok's embedded category taxonomy without hard-coding categories."""
    found: dict[str, TikTokCategory] = {}
    for payload in payloads:
        for node in _walk(payload):
            category_id = str(node.get("category_id") or "").strip()
            name = str(node.get("category_name") or "").strip()
            slug = str(node.get("category_name_en") or "").strip()
            level = node.get("category_level")
            parent_id = str(node.get("parent_category_id") or "").strip()
            if not (category_id and name and slug and isinstance(level, int) and parent_id):
                continue
            found[category_id] = TikTokCategory(
                category_id=category_id,
                name=name,
                slug=slug,
                level=level,
                parent_id=parent_id,
                is_leaf=bool(node.get("is_leaf", False)),
            )
    return sorted(found.values(), key=lambda item: (item.level, item.name.casefold()))


def fetch_categories(url: str = ALL_CATEGORIES_URL) -> list[TikTokCategory]:
    html = fetch_category_page(url)
    return categories_from_payloads(extract_json_payloads(html))


def children_of(categories: list[TikTokCategory], parent_id: str) -> list[TikTokCategory]:
    return sorted(
        (item for item in categories if item.parent_id == str(parent_id)),
        key=lambda item: item.name.casefold(),
    )


def roots(categories: list[TikTokCategory]) -> list[TikTokCategory]:
    return children_of(categories, "0")
