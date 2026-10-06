from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from platforms.common.emoji_picker import (
    CATEGORY_LABELS,
    EMOJI_CATALOG,
    TONE_CAPABLE,
    TONE_MODIFIERS,
    apply_skin_tone,
)

ASSET_DIR = ROOT / "assets" / "emoji"
SPRITE_PATH = ASSET_DIR / "twemoji_32.png"
MANIFEST_PATH = ASSET_DIR / "twemoji_manifest.json"

EMOJI_DATA_URL = "https://raw.githubusercontent.com/iamcal/emoji-data/master/emoji.json"
SPRITE_URL = (
    "https://raw.githubusercontent.com/iamcal/emoji-data/master/"
    "sheets-clean/sheet_twitter_32_clean.png"
)
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _download(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Pulse-Social-Emoji-Vendor/1.0"},
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def _unicode_text(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return "".join(chr(int(part, 16)) for part in value.split("-"))
    except ValueError:
        return None


def _wanted_emojis() -> set[str]:
    wanted = {
        emoji
        for values in EMOJI_CATALOG.values()
        for emoji in values
    }
    wanted.update(
        glyph
        for name, glyph in CATEGORY_LABELS.items()
        if name != "RECENT"
    )
    for emoji in TONE_CAPABLE:
        for tone in TONE_MODIFIERS:
            wanted.add(apply_skin_tone(emoji, tone))
    return wanted


def _source_index(records: list[dict]) -> dict[str, list[int]]:
    index: dict[str, list[int]] = {}

    def add(record: dict) -> None:
        if not record.get("has_img_twitter"):
            return
        x = record.get("sheet_x")
        y = record.get("sheet_y")
        if not isinstance(x, int) or not isinstance(y, int):
            return
        coords = [x, y]
        for key in ("unified", "non_qualified"):
            text = _unicode_text(record.get(key))
            if text:
                index[text] = coords

    for record in records:
        add(record)
        variations = record.get("skin_variations") or {}
        if isinstance(variations, dict):
            for variation in variations.values():
                if isinstance(variation, dict):
                    add(variation)
    return index


def _build_manifest(records: list[dict]) -> dict[str, list[int]]:
    source = _source_index(records)
    manifest: dict[str, list[int]] = {}
    missing: list[str] = []

    for emoji in sorted(_wanted_emojis()):
        coords = source.get(emoji)
        if coords is None:
            coords = source.get(emoji.replace("\ufe0f", ""))
        if coords is None:
            missing.append(emoji)
            continue
        manifest[emoji] = coords

    if missing:
        preview = " ".join(missing[:20])
        print(f"[emoji] {len(missing)} catalog entries have no Twitter artwork: {preview}")
    return manifest


def _write_assets() -> tuple[int, int]:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)

    print("[emoji] Downloading emoji metadata...")
    records = json.loads(_download(EMOJI_DATA_URL).decode("utf-8"))
    manifest = _build_manifest(records)

    print("[emoji] Downloading clean 32px Twemoji sprite sheet...")
    sprite = _download(SPRITE_URL)
    if not sprite.startswith(PNG_MAGIC):
        raise RuntimeError("Downloaded Twemoji sprite is not a PNG file.")
    SPRITE_PATH.write_bytes(sprite)

    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    return len(manifest), len(sprite)


def _commit_and_push() -> None:
    paths = [
        str(SPRITE_PATH.relative_to(ROOT)),
        str(MANIFEST_PATH.relative_to(ROOT)),
    ]
    subprocess.run(["git", "add", "--", *paths], cwd=ROOT, check=True)
    changed = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=ROOT,
        check=False,
    ).returncode != 0

    if changed:
        subprocess.run(
            ["git", "commit", "-m", "Bundle full-colour Twemoji sprite assets"],
            cwd=ROOT,
            check=True,
        )
    else:
        print("[emoji] Assets already match the committed versions.")

    subprocess.run(
        ["git", "push", "origin", "HEAD:beta-emoji-release"],
        cwd=ROOT,
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Vendor the offline Twemoji sprite used by Pulse Social."
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Commit the generated assets and push them to beta-emoji-release.",
    )
    args = parser.parse_args()

    count, size = _write_assets()
    print(f"[emoji] Ready: {count} emoji mappings, {size / (1024 * 1024):.1f} MiB sprite.")

    if args.commit:
        _commit_and_push()
        print("[emoji] Committed and pushed to beta-emoji-release.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
