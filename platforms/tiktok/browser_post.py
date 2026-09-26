from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from playwright.sync_api import Locator, Page, sync_playwright

from .browser_session import CDP_URL

UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload"
POSTING_PAGE_NAME = "pulse-social-tiktok-auto-post"

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}


def _existing_tiktok_context(browser):
    fallback = None
    for context in browser.contexts:
        if fallback is None:
            fallback = context
        for page in context.pages:
            try:
                if "tiktok.com" in page.url.lower():
                    return context
            except Exception:
                pass
    return fallback


def _posting_page(context) -> tuple[Page, bool]:
    for page in context.pages:
        try:
            if page.is_closed():
                continue
            if page.evaluate("window.name") == POSTING_PAGE_NAME:
                return page, False
        except Exception:
            continue

    page = context.new_page()
    try:
        page.evaluate("(name) => { window.name = name; }", POSTING_PAGE_NAME)
    except Exception:
        pass
    return page, True


def _visible_text(page: Page) -> str:
    try:
        return page.locator("body").inner_text(timeout=2500)
    except Exception:
        return ""


def _looks_logged_out(page: Page) -> bool:
    url = page.url.lower()
    if "login" in url:
        return True

    text = _visible_text(page).lower()
    login_markers = (
        "log in to tiktok",
        "login to tiktok",
        "sign in to tiktok",
    )
    return any(marker in text for marker in login_markers)


def _click_first_visible(page: Page, names: tuple[str, ...]) -> bool:
    for name in names:
        for role in ("button", "tab"):
            try:
                control = page.get_by_role(role, name=name, exact=False)
                count = min(control.count(), 6)
                for index in range(count):
                    item = control.nth(index)
                    if item.is_visible():
                        item.click(timeout=3000)
                        page.wait_for_timeout(500)
                        return True
            except Exception:
                pass
    return False


def _file_input_for_kind(page: Page, kind: str) -> Locator:
    inputs = page.locator('input[type="file"]')
    deadline = time.time() + 12
    last_count = 0

    while time.time() < deadline:
        try:
            last_count = inputs.count()
            if last_count:
                preferred = []
                fallback = []
                for index in range(last_count):
                    item = inputs.nth(index)
                    accept = (item.get_attribute("accept") or "").lower()
                    if kind == "image" and ("image" in accept or ".jpg" in accept or ".png" in accept):
                        preferred.append(item)
                    elif kind == "video" and ("video" in accept or ".mp4" in accept or ".webm" in accept):
                        preferred.append(item)
                    else:
                        fallback.append(item)

                if preferred:
                    return preferred[0]

                # TikTok sometimes leaves accept blank and validates after selection.
                for item in fallback:
                    accept = (item.get_attribute("accept") or "").strip()
                    if not accept:
                        return item
        except Exception:
            pass

        page.wait_for_timeout(300)

    raise RuntimeError(
        f"TikTok upload page did not expose a {kind} file picker "
        f"(found {last_count} file input(s))."
    )


def _select_photo_mode(page: Page) -> None:
    # TikTok has used several labels while rolling photo upload across desktop.
    # Try the human-facing controls first, then rely on the image file input.
    _click_first_visible(
        page,
        (
            "Photo",
            "Photos",
            "Image",
            "Images",
            "Photo post",
        ),
    )


def _caption_editor(page: Page) -> Locator:
    selectors = (
        'textarea[placeholder*="caption" i]',
        'textarea[aria-label*="caption" i]',
        '[contenteditable="true"][data-e2e*="caption" i]',
        '[contenteditable="true"][aria-label*="caption" i]',
        '[contenteditable="true"][aria-label*="description" i]',
        '[contenteditable="true"][data-placeholder*="caption" i]',
    )

    for selector in selectors:
        try:
            locator = page.locator(selector)
            for index in range(min(locator.count(), 6)):
                item = locator.nth(index)
                if item.is_visible():
                    return item
        except Exception:
            pass

    # Last-resort: choose the first visible editor that is not obviously search.
    try:
        editors = page.locator('textarea, [contenteditable="true"]')
        for index in range(min(editors.count(), 12)):
            item = editors.nth(index)
            if not item.is_visible():
                continue
            aria = (item.get_attribute("aria-label") or "").lower()
            placeholder = (item.get_attribute("placeholder") or "").lower()
            combined = f"{aria} {placeholder}"
            if "search" in combined:
                continue
            return item
    except Exception:
        pass

    raise RuntimeError("TikTok caption editor was not found after media upload.")


def _fill_caption(page: Page, caption: str) -> None:
    if not caption:
        return

    editor = _caption_editor(page)
    editor.focus()

    try:
        tag = editor.evaluate("(el) => el.tagName.toLowerCase()")
    except Exception:
        tag = ""

    if tag == "textarea":
        editor.fill(caption)
    else:
        page.keyboard.press("Control+A")
        page.keyboard.insert_text(caption)


def _music_search_input(page: Page) -> Locator | None:
    selectors = (
        'input[placeholder*="search" i]',
        'input[aria-label*="search" i]',
        'input[data-e2e*="search" i]',
    )
    for selector in selectors:
        try:
            locator = page.locator(selector)
            for index in range(min(locator.count(), 12)):
                item = locator.nth(index)
                if not item.is_visible():
                    continue
                context_text = ""
                try:
                    context_text = item.evaluate(
                        "(el) => (el.closest('[role=dialog]') || el.parentElement || el).innerText"
                    )
                except Exception:
                    pass
                if any(word in str(context_text).lower() for word in ("sound", "music", "song", "audio")):
                    return item
        except Exception:
            pass
    return None


def _add_tiktok_sound(
    page: Page,
    query: str,
    log: Callable[[str], None] | None = None,
) -> None:
    clean_query = query.strip()
    if not clean_query:
        return

    opened = _click_first_visible(
        page,
        (
            "Add sound",
            "Add music",
            "Choose sound",
            "Choose music",
            "Sounds",
            "Music",
        ),
    )
    if not opened:
        raise RuntimeError(
            "SOUND PICKER NOT FOUND. TikTok did not expose an Add sound/music control on this upload page."
        )

    search = _music_search_input(page)
    if search is None:
        raise RuntimeError(
            "SOUND SEARCH NOT FOUND. TikTok opened the sound picker but Pulse could not find its search box."
        )

    search.fill(clean_query)
    page.keyboard.press("Enter")
    page.wait_for_timeout(1600)

    result = None
    terms = [term.lower() for term in clean_query.split() if len(term) > 1]
    try:
        candidates = page.locator(
            '[role="dialog"] button, [role="dialog"] [role="option"], '
            '[role="dialog"] [data-e2e*="sound"], [role="dialog"] [data-e2e*="music"]'
        )
        for index in range(min(candidates.count(), 60)):
            item = candidates.nth(index)
            if not item.is_visible():
                continue
            try:
                text = " ".join(item.inner_text(timeout=500).split()).lower()
            except Exception:
                text = ""
            if text and terms and all(term in text for term in terms):
                result = item
                break
    except Exception:
        pass

    if result is None:
        try:
            text_match = page.get_by_text(clean_query, exact=False)
            for index in range(min(text_match.count(), 12)):
                item = text_match.nth(index)
                if item.is_visible():
                    result = item
                    break
        except Exception:
            pass

    if result is None:
        raise RuntimeError(
            f'SOUND NOT FOUND | TikTok returned no visible match for "{clean_query}".'
        )

    try:
        result.click(timeout=5000)
    except Exception:
        try:
            result.locator("xpath=ancestor::button[1]").click(timeout=5000)
        except Exception as exc:
            raise RuntimeError(
                f'SOUND SELECT FAILED | Found "{clean_query}" but could not select it.'
            ) from exc

    page.wait_for_timeout(800)
    _click_first_visible(page, ("Use", "Use sound", "Add", "Done", "Confirm"))
    if log:
        log(f'TIKTOK SOUND | selected "{clean_query}"')


def _post_button(page: Page) -> Locator:
    deadline = time.time() + 20
    while time.time() < deadline:
        candidates = (
            page.get_by_role("button", name="Post", exact=True),
            page.get_by_role("button", name="Post now", exact=False),
            page.locator('[data-e2e*="post"][role="button"]'),
            page.locator('button:has-text("Post")'),
        )
        for locator in candidates:
            try:
                for index in range(min(locator.count(), 6)):
                    item = locator.nth(index)
                    if item.is_visible():
                        return item
            except Exception:
                pass
        page.wait_for_timeout(400)

    raise RuntimeError("TikTok Post button was not found.")


def _visible_error(page: Page) -> str | None:
    selectors = (
        '[role="alert"]',
        '[data-e2e*="toast"]',
        '[class*="toast"]',
    )
    for selector in selectors:
        try:
            texts = page.locator(selector).all_inner_texts()
        except Exception:
            continue
        for text in texts:
            clean = " ".join(text.split())
            lower = clean.lower()
            if any(word in lower for word in ("failed", "error", "couldn't", "cannot", "invalid")):
                return clean
    return None


def publish_browser_post(
    caption: str,
    media_paths: list[str],
    log: Callable[[str], None] | None = None,
    *,
    music_query: str = "",
) -> None:
    if not media_paths:
        raise RuntimeError("Choose at least one TikTok image or video.")

    paths = [Path(path) for path in media_paths]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise RuntimeError("TikTok media file missing: " + ", ".join(missing))

    suffixes = {path.suffix.lower() for path in paths}
    image_only = bool(suffixes) and suffixes.issubset(IMAGE_SUFFIXES)
    video_only = len(paths) == 1 and paths[0].suffix.lower() in VIDEO_SUFFIXES

    if not image_only and not video_only:
        raise RuntimeError(
            "TikTok posts currently support either one video or one/more images per queued post."
        )

    kind = "image" if image_only else "video"

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.connect_over_cdp(CDP_URL, timeout=5000)
        except Exception as exc:
            raise RuntimeError(
                "TikTok browser is not controllable. Connect the Pulse Brave browser first."
            ) from exc

        context = _existing_tiktok_context(browser)
        if context is None:
            raise RuntimeError("Controlled browser has no usable context.")

        page, created = _posting_page(context)
        if log:
            log(
                "TIKTOK POST PAGE | opening dedicated uploader"
                if created
                else "TIKTOK POST PAGE | reusing dedicated uploader"
            )

        page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)

        if _looks_logged_out(page):
            page.bring_to_front()
            raise RuntimeError(
                "TikTok is not logged in in the controlled Brave profile. "
                "Log in once in the TikTok tab, then retry."
            )

        if kind == "image":
            _select_photo_mode(page)

        file_input = _file_input_for_kind(page, kind)
        if log:
            label = f"{len(paths)} image(s)" if kind == "image" else paths[0].name
            log(f"MEDIA UPLOAD | {label}")

        file_input.set_input_files([str(path) for path in paths])
        page.wait_for_timeout(2500)

        error = _visible_error(page)
        if error:
            raise RuntimeError(f"TikTok rejected the media: {error}")

        if music_query.strip():
            _add_tiktok_sound(page, music_query, log=log)

        _fill_caption(page, caption)

        post_button = _post_button(page)
        deadline = time.time() + 120
        while time.time() < deadline:
            error = _visible_error(page)
            if error:
                raise RuntimeError(f"TikTok rejected the post: {error}")

            try:
                if post_button.is_enabled():
                    break
            except Exception:
                post_button = _post_button(page)
            page.wait_for_timeout(500)
        else:
            raise RuntimeError("TikTok Post button stayed disabled while media was processing.")

        post_button.click(timeout=10000)
        page.wait_for_timeout(2500)

        error = _visible_error(page)
        if error:
            raise RuntimeError(f"TikTok post failed: {error}")

        if log:
            log("TIKTOK POST | submitted through controlled browser")
