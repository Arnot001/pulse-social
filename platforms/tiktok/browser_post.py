from __future__ import annotations

import html
import re
import time
from pathlib import Path
from urllib.parse import quote, unquote
from typing import Callable

from playwright.sync_api import Locator, Page, sync_playwright

from .browser_session import CDP_URL

UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload"
SEARCH_URL = "https://www.tiktok.com/search?q={query}"
POSTING_PAGE_NAME = "pulse-social-tiktok-auto-post"
SOUND_SEARCH_PAGE_NAME = "pulse-social-tiktok-sound-search"

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


def _named_page(context, page_name: str) -> tuple[Page, bool]:
    for page in context.pages:
        try:
            if page.is_closed():
                continue
            if page.evaluate("window.name") == page_name:
                return page, False
        except Exception:
            continue

    page = context.new_page()
    try:
        page.evaluate("(name) => { window.name = name; }", page_name)
    except Exception:
        pass
    return page, True


def _posting_page(context) -> tuple[Page, bool]:
    return _named_page(context, POSTING_PAGE_NAME)


def _sound_search_page(context) -> tuple[Page, bool]:
    return _named_page(context, SOUND_SEARCH_PAGE_NAME)


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
                blank_accept = []
                for index in range(last_count):
                    item = inputs.nth(index)
                    accept = (item.get_attribute("accept") or "").lower()
                    if kind == "image" and (
                        "image" in accept
                        or ".jpg" in accept
                        or ".jpeg" in accept
                        or ".png" in accept
                        or ".webp" in accept
                    ):
                        return item
                    if kind == "video" and (
                        "video" in accept
                        or ".mp4" in accept
                        or ".mov" in accept
                        or ".webm" in accept
                    ):
                        return item
                    if not accept.strip():
                        blank_accept.append(item)

                # A blank accept input is a safe fallback only for video. On the
                # current TikTok Studio page, using it for a PNG can make the UI
                # look like a broken video upload.
                if kind == "video" and blank_accept:
                    return blank_accept[0]
        except Exception:
            pass

        page.wait_for_timeout(300)

    if kind == "image":
        raise RuntimeError(
            "PHOTO UPLOAD NOT EXPOSED | TikTok Studio is showing its video uploader "
            "instead of a photo picker on this account/session."
        )

    raise RuntimeError(
        f"TikTok upload page did not expose a {kind} file picker "
        f"(found {last_count} file input(s))."
    )


def _select_photo_mode(page: Page) -> None:
    # TikTok Studio currently renders Videos / Photos as top-level upload tabs.
    # The exact accessibility role varies, so use the semantic routes first and
    # then an exact visible-text fallback.
    if _click_first_visible(page, ("Photos", "Photo")):
        page.wait_for_timeout(600)
        return

    for selector in (
        '[role="tab"]:has-text("Photos")',
        'text="Photos"',
        'text="Photo"',
    ):
        try:
            locator = page.locator(selector)
            for index in range(min(locator.count(), 6)):
                item = locator.nth(index)
                if item.is_visible():
                    item.click(timeout=3000)
                    page.wait_for_timeout(600)
                    return
        except Exception:
            pass

    raise RuntimeError(
        "PHOTO TAB NOT FOUND | TikTok Studio did not expose its Photos upload tab."
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


def _open_sound_picker(page: Page) -> None:
    if _music_search_input(page) is not None:
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


def _search_sound_picker(page: Page, query: str) -> None:
    _open_sound_picker(page)
    search = _music_search_input(page)
    if search is None:
        raise RuntimeError(
            "SOUND SEARCH NOT FOUND. TikTok opened the sound picker but Pulse could not find its search box."
        )

    search.fill(query)
    page.keyboard.press("Enter")
    page.wait_for_timeout(1800)


def _sound_candidate_locator(page: Page) -> Locator:
    return page.locator(
        '[role="dialog"] button, [role="dialog"] [role="option"], '
        '[role="dialog"] [data-e2e*="sound"], [role="dialog"] [data-e2e*="music"], '
        '[data-e2e*="sound-item"], [data-e2e*="music-item"]'
    )


def _clean_sound_result(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.splitlines()]
    lines = [line for line in lines if line]
    ignored = {
        "add",
        "use",
        "done",
        "confirm",
        "cancel",
        "search",
        "sounds",
        "music",
        "commercial sounds",
    }
    useful = [line for line in lines if line.lower() not in ignored]
    return " — ".join(useful[:4]).strip(" —")


def _sound_result_texts(page: Page, limit: int = 25) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()

    try:
        candidates = _sound_candidate_locator(page)
        for index in range(min(candidates.count(), 100)):
            item = candidates.nth(index)
            if not item.is_visible():
                continue
            try:
                clean = _clean_sound_result(item.inner_text(timeout=500))
            except Exception:
                continue
            if not clean or len(clean) > 220:
                continue
            key = clean.casefold()
            if key in seen:
                continue
            seen.add(key)
            results.append(clean)
            if len(results) >= limit:
                return results
    except Exception:
        pass

    # Some TikTok picker variants render result rows as plain divs rather than
    # buttons/options. Fall back to concise visible lines from the open dialog.
    try:
        dialog = page.locator('[role="dialog"]').last
        text = dialog.inner_text(timeout=1500)
        for raw in text.splitlines():
            clean = " ".join(raw.split())
            key = clean.casefold()
            if (
                not clean
                or len(clean) > 120
                or key in seen
                or key in {
                    "add sound",
                    "add music",
                    "sounds",
                    "music",
                    "search",
                    "cancel",
                    "done",
                    "use",
                }
            ):
                continue
            seen.add(key)
            results.append(clean)
            if len(results) >= limit:
                break
    except Exception:
        pass

    return results


def _sound_name_from_href(href: str) -> str:
    value = unquote((href or "").split("?", 1)[0]).rstrip("/")
    if not value:
        return ""
    slug = value.rsplit("/", 1)[-1]
    slug = re.sub(r"-\\d{8,}$", "", slug)
    slug = slug.replace("-", " ").replace("_", " ")
    return " ".join(slug.split())


def _search_page_sound_results(page: Page, limit: int = 25) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        clean = _clean_sound_result(html.unescape(raw or ""))
        clean = " ".join(clean.split())
        if not clean or len(clean) > 220:
            return
        key = clean.casefold()
        if key in seen:
            return
        seen.add(key)
        results.append(clean)

    # TikTok has used both /music/ and /sound/ routes. Do not require the
    # anchors to be in the current viewport because search results are lazy
    # rendered and their audio links can be off-screen.
    try:
        anchors = page.locator('a[href*="/music/"], a[href*="/sound/"]')
        for index in range(min(anchors.count(), 250)):
            item = anchors.nth(index)
            text = ""
            try:
                text = item.inner_text(timeout=400)
            except Exception:
                pass

            if not text:
                text = (
                    item.get_attribute("aria-label")
                    or item.get_attribute("title")
                    or ""
                )

            if not text:
                href = item.get_attribute("href") or ""
                text = _sound_name_from_href(href)

            add(text)
            if len(results) >= limit:
                return results
    except Exception:
        pass

    # Current TikTok search often keeps music metadata in the page hydration
    # payload even when it does not render a dedicated Sounds tab. Pull only
    # explicit music-title fields as a fallback; never populate the dropdown
    # with arbitrary video/search text.
    try:
        markup = page.content()
        patterns = (
            r'"musicName"\\s*:\\s*"([^"]{1,180})"',
            r'"musicTitle"\\s*:\\s*"([^"]{1,180})"',
            r'"music_title"\\s*:\\s*"([^"]{1,180})"',
        )
        for pattern in patterns:
            for match in re.findall(pattern, markup, flags=re.IGNORECASE):
                try:
                    decoded = bytes(match, "utf-8").decode("unicode_escape")
                except Exception:
                    decoded = match
                add(decoded)
                if len(results) >= limit:
                    return results
    except Exception:
        pass

    return results


def search_tiktok_sounds(
    query: str,
    media_paths: list[str] | None = None,
    log: Callable[[str], None] | None = None,
) -> list[str]:
    clean_query = query.strip()
    if not clean_query:
        raise RuntimeError("Type a TikTok sound search first.")
    if not media_paths:
        raise RuntimeError(
            "Add the image/video first. TikTok only exposes the post sound picker "
            "after media is loaded."
        )

    paths = [Path(path) for path in media_paths]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise RuntimeError("TikTok media file missing: " + ", ".join(missing))

    suffixes = {path.suffix.lower() for path in paths}
    image_only = bool(suffixes) and suffixes.issubset(IMAGE_SUFFIXES)
    video_only = len(paths) == 1 and paths[0].suffix.lower() in VIDEO_SUFFIXES
    if not image_only and not video_only:
        raise RuntimeError(
            "Choose either one video or one/more images before searching sounds."
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

        page, _created = _sound_search_page(context)
        try:
            page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1400)

            if _looks_logged_out(page):
                raise RuntimeError(
                    "TikTok is not logged in in the controlled Brave profile. "
                    "Log in once in the TikTok tab, then retry."
                )

            if kind == "image":
                _select_photo_mode(page)

            file_input = _file_input_for_kind(page, kind)
            if log:
                media_note = (
                    f"{len(paths)} image(s)"
                    if kind == "image"
                    else paths[0].name
                )
                log(f"TIKTOK SOUND PREP | loading {media_note}")

            file_input.set_input_files([str(path) for path in paths])
            page.wait_for_timeout(2600)

            error = _visible_error(page)
            if error:
                raise RuntimeError(
                    f"TikTok rejected the media while opening its sound picker: {error}"
                )

            _search_sound_picker(page, clean_query)
            results = _sound_result_texts(page)
            if not results:
                try:
                    dialog_text = " ".join(
                        page.locator('[role="dialog"]').last.inner_text(timeout=1000).split()
                    )
                except Exception:
                    dialog_text = ""
                detail = f" | picker={dialog_text[:220]}" if dialog_text else ""
                raise RuntimeError(
                    f'SOUND RESULTS EMPTY | TikTok opened the post sound picker for '
                    f'"{clean_query}" but Pulse found no selectable sound rows{detail}'
                )

            if log:
                log(
                    f'TIKTOK SOUND SEARCH | "{clean_query}" | '
                    f'{len(results)} result(s) from post sound picker'
                )
            return results
        finally:
            # This page exists only to query the same picker TikTok will use at
            # post time. Close it so ADD MUSIC does not leave stray Studio tabs.
            try:
                if not page.is_closed():
                    page.close()
            except Exception:
                pass


def _add_tiktok_sound(
    page: Page,
    selection: str,
    log: Callable[[str], None] | None = None,
    *,
    search_query: str = "",
) -> None:
    clean_selection = selection.strip()
    if not clean_selection:
        return

    lookup = search_query.strip() or clean_selection
    _search_sound_picker(page, lookup)

    result = None
    selection_terms = [
        term.lower()
        for term in clean_selection.replace("—", " ").split()
        if len(term) > 1
    ]

    try:
        candidates = _sound_candidate_locator(page)
        for index in range(min(candidates.count(), 100)):
            item = candidates.nth(index)
            if not item.is_visible():
                continue
            try:
                text = _clean_sound_result(item.inner_text(timeout=500))
            except Exception:
                text = ""
            lowered = text.lower()
            if text and (
                lowered == clean_selection.lower()
                or (selection_terms and all(term in lowered for term in selection_terms))
            ):
                result = item
                break
    except Exception:
        pass

    if result is None:
        try:
            text_match = page.get_by_text(clean_selection, exact=False)
            for index in range(min(text_match.count(), 12)):
                item = text_match.nth(index)
                if item.is_visible():
                    result = item
                    break
        except Exception:
            pass

    if result is None:
        raise RuntimeError(
            f'SOUND NOT FOUND | TikTok could not re-find selected sound "{clean_selection}".'
        )

    try:
        result.click(timeout=5000)
    except Exception:
        try:
            result.locator("xpath=ancestor::button[1]").click(timeout=5000)
        except Exception as exc:
            raise RuntimeError(
                f'SOUND SELECT FAILED | Found "{clean_selection}" but could not select it.'
            ) from exc

    page.wait_for_timeout(800)
    _click_first_visible(page, ("Use", "Use sound", "Add", "Done", "Confirm"))
    if log:
        log(f'TIKTOK SOUND | selected "{clean_selection}"')


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
    music_search: str = "",
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
            _add_tiktok_sound(
                page,
                music_query,
                log=log,
                search_query=music_search,
            )

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
