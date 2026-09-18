from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from playwright.sync_api import sync_playwright

APP_DIR = Path(os.environ["LOCALAPPDATA"]) / "Pulse Social"
APP_DIR.mkdir(parents=True, exist_ok=True)
QUEUE_FILE = APP_DIR / "x_auto_post_queue.json"
HISTORY_FILE = APP_DIR / "x_auto_post_history.txt"
CDP_URL = "http://127.0.0.1:9222"
CHROME_USER_DATA = Path(os.environ["LOCALAPPDATA"]) / "Google" / "Chrome" / "User Data"
DEVTOOLS_ACTIVE_PORT = CHROME_USER_DATA / "DevToolsActivePort"
X_ACTION_LOCK = threading.Lock()


@dataclass
class QueuedPost:
    post_id: str
    text: str
    due_at: str
    status: str = "queued"


def load_queue() -> list[QueuedPost]:
    if not QUEUE_FILE.exists():
        return []
    try:
        data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
        return [QueuedPost(**item) for item in data if isinstance(item, dict)]
    except Exception:
        return []


def save_queue(items: list[QueuedPost]) -> None:
    QUEUE_FILE.write_text(json.dumps([asdict(x) for x in items], indent=2, ensure_ascii=False), encoding="utf-8")


def add_post(text: str, due_at: datetime) -> QueuedPost:
    clean = text.strip()
    if not clean:
        raise ValueError("Post text is empty.")
    item = QueuedPost(post_id=f"{int(time.time()*1000)}", text=clean, due_at=due_at.isoformat(timespec="seconds"))
    items = load_queue()
    items.append(item)
    items.sort(key=lambda x: x.due_at)
    save_queue(items)
    return item


def remove_post(post_id: str) -> None:
    save_queue([x for x in load_queue() if x.post_id != post_id])


def _x_page(context):
    for page in context.pages:
        try:
            if "x.com" in page.url.lower() or "twitter.com" in page.url.lower():
                return page
        except Exception:
            pass
    page = context.new_page()
    page.goto("https://x.com/home", wait_until="domcontentloaded")
    return page


def _chrome_cdp_endpoint() -> str:
    """Prefer Chrome's authorised live-session endpoint; keep legacy 9222 as fallback."""
    if DEVTOOLS_ACTIVE_PORT.exists():
        try:
            lines = DEVTOOLS_ACTIVE_PORT.read_text(encoding="utf-8").splitlines()
            port = lines[0].strip()
            browser_path = lines[1].strip() if len(lines) > 1 else ""
            if port.isdigit():
                if browser_path.startswith("/"):
                    return f"ws://127.0.0.1:{port}{browser_path}"
                return f"http://127.0.0.1:{port}"
        except OSError:
            pass
    return CDP_URL


def publish_text(text: str) -> None:
    with X_ACTION_LOCK:
        with sync_playwright() as p:
            endpoint = _chrome_cdp_endpoint()
            try:
                browser = p.chromium.connect_over_cdp(endpoint, timeout=15000)
            except Exception as exc:
                if endpoint == CDP_URL:
                    raise RuntimeError(
                        "Chrome live-session debugging was not found. In your normal Chrome open "
                        "chrome://inspect/#remote-debugging and enable 'Allow remote debugging for this browser instance'."
                    ) from exc
                raise RuntimeError(
                    "Chrome offered a live debugging session but Pulse could not attach. "
                    "Approve Chrome's debugging permission prompt if it appears, then retry."
                ) from exc
            if not browser.contexts:
                raise RuntimeError("Chrome attached but no browser context was available.")
            page = _x_page(browser.contexts[0])
            if "x.com" not in page.url.lower():
                page.goto("https://x.com/home", wait_until="domcontentloaded")
            page.goto("https://x.com/compose/post", wait_until="domcontentloaded")
            editor = page.locator('[data-testid="tweetTextarea_0"]').first
            editor.wait_for(state="visible", timeout=10000)
            editor.click()
            editor.fill(text)
            post_button = page.locator('[data-testid="tweetButton"]').first
            if post_button.count() == 0:
                post_button = page.locator('[data-testid="tweetButtonInline"]').first
            post_button.wait_for(state="visible", timeout=5000)
            if post_button.is_disabled():
                raise RuntimeError("X Post button is disabled.")
            post_button.click(timeout=5000)
            page.wait_for_timeout(1500)


def run_scheduler(stop_event: threading.Event, log: Callable[[str], None]) -> None:
    log("AUTO POST scheduler started.")
    while not stop_event.wait(5):
        items = load_queue()
        now = datetime.now()
        changed = False
        for item in items:
            if item.status != "queued":
                continue
            try:
                due = datetime.fromisoformat(item.due_at)
            except ValueError:
                item.status = "invalid"
                changed = True
                continue
            if due > now:
                continue
            try:
                log(f"POSTING | {item.text[:100]}")
                publish_text(item.text)
                item.status = "posted"
                stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with HISTORY_FILE.open("a", encoding="utf-8") as f:
                    f.write(f"{stamp} | POSTED | {item.text.replace(chr(10), ' ')}\n")
                log("POSTED successfully.")
            except Exception as exc:
                item.status = "error"
                log(f"POST ERROR | {exc}")
            changed = True
        if changed:
            save_queue(items)
    log("AUTO POST scheduler stopped.")
