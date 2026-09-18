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
CDP_PORTS = (9222, 9223, 9224, 9225)
BROWSER_USER_DATA_DIRS = (
    ("Chrome", Path(os.environ["LOCALAPPDATA"]) / "Google" / "Chrome" / "User Data"),
    ("Brave", Path(os.environ["LOCALAPPDATA"]) / "BraveSoftware" / "Brave-Browser" / "User Data"),
)
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


def _candidate_endpoints():
    seen = set()
    for label, user_data_dir in BROWSER_USER_DATA_DIRS:
        port_file = user_data_dir / "DevToolsActivePort"
        if not port_file.exists():
            continue
        try:
            lines = [line.strip() for line in port_file.read_text(encoding="utf-8").splitlines() if line.strip()]
            if len(lines) < 2 or not lines[0].isdigit():
                continue
            endpoint = f"ws://127.0.0.1:{lines[0]}{lines[1]}"
            if endpoint not in seen:
                seen.add(endpoint)
                yield label, endpoint
        except OSError:
            pass
    for port in CDP_PORTS:
        endpoint = f"http://127.0.0.1:{port}"
        if endpoint not in seen:
            seen.add(endpoint)
            yield f"CDP {port}", endpoint


def _connect_x_browser(playwright):
    fallback = None
    attempts = []
    for label, endpoint in _candidate_endpoints():
        try:
            browser = playwright.chromium.connect_over_cdp(endpoint, timeout=3500)
        except Exception as exc:
            attempts.append(f"{label}: {type(exc).__name__}")
            continue
        for context in browser.contexts:
            for page in context.pages:
                try:
                    url = page.url.lower()
                    if "x.com" in url or "twitter.com" in url:
                        return browser, context, page, label
                except Exception:
                    pass
        if fallback is None and browser.contexts:
            fallback = (browser, browser.contexts[0], label)
    if fallback is not None:
        browser, context, label = fallback
        return browser, context, _x_page(context), label
    detail = "; ".join(attempts) if attempts else "no debugging endpoints discovered"
    raise RuntimeError(
        "NO CONTROLLABLE X BROWSER FOUND. X may be open, but Pulse needs that browser's "
        f"debugging connection to be enabled. Discovery: {detail}."
    )


def publish_text(text: str) -> None:
    with X_ACTION_LOCK:
        with sync_playwright() as p:
            _browser, context, page, _browser_label = _connect_x_browser(p)
            if not context:
                raise RuntimeError("Browser attached but no browser context was available.")
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
