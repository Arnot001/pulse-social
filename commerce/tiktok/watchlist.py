from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Pulse Social"
WATCHLIST_FILE = APP_DIR / "tiktok_watchlist.json"


@dataclass
class ProductWatch:
    product_id: str
    title: str
    url: str
    interval_minutes: int = 15
    any_drop: bool = True
    new_low: bool = True
    target_price: float | None = None
    drop_pct: float | None = None
    desktop: bool = True
    discord: bool = False
    telegram: bool = False
    added_at: str = ""

    def __post_init__(self):
        if not self.added_at:
            self.added_at = datetime.now(timezone.utc).isoformat()


def load_watchlist(path: Path = WATCHLIST_FILE) -> list[ProductWatch]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [ProductWatch(**item) for item in data if isinstance(item, dict)]
    except (OSError, ValueError, TypeError):
        return []


def save_watchlist(items: list[ProductWatch], path: Path = WATCHLIST_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(item) for item in items], indent=2, ensure_ascii=False), encoding="utf-8")


def upsert_watch(watch: ProductWatch, path: Path = WATCHLIST_FILE) -> None:
    items = load_watchlist(path)
    items = [item for item in items if item.product_id != watch.product_id]
    items.append(watch)
    save_watchlist(items, path)


def remove_watch(product_id: str, path: Path = WATCHLIST_FILE) -> None:
    save_watchlist([item for item in load_watchlist(path) if item.product_id != product_id], path)
