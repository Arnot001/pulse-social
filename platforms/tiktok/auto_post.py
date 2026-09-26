from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import requests

from .browser_post import IMAGE_SUFFIXES, VIDEO_SUFFIXES, publish_browser_post
from .oauth import get_access_token

APP_DIR = Path(os.environ["LOCALAPPDATA"]) / "Pulse Social"
APP_DIR.mkdir(parents=True, exist_ok=True)
QUEUE_FILE = APP_DIR / "tiktok_auto_post_queue.json"
HISTORY_FILE = APP_DIR / "tiktok_auto_post_history.txt"
MEDIA_CACHE_DIR = APP_DIR / "tiktok_media_cache"
MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)

API_BASE = "https://open.tiktokapis.com"
CREATOR_INFO_URL = f"{API_BASE}/v2/post/publish/creator_info/query/"
VIDEO_INIT_URL = f"{API_BASE}/v2/post/publish/video/init/"
STATUS_URL = f"{API_BASE}/v2/post/publish/status/fetch/"

MAX_CAPTION_UTF16 = 2200
MAX_VIDEO_BYTES = 4 * 1024 * 1024 * 1024
WHOLE_UPLOAD_LIMIT = 64_000_000
CHUNK_SIZE = 10_000_000
SCHEDULER_INTERVAL_SECONDS = 10
REQUEST_TIMEOUT = 45
UPLOAD_TIMEOUT = 180

TIKTOK_ACTION_LOCK = threading.Lock()


@dataclass
class TikTokQueuedPost:
    post_id: str
    caption: str
    due_at: str
    video_path: str = ""
    media_paths: list[str] = field(default_factory=list)
    privacy_level: str = "PUBLIC"
    disable_comment: bool = False
    disable_duet: bool = False
    disable_stitch: bool = False
    brand_content_toggle: bool = False
    brand_organic_toggle: bool = False
    is_aigc: bool = False
    music_query: str = ""
    music_search: str = ""
    status: str = "queued"
    publish_id: str = ""
    remote_status: str = ""
    fail_reason: str = ""


def load_queue() -> list[TikTokQueuedPost]:
    if not QUEUE_FILE.exists():
        return []
    try:
        raw = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
        return [TikTokQueuedPost(**item) for item in raw if isinstance(item, dict)]
    except Exception:
        return []


def save_queue(items: list[TikTokQueuedPost]) -> None:
    QUEUE_FILE.write_text(
        json.dumps([asdict(item) for item in items], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _normalize_media_paths(media_paths: str | list[str]) -> list[str]:
    if isinstance(media_paths, str):
        raw = [media_paths] if media_paths else []
    else:
        raw = list(media_paths or [])

    paths = [Path(path) for path in raw]
    if not paths:
        raise ValueError("Choose at least one TikTok image or video.")
    missing = [str(path) for path in paths if not path.exists() or not path.is_file()]
    if missing:
        raise ValueError("TikTok media file missing: " + ", ".join(missing))

    suffixes = {path.suffix.lower() for path in paths}
    image_only = suffixes.issubset(IMAGE_SUFFIXES)
    video_only = len(paths) == 1 and paths[0].suffix.lower() in VIDEO_SUFFIXES
    if not image_only and not video_only:
        raise ValueError(
            "Choose either one video or one/more images for each TikTok post."
        )
    return [str(path) for path in paths]


def item_media_paths(item: TikTokQueuedPost) -> list[str]:
    if item.media_paths:
        return list(item.media_paths)
    if item.video_path:
        return [item.video_path]
    return []


def add_post(
    caption: str,
    due_at: datetime,
    media_paths: str | list[str],
    *,
    privacy_level: str = "PUBLIC",
    disable_comment: bool = False,
    disable_duet: bool = False,
    disable_stitch: bool = False,
    brand_content_toggle: bool = False,
    brand_organic_toggle: bool = False,
    is_aigc: bool = False,
    music_query: str = "",
    music_search: str = "",
) -> TikTokQueuedPost:
    clean = caption.strip()
    if _utf16_length(clean) > MAX_CAPTION_UTF16:
        raise ValueError("TikTok captions can be at most 2200 UTF-16 characters.")

    media = _normalize_media_paths(media_paths)
    legacy_video_path = media[0] if len(media) == 1 and Path(media[0]).suffix.lower() in VIDEO_SUFFIXES else ""

    item = TikTokQueuedPost(
        post_id=f"{int(time.time() * 1000)}",
        caption=clean,
        due_at=due_at.isoformat(timespec="seconds"),
        video_path=legacy_video_path,
        media_paths=media,
        privacy_level=privacy_level,
        disable_comment=disable_comment,
        disable_duet=disable_duet,
        disable_stitch=disable_stitch,
        brand_content_toggle=brand_content_toggle,
        brand_organic_toggle=brand_organic_toggle,
        is_aigc=is_aigc,
        music_query=music_query.strip(),
        music_search=music_search.strip(),
    )
    items = load_queue()
    items.append(item)
    items.sort(key=lambda row: row.due_at)
    save_queue(items)
    return item


def remove_post(post_id: str) -> None:
    save_queue([item for item in load_queue() if item.post_id != post_id])


def _check_api_response(response: requests.Response, action: str) -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"TikTok {action} returned invalid JSON (HTTP {response.status_code}).") from exc

    if response.status_code >= 400:
        detail = payload.get("error") if isinstance(payload, dict) else None
        raise RuntimeError(f"TikTok {action} failed (HTTP {response.status_code}): {detail or payload}")

    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict) and error.get("code") not in (None, "", "ok"):
        message = error.get("message") or error.get("code")
        raise RuntimeError(f"TikTok {action} failed: {message}")

    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else {}


def _post_json(url: str, token: str, body: dict, action: str) -> dict:
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        json=body,
        timeout=REQUEST_TIMEOUT,
    )
    return _check_api_response(response, action)


def query_creator_info(token: str | None = None) -> dict:
    access_token = (token or get_access_token()).strip()
    if not access_token:
        raise RuntimeError("TikTok is not connected. Use CONNECT TIKTOK first.")
    return _post_json(CREATOR_INFO_URL, access_token, {}, "creator info")


def _transcode_video_for_tiktok(source: Path, log: Callable[[str], None] | None = None) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            "FFmpeg is required to prepare TikTok videos. Install FFmpeg, reopen Pulse Social, and retry."
        )

    target = MEDIA_CACHE_DIR / f"{source.stem[:48]}-{int(time.time() * 1000)}-tiktok.mp4"
    if log:
        log(f"VIDEO PREP | {source.name} | converting to TikTok-safe H.264/AAC MP4")

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
        "fps=30,format=yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "22",
        "-maxrate",
        "12M",
        "-bufsize",
        "24M",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
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
            timeout=1800,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired as exc:
        target.unlink(missing_ok=True)
        raise RuntimeError("TikTok video preparation timed out after 30 minutes.") from exc

    if result.returncode != 0 or not target.exists() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        detail = " ".join((result.stderr or "").strip().split())
        if len(detail) > 600:
            detail = detail[-600:]
        raise RuntimeError(
            f"FFmpeg could not prepare the TikTok video: {detail or 'unknown conversion error'}"
        )

    if target.stat().st_size > MAX_VIDEO_BYTES:
        target.unlink(missing_ok=True)
        raise RuntimeError("Prepared TikTok video is larger than TikTok's 4 GB upload limit.")

    if log:
        size_mb = target.stat().st_size / (1024 * 1024)
        log(f"VIDEO READY | {target.name} | {size_mb:.1f} MB")
    return target


def chunk_plan(video_size: int) -> tuple[int, int]:
    if video_size <= 0:
        raise ValueError("Video file is empty.")
    if video_size <= WHOLE_UPLOAD_LIMIT:
        return video_size, 1

    count = video_size // CHUNK_SIZE
    if count < 1:
        count = 1
    if count > 1000:
        raise ValueError("Video would require more than TikTok's 1000 upload chunks.")
    return CHUNK_SIZE, count


def _init_direct_post(item: TikTokQueuedPost, prepared: Path, token: str) -> tuple[str, str]:
    creator = query_creator_info(token)
    allowed_privacy = creator.get("privacy_level_options") or []
    if allowed_privacy and item.privacy_level not in allowed_privacy:
        raise RuntimeError(
            f"TikTok account does not currently allow privacy level {item.privacy_level}. "
            f"Allowed: {', '.join(allowed_privacy)}"
        )

    video_size = prepared.stat().st_size
    chunk_size, total_chunk_count = chunk_plan(video_size)
    body = {
        "post_info": {
            "title": item.caption,
            "privacy_level": item.privacy_level,
            "disable_duet": bool(item.disable_duet),
            "disable_comment": bool(item.disable_comment),
            "disable_stitch": bool(item.disable_stitch),
            "video_cover_timestamp_ms": 0,
            "brand_content_toggle": bool(item.brand_content_toggle),
            "brand_organic_toggle": bool(item.brand_organic_toggle),
            "is_aigc": bool(item.is_aigc),
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": video_size,
            "chunk_size": chunk_size,
            "total_chunk_count": total_chunk_count,
        },
    }
    data = _post_json(VIDEO_INIT_URL, token, body, "video publish init")
    publish_id = str(data.get("publish_id") or "")
    upload_url = str(data.get("upload_url") or "")
    if not publish_id or not upload_url:
        raise RuntimeError("TikTok did not return a publish_id and upload_url.")
    return publish_id, upload_url


def _upload_video(
    prepared: Path,
    upload_url: str,
    log: Callable[[str], None] | None = None,
) -> None:
    total = prepared.stat().st_size
    chunk_size, total_chunks = chunk_plan(total)

    with prepared.open("rb") as handle:
        start = 0
        for index in range(total_chunks):
            if index == total_chunks - 1:
                data = handle.read()
            else:
                data = handle.read(chunk_size)
            if not data:
                raise RuntimeError("TikTok upload stopped because a video chunk was empty.")

            end = start + len(data) - 1
            response = requests.put(
                upload_url,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(data)),
                    "Content-Range": f"bytes {start}-{end}/{total}",
                },
                data=data,
                timeout=UPLOAD_TIMEOUT,
            )
            expected = 201 if index == total_chunks - 1 else 206
            if response.status_code != expected:
                body = (response.text or "").strip()
                if len(body) > 500:
                    body = body[:500]
                raise RuntimeError(
                    f"TikTok video upload chunk {index + 1}/{total_chunks} failed "
                    f"(HTTP {response.status_code}, expected {expected}): {body}"
                )

            if log:
                pct = int(((index + 1) / total_chunks) * 100)
                log(f"UPLOAD | chunk {index + 1}/{total_chunks} | {pct}%")
            start = end + 1


def submit_direct_post(
    item: TikTokQueuedPost,
    log: Callable[[str], None] | None = None,
) -> str:
    token = get_access_token().strip()
    if not token:
        raise RuntimeError("TikTok is not connected. Use CONNECT TIKTOK first.")

    source = Path(item.video_path)
    if not source.exists():
        raise RuntimeError(f"Video file no longer exists: {source}")

    prepared = _transcode_video_for_tiktok(source, log)
    try:
        publish_id, upload_url = _init_direct_post(item, prepared, token)
        if log:
            log(f"TIKTOK INIT | publish_id={publish_id}")
        _upload_video(prepared, upload_url, log)
        return publish_id
    finally:
        prepared.unlink(missing_ok=True)


def fetch_publish_status(publish_id: str, token: str | None = None) -> dict:
    access_token = (token or get_access_token()).strip()
    if not access_token:
        raise RuntimeError("TikTok is not connected.")
    return _post_json(
        STATUS_URL,
        access_token,
        {"publish_id": publish_id},
        "publish status",
    )


def _record_history(item: TikTokQueuedPost) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with HISTORY_FILE.open("a", encoding="utf-8") as handle:
        handle.write(
            f"{stamp} | POSTED | media={len(item_media_paths(item))} | "
            f"music={item.music_query or 'none'} | privacy={item.privacy_level} | "
            f"{item.caption.replace(chr(10), ' ')}\n"
        )


def run_scheduler(stop_event: threading.Event, log: Callable[[str], None]) -> None:
    log("TIKTOK AUTO POST scheduler started.")
    while not stop_event.wait(SCHEDULER_INTERVAL_SECONDS):
        with TIKTOK_ACTION_LOCK:
            items = load_queue()
            now = datetime.now()
            changed = False

            for item in items:
                if item.status == "queued":
                    try:
                        due = datetime.fromisoformat(item.due_at)
                    except ValueError:
                        item.status = "error"
                        item.fail_reason = "Invalid scheduled date/time."
                        changed = True
                        continue

                    if due > now:
                        continue

                    try:
                        media = item_media_paths(item)
                        image_count = sum(
                            1 for path in media if Path(path).suffix.lower() in IMAGE_SUFFIXES
                        )
                        media_note = (
                            f"IMAGES {image_count}"
                            if image_count
                            else f"VIDEO {Path(media[0]).name if media else '<missing>'}"
                        )
                        music_note = f' | SOUND "{item.music_query}"' if item.music_query else ""
                        log(f"POSTING | {item.caption[:100]} | {media_note}{music_note}")
                        publish_browser_post(
                            item.caption,
                            media,
                            log=log,
                            music_query=item.music_query,
                            music_search=item.music_search,
                            privacy_level=item.privacy_level,
                        )
                        item.status = "posted"
                        item.publish_id = ""
                        item.remote_status = "BROWSER_POSTED"
                        item.fail_reason = ""
                        _record_history(item)
                        changed = True
                        log("POSTED successfully.")
                    except Exception as exc:
                        item.status = "error"
                        item.fail_reason = str(exc)
                        changed = True
                        log(f"POST ERROR | {exc}")

                elif item.status == "processing" and item.publish_id:
                    try:
                        data = fetch_publish_status(item.publish_id)
                        remote_status = str(data.get("status") or "")
                        if remote_status and remote_status != item.remote_status:
                            item.remote_status = remote_status
                            log(f"TIKTOK STATUS | {item.publish_id} | {remote_status}")
                            changed = True

                        if remote_status == "PUBLISH_COMPLETE":
                            item.status = "posted"
                            item.fail_reason = ""
                            _record_history(item)
                            changed = True
                            log("POSTED successfully.")
                        elif remote_status == "FAILED":
                            item.status = "error"
                            item.fail_reason = str(data.get("fail_reason") or "TikTok publish failed.")
                            changed = True
                            log(f"POST ERROR | {item.fail_reason}")
                    except Exception as exc:
                        log(f"STATUS CHECK ERROR | {item.publish_id} | {exc}")

            if changed:
                save_queue(items)

    log("TIKTOK AUTO POST scheduler stopped.")
