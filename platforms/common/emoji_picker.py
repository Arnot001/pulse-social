from __future__ import annotations

import json
import os
import tkinter as tk
import unicodedata
from pathlib import Path
from typing import Callable, Iterable

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

# Curated Unicode only. No external artwork, web service, or runtime dependency.
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
            return emoji[:-1] + modifier + "\ufe0f"
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
        ("LIGHT", "🏻"),
        ("MEDIUM-LIGHT", "🏼"),
        ("MEDIUM", "🏽"),
        ("MEDIUM-DARK", "🏾"),
        ("DARK", "🏿"),
    ]
    tone_buttons: dict[str, tk.Button] = {}

    body = tk.Frame(window, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
    body.pack(fill="both", expand=True, padx=18, pady=(0, 16))
    canvas = tk.Canvas(body, bg=PANEL, highlightthickness=0, bd=0)
    scroll = tk.Scrollbar(body, orient="vertical", command=canvas.yview)
    grid = tk.Frame(canvas, bg=PANEL)
    canvas_window = canvas.create_window((0, 0), window=grid, anchor="nw")
    canvas.configure(yscrollcommand=scroll.set)
    canvas.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    empty = tk.Label(
        grid,
        text="No matching emoji",
        fg=MUTED,
        bg=PANEL,
        font=("Segoe UI", 10),
    )

    def render(*_):
        for child in grid.winfo_children():
            child.destroy()
        values = filter_emojis(category_var.get(), search_var.get(), tone_var.get())
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
                    cursor="hand2",
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

    for name, glyph in CATEGORY_LABELS.items():
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

    for name, glyph in tone_labels:
        btn = tk.Button(
            tone_bar,
            text=glyph,
            command=lambda value=name: set_tone(value),
            bg=PANEL_2,
            fg=TEXT,
            activebackground=accent,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            padx=7,
            pady=3,
            font=("Segoe UI Emoji", 10),
            cursor="hand2",
        )
        btn.pack(side="left", padx=(5, 0))
        tone_buttons[name] = btn

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
    canvas.bind_all("<MouseWheel>", wheel)
    search_var.trace_add("write", render)
    window.bind("<Escape>", lambda _event: close())
    window.protocol("WM_DELETE_WINDOW", close)
    render()
    search.focus_set()
    return window
