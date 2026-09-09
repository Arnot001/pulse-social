from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Pulse Social"
SETTINGS_FILE = APP_DIR / "tiktok_notifications.json"

DEFAULTS = {"discord_webhook": "", "telegram_bot_token": "", "telegram_chat_id": ""}


def load_settings(path: Path = SETTINGS_FILE) -> dict:
    if not path.exists():
        return DEFAULTS.copy()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {**DEFAULTS, **data}
    except (OSError, ValueError, TypeError):
        return DEFAULTS.copy()


def save_settings(settings: dict, path: Path = SETTINGS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**DEFAULTS, **settings}, indent=2), encoding="utf-8")


def _post_json(url: str, payload: dict, timeout: int = 15) -> None:
    request = Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json", "User-Agent": "Pulse-Social/0.1"}, method="POST")
    with urlopen(request, timeout=timeout) as response:
        response.read()


def send_discord(webhook: str, message: str) -> None:
    if webhook:
        _post_json(webhook, {"content": message})


def send_telegram(bot_token: str, chat_id: str, message: str) -> None:
    if not (bot_token and chat_id):
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    request = Request(url, data=urlencode({"chat_id": chat_id, "text": message, "disable_web_page_preview": "false"}).encode("utf-8"), headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "Pulse-Social/0.1"}, method="POST")
    with urlopen(request, timeout=15) as response:
        response.read()


def alert_message(item: dict, reason: str) -> str:
    currency = item.get("currency", "GBP")
    current = item.get("price")
    previous = item.get("previous_price")
    price = f"{currency} {current:.2f}" if isinstance(current, (int, float)) else str(current)
    move = ""
    if isinstance(previous, (int, float)) and isinstance(current, (int, float)):
        pct = ((current - previous) / previous * 100) if previous else 0
        move = f"\n{currency} {previous:.2f} -> {price} ({pct:+.1f}%)"
    return f"PULSE SOCIAL - TIKTOK SHOP ALERT\n{reason}\n{item.get('title', '')}{move or chr(10) + price}\n{item.get('url', '')}"
