"""Local full-colour emoji assets used by the Pulse Social picker.

The bundled PNGs come from the Twitter image set in iamcal/emoji-data.
They are embedded as base64 text so runtime rendering is fully offline.
"""

from __future__ import annotations

from .emoji_assets_categories import ASSETS as CATEGORY_ASSETS
from .emoji_assets_smileys_01 import ASSETS as SMILEYS_01
from .emoji_assets_smileys_02 import ASSETS as SMILEYS_02
from .emoji_assets_smileys_03 import ASSETS as SMILEYS_03
from .emoji_assets_smileys_04 import ASSETS as SMILEYS_04
from .emoji_assets_smileys_05 import ASSETS as SMILEYS_05
from .emoji_assets_smileys_06 import ASSETS as SMILEYS_06
from .emoji_assets_smileys_07 import ASSETS as SMILEYS_07

ASSETS: dict[str, str] = {}
for _pack in (
    CATEGORY_ASSETS,
    SMILEYS_01,
    SMILEYS_02,
    SMILEYS_03,
    SMILEYS_04,
    SMILEYS_05,
    SMILEYS_06,
    SMILEYS_07,
):
    ASSETS.update(_pack)


def asset_base64(emoji: str) -> str | None:
    return ASSETS.get(emoji)
