from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from playwright.sync_api import Locator, Page, Response, sync_playwright

from platforms.browser_control import CDP_URL

CONTENT_URL = "https://www.tiktok.com/tiktokstudio/content"
CLEANUP_PAGE_NAME = "pulse-social-tiktok-cleanup"
APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Pulse Social"
APP_DIR.mkdir(parents=True, exist_ok=True)
CLEANUP_LOG_FILE = APP_DIR / "tiktok_cleanup_log.txt"

ITEM_LIST_FRAGMENT = "/tiktok/creator/manage/item_list/v1/"
VIDEO_ITEM_TYPE = 1
PHOTO_ITEM_TYPE = 2


@dataclass(frozen=True)
class TikTokItem:
    item_id: str
    desc: str
    item_type: int
    post_time: int
    play_count: int
    like_count: int
    comment_count: int
    share_count: int
    favorite_count: int
    visibility: int | None
    status: int | None
    in_review: bool
    can_delete: bool

    @property
    def kind(self) -> str:
        if self.item_type == VIDEO_ITEM_TYPE:
            return "video"
        if self.item_type == PHOTO_ITEM_TYPE:
            return "photo"
        return "other"


@dataclass(frozen=True)
class CleanupOptions:
    mode: str = "videos"
    delete_all: bool = False
    max_actions: int = 10
    dry_run: bool = True
    delay_seconds: float = 1.25


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_item(raw: dict) -> TikTokItem:
    permissions = raw.get("permissions") or {}
    delete_info = permissions.get("can_delete") or {}
    show_type = delete_info.get("show_type")
    can_delete = show_type is None or _as_int(show_type) > 0

    return TikTokItem(
        item_id=str(raw.get("item_id") or "").strip(),
        desc=str(raw.get("desc") or "").strip(),
        item_type=_as_int(raw.get("item_type"), -1),
        post_time=_as_int(raw.get("post_time")),
        play_count=_as_int(raw.get("play_count")),
        like_count=_as_int(raw.get("like_count")),
        comment_count=_as_int(raw.get("comment_count")),
        share_count=_as_int(raw.get("share_count")),
        favorite_count=_as_int(raw.get("favorite_count")),
        visibility=(
            _as_int(raw.get("visibility"))
            if raw.get("visibility") is not None
            else None
        ),
        status=(
            _as_int(raw.get("status"))
            if raw.get("status") is not None
            else None
        ),
        in_review=bool(raw.get("in_review")),
        can_delete=can_delete,
    )


def _mode_matches(item: TikTokItem, mode: str) -> bool:
    clean = (mode or "").strip().lower()
    if clean == "videos":
        return item.kind == "video"
    if clean in {"photos", "photo", "photo posts"}:
        return item.kind == "photo"
    if clean == "everything":
        return True
    raise ValueError(f"Unsupported TikTok cleanup mode: {mode}")


def select_targets(
    items: list[TikTokItem],
    mode: str,
    limit: int | None = None,
    *,
    excluded_ids: set[str] | None = None,
) -> list[TikTokItem]:
    excluded = excluded_ids or set()
    selected = [
        item
        for item in items
        if item.item_id
        and item.item_id not in excluded
        and item.can_delete
        and _mode_matches(item, mode)
    ]
    selected.sort(key=lambda item: (item.post_time, item.item_id), reverse=True)
    if limit is not None:
        selected = selected[: max(0, int(limit))]
    return selected


def _log_deleted(item: TikTokItem) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    preview = " ".join(item.desc.split())[:180]
    CLEANUP_LOG_FILE.write_text(
        "",
        encoding="utf-8",
    ) if not CLEANUP_LOG_FILE.exists() else None
    with CLEANUP_LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(
            f"{stamp} | DELETED | {item.kind.upper()} | {item.item_id} | {preview}\n"
        )


def _item_list_response(response: Response) -> bool:
    if ITEM_LIST_FRAGMENT not in response.url:
        return False
    if response.request.method.upper() != "POST":
        return False
    post_data = response.request.post_data or ""
    try:
        payload = json.loads(post_data)
        return _as_int(payload.get("size")) >= 20
    except Exception:
        compact = post_data.replace(" ", "")
        return '"size":50' in compact or '"size":100' in compact


def _existing_context(browser):
    if not browser.contexts:
        return None
    for context in browser.contexts:
        for page in context.pages:
            try:
                if "tiktok.com" in page.url.lower():
                    return context
            except Exception:
                pass
    return browser.contexts[0]


def _background_named_page(browser, context, page_name: str) -> tuple[Page, bool]:
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
        session.send("Target.createTarget", {"url": marker, "background": True})
        deadline = time.time() + 3
        while time.time() < deadline:
            for page in context.pages:
                try:
                    if not page.is_closed() and page.url == marker:
                        page.evaluate("(name) => { window.name = name; }", page_name)
                        return page, True
                except Exception:
                    pass
            time.sleep(0.05)
    except Exception:
        pass
    finally:
        if session is not None:
            try:
                session.detach()
            except Exception:
                pass

    page = context.new_page()
    try:
        page.evaluate("(name) => { window.name = name; }", page_name)
    except Exception:
        pass
    return page, True


def _looks_logged_out(page: Page) -> bool:
    try:
        url = page.url.lower()
        if "login" in url or "signin" in url:
            return True
    except Exception:
        pass
    try:
        login = page.get_by_text("Log in", exact=True)
        return any(login.nth(i).is_visible() for i in range(min(login.count(), 8)))
    except Exception:
        return False


def load_studio_items(page: Page) -> tuple[list[TikTokItem], bool]:
    """Load TikTok Studio's own newest-first post inventory from its page traffic."""

    def navigate() -> None:
        if "tiktok.com/tiktokstudio/content" in page.url.lower():
            page.reload(wait_until="domcontentloaded", timeout=30000)
        else:
            page.goto(CONTENT_URL, wait_until="domcontentloaded", timeout=30000)

    try:
        with page.expect_response(_item_list_response, timeout=30000) as response_info:
            navigate()
        response = response_info.value
    except Exception as first_error:
        def any_item_list(response: Response) -> bool:
            return (
                ITEM_LIST_FRAGMENT in response.url
                and response.request.method.upper() == "POST"
            )

        try:
            with page.expect_response(any_item_list, timeout=20000) as response_info:
                page.reload(wait_until="domcontentloaded", timeout=30000)
            response = response_info.value
        except Exception as second_error:
            if _looks_logged_out(page):
                raise RuntimeError(
                    "TikTok is not logged in in the dedicated Pulse browser. "
                    "Log in once, then retry."
                ) from second_error
            raise RuntimeError(
                "TikTok Studio post inventory did not appear. "
                f"First wait: {first_error}; fallback: {second_error}"
            ) from second_error

    payload = response.json()
    raw_items = payload.get("item_list") or []
    items = [normalize_item(raw) for raw in raw_items if isinstance(raw, dict)]
    items.sort(key=lambda item: (item.post_time, item.item_id), reverse=True)
    return items, bool(payload.get("has_more"))


def _row_from_match(match: Locator) -> Locator | None:
    for xpath in ("ancestor::tr[1]", "ancestor::*[@role='row'][1]"):
        try:
            row = match.locator(f"xpath={xpath}").first
            if row.count() and row.is_visible():
                return row
        except Exception:
            pass

    current = match
    for _ in range(7):
        try:
            current = current.locator("xpath=..").first
            if not current.count() or not current.is_visible():
                continue
            controls = current.locator('button, [role="button"]')
            if controls.count() >= 1:
                return current
        except Exception:
            pass
    return None


def _find_item_row_once(page: Page, item: TikTokItem) -> Locator | None:
    for selector in (
        f'a[href*="{item.item_id}"]',
        f'[data-item-id="{item.item_id}"]',
        f'[data-id="{item.item_id}"]',
    ):
        try:
            matches = page.locator(selector)
            for index in range(min(matches.count(), 12)):
                match = matches.nth(index)
                if not match.is_visible():
                    continue
                row = _row_from_match(match)
                if row is not None:
                    return row
        except Exception:
            pass

    clean_desc = " ".join(item.desc.split())
    if not clean_desc:
        return None

    probes = [clean_desc]
    if len(clean_desc) > 80:
        probes.append(clean_desc[:80].rstrip())

    for probe in probes:
        try:
            matches = page.get_by_text(probe, exact=(probe == clean_desc))
            rows: list[Locator] = []
            seen_text: set[str] = set()
            for index in range(min(matches.count(), 30)):
                match = matches.nth(index)
                if not match.is_visible():
                    continue
                row = _row_from_match(match)
                if row is None:
                    continue
                try:
                    row_text = " ".join(row.inner_text(timeout=500).split())
                except Exception:
                    row_text = f"row-{index}"
                if row_text in seen_text:
                    continue
                seen_text.add(row_text)
                rows.append(row)
            if len(rows) == 1:
                return rows[0]
        except Exception:
            pass

    return None


def _find_item_row(page: Page, item: TikTokItem) -> Locator | None:
    try:
        page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass

    for _ in range(18):
        row = _find_item_row_once(page, item)
        if row is not None:
            return row
        try:
            page.mouse.wheel(0, 900)
        except Exception:
            pass
        page.wait_for_timeout(220)
    return None


def _more_button(row: Locator) -> Locator | None:
    selectors = (
        'button[aria-label*="more" i]',
        '[role="button"][aria-label*="more" i]',
        'button[title*="more" i]',
        '[role="button"][title*="more" i]',
        'button[aria-label*="action" i]',
        '[role="button"][aria-label*="action" i]',
        '[data-e2e*="more" i]',
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

    try:
        controls = row.locator('button, [role="button"]')
        visible = [
            controls.nth(index)
            for index in range(min(controls.count(), 20))
            if controls.nth(index).is_visible()
        ]
        return visible[-1] if visible else None
    except Exception:
        return None


def _visible_exact_delete(page: Page) -> Locator | None:
    for role in ("menuitem", "button"):
        try:
            matches = page.get_by_role(role, name="Delete", exact=True)
            for index in range(min(matches.count(), 12)):
                item = matches.nth(index)
                if item.is_visible():
                    return item
        except Exception:
            pass
    try:
        matches = page.get_by_text("Delete", exact=True)
        for index in range(min(matches.count(), 20)):
            item = matches.nth(index)
            if item.is_visible():
                return item
    except Exception:
        pass
    return None


def _confirm_delete(page: Page) -> Locator | None:
    try:
        dialogs = page.locator('[role="dialog"]')
        for dialog_index in range(dialogs.count() - 1, -1, -1):
            dialog = dialogs.nth(dialog_index)
            if not dialog.is_visible():
                continue
            matches = dialog.get_by_role("button", name="Delete", exact=True)
            for index in range(min(matches.count(), 8)):
                button = matches.nth(index)
                if button.is_visible():
                    return button
    except Exception:
        pass
    return None


def delete_studio_item(
    page: Page,
    item: TikTokItem,
    log: Callable[[str], None],
) -> bool:
    if not item.can_delete:
        log(f"SKIP | TikTok says item {item.item_id} cannot be deleted.")
        return False

    row = _find_item_row(page, item)
    if row is None:
        log(f"SKIP | Could not safely match Studio row for {item.item_id}.")
        return False

    more = _more_button(row)
    if more is None:
        log(f"SKIP | No Actions/More control found for {item.item_id}.")
        return False

    try:
        more.click(timeout=5000)
        page.wait_for_timeout(300)
    except Exception as exc:
        log(f"SKIP | Could not open actions for {item.item_id}: {exc}")
        return False

    delete_action = _visible_exact_delete(page)
    if delete_action is None:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        log(f"SKIP | Exact Delete action not found for {item.item_id}.")
        return False

    try:
        delete_action.click(timeout=5000)
        page.wait_for_timeout(350)
    except Exception as exc:
        log(f"SKIP | Delete menu click failed for {item.item_id}: {exc}")
        return False

    confirm = _confirm_delete(page)
    if confirm is None:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        log(
            f"SKIP | Delete confirmation was not verified for {item.item_id}; "
            "nothing confirmed."
        )
        return False

    try:
        confirm.click(timeout=5000)
        page.wait_for_timeout(850)
    except Exception as exc:
        log(f"SKIP | Delete confirmation failed for {item.item_id}: {exc}")
        return False

    _log_deleted(item)
    log(f"DELETED | {item.kind.upper()} | {item.item_id} | {item.desc[:100]}")
    return True


def _preview_line(item: TikTokItem) -> str:
    review = " | UNDER REVIEW" if item.in_review else ""
    return (
        f"PREVIEW | {item.kind.upper()} | {item.item_id} | "
        f"views {item.play_count} | likes {item.like_count}{review} | "
        f"{item.desc[:120]}"
    )


def run_cleanup(
    options: CleanupOptions,
    *,
    log: Callable[[str], None],
    stop_event,
    arm_event=None,
    state: Callable[[str], None] | None = None,
) -> int:
    """Scan and optionally delete TikTok Studio posts from the user's own account."""
    if not options.delete_all and options.max_actions <= 0:
        raise ValueError("Delete count must be at least 1, or choose DELETE ALL.")

    if state:
        state("attaching")
    log("Attaching to the dedicated Pulse browser...")

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.connect_over_cdp(CDP_URL, timeout=10000)
        except Exception as exc:
            raise RuntimeError(
                "Pulse browser is not controllable. Attach it from the Control Deck first."
            ) from exc

        context = _existing_context(browser)
        if context is None:
            raise RuntimeError("Pulse browser connected, but no browser context was available.")

        page, _created = _background_named_page(browser, context, CLEANUP_PAGE_NAME)
        failed_ids: set[str] = set()

        items, has_more = load_studio_items(page)
        matching = select_targets(items, options.mode, excluded_ids=failed_ids)
        initial_limit = None if options.delete_all else options.max_actions
        initial_targets = matching if initial_limit is None else matching[:initial_limit]

        counts = {
            "videos": sum(1 for item in items if item.kind == "video"),
            "photos": sum(1 for item in items if item.kind == "photo"),
        }
        log(
            f"SCAN | loaded {len(items)} post(s) | {counts['videos']} videos | "
            f"{counts['photos']} photos | newest first"
        )
        if has_more:
            log(
                "SCAN | TikTok reports more posts beyond this batch; DELETE ALL will "
                "continue batch-by-batch until none remain."
            )

        if not initial_targets:
            log(f"CLEANUP COMPLETE | no matching {options.mode} found.")
            if state:
                state("idle")
            return 0

        target_label = "DELETE ALL" if options.delete_all else f"DELETE {options.max_actions}"
        log(
            f"RUN LOCKED | {'PREVIEW ONLY' if options.dry_run else 'LIVE DELETE'} | "
            f"{options.mode.upper()} | {target_label}"
        )

        if arm_event is not None:
            if state:
                state("armed")
            log("Click ARM / CONTINUE once to begin.")
            arm_event.wait()

        if stop_event.is_set():
            log("Stopped before cleanup began.")
            if state:
                state("idle")
            return 0

        if state:
            state("running")

        if options.dry_run:
            preview_targets = initial_targets
            for item in preview_targets:
                if stop_event.is_set():
                    break
                log(_preview_line(item))
            if options.delete_all and has_more:
                log(
                    "PREVIEW NOTE | current Studio batch shown above. Live DELETE ALL "
                    "continues through later batches too."
                )
            log(f"Done. Previewed {len(preview_targets)} matching post(s); nothing deleted.")
            if state:
                state("idle")
            return len(preview_targets)

        deleted = 0
        stale_rounds = 0

        while not stop_event.is_set():
            remaining = None
            if not options.delete_all:
                remaining = options.max_actions - deleted
                if remaining <= 0:
                    break

            items, has_more = load_studio_items(page)
            candidates = select_targets(
                items,
                options.mode,
                remaining,
                excluded_ids=failed_ids,
            )
            if not candidates:
                if has_more and failed_ids:
                    log(
                        "No deletable matching posts remain in the current Studio batch. "
                        "Stopping rather than looping on failed matches."
                    )
                else:
                    log(f"No matching {options.mode} remain.")
                break

            progressed = False
            for item in candidates:
                if stop_event.is_set():
                    break
                ok = delete_studio_item(page, item, log)
                if ok:
                    deleted += 1
                    progressed = True
                    stale_rounds = 0
                    limit = "ALL" if options.delete_all else str(options.max_actions)
                    log(f"PROGRESS | {deleted}/{limit}")
                    if options.delay_seconds > 0:
                        time.sleep(options.delay_seconds)
                else:
                    failed_ids.add(item.item_id)

                if not options.delete_all and deleted >= options.max_actions:
                    break

            if stop_event.is_set():
                break
            if not options.delete_all and deleted >= options.max_actions:
                break

            if not progressed:
                stale_rounds += 1
                if stale_rounds >= 2:
                    log("No progress after repeated passes. Stopping safely.")
                    break
            else:
                stale_rounds = 0

        if stop_event.is_set():
            log("STOPPED | no further posts will be deleted.")
        else:
            log(f"CLEANUP COMPLETE | deleted {deleted} post(s).")

        if state:
            state("idle")
        return deleted
