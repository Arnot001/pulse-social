from __future__ import annotations

import base64

from platforms.common.emoji_assets import asset_base64


def test_bundled_smiley_asset_is_png():
    data = asset_base64("😀")
    assert data
    assert base64.b64decode(data).startswith(b"\x89PNG\r\n\x1a\n")


def test_bundled_category_asset_is_png():
    data = asset_base64("❤️")
    assert data
    assert base64.b64decode(data).startswith(b"\x89PNG\r\n\x1a\n")


def test_bundled_manifest_tiles_are_in_bounds_nonempty_and_cover_catalog():
    from PIL import Image
    from platforms.common import emoji_picker as picker

    manifest = picker._load_sprite_manifest()
    with Image.open(picker._resource_path(picker.SPRITE_RELATIVE_PATH)) as source:
        sheet = source.convert("RGBA")
    for emoji, (sheet_x, sheet_y) in manifest.items():
        x, y = sheet_x * 34 + 1, sheet_y * 34 + 1
        assert 0 <= x < x + 32 <= sheet.width, ascii(emoji)
        assert 0 <= y < y + 32 <= sheet.height, ascii(emoji)
        assert sheet.crop((x, y, x + 32, y + 32)).getbbox(), ascii(emoji)
    for category in picker.EMOJI_CATALOG:
        for tone in picker.TONE_MODIFIERS:
            for emoji in picker.filter_emojis(category, tone=tone):
                assert picker.asset_base64(emoji) or emoji in manifest or emoji.replace("\ufe0f", "") in manifest, ascii(emoji)


def test_resource_path_supports_packaged_and_source_assets(tmp_path, monkeypatch):
    import sys
    from platforms.common import emoji_picker as picker

    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    source_path = picker._resource_path(picker.SPRITE_RELATIVE_PATH)
    assert source_path.is_file()
    bundled = tmp_path / picker.SPRITE_RELATIVE_PATH
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"test resource")
    assert picker._resource_path(picker.SPRITE_RELATIVE_PATH) == bundled
