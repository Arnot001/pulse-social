from __future__ import annotations

import json
import os
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

APP_DIR = Path(os.environ["LOCALAPPDATA"]) / "Pulse Social"
APP_DIR.mkdir(parents=True, exist_ok=True)
QUEUE_FILE = APP_DIR / "x_auto_post_queue.json"
HISTORY_FILE = APP_DIR / "x_auto_post_history.txt"
MEDIA_CACHE_DIR = APP_DIR / "x_media_cache"
MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
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
    media_paths: list[str] = field(default_factory=list)


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


def add_post(text: str, due_at: datetime, media_paths: list[str] | None = None) -> QueuedPost:
    clean = text.strip()
    media = [str(Path(path)) for path in (media_paths or [])]
    if not clean and not media:
        raise ValueError("Post text and media are both empty.")
    item = QueuedPost(
        post_id=f"{int(time.time()*1000)}",
        text=clean,
        due_at=due_at.isoformat(timespec="seconds"),
        media_paths=media,
    )
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
            _browser, context, page, _browser_label = _connect_x_browser(p)
            if not context:
                raise RuntimeError("Browser attached but no browser context was available.")
            if "x.com" not in page.url.lower() or "/home" not in page.url.lower():
                page.goto("https://x.com/home", wait_until="domcontentloaded")
            _dismiss_x_overlays(page)

            # Use X's inline Home composer instead of /compose/post. The modal
            # composer is aggressively autosaved by X and can leave a duplicate
            # draft after successful media posts.
            editor = page.locator('[data-testid="tweetTextarea_0"]').first
            editor.wait_for(state="visible", timeout=10000)
            if text:
                editor.click()
                editor.fill(text)

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
                media_note = f" | MEDIA {len(item.media_paths)}" if item.media_paths else ""
                log(f"POSTING | {item.text[:100]}{media_note}")
                publish_post(item.text, item.media_paths, log=log)
                item.status = "posted"
                stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with HISTORY_FILE.open("a", encoding="utf-8") as f:
                    f.write(f"{stamp} | POSTED | media={len(item.media_paths)} | {item.text.replace(chr(10), ' ')}\n")
                log("POSTED successfully.")
            except Exception as exc:
                item.status = "error"
                log(f"POST ERROR | {exc}")
            changed = True
        if changed:
            save_queue(items)
    log("AUTO POST scheduler stopped.")
