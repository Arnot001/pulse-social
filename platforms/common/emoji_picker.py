from __future__ import annotations

import json
import logging
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk
import unicodedata
from pathlib import Path
from typing import Callable, Iterable

from .emoji_assets import asset_base64

try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk
except ImportError:
    Image = ImageDraw = ImageFont = ImageTk = None

APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Pulse Social"
RECENTS_PATH = APP_DIR / "emoji_recents.json"
MAX_RECENTS = 36

BG = "#070910"
PANEL = "#101622"
PANEL_2 = "#151d2c"
BORDER = "#28354b"
TEXT = "#f7f8fb"
MUTED = "#8e9aae"
ACCENT = "#ff0a8a"
CYAN = "#25f4ee"
GLOW_SOFT = "#2a1230"
CYAN_SOFT = "#102c35"
EMOJI_FONT_PATH = Path(os.environ.get("WINDIR", r"C:\\Windows")) / "Fonts" / "seguiemj.ttf"
SPRITE_RELATIVE_PATH = Path("assets") / "emoji" / "twemoji_32.png"
SPRITE_MANIFEST_RELATIVE_PATH = Path("assets") / "emoji" / "twemoji_manifest.json"
SPRITE_SIZE = 32
SPRITE_CELL = SPRITE_SIZE + 2


def _resource_path(relative: Path) -> Path:
    packaged_root = getattr(sys, "_MEIPASS", None)
    if packaged_root:
        candidate = Path(packaged_root) / relative
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parents[2] / relative


def _load_sprite_manifest() -> dict[str, list[int]]:
    path = _resource_path(SPRITE_MANIFEST_RELATIVE_PATH)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        emoji: coords
        for emoji, coords in data.items()
        if isinstance(emoji, str)
        and isinstance(coords, list)
        and len(coords) == 2
        and all(isinstance(value, int) for value in coords)
    }
TONE_SWATCHES = {
    "DEFAULT": TEXT,
    "LIGHT": "#f6d6bd",
    "MEDIUM-LIGHT": "#e6b487",
    "MEDIUM": "#bf835f",
    "MEDIUM-DARK": "#8a5a3b",
    "DARK": "#5b3826",
}

CATEGORY_LABELS = {
    "RECENT": "◷",
    "SMILEYS": "😀",
    "PEOPLE": "👋",
    "ANIMALS": "🐶",
    "FOOD": "🍕",
    "ACTIVITY": "⚽",
    "TRAVEL": "✈️",
    "OBJECTS": "💡",
    "SYMBOLS": "❤️",
    "FLAGS": "🏁",
}

# Curated Unicode catalog; artwork is bundled locally. No runtime network access.
EMOJI_CATALOG = {
    "SMILEYS": "😀 😃 😄 😁 😆 😅 😂 🤣 😊 😇 🙂 🙃 😉 😌 😍 🥰 😘 😗 😙 😚 😋 😛 😝 😜 🤪 🤨 🧐 🤓 😎 🥸 🤩 🥳 😏 😒 😞 😔 😟 😕 🙁 ☹️ 😣 😖 😫 😩 🥺 😢 😭 😤 😠 😡 🤬 🤯 😳 🥵 🥶 😱 😨 😰 😥 😓 🤗 🤔 🫣 🤭 🫢 🫡 🤫 🫠 🤥 😶 🫥 😐 🫤 😑 😬 🙄 😯 😦 😧 😮 😲 🥱 😴 🤤 😪 😵 😵‍💫 🤐 🥴 🤢 🤮 🤧 😷 🤒 🤕 🤑 🤠 😈 👿 👹 👺 🤡 💩 👻 💀 ☠️ 👽 👾 🤖 🎃 😺 😸 😹 😻 😼 😽 🙀 😿 😾".split(),
    "PEOPLE": "👋 🤚 🖐️ ✋ 🖖 🫱 🫲 🫳 🫴 👌 🤌 🤏 ✌️ 🤞 🫰 🤟 🤘 🤙 👈 👉 👆 🖕 👇 ☝️ 👍 👎 ✊ 👊 🤛 🤜 👏 🙌 🫶 👐 🤲 🤝 🙏 ✍️ 💅 🤳 💪 🦾 🦵 🦿 🦶 👂 🦻 👃 🧠 🫀 🫁 🦷 🦴 👀 👁️ 👅 👄 🫦 👶 🧒 👦 👧 🧑 👱 👨 🧔 👩 🧓 👴 👵 🙍 🙎 🙅 🙆 💁 🙋 🧏 🙇 🤦 🤷 👮 🕵️ 💂 🥷 👷 🫅 🤴 👸 👳 👲 🧕 🤵 👰 🤰 🫃 🫄 🤱 👼 🎅 🤶 🦸 🦹 🧙 🧚 🧛 🧜 🧝 🧞 🧟 💆 💇 🚶 🧍 🧎 🏃 💃 🕺 🕴️ 👯 🧖 🧗 🤺 🏇 ⛷️ 🏂 🏌️ 🏄 🚣 🏊 ⛹️ 🏋️ 🚴 🚵 🤸 🤼 🤽 🤾 🤹 🧘 🛀 🛌 👭 👫 👬 💏 💑 👪".split(),
    "ANIMALS": "🐶 🐱 🐭 🐹 🐰 🦊 🐻 🐼 🐻‍❄️ 🐨 🐯 🦁 🐮 🐷 🐽 🐸 🐵 🙈 🙉 🙊 🐒 🐔 🐧 🐦 🐤 🐣 🐥 🦆 🦅 🦉 🦇 🐺 🐗 🐴 🦄 🐝 🪲 🐛 🦋 🐌 🐞 🐜 🪰 🪱 🦟 🦗 🕷️ 🦂 🐢 🐍 🦎 🐙 🦑 🦐 🦞 🦀 🐡 🐠 🐟 🐬 🐳 🐋 🦈 🐊 🐅 🐆 🦓 🦍 🦧 🐘 🦛 🦏 🐪 🐫 🦒 🦘 🦬 🐃 🐂 🐄 🐎 🐖 🐏 🐑 🦙 🐐 🦌 🐕 🐩 🦮 🐕‍🦺 🐈 🐈‍⬛ 🪶 🐓 🦃 🦚 🦜 🦢 🦩 🕊️ 🐇 🦝 🦨 🦡 🦫 🦦 🦥 🐁 🐀 🐿️ 🦔 🌵 🎄 🌲 🌳 🌴 🪴 🌱 🌿 ☘️ 🍀 🎍 🎋 🍃 🍂 🍁 🍄 🪺 🪹 🐚 🪸 🌾 💐 🌷 🌹 🥀 🌺 🌸 🌼 🌻 🌞 🌝 🌚 🌕 🌙 ⭐ 🌟 ✨ ⚡ ☄️ 💥 🔥 🌪️ 🌈 ☀️ 🌤️ ⛅ 🌧️ ⛈️ ❄️ ☃️".split(),
    "FOOD": "🍏 🍎 🍐 🍊 🍋 🍌 🍉 🍇 🍓 🫐 🍈 🍒 🍑 🥭 🍍 🥥 🥝 🍅 🍆 🥑 🥦 🥬 🥒 🌶️ 🫑 🌽 🥕 🫒 🧄 🧅 🥔 🍠 🫘 🥐 🥯 🍞 🥖 🥨 🧀 🥚 🍳 🧈 🥞 🧇 🥓 🥩 🍗 🍖 🌭 🍔 🍟 🍕 🫓 🥪 🥙 🧆 🌮 🌯 🫔 🥗 🥘 🫕 🥫 🍝 🍜 🍲 🍛 🍣 🍱 🥟 🦪 🍤 🍙 🍚 🍘 🍥 🥠 🥮 🍢 🍡 🍧 🍨 🍦 🥧 🧁 🍰 🎂 🍮 🍭 🍬 🍫 🍿 🍩 🍪 🌰 🥜 🍯 🥛 🍼 ☕ 🫖 🍵 🧃 🥤 🧋 🍶 🍺 🍻 🥂 🍷 🥃 🍸 🍹 🧉 🍾 🧊 🥄 🍴 🍽️ 🥣 🥡 🥢 🧂".split(),
    "ACTIVITY": "⚽ 🏀 🏈 ⚾ 🥎 🎾 🏐 🏉 🥏 🎱 🪀 🏓 🏸 🏒 🏑 🥍 🏏 🪃 🥅 ⛳ 🪁 🏹 🎣 🤿 🥊 🥋 🎽 🛹 🛼 🛷 ⛸️ 🥌 🎿 ⛷️ 🏂 🪂 🏋️ 🤼 🤸 ⛹️ 🤺 🤾 🏌️ 🏇 🧘 🏄 🏊 🤽 🚣 🧗 🚴 🚵 🏆 🥇 🥈 🥉 🏅 🎖️ 🏵️ 🎗️ 🎫 🎟️ 🎪 🤹 🎭 🩰 🎨 🎬 🎤 🎧 🎼 🎹 🥁 🪘 🎷 🎺 🪗 🎸 🪕 🎻 🎲 ♟️ 🎯 🎳 🎮 🎰 🧩".split(),
    "TRAVEL": "🚗 🚕 🚙 🚌 🚎 🏎️ 🚓 🚑 🚒 🚐 🛻 🚚 🚛 🚜 🏍️ 🛵 🚲 🛴 🚨 🚔 🚍 🚘 🚖 🚡 🚠 🚟 🚃 🚋 🚞 🚝 🚄 🚅 🚈 🚂 🚆 🚇 🚊 🚉 ✈️ 🛫 🛬 🛩️ 💺 🛰️ 🚀 🛸 🚁 🛶 ⛵ 🚤 🛥️ 🛳️ ⛴️ 🚢 ⚓ 🛟 ⛽ 🚧 🚦 🚥 🗺️ 🗿 🗽 🗼 🏰 🏯 🏟️ 🎡 🎢 🎠 ⛲ ⛱️ 🏖️ 🏝️ 🏜️ 🌋 ⛰️ 🏔️ 🗻 🏕️ ⛺ 🛖 🏠 🏡 🏢 🏥 🏦 🏨 🏪 🏫 🏬 🏭 🏛️ ⛪ 🕌 🛕 🕍 ⛩️ 🕋 🌁 🌃 🏙️ 🌄 🌅 🌆 🌇 🌉 ♨️ 🎑 🏞️".split(),
    "OBJECTS": "⌚ 📱 📲 💻 ⌨️ 🖥️ 🖨️ 🖱️ 🖲️ 🕹️ 🗜️ 💽 💾 💿 📀 📼 📷 📸 📹 🎥 📽️ 🎞️ 📞 ☎️ 📟 📠 📺 📻 🎙️ 🎚️ 🎛️ 🧭 ⏱️ ⏲️ ⏰ 🕰️ ⌛ ⏳ 📡 🔋 🪫 🔌 💡 🔦 🕯️ 🧯 🛢️ 💸 💵 💴 💶 💷 🪙 💰 💳 💎 ⚖️ 🪜 🧰 🪛 🔧 🔨 ⚒️ 🛠️ ⛏️ 🪚 🔩 ⚙️ 🪤 🧱 ⛓️ 🧲 🔫 💣 🧨 🪓 🔪 🗡️ ⚔️ 🛡️ 🚬 ⚰️ 🪦 ⚱️ 🏺 🔮 📿 🧿 🪬 💈 ⚗️ 🔭 🔬 🕳️ 🩹 🩺 💊 💉 🩸 🧬 🦠 🧫 🧪 🌡️ 🧹 🪠 🧺 🧻 🚽 🚿 🛁 🧼 🪥 🪒 🧽 🪣 🧴 🔑 🗝️ 🚪 🪑 🛋️ 🛏️ 🪞 🪟 🧸 🖼️ 🛍️ 🛒 🎁 🎈 🎏 🎀 🪄 🪅 🎊 🎉 🪩 🧧 ✉️ 📩 📨 📧 💌 📥 📤 📦 🏷️ 📪 📫 📬 📭 📮 📯 📜 📃 📄 📑 🧾 📊 📈 📉 🗒️ 🗓️ 📆 📅 🗑️ 📇 🗃️ 🗳️ 🗄️ 📋 📁 📂 🗂️ 🗞️ 📰 📓 📔 📒 📕 📗 📘 📙 📚 📖 🔖 🧷 🔗 📎 🖇️ 📐 📏 🧮 📌 📍 ✂️ 🖊️ 🖋️ ✒️ 🖌️ 🖍️ ✏️ 🔍 🔎 🔏 🔐 🔒 🔓".split(),
    "SYMBOLS": "❤️ 🩷 🧡 💛 💚 💙 🩵 💜 🤎 🖤 🩶 🤍 💔 ❣️ 💕 💞 💓 💗 💖 💘 💝 💟 ☮️ ✝️ ☪️ 🕉️ ☸️ ✡️ 🔯 🕎 ☯️ ☦️ 🛐 ⛎ ♈ ♉ ♊ ♋ ♌ ♍ ♎ ♏ ♐ ♑ ♒ ♓ 🆔 ⚛️ ☢️ ☣️ 📴 📳 🈶 🈚 🈸 🈺 🈷️ ✴️ 🆚 💮 🉐 ㊙️ ㊗️ 🈴 🈵 🈹 🈲 🅰️ 🅱️ 🆎 🆑 🅾️ 🆘 ❌ ⭕ 🛑 ⛔ 📛 🚫 💯 💢 ♨️ 🚷 🚯 🚳 🚱 🔞 📵 🚭 ❗ ❕ ❓ ❔ ‼️ ⁉️ 🔅 🔆 〽️ ⚠️ 🚸 🔱 ⚜️ 🔰 ♻️ ✅ 🈯 💹 ❇️ ✳️ ❎ 🌐 💠 Ⓜ️ 🌀 💤 🏧 🚾 ♿ 🅿️ 🛗 🈳 🈂️ 🛂 🛃 🛄 🛅 🚹 🚺 🚼 🚻 🚮 🎦 📶 🈁 🔣 ℹ️ 🔤 🔡 🔠 🆖 🆗 🆙 🆒 🆕 🆓 0️⃣ 1️⃣ 2️⃣ 3️⃣ 4️⃣ 5️⃣ 6️⃣ 7️⃣ 8️⃣ 9️⃣ 🔟 🔢 #️⃣ *️⃣ ⏏️ ▶️ ⏸️ ⏯️ ⏹️ ⏺️ ⏭️ ⏮️ ⏩ ⏪ 🔀 🔁 🔂 ◀️ 🔼 🔽 ⬆️ ⬇️ ⬅️ ➡️ ↗️ ↘️ ↙️ ↖️ ↕️ ↔️ 🔄 ↪️ ↩️ 🔃 ⤴️ ⤵️ #️⃣ ™️ ©️ ®️ 〰️ ➰ ➿ ✔️ ☑️ 🔘 🔴 🟠 🟡 🟢 🔵 🟣 🟤 ⚫ ⚪ 🟥 🟧 🟨 🟩 🟦 🟪 🟫 ⬛ ⬜ ◼️ ◻️ ◾ ◽ ▪️ ▫️ 🔶 🔷 🔸 🔹 🔺 🔻 💬 👁️‍🗨️ 🗨️ 🗯️ 💭".split(),
    "FLAGS": "🏁 🚩 🎌 🏴 🏳️ 🏳️‍🌈 🏳️‍⚧️ 🇬🇧 🇺🇸 🇮🇪 🇫🇷 🇩🇪 🇪🇸 🇮🇹 🇵🇹 🇳🇱 🇧🇪 🇨🇭 🇦🇹 🇩🇰 🇸🇪 🇳🇴 🇫🇮 🇮🇸 🇵🇱 🇨🇿 🇬🇷 🇹🇷 🇺🇦 🇷🇴 🇭🇺 🇭🇷 🇷🇸 🇦🇱 🇧🇬 🇨🇾 🇲🇹 🇦🇺 🇳🇿 🇨🇦 🇲🇽 🇧🇷 🇦🇷 🇨🇱 🇨🇴 🇯🇵 🇰🇷 🇨🇳 🇮🇳 🇵🇰 🇧🇩 🇹🇭 🇻🇳 🇸🇬 🇲🇾 🇮🇩 🇵🇭 🇿🇦 🇪🇬 🇳🇬 🇰🇪 🇲🇦 🇸🇦 🇦🇪 🇮🇱".split(),
}

TONE_MODIFIERS = {
    "DEFAULT": "",
    "LIGHT": "🏻",
    "MEDIUM-LIGHT": "🏼",
    "MEDIUM": "🏽",
    "MEDIUM-DARK": "🏾",
    "DARK": "🏿",
}

TONE_CAPABLE = set(
    "👋 🤚 🖐️ ✋ 🖖 🫱 🫲 🫳 🫴 👌 🤌 🤏 ✌️ 🤞 🫰 🤟 🤘 🤙 👈 👉 👆 🖕 👇 ☝️ 👍 👎 ✊ 👊 🤛 🤜 👏 🙌 🫶 👐 🤲 🙏 ✍️ 💅 🤳 💪 🦵 🦶 👂 👃 👶 🧒 👦 👧 🧑 👱 👨 👩 🧓 👴 👵 🙍 🙎 🙅 🙆 💁 🙋 🧏 🙇 🤦 🤷 👮 🕵️ 💂 🥷 👷 🫅 🤴 👸 👳 👲 🧕 🤵 👰 🤰 🤱 👼 🎅 🤶 💆 💇 🚶 🧍 🧎 🏃 💃 🕺 🛀".split()
)

ALIASES = {
    "lol": {"😂", "🤣", "😆"},
    "laugh": {"😂", "🤣", "😆", "😹"},
    "love": {"❤️", "🩷", "😍", "🥰", "😘", "💕", "💖"},
    "heart": {"❤️", "🩷", "🧡", "💛", "💚", "💙", "💜", "🖤", "🤍", "💔"},
    "fire": {"🔥"},
    "football": {"⚽", "🏈"},
    "soccer": {"⚽"},
    "party": {"🥳", "🎉", "🎊"},
    "money": {"💰", "💸", "💵", "🤑"},
    "thumb": {"👍", "👎"},
    "win": {"🏆", "🥇", "🎉"},
    "cry": {"😭", "😢"},
    "angry": {"😠", "😡", "🤬"},
    "shock": {"😱", "🤯", "😲"},
}


def _load_recents() -> list[str]:
    try:
        data = json.loads(RECENTS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return [value for value in data if isinstance(value, str) and value][:MAX_RECENTS]


def _save_recents(values: Iterable[str]) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    RECENTS_PATH.write_text(
        json.dumps(list(values)[:MAX_RECENTS], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def remember_emoji(emoji: str) -> None:
    values = [value for value in _load_recents() if value != emoji]
    values.insert(0, emoji)
    try:
        _save_recents(values)
    except OSError:
        pass


def emoji_search_text(emoji: str) -> str:
    names: list[str] = []
    for char in emoji:
        if char in {"\ufe0f", "\u200d"} or char in TONE_MODIFIERS.values():
            continue
        name = unicodedata.name(char, "")
        if name:
            names.append(name.lower())
    aliases = [key for key, values in ALIASES.items() if emoji in values]
    return " ".join(names + aliases)


def apply_skin_tone(emoji: str, tone: str) -> str:
    modifier = TONE_MODIFIERS.get(tone, "")
    if not modifier:
        return emoji
    if emoji in TONE_CAPABLE:
        if emoji.endswith("\ufe0f"):
            return emoji[:-1] + modifier
        return emoji + modifier
    return emoji


def filter_emojis(category: str, query: str = "", tone: str = "DEFAULT") -> list[str]:
    category = category.upper()
    source = _load_recents() if category == "RECENT" else EMOJI_CATALOG.get(category, [])
    query = query.strip().lower()
    if query:
        source = [
            emoji
            for emoji in source
            if query in emoji_search_text(emoji)
            or any(query in alias and emoji in values for alias, values in ALIASES.items())
        ]
    return [apply_skin_tone(emoji, tone) for emoji in source]


def insert_emoji(target: tk.Misc, emoji: str) -> None:
    if isinstance(target, tk.Text):
        try:
            if target.tag_ranges(tk.SEL):
                target.delete(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            pass
        target.insert(tk.INSERT, emoji)
        target.see(tk.INSERT)
    elif isinstance(target, tk.Entry):
        try:
            target.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        target.insert(target.index(tk.INSERT), emoji)
    else:
        raise TypeError("Pulse emoji picker target must be a Tk Text or Entry widget.")
    target.focus_set()


def open_emoji_picker(
    target: tk.Misc,
    *,
    on_insert: Callable[[], None] | None = None,
    accent: str = ACCENT,
) -> tk.Toplevel:
    parent = target.winfo_toplevel()
    existing = getattr(parent, "_pulse_emoji_picker", None)
    if existing is not None:
        try:
            if existing.winfo_exists():
                existing.lift()
                existing.focus_force()
                return existing
        except tk.TclError:
            pass

    window = tk.Toplevel(parent)
    parent._pulse_emoji_picker = window
    window.title("Pulse Social — Emoji")
    window.geometry("590x490")
    window.minsize(520, 430)
    window.configure(bg=BG)
    window.transient(parent)

    category_var = tk.StringVar(value="RECENT" if _load_recents() else "SMILEYS")
    search_var = tk.StringVar()
    tone_var = tk.StringVar(value="DEFAULT")

    header = tk.Frame(window, bg=BG)
    header.pack(fill="x", padx=18, pady=(16, 8))
    tk.Label(header, text="PULSE", fg=TEXT, bg=BG, font=("Segoe UI", 18, "bold")).pack(side="left")
    tk.Label(header, text=" // EMOJI", fg=accent, bg=BG, font=("Segoe UI", 18, "bold")).pack(side="left")
    tk.Label(
        header,
        text="LOCAL",
        fg=CYAN,
        bg=BG,
        font=("Consolas", 8, "bold"),
    ).pack(side="right", pady=7)

    search = tk.Entry(
        window,
        textvariable=search_var,
        bg=PANEL_2,
        fg=TEXT,
        insertbackground=TEXT,
        relief="flat",
        font=("Segoe UI", 10),
    )
    search.pack(fill="x", padx=18, pady=(0, 8), ipady=8)

    category_bar = tk.Frame(window, bg=BG)
    category_bar.pack(fill="x", padx=18, pady=(0, 8))
    category_buttons: dict[str, tk.Button] = {}

    tone_bar = tk.Frame(window, bg=BG)
    tone_bar.pack(fill="x", padx=18, pady=(0, 8))
    tk.Label(tone_bar, text="SKIN TONE", fg=MUTED, bg=BG, font=("Consolas", 8, "bold")).pack(side="left")
    tone_labels = [
        ("DEFAULT", "●"),
        ("LIGHT", "●"),
        ("MEDIUM-LIGHT", "●"),
        ("MEDIUM", "●"),
        ("MEDIUM-DARK", "●"),
        ("DARK", "●"),
    ]
    tone_buttons: dict[str, tk.Button] = {}

    style = ttk.Style(window)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(
        "PulseEmoji.Vertical.TScrollbar",
        troughcolor=BG,
        background=PANEL_2,
        bordercolor=BG,
        lightcolor=PANEL_2,
        darkcolor=PANEL_2,
        arrowcolor=MUTED,
        relief="flat",
        width=11,
    )
    style.map(
        "PulseEmoji.Vertical.TScrollbar",
        background=[("active", accent)],
        arrowcolor=[("active", TEXT)],
    )

    body_glow = tk.Frame(window, bg=GLOW_SOFT, padx=1, pady=1)
    body_glow.pack(fill="both", expand=True, padx=18, pady=(0, 16))
    body = tk.Frame(body_glow, bg=PANEL, highlightthickness=1, highlightbackground=CYAN_SOFT)
    body.pack(fill="both", expand=True)
    canvas = tk.Canvas(body, bg=PANEL, highlightthickness=0, bd=0)
    scroll = ttk.Scrollbar(
        body,
        orient="vertical",
        command=canvas.yview,
        style="PulseEmoji.Vertical.TScrollbar",
    )
    grid = tk.Frame(canvas, bg=PANEL)
    canvas_window = canvas.create_window((0, 0), window=grid, anchor="nw")
    canvas.configure(yscrollcommand=scroll.set)
    canvas.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    emoji_images: dict[tuple[str, int], object | None] = {}
    category_image_refs: dict[str, object] = {}
    sprite_manifest = _load_sprite_manifest()
    sprite_image = None
    sprite_state = "idle"
    sprite_error = None
    sprite_path = _resource_path(SPRITE_RELATIVE_PATH)
    image_sources: dict[tuple[str, int], str] = {}
    reported_error = False

    def report_sprite_error(error):
        nonlocal sprite_error, reported_error
        sprite_error = str(error)
        if not reported_error:
            logging.getLogger(__name__).error("Emoji sprite artwork unavailable: %s", error)
            reported_error = True

    # Read-only diagnostics for the actual picker, including the visible buttons.
    window._emoji_diagnostics = lambda: {
        "sprite_state": sprite_state,
        "sprite_error": str(sprite_error) if sprite_error else None,
        "category": category_var.get(),
        "sources": [getattr(btn, "_emoji_source", None) for btn in grid.winfo_children()],
    }

    def poll_sprite_loader():
        if sprite_state == "loading":
            try:
                if window.winfo_exists():
                    window.after(50, poll_sprite_loader)
            except tk.TclError:
                pass
            return
        if sprite_state == "failed":
            report_sprite_error(sprite_error)
        if sprite_state == "ready":
            try:
                if window.winfo_exists():
                    render()
            except tk.TclError:
                pass

    def start_sprite_loader():
        nonlocal sprite_state
        if sprite_state != "idle":
            return
        error = None
        if Image is None or ImageTk is None:
            error = f"Pillow is required by {sys.executable}; install the project requirements and restart Social."
        elif not sprite_manifest:
            error = "The bundled emoji manifest is missing or invalid."
        elif not sprite_path.exists():
            error = f"The bundled emoji sprite is missing: {sprite_path}"
        if error:
            sprite_state = "failed"
            report_sprite_error(error)
            return

        sprite_state = "loading"

        def worker():
            nonlocal sprite_image, sprite_state, sprite_error
            try:
                with Image.open(sprite_path) as source:
                    loaded = source.convert("RGBA")
                    loaded.load()
                sprite_image = loaded
                sprite_state = "ready"
            except Exception as exc:
                sprite_error = exc
                sprite_state = "failed"

        threading.Thread(
            target=worker,
            name="PulseEmojiSpriteLoader",
            daemon=True,
        ).start()
        window.after(50, poll_sprite_loader)

    def colour_emoji_image(emoji: str, size: int):
        key = (emoji, size)
        if key in emoji_images:
            return emoji_images[key]

        bundled = asset_base64(emoji)
        if bundled:
            try:
                photo = tk.PhotoImage(master=window, data=bundled)
                divisor = 2 if size >= 24 else 3
                photo = photo.subsample(divisor, divisor)
                emoji_images[key] = photo
                image_sources[key] = "embedded"
                return photo
            except tk.TclError:
                pass

        coords = sprite_manifest.get(emoji)
        if coords is None:
            coords = sprite_manifest.get(emoji.replace("\ufe0f", ""))
        if sprite_image is not None and coords is not None and ImageTk is not None:
            try:
                source_x = coords[0] * SPRITE_CELL + 1
                source_y = coords[1] * SPRITE_CELL + 1
                if (source_x < 1 or source_y < 1
                        or source_x + SPRITE_SIZE > sprite_image.width
                        or source_y + SPRITE_SIZE > sprite_image.height):
                    raise ValueError("Emoji sprite coordinates are outside the bundled sheet.")
                tile = sprite_image.crop(
                    (
                        source_x,
                        source_y,
                        source_x + SPRITE_SIZE,
                        source_y + SPRITE_SIZE,
                    )
                )
                if size != SPRITE_SIZE:
                    resampling = getattr(Image, "Resampling", Image)
                    tile = tile.resize((size, size), resampling.LANCZOS)
                # Called only by Tk callbacks; the worker decodes Pillow data only.
                photo = ImageTk.PhotoImage(tile, master=window)
                emoji_images[key] = photo
                image_sources[key] = "sprite"
                return photo
            except Exception as exc:
                report_sprite_error(exc)

        # Never cache a font substitute for artwork that exists. Loading or
        # rendering failures must stay diagnosable and allow a later render.
        if coords is not None:
            return None

        if Image is None or ImageDraw is None or ImageFont is None or ImageTk is None:
            emoji_images[key] = None
            return None
        if not EMOJI_FONT_PATH.exists():
            emoji_images[key] = None
            return None

        try:
            canvas_size = max(40, size + 18)
            image = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            font = ImageFont.truetype(str(EMOJI_FONT_PATH), size=size)
            draw.text(
                (canvas_size // 2, canvas_size // 2),
                emoji,
                font=font,
                anchor="mm",
                embedded_color=True,
            )
            photo = ImageTk.PhotoImage(image, master=window)
        except Exception:
            photo = None

        emoji_images[key] = photo
        image_sources[key] = "font"
        return photo

    def render(*_):
        for child in grid.winfo_children():
            child.destroy()
        values = filter_emojis(category_var.get(), search_var.get(), tone_var.get())
        needs_sprite = any(
            asset_base64(emoji) is None
            and (
                emoji in sprite_manifest
                or emoji.replace("\ufe0f", "") in sprite_manifest
            )
            for emoji in values
        )
        if needs_sprite and sprite_state == "idle":
            start_sprite_loader()
        if not values:
            tk.Label(
                grid,
                text="No matching emoji",
                fg=MUTED,
                bg=PANEL,
                font=("Segoe UI", 10),
            ).grid(row=0, column=0, padx=16, pady=24, sticky="w")
        else:
            columns = 10
            for index, emoji in enumerate(values):
                tile_glow = accent if index % 2 == 0 else CYAN
                photo = colour_emoji_image(emoji, 28)
                has_sprite_asset = (
                    emoji in sprite_manifest
                    or emoji.replace("\ufe0f", "") in sprite_manifest
                )
                waiting_for_colour = (
                    photo is None
                    and has_sprite_asset
                )
                if photo is not None:
                    btn = tk.Button(
                        grid,
                        image=photo,
                        command=lambda value=emoji: choose(value),
                        bg=PANEL,
                        activebackground=PANEL_2,
                        relief="flat",
                        bd=0,
                        width=46,
                        height=44,
                        padx=0,
                        pady=0,
                        highlightthickness=1,
                        highlightbackground=PANEL,
                        highlightcolor=tile_glow,
                        cursor="hand2",
                    )
                elif waiting_for_colour:
                    btn = tk.Button(
                        grid,
                        text="·",
                        state="disabled",
                        disabledforeground=MUTED,
                        bg=PANEL,
                        relief="flat",
                        bd=0,
                        width=3,
                        height=1,
                        font=("Segoe UI", 18, "bold"),
                        highlightthickness=1,
                        highlightbackground=PANEL,
                    )
                else:
                    btn = tk.Button(
                        grid,
                        text=emoji,
                        command=lambda value=emoji: choose(value),
                        bg=PANEL,
                        fg=TEXT,
                        activebackground=PANEL_2,
                        activeforeground=TEXT,
                        relief="flat",
                        bd=0,
                        width=3,
                        height=1,
                        font=("Segoe UI Emoji", 18),
                        highlightthickness=1,
                        highlightbackground=PANEL,
                        highlightcolor=tile_glow,
                        cursor="hand2",
                    )

                btn._emoji = emoji
                btn._emoji_photo = photo
                btn._emoji_source = image_sources.get((emoji, 28), "pending" if has_sprite_asset else "font")
                btn.bind(
                    "<Enter>",
                    lambda _event, widget=btn, glow=tile_glow: widget.configure(
                        bg=PANEL_2,
                        highlightbackground=glow,
                    ),
                )
                btn.bind(
                    "<Leave>",
                    lambda _event, widget=btn: widget.configure(
                        bg=PANEL,
                        highlightbackground=PANEL,
                    ),
                )
                btn.grid(row=index // columns, column=index % columns, padx=2, pady=2, sticky="nsew")
        for column in range(10):
            grid.grid_columnconfigure(column, weight=1)
        grid.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.yview_moveto(0)
        for name, btn in category_buttons.items():
            active = name == category_var.get()
            btn.configure(bg=accent if active else PANEL_2, fg=TEXT)
        for name, btn in tone_buttons.items():
            active = name == tone_var.get()
            btn.configure(bg=accent if active else PANEL_2)

    def choose(emoji: str):
        insert_emoji(target, emoji)
        remember_emoji(emoji)
        if on_insert:
            on_insert()
        if category_var.get() == "RECENT":
            render()

    def set_category(name: str):
        category_var.set(name)
        render()

    def set_tone(name: str):
        tone_var.set(name)
        render()

    # Start the full-colour sheet immediately in the background so non-smiley
    # categories are ready before the user opens them. The Tk UI never decodes
    # the large PNG itself.
    start_sprite_loader()

    for name, glyph in CATEGORY_LABELS.items():
        photo = colour_emoji_image(glyph, 18) if name != "RECENT" else None
        if photo is not None:
            category_image_refs[name] = photo
            btn = tk.Button(
                category_bar,
                image=photo,
                command=lambda value=name: set_category(value),
                bg=PANEL_2,
                activebackground=accent,
                relief="flat",
                bd=0,
                width=38,
                height=32,
                padx=0,
                pady=0,
                cursor="hand2",
            )
        else:
            btn = tk.Button(
                category_bar,
                text=glyph,
                command=lambda value=name: set_category(value),
                bg=PANEL_2,
                fg=TEXT,
                activebackground=accent,
                activeforeground=TEXT,
                relief="flat",
                bd=0,
                padx=7,
                pady=5,
                font=("Segoe UI Emoji", 11),
                cursor="hand2",
            )
        btn.pack(side="left", padx=(0, 4))
        category_buttons[name] = btn
        btn._emoji_category = name

    for name, glyph in tone_labels:
        btn = tk.Button(
            tone_bar,
            text=glyph,
            command=lambda value=name: set_tone(value),
            bg=PANEL_2,
            fg=TONE_SWATCHES[name],
            activebackground=accent,
            activeforeground=TONE_SWATCHES[name],
            relief="flat",
            bd=0,
            padx=7,
            pady=3,
            font=("Segoe UI", 12, "bold"),
            cursor="hand2",
        )
        btn.pack(side="left", padx=(5, 0))
        tone_buttons[name] = btn
        btn._emoji_tone = name

    def resize_grid(event):
        canvas.itemconfigure(canvas_window, width=event.width)

    def wheel(event):
        canvas.yview_scroll(-1 * int(event.delta / 120), "units")

    def close():
        try:
            if getattr(parent, "_pulse_emoji_picker", None) is window:
                parent._pulse_emoji_picker = None
        except tk.TclError:
            pass
        window.destroy()

    canvas.bind("<Configure>", resize_grid)
    window.bind("<MouseWheel>", wheel)
    search_var.trace_add("write", render)
    window.bind("<Escape>", lambda _event: close())
    window.protocol("WM_DELETE_WINDOW", close)
    render()
    search.focus_set()
    return window
