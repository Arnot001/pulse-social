from __future__ import annotations

import json
import time
import urllib.request
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

from platforms.browser_control import CDP_PORT, CDP_URL, connect_browser, port_open

TIKTOK_URL = "https://www.tiktok.com/"
TIKTOK_SHOP_URL = "https://shop.tiktok.com/gb/c"


def _port_open() -> bool:
    return port_open(CDP_PORT)


def _targets() -> list[dict]:
    if not _port_open():
        return []
    try:
        with urllib.request.urlopen(f"{CDP_URL}/json/list", timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, list) else []
    except Exception:
        return []



def _is_exact_shop_category_target(target: dict) -> bool:
    if str(target.get("type") or "").lower() != "page":
        return False

    try:
        parsed = urlparse(str(target.get("url") or ""))
    except Exception:
        return False

    return (
        parsed.hostname == "shop.tiktok.com"
        and parsed.path.rstrip("/") == "/gb/c"
    )


def _close_exact_shop_category_targets() -> int:
    """Close only restored TikTok Shop root-category tabs.

    A frozen restored /gb/c target can prevent Playwright from completing its
    whole-browser CDP attach. This deliberately leaves X, normal TikTok,
    product/category-detail pages and unrelated tabs untouched.
    """
    closed = 0

    for target in _targets():
        if not _is_exact_shop_category_target(target):
            continue

        target_id = str(target.get("id") or "").strip()
        if not target_id:
            continue

        try:
            with urllib.request.urlopen(
                f"{CDP_URL}/json/close/{target_id}",
                timeout=2,
            ) as response:
                response.read()
            closed += 1
        except Exception:
            continue

    return closed

def tiktok_browser_status() -> str:
    if not _port_open():
        return "PULSE BROWSER NOT CONNECTED"

    for target in _targets():
        url = str(target.get("url") or "").lower()
        if "tiktok.com" in url:
            return "CONNECTED // TIKTOK TAB READY"

    return "CONNECTED // NO TIKTOK TAB"


def read_tiktok_shop_html(timeout_seconds: float = 30.0) -> str:
    """Read the real Shop category page from Pulse's dedicated browser.

    TikTok can return a Security Check to raw HTTP clients while the normal
    browser session has the genuine page. This helper never bypasses a
    challenge: it only reads an already-rendered, browser-owned category page.
    """
    deadline = time.time() + max(1.0, float(timeout_seconds))
    last_error: Exception | None = None

    if not _port_open():
        ok, message = connect_browser()
        if not ok:
            raise RuntimeError(message)

    while time.time() < deadline:
        try:
            with sync_playwright() as p:
                try:
                    browser = p.chromium.connect_over_cdp(CDP_URL, timeout=10000)
                except PlaywrightTimeoutError as exc:
                    last_error = exc
                    if _close_exact_shop_category_targets():
                        time.sleep(0.4)
                        continue
                    raise

                if not browser.contexts:
                    raise RuntimeError("Browser connected, but no browser context was available.")

                category_page = None

                for context in browser.contexts:
                    for page in context.pages:
                        try:
                            parsed = urlparse(page.url)
                            if (
                                parsed.hostname == "shop.tiktok.com"
                                and parsed.path.rstrip("/") == "/gb/c"
                            ):
                                category_page = page
                                break
                        except Exception:
                            continue
                    if category_page is not None:
                        break

                if category_page is None:
                    context = browser.contexts[0]
                    category_page = context.new_page()
                    category_page.goto(
                        TIKTOK_SHOP_URL,
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )

                while time.time() < deadline:
                    html = category_page.content()
                    lower = html.casefold()

                    if "security check" in lower:
                        raise RuntimeError(
                            "TikTok Shop is showing a Security Check in the dedicated Pulse Browser."
                        )

                    if "category_id" in html and "category_name" in html:
                        return html

                    time.sleep(0.5)

                raise RuntimeError("TikTok Shop category taxonomy did not become ready in time.")

        except Exception as exc:
            last_error = exc

        if time.time() < deadline:
            time.sleep(0.8)

    raise RuntimeError(
        f"Could not read TikTok Shop categories from the dedicated Pulse Browser: {last_error}"
    )


def open_tiktok_browser(*, shop: bool = False) -> tuple[bool, str]:
    """Open or focus TikTok inside the dedicated Pulse Chromium browser."""
    target_url = TIKTOK_SHOP_URL if shop else TIKTOK_URL
    label = "TIKTOK SHOP" if shop else "TIKTOK"
    if not _port_open():
        ok, message = connect_browser()
        if not ok:
            return False, message

    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with sync_playwright() as p:
                try:
                    browser = p.chromium.connect_over_cdp(CDP_URL, timeout=10000)
                except PlaywrightTimeoutError as exc:
                    last_error = exc
                    if shop and _close_exact_shop_category_targets():
                        time.sleep(0.4)
                        continue
                    raise

                if not browser.contexts:
                    last_error = RuntimeError(
                        "Browser connected, but no browser context was available."
                    )
                else:
                    for context in browser.contexts:
                        for page in context.pages:
                            try:
                                url = page.url.lower()
                                matches = (urlparse(url).hostname == "shop.tiktok.com" if shop
                                           else "tiktok.com" in url)
                                if matches:
                                    page.bring_to_front()
                                    return True, f"CONNECTED // EXISTING {label} TAB"
                            except Exception:
                                pass

                    context = browser.contexts[0]
                    page = context.new_page()
                    page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                    page.bring_to_front()
                    return True, f"CONNECTED // {label} OPENED"
        except Exception as exc:
            last_error = exc

        if attempt < 3:
            time.sleep(0.8)

    return (
        False,
        f"Could not attach {label} to the dedicated Pulse browser after 3 attempts: "
        f"{last_error}",
    )
