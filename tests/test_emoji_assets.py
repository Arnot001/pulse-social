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
