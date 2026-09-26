from __future__ import annotations

import json
import socket
import time
import urllib.request

from playwright.sync_api import sync_playwright

CDP_PORT = 9222
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"
TIKTOK_URL = "https://www.tiktok.com/"


def _port_open() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.35)
        return sock.connect_ex(("127.0.0.1", CDP_PORT)) == 0


def _targets() -> list[dict]:
    if not _port_open():
        return []
    try:
        with urllib.request.urlopen(f"{CDP_URL}/json/list", timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, list) else []
    except Exception:
        return []


def tiktok_browser_status() -> str:
    if not _port_open():
        return "BROWSER NOT CONNECTED"

    for target in _targets():
        url = str(target.get("url") or "").lower()
        if "tiktok.com" in url:
            return "CONNECTED // TIKTOK TAB READY"

    return "CONNECTED // NO TIKTOK TAB"


def open_tiktok_browser() -> tuple[bool, str]:
    """Open or focus TikTok inside the already-controlled Brave/Chrome session."""
    if not _port_open():
        return (
            False,
            "Pulse browser control is not connected. Connect the X/Brave browser first.",
        )

    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(CDP_URL, timeout=10000)
                if not browser.contexts:
                    last_error = RuntimeError(
                        "Browser connected, but no browser context was available."
                    )
                else:
                    for context in browser.contexts:
                        for page in context.pages:
                            try:
                                if "tiktok.com" in page.url.lower():
                                    page.bring_to_front()
                                    return True, "CONNECTED // EXISTING TIKTOK TAB"
                            except Exception:
                                pass

                    context = browser.contexts[0]
                    page = context.new_page()
                    page.goto(TIKTOK_URL, wait_until="domcontentloaded", timeout=30000)
                    page.bring_to_front()
                    return True, "CONNECTED // TIKTOK OPENED"
        except Exception as exc:
            last_error = exc

        if attempt < 3:
            time.sleep(0.8)

    return (
        False,
        "Could not attach TikTok to the controlled browser after 3 attempts: "
        f"{last_error}",
    )
