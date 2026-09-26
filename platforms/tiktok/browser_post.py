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
SOUND_PREVIEW_PAGE_NAME = "pulse-social-tiktok-sound-preview"
DELETE_PAGE_NAME = "pulse-social-tiktok-auto-delete"

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


def _background_named_page(browser, context, page_name: str) -> tuple[Page, bool]:
    """Create/reuse a CDP tab without activating the Brave window."""
    for page in context.pages:
        try:
            if page.is_closed():
                continue
            if page.evaluate("window.name") == page_name:
                return page, False
        except Exception:
            continue

    marker = f"about:blank#{page_name}-{int(time.time() * 1000)}"
    session = None
    try:
        session = browser.new_browser_cdp_session()
        session.send(
            "Target.createTarget",
            {
                "url": marker,
                "background": True,
            },
        )

        deadline = time.time() + 3
        while time.time() < deadline:
            for page in context.pages:
                try:
                    if page.is_closed():
                        continue
                    if page.url == marker:
                        page.evaluate(
                            "(name) => { window.name = name; }",
                            page_name,
                        )
                        return page, True
                except Exception:
                    continue
            time.sleep(0.05)
    except Exception:
        pass
    finally:
        if session is not None:
            try:
                session.detach()
            except Exception:
                pass

    # Older Chromium builds can reject Target.createTarget(background=True).
    # Keep a compatible fallback rather than breaking sound search entirely.
    return _named_page(context, page_name)


def _posting_page(context) -> tuple[Page, bool]:
    return _named_page(context, POSTING_PAGE_NAME)


def _sound_search_page(browser, context) -> tuple[Page, bool]:
    return _background_named_page(browser, context, SOUND_SEARCH_PAGE_NAME)


def _sound_preview_page(browser, context) -> tuple[Page, bool]:
    return _background_named_page(browser, context, SOUND_PREVIEW_PAGE_NAME)


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
        '[role="dialog"] button, '
        '[role="dialog"] [role="button"], '
        '[role="dialog"] [role="option"], '
        '[role="dialog"] li, '
        '[role="dialog"] [data-e2e], '
        '[data-e2e*="sound" i], '
        '[data-e2e*="music" i], '
        '[data-e2e*="audio" i], '
        '[class*="sound" i], '
        '[class*="music" i], '
        '[class*="audio" i]'
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
    ignored = {
        "add",
        "add sound",
        "add music",
        "use",
        "use sound",
        "done",
        "confirm",
        "cancel",
        "search",
        "sounds",
        "sound",
        "music",
        "commercial sounds",
        "volume",
        "original sound",
    }

    def add(raw: str) -> None:
        clean = _clean_sound_result(raw)
        clean = " ".join(clean.split())
        key = clean.casefold()
        if (
            not clean
            or len(clean) > 220
            or key in seen
            or key in ignored
        ):
            return
        seen.add(key)
        results.append(clean)

    try:
        candidates = _sound_candidate_locator(page)
        for index in range(min(candidates.count(), 350)):
            item = candidates.nth(index)
            if not item.is_visible():
                continue
            text = ""
            try:
                text = item.inner_text(timeout=350)
            except Exception:
                pass
            if not text:
                text = (
                    item.get_attribute("aria-label")
                    or item.get_attribute("title")
                    or ""
                )
            add(text)
            if len(results) >= limit:
                return results
    except Exception:
        pass

    # Picker rows are sometimes rendered in a React portal outside role=dialog.
    # Scan concise visible body lines as a final fallback, while filtering the
    # stable Studio chrome so it cannot pollute the dropdown.
    try:
        body_text = page.locator("body").inner_text(timeout=1500)
        chrome = {
            "upload",
            "videos",
            "photos",
            "post",
            "discard",
            "caption",
            "description",
            "select video",
            "select photos",
            "select photo",
            "comments",
            "duet",
            "stitch",
            "copyright check",
            "manage",
            "home",
            "posts",
            "view analytics",
            "monetisation",
            "royalty-free sounds",
        }
        for raw in body_text.splitlines():
            clean = " ".join(raw.split())
            key = clean.casefold()
            if (
                not clean
                or len(clean) > 160
                or key in ignored
                or key in chrome
                or key in seen
            ):
                continue
            # Sound rows normally contain a title/artist/duration-sized phrase.
            # Exclude obvious sentences and uploader help copy.
            if clean.count(" ") > 14:
                continue
            add(clean)
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

        page, _created = _sound_search_page(browser, context)
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

            # TikTok's sound search is asynchronous and can take several seconds
            # even after the search box has accepted the query.
            results: list[str] = []
            deadline = time.time() + 12
            while time.time() < deadline:
                results = _sound_result_texts(page)
                if results:
                    break
                page.wait_for_timeout(500)

            if not results:
                try:
                    dialog_text = " ".join(
                        page.locator('[role="dialog"]').last.inner_text(timeout=1000).split()
                    )
                except Exception:
                    dialog_text = ""
                try:
                    candidate_count = _sound_candidate_locator(page).count()
                except Exception:
                    candidate_count = -1
                detail = (
                    f" | picker={dialog_text[:220]}"
                    if dialog_text
                    else ""
                )
                raise RuntimeError(
                    f'SOUND RESULTS EMPTY | TikTok opened the post sound picker for '
                    f'"{clean_query}" but Pulse found no selectable sound rows'
                    f'{detail} | candidates={candidate_count}'
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


def _find_sound_result(page: Page, selection: str) -> Locator | None:
    clean_selection = selection.strip()
    if not clean_selection:
        return None

    selection_terms = [
        term.lower()
        for term in clean_selection.replace("—", " ").split()
        if len(term) > 1
    ]

    try:
        candidates = _sound_candidate_locator(page)
        for index in range(min(candidates.count(), 350)):
            item = candidates.nth(index)
            if not item.is_visible():
                continue
            text = ""
            try:
                text = _clean_sound_result(item.inner_text(timeout=350))
            except Exception:
                pass
            if not text:
                text = (
                    item.get_attribute("aria-label")
                    or item.get_attribute("title")
                    or ""
                )
            lowered = " ".join(text.split()).lower()
            if lowered and (
                lowered == clean_selection.lower()
                or (
                    selection_terms
                    and all(term in lowered for term in selection_terms)
                )
            ):
                return item
    except Exception:
        pass

    try:
        text_match = page.get_by_text(clean_selection, exact=False)
        for index in range(min(text_match.count(), 20)):
            item = text_match.nth(index)
            if item.is_visible():
                return item
    except Exception:
        pass

    return None


def _preview_control_for_result(result: Locator) -> Locator | None:
    selectors = (
        'button[aria-label*="play" i]',
        'button[title*="play" i]',
        '[role="button"][aria-label*="play" i]',
        '[role="button"][title*="play" i]',
        '[data-e2e*="play" i]',
    )

    containers = [result]
    for hops in (1, 2, 3):
        try:
            containers.append(
                result.locator("xpath=" + "/".join([".."] * hops))
            )
        except Exception:
            pass

    for container in containers:
        for selector in selectors:
            try:
                controls = container.locator(selector)
                for index in range(min(controls.count(), 8)):
                    control = controls.nth(index)
                    if control.is_visible():
                        return control
            except Exception:
                pass

    return None


def preview_tiktok_sound(
    selection: str,
    search_query: str,
    media_paths: list[str],
    log: Callable[[str], None] | None = None,
) -> None:
    clean_selection = selection.strip()
    lookup = search_query.strip() or clean_selection
    if not clean_selection:
        raise RuntimeError("Choose a TikTok sound result first.")
    if not media_paths:
        raise RuntimeError("Add the image/video before previewing a TikTok sound.")

    paths = [Path(path) for path in media_paths]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise RuntimeError("TikTok media file missing: " + ", ".join(missing))

    suffixes = {path.suffix.lower() for path in paths}
    image_only = bool(suffixes) and suffixes.issubset(IMAGE_SUFFIXES)
    video_only = len(paths) == 1 and paths[0].suffix.lower() in VIDEO_SUFFIXES
    if not image_only and not video_only:
        raise RuntimeError(
            "Choose either one video or one/more images before previewing sounds."
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

        page, _created = _sound_preview_page(browser, context)
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
        file_input.set_input_files([str(path) for path in paths])
        page.wait_for_timeout(2400)

        error = _visible_error(page)
        if error:
            raise RuntimeError(
                f"TikTok rejected the media while preparing the sound preview: {error}"
            )

        _search_sound_picker(page, lookup)
        result = _find_sound_result(page, clean_selection)
        if result is None:
            raise RuntimeError(
                f'PREVIEW SOUND NOT FOUND | TikTok could not re-find "{clean_selection}".'
            )

        control = _preview_control_for_result(result)
        if control is not None:
            control.click(timeout=5000)
        else:
            # Some picker builds make the whole sound row the preview/select
            # target rather than exposing a separate play button. This is a
            # disposable preview tab, so selecting the row is safe.
            result.click(timeout=5000)

        page.wait_for_timeout(500)

        # If TikTok rendered an audio element but the row/control click only
        # selected it, explicitly start that already-authorised in-page audio.
        try:
            audios = page.locator("audio")
            for index in range(min(audios.count(), 6)):
                audio = audios.nth(index)
                try:
                    started = audio.evaluate(
                        """(el) => {
                            try {
                                el.currentTime = 0;
                                const promise = el.play();
                                return promise ? promise.then(() => true).catch(() => false) : true;
                            } catch (_) {
                                return false;
                            }
                        }"""
                    )
                    if started:
                        break
                except Exception:
                    pass
        except Exception:
            pass

        if log:
            log(f'TIKTOK SOUND PREVIEW | playing "{clean_selection}" in background')


def stop_tiktok_sound_preview(
    log: Callable[[str], None] | None = None,
) -> bool:
    stopped = False
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.connect_over_cdp(CDP_URL, timeout=5000)
        except Exception:
            return False

        for context in browser.contexts:
            for page in context.pages:
                try:
                    if page.is_closed():
                        continue
                    if page.evaluate("window.name") != SOUND_PREVIEW_PAGE_NAME:
                        continue
                    try:
                        page.locator("audio").evaluate_all(
                            "(items) => items.forEach((audio) => { try { audio.pause(); audio.currentTime = 0; } catch (_) {} })"
                        )
                    except Exception:
                        pass
                    page.close()
                    stopped = True
                except Exception:
                    pass

    if stopped and log:
        log("TIKTOK SOUND PREVIEW | stopped")
    return stopped


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

    result = _find_sound_result(page, clean_selection)

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


def _normalize_privacy_level(value: str) -> str:
    clean = (value or "").strip().upper()
    aliases = {
        "PUBLIC": "PUBLIC",
        "PUBLIC_TO_EVERYONE": "PUBLIC",
        "EVERYONE": "PUBLIC",
        "FRIENDS": "FRIENDS",
        "MUTUAL_FOLLOW_FRIENDS": "FRIENDS",
        "PRIVATE": "PRIVATE",
        "SELF_ONLY": "PRIVATE",
        "ONLY YOU": "PRIVATE",
        "ONLY_YOU": "PRIVATE",
    }
    return aliases.get(clean, clean or "PUBLIC")


def _privacy_target_labels(level: str) -> tuple[str, ...]:
    normalized = _normalize_privacy_level(level)
    if normalized == "PUBLIC":
        return ("Everyone", "Public")
    if normalized == "FRIENDS":
        return ("Friends",)
    if normalized == "PRIVATE":
        return ("Only you", "Private")
    raise RuntimeError(f"Unsupported TikTok privacy option: {level}")


def _set_post_privacy(page: Page, privacy_level: str) -> None:
    normalized = _normalize_privacy_level(privacy_level)
    targets = _privacy_target_labels(normalized)

    # TikTok Studio has used several labels for this field across uploader
    # versions. Prefer controls near a privacy / audience label so we do not
    # accidentally click an unrelated "Public" or "Friends" element.
    trigger = None
    trigger_selectors = (
        'button[aria-label*="privacy" i]',
        'button[aria-label*="audience" i]',
        '[role="combobox"][aria-label*="privacy" i]',
        '[role="combobox"][aria-label*="audience" i]',
        '[data-e2e*="privacy" i]',
        '[data-e2e*="audience" i]',
    )

    for selector in trigger_selectors:
        try:
            locator = page.locator(selector)
            for index in range(min(locator.count(), 12)):
                item = locator.nth(index)
                if item.is_visible():
                    trigger = item
                    break
            if trigger is not None:
                break
        except Exception:
            pass

    if trigger is None:
        # Locate the row by its visible label, then search nearby for a button
        # or combobox. Current Studio wording includes variants of "Who can
        # view/watch this post".
        label_terms = (
            "Who can view",
            "Who can watch",
            "Visibility",
            "Privacy",
            "Audience",
        )
        for term in label_terms:
            try:
                labels = page.get_by_text(term, exact=False)
                for index in range(min(labels.count(), 10)):
                    label = labels.nth(index)
                    if not label.is_visible():
                        continue
                    containers = [label]
                    for hops in (1, 2, 3, 4):
                        try:
                            containers.append(
                                label.locator("xpath=" + "/".join([".."] * hops))
                            )
                        except Exception:
                            pass
                    for container in containers:
                        try:
                            controls = container.locator(
                                'button, [role="combobox"], [role="button"]'
                            )
                            for ctrl_index in range(min(controls.count(), 12)):
                                control = controls.nth(ctrl_index)
                                if control.is_visible():
                                    trigger = control
                                    break
                            if trigger is not None:
                                break
                        except Exception:
                            pass
                    if trigger is not None:
                        break
                if trigger is not None:
                    break
            except Exception:
                pass

    # Some builds expose the current audience itself as the clickable control.
    if trigger is None:
        for current in (
            "Everyone",
            "Public",
            "Friends",
            "Only you",
            "Private",
        ):
            try:
                matches = page.get_by_text(current, exact=True)
                for index in range(min(matches.count(), 12)):
                    item = matches.nth(index)
                    if item.is_visible():
                        trigger = item
                        break
                if trigger is not None:
                    break
            except Exception:
                pass

    if trigger is None:
        raise RuntimeError(
            f"PRIVACY CONTROL NOT FOUND | Could not set TikTok visibility to {normalized}."
        )

    # If the requested value is already displayed, no dropdown action is needed.
    try:
        current_text = " ".join(trigger.inner_text(timeout=500).split()).casefold()
    except Exception:
        current_text = ""
    if any(target.casefold() in current_text for target in targets):
        return

    trigger.click(timeout=5000)
    page.wait_for_timeout(350)

    for target in targets:
        # Prefer listbox/menu options, then fall back to exact visible text.
        for role in ("option", "menuitem", "radio", "button"):
            try:
                options = page.get_by_role(role, name=target, exact=False)
                for index in range(min(options.count(), 12)):
                    option = options.nth(index)
                    if option.is_visible():
                        option.click(timeout=4000)
                        page.wait_for_timeout(350)
                        return
            except Exception:
                pass

        try:
            options = page.get_by_text(target, exact=True)
            for index in range(min(options.count(), 20)):
                option = options.nth(index)
                if option.is_visible():
                    option.click(timeout=4000)
                    page.wait_for_timeout(350)
                    return
        except Exception:
            pass

    raise RuntimeError(
        f"PRIVACY OPTION NOT FOUND | TikTok did not expose {normalized} in its audience menu."
    )


def _open_tiktok_posts(page: Page) -> None:
    page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(1000)

    if _looks_logged_out(page):
        raise RuntimeError(
            "TikTok is not logged in in the controlled Brave profile. "
            "Log in once in the TikTok tab, then retry."
        )

    # Use TikTok Studio's own Posts navigation so we do not depend on a
    # private/unstable content-management URL.
    for role in ("link", "button"):
        try:
            posts = page.get_by_role(role, name="Posts", exact=True)
            for index in range(min(posts.count(), 8)):
                item = posts.nth(index)
                if item.is_visible():
                    item.click(timeout=5000)
                    page.wait_for_timeout(1200)
                    return
        except Exception:
            pass

    try:
        posts = page.get_by_text("Posts", exact=True)
        for index in range(min(posts.count(), 12)):
            item = posts.nth(index)
            if item.is_visible():
                item.click(timeout=5000)
                page.wait_for_timeout(1200)
                return
    except Exception:
        pass

    raise RuntimeError("POSTS PAGE NOT FOUND | TikTok Studio did not expose its Posts section.")


def _post_row_for_caption(page: Page, caption: str) -> Locator:
    clean = " ".join((caption or "").split())
    if not clean:
        raise RuntimeError(
            "AUTO DELETE NEEDS A CAPTION | Pulse will not guess which TikTok post to delete."
        )

    matches: list[Locator] = []

    def collect(locator: Locator) -> None:
        try:
            for index in range(min(locator.count(), 20)):
                item = locator.nth(index)
                if item.is_visible():
                    matches.append(item)
        except Exception:
            pass

    # Prefer the full caption. TikTok normalises whitespace in text matching.
    try:
        collect(page.get_by_text(clean, exact=True))
    except Exception:
        pass

    # TikTok Studio can truncate captions in the table. Only use a reasonably
    # distinctive prefix and still refuse if more than one row matches.
    if not matches:
        prefix = clean[:80].strip()
        if len(prefix) >= 12:
            try:
                collect(page.get_by_text(prefix, exact=False))
            except Exception:
                pass

    # De-duplicate locator handles by their DOM text/position as best we can.
    unique: list[Locator] = []
    seen = set()
    for item in matches:
        try:
            box = item.bounding_box()
            key = (
                " ".join(item.inner_text(timeout=400).split()),
                None if box is None else round(box.get("y", 0), 1),
            )
        except Exception:
            key = (str(len(unique)), None)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    if not unique:
        raise RuntimeError(
            f'AUTO DELETE POST NOT FOUND | TikTok Studio has no visible post matching "{clean[:80]}".'
        )
    if len(unique) > 1:
        raise RuntimeError(
            f'AUTO DELETE AMBIGUOUS | {len(unique)} visible posts match "{clean[:80]}". '
            "Pulse refused to guess."
        )

    match = unique[0]

    # Prefer semantic table/list rows.
    for xpath in (
        "ancestor::tr[1]",
        "ancestor::*[@role='row'][1]",
    ):
        try:
            row = match.locator(f"xpath={xpath}")
            if row.count() and row.first.is_visible():
                return row.first
        except Exception:
            pass

    # TikTok Studio also uses nested div cards. Walk outward until we find a
    # container with the post text and at least one action button.
    current = match
    for _ in range(7):
        try:
            current = current.locator("xpath=..")
            if not current.count() or not current.first.is_visible():
                continue
            buttons = current.first.locator('button, [role="button"]')
            if buttons.count() >= 1:
                return current.first
        except Exception:
            pass

    raise RuntimeError(
        "AUTO DELETE ROW NOT FOUND | Pulse found the post text but not its action controls."
    )


def _more_action_button(row: Locator) -> Locator | None:
    selectors = (
        'button[aria-label*="more" i]',
        'button[title*="more" i]',
        '[role="button"][aria-label*="more" i]',
        '[role="button"][title*="more" i]',
        'button[aria-label*="action" i]',
        '[role="button"][aria-label*="action" i]',
    )
    for selector in selectors:
        try:
            controls = row.locator(selector)
            for index in range(min(controls.count(), 12)):
                control = controls.nth(index)
                if control.is_visible():
                    return control
        except Exception:
            pass

    # The current Studio action is an ellipsis icon. Accept a button only when
    # its accessible/text label clearly looks like an ellipsis/more control.
    try:
        buttons = row.locator('button, [role="button"]')
        for index in range(min(buttons.count(), 20)):
            button = buttons.nth(index)
            if not button.is_visible():
                continue
            label = " ".join(
                [
                    button.get_attribute("aria-label") or "",
                    button.get_attribute("title") or "",
                    button.inner_text(timeout=300) or "",
                ]
            ).strip().casefold()
            if any(token in label for token in ("more", "ellipsis", "...", "⋯", "•••")):
                return button
    except Exception:
        pass

    return None


def delete_browser_post(
    caption: str,
    log: Callable[[str], None] | None = None,
) -> None:
    """Delete one exact TikTok Studio post; never guess when matching is ambiguous."""
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

        page, _created = _background_named_page(browser, context, DELETE_PAGE_NAME)
        try:
            _open_tiktok_posts(page)
            row = _post_row_for_caption(page, caption)

            more = _more_action_button(row)
            if more is None:
                raise RuntimeError(
                    "AUTO DELETE ACTION NOT FOUND | Pulse found the post but not TikTok's More menu."
                )

            more.click(timeout=5000)
            page.wait_for_timeout(400)

            delete_action = None
            for role in ("menuitem", "button"):
                try:
                    options = page.get_by_role(role, name="Delete", exact=True)
                    for index in range(min(options.count(), 8)):
                        item = options.nth(index)
                        if item.is_visible():
                            delete_action = item
                            break
                    if delete_action is not None:
                        break
                except Exception:
                    pass

            if delete_action is None:
                try:
                    options = page.get_by_text("Delete", exact=True)
                    for index in range(min(options.count(), 12)):
                        item = options.nth(index)
                        if item.is_visible():
                            delete_action = item
                            break
                except Exception:
                    pass

            if delete_action is None:
                raise RuntimeError(
                    "AUTO DELETE MENU OPTION NOT FOUND | TikTok's More menu had no visible Delete action."
                )

            delete_action.click(timeout=5000)
            page.wait_for_timeout(500)

            # Confirmation is expected. Only click a Delete button inside a
            # visible dialog; otherwise stop rather than guessing.
            confirm = None
            try:
                dialogs = page.locator('[role="dialog"]')
                for dialog_index in range(dialogs.count() - 1, -1, -1):
                    dialog = dialogs.nth(dialog_index)
                    if not dialog.is_visible():
                        continue
                    buttons = dialog.get_by_role("button", name="Delete", exact=True)
                    for index in range(min(buttons.count(), 6)):
                        item = buttons.nth(index)
                        if item.is_visible():
                            confirm = item
                            break
                    if confirm is not None:
                        break
            except Exception:
                pass

            if confirm is None:
                raise RuntimeError(
                    "AUTO DELETE CONFIRMATION NOT FOUND | Pulse refused to confirm an unverified delete."
                )

            confirm.click(timeout=5000)
            page.wait_for_timeout(1200)

            if log:
                clean = " ".join((caption or "").split())
                log(f'AUTO DELETE | deleted "{clean[:100]}"')
        finally:
            try:
                if not page.is_closed():
                    page.close()
            except Exception:
                pass


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
    privacy_level: str = "PUBLIC",
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
        _set_post_privacy(page, privacy_level)
        if log:
            log(f"PRIVACY | {_normalize_privacy_level(privacy_level)}")

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
