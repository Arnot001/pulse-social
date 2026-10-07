from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from playwright.sync_api import sync_playwright

from platforms import browser_control

APP_DIR = Path(os.environ["LOCALAPPDATA"]) / "Pulse Social"
APP_DIR.mkdir(parents=True, exist_ok=True)
QUEUE_FILE = APP_DIR / "x_auto_post_queue.json"
HISTORY_FILE = APP_DIR / "x_auto_post_history.txt"
MEDIA_CACHE_DIR = APP_DIR / "x_media_cache"
MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
POSTING_PAGE_NAME = "pulse-social-auto-post"
X_ACTION_LOCK = threading.Lock()
QUEUE_LOCK = threading.RLock()
SCHEDULER_LOCK = threading.Lock()
_POSTING_TARGET_ID = None


@dataclass
class QueuedPost:
    post_id: str
    text: str
    due_at: str
    status: str = "queued"
    media_paths: list[str] = field(default_factory=list)
    posted_at: str = ""


def load_queue() -> list[QueuedPost]:
    with QUEUE_LOCK:
        if not QUEUE_FILE.exists():
            return []
        try:
            data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
            unique = {}
            for record in data:
                if not isinstance(record, dict):
                    continue
                item = QueuedPost(**record)
                previous = unique.get(item.post_id)
                # A persisted success must never be requeued by a duplicate record.
                if previous is None or (previous.status != "posted" and item.status != "queued"):
                    unique[item.post_id] = item
            return list(unique.values())
        except (OSError, ValueError, TypeError):
            return []


def save_queue(items: list[QueuedPost]) -> None:
    with QUEUE_LOCK:
        temporary = QUEUE_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps([asdict(x) for x in items], indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(QUEUE_FILE)


def add_post(text: str, due_at: datetime, media_paths: list[str] | None = None) -> QueuedPost:
    clean = text.strip()
    media = [str(Path(path)) for path in (media_paths or [])]
    if not clean and not media:
        raise ValueError("Post text and media are both empty.")
    item = QueuedPost(
        post_id=uuid.uuid4().hex,
        text=clean,
        due_at=due_at.isoformat(timespec="seconds"),
        media_paths=media,
    )
    with QUEUE_LOCK:
        items = load_queue()
        items.append(item)
        items.sort(key=lambda x: x.due_at)
        save_queue(items)
    return item


def remove_post(post_id: str) -> None:
    with QUEUE_LOCK:
        save_queue([x for x in load_queue() if x.post_id != post_id])


def _verify_pulse_profile(browser) -> None:
    """Verify the CDP browser process uses a Pulse profile before touching its tabs."""
    session = browser.new_browser_cdp_session()
    try:
        processes = session.send("SystemInfo.getProcessInfo")["processInfo"]
        pid = int(next(process["id"] for process in processes if process["type"] == "browser"))
    finally:
        session.detach()
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}').CommandLine | ConvertTo-Json -Compress"],
        capture_output=True, text=True, timeout=10,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    command = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else ""
    match = re.search(r'(?:"--user-data-dir=([^\"]+)"|--user-data-dir="([^\"]+)"|--user-data-dir=([^\s\"]+))', command or "")
    profile = Path(next(value for value in match.groups() if value)).resolve() if match else None
    allowed = { (browser_control.BROWSER_PROFILE_ROOT / name).resolve()
                for name in ("brave", "chrome", "edge") }
    if profile not in allowed:
        raise RuntimeError("X Auto Post requires the dedicated Pulse Browser profile. Reconnect Pulse Browser first.")


def _connect_x_browser(playwright):
    # Only Pulse's endpoint is eligible; never scan normal browser profiles/ports.
    if not browser_control.cdp_responding():
        ok, detail = browser_control.connect_browser()
        if not ok:
            raise RuntimeError(detail)
    browser = playwright.chromium.connect_over_cdp(browser_control.CDP_URL, timeout=3500)
    _verify_pulse_profile(browser)
    if not browser.contexts:
        raise RuntimeError("Pulse Browser attached but no browser context was available.")
    return browser, browser.contexts[0], None, "Pulse Browser"


def _dismiss_x_overlays(page) -> None:
    """Dismiss known benign X interstitials that can block the composer."""
    candidates = (
        ("button", "Got it"),
        ("button", "Continue"),
        ("button", "Close"),
    )
    for role, name in candidates:
        try:
            control = page.get_by_role(role, name=name, exact=True)
            if control.count() and control.first.is_visible():
                control.first.click(timeout=2500)
                page.wait_for_timeout(300)
                return
        except Exception:
            pass


def _close_x_composer(page) -> None:
    """Close any stale X composer left behind after a confirmed post, discarding draft residue."""
    try:
        dialog = page.get_by_role("dialog")
        if not dialog.count() or not dialog.first.is_visible():
            return
    except Exception:
        return

    try:
        close_button = dialog.first.locator('[aria-label="Close"]').first
        if close_button.count() and close_button.is_visible():
            close_button.click(timeout=2500)
            page.wait_for_timeout(400)
        else:
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)
    except Exception:
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)
        except Exception:
            return

    # X may offer to save the still-open composer as a draft. We never want
    # scheduled posts to leave duplicate drafts after the post succeeded.
    for label in ("Discard", "Delete"):
        try:
            action = page.get_by_role("button", name=label, exact=True)
            if action.count() and action.first.is_visible():
                action.first.click(timeout=2500)
                page.wait_for_timeout(300)
                return
        except Exception:
            pass


def _posting_target_id(context, page):
    session = context.new_cdp_session(page)
    try:
        return session.send("Target.getTargetInfo")["targetInfo"]["targetId"]
    finally:
        session.detach()


def _get_or_create_posting_page(context):
    """Reacquire the same Chromium target across Playwright connections."""
    global _POSTING_TARGET_ID
    for page in context.pages:
        try:
            if page.is_closed():
                continue
            target_id = _posting_target_id(context, page)
            if target_id == _POSTING_TARGET_ID or page.evaluate("window.name") == POSTING_PAGE_NAME:
                _POSTING_TARGET_ID = target_id
                return page, False
        except Exception:
            continue

    page = context.new_page()
    _POSTING_TARGET_ID = _posting_target_id(context, page)
    return page, True


def _x_media_processing_error(page) -> str | None:
    """Return X's visible media-upload error, if it has already rejected the file."""
    try:
        messages = page.locator('[data-testid="toast"], [role="alert"]').all_inner_texts()
    except Exception:
        return None
    for message in messages:
        clean = " ".join(message.split())
        lowered = clean.lower()
        if (
            "could not be processed" in lowered
            or "failed to upload" in lowered
            or "media upload failed" in lowered
            or ("video" in lowered and "upload" in lowered and "error" in lowered)
        ):
            return clean
    return None


def _transcode_video_for_x(source: Path, log: Callable[[str], None] | None = None) -> Path:
    """Create a conservative X-safe H.264/AAC MP4 copy of a video."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            "FFmpeg is required to prepare videos for X. Install FFmpeg, reopen Pulse Social, and retry."
        )

    target = MEDIA_CACHE_DIR / f"{source.stem[:40]}-{uuid.uuid4().hex[:10]}-x.mp4"
    if log:
        log(f"VIDEO PREP | {source.name} | converting to X-safe H.264/AAC MP4")

    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-vf",
        "scale=1280:1280:force_original_aspect_ratio=decrease:force_divisible_by=2,fps=30,format=yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "23",
        "-maxrate",
        "8M",
        "-bufsize",
        "16M",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        str(target),
    ]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=900,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired as exc:
        target.unlink(missing_ok=True)
        raise RuntimeError("Video preparation timed out after 15 minutes.") from exc

    if result.returncode != 0 or not target.exists() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        detail = " ".join((result.stderr or "").strip().split())
        if len(detail) > 500:
            detail = detail[-500:]
        raise RuntimeError(f"FFmpeg could not prepare the video for X: {detail or 'unknown conversion error'}")

    if log:
        mb = target.stat().st_size / (1024 * 1024)
        log(f"VIDEO READY | {target.name} | {mb:.1f} MB")
    return target


def _prepare_media_for_x(
    media: list[Path], log: Callable[[str], None] | None = None
) -> tuple[list[Path], list[Path]]:
    prepared: list[Path] = []
    temporary: list[Path] = []
    try:
        for path in media:
            if path.suffix.lower() in VIDEO_SUFFIXES:
                converted = _transcode_video_for_x(path, log)
                prepared.append(converted)
                temporary.append(converted)
            else:
                prepared.append(path)
    except Exception:
        for path in temporary:
            path.unlink(missing_ok=True)
        raise
    return prepared, temporary


def publish_post(
    text: str,
    media_paths: list[str] | None = None,
    log: Callable[[str], None] | None = None,
) -> None:
    with X_ACTION_LOCK:
        media = [Path(path) for path in (media_paths or [])]
        missing = [str(path) for path in media if not path.exists()]
        if missing:
            raise RuntimeError("Media file missing: " + ", ".join(missing))

        prepared_media, temporary_media = _prepare_media_for_x(media, log)
        try:
            with sync_playwright() as p:
                _browser, context, _existing_page, _browser_label = _connect_x_browser(p)
                if not context:
                    raise RuntimeError("Browser attached but no browser context was available.")

                # Keep one dedicated Pulse tab and reuse it for every scheduled post.
                # We still hard-navigate it back to Home each time, so stale media/profile
                # route state cannot poison the next post, but tabs no longer accumulate.
                page, created = _get_or_create_posting_page(context)
                if log:
                    log(
                        "X POST PAGE | opening dedicated Home composer"
                        if created
                        else "X POST PAGE | reusing dedicated Home composer"
                    )
                page.goto(
                    "https://x.com/home",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                # Set the marker on X's origin, after navigation (which can clear window.name).
                # The target ID also survives navigation and new Playwright connections.
                page.evaluate("(name) => { window.name = name; }", POSTING_PAGE_NAME)
                _dismiss_x_overlays(page)

                editor = page.locator('[data-testid="tweetTextarea_0"]').first
                try:
                    editor.wait_for(state="visible", timeout=15000)
                except Exception as exc:
                    raise RuntimeError(
                        f"X Home composer did not become ready. Current page: {page.url}"
                    ) from exc

                if text:
                    # Programmatic focus avoids X's transparent SPA layers stealing
                    # mouse clicks from the composer after a previous media post.
                    editor.focus()
                    page.keyboard.insert_text(text)

                if prepared_media:
                    file_input = page.locator('input[type="file"]').first
                    file_input.wait_for(state="attached", timeout=10000)
                    file_input.set_input_files([str(path) for path in prepared_media])
                    # X can take a while to process video, but it can also reject a file
                    # immediately. Detect that state instead of waiting on a disabled Post
                    # button for two minutes and making the UI look like it is looping.
                    page.wait_for_timeout(1200)
                    media_error = _x_media_processing_error(page)
                    if media_error:
                        raise RuntimeError(f"X rejected the media: {media_error}")

                post_button = page.locator('[data-testid="tweetButton"]').first
                if post_button.count() == 0:
                    post_button = page.locator('[data-testid="tweetButtonInline"]').first
                post_button.wait_for(state="visible", timeout=10000)
                deadline = time.time() + (120 if prepared_media else 15)
                while post_button.is_disabled() and time.time() < deadline:
                    if prepared_media:
                        media_error = _x_media_processing_error(page)
                        if media_error:
                            raise RuntimeError(f"X rejected the media: {media_error}")
                    page.wait_for_timeout(500)
                if post_button.is_disabled():
                    if prepared_media:
                        media_error = _x_media_processing_error(page)
                        if media_error:
                            raise RuntimeError(f"X rejected the media: {media_error}")
                    raise RuntimeError("X Post button stayed disabled while media was processing.")
                post_button.click(timeout=10000)

                # Inline Home composer should reset after a successful post and does
                # not need modal cleanup. Wait briefly for X to clear the composer.
                page.wait_for_timeout(1500)
        finally:
            for path in temporary_media:
                path.unlink(missing_ok=True)


def _save_post_result(item: QueuedPost) -> None:
    """Merge one result into current state without losing edits made during posting."""
    with QUEUE_LOCK:
        items = load_queue()
        for index, current in enumerate(items):
            if current.post_id == item.post_id:
                items[index] = item
                break
        else:
            # If removed while in flight, still retain a confirmed successful post.
            if item.status == "posted":
                items.append(item)
        save_queue(items)


def run_scheduler(stop_event: threading.Event, log: Callable[[str], None]) -> None:
    log("AUTO POST scheduler started.")
    while not stop_event.wait(5):
        # Multiple open windows must not publish stale snapshots of the same queue.
        with SCHEDULER_LOCK:
            now = datetime.now()
            for candidate in load_queue():
                if stop_event.is_set():
                    break
                item = next((x for x in load_queue() if x.post_id == candidate.post_id), None)
                if item is None or item.status != "queued":
                    continue
                try:
                    due = datetime.fromisoformat(item.due_at)
                except ValueError:
                    item.status = "invalid"
                    _save_post_result(item)
                    continue
                if due > now:
                    continue
                try:
                    media_note = f" | MEDIA {len(item.media_paths)}" if item.media_paths else ""
                    log(f"POSTING | {item.text[:100]}{media_note}")
                    publish_post(item.text, item.media_paths, log=log)
                except Exception as exc:
                    item.status = "error"
                    _save_post_result(item)
                    log(f"POST ERROR | {exc}")
                    continue

                item.status = "posted"
                item.posted_at = datetime.now().isoformat(timespec="seconds")
                # Persist before notifying the UI; it can now display this success immediately.
                _save_post_result(item)
                try:
                    with HISTORY_FILE.open("a", encoding="utf-8") as f:
                        f.write(f"{item.posted_at} | POSTED | media={len(item.media_paths)} | {item.text.replace(chr(10), ' ')}\n")
                except OSError as exc:
                    # A history-log failure must not turn a published post into a retry.
                    log(f"HISTORY WARNING | {exc}")
                log("POSTED successfully.")
    log("AUTO POST scheduler stopped.")
