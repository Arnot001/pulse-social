from __future__ import annotations

import subprocess
import sys
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import messagebox

from platforms.browser_control import running_browser_names
from platforms.common.onboarding import open_get_started
from platforms.pdh_bridge import bridge_status, ensure_bridge_server

BG = "#070910"
SURFACE = "#0a0f18"
PANEL = "#101827"
PANEL_2 = "#151f30"
BORDER = "#26354b"
TEXT = "#f8f9fc"
MUTED = "#93a0b4"
SUBTLE = "#65748a"
ACCENT = "#ff0a8a"
ACCENT_2 = "#ff48ad"
GLOW = "#ff1493"
GLOW_SOFT = "#42152f"
CYAN = "#27def5"
CYAN_SOFT = "#102d37"
SUCCESS = "#31d27c"
DANGER = "#9c213b"
ROOT = Path(__file__).resolve().parent
children: list[subprocess.Popen] = []
status_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pdh-status")
status_future = None
status_after_id = None


def launch(script: str) -> None:
    proc = subprocess.Popen([sys.executable, str(ROOT / script)], cwd=str(ROOT))
    children.append(proc)


def open_tiktok_cleanup() -> None:
    try:
        from platforms.tiktok.cleanup_ui import open_cleanup_window

        window = open_cleanup_window(root)
        window.lift()
        try:
            window.focus_force()
        except tk.TclError:
            pass
    except Exception as exc:
        messagebox.showerror(
            "TikTok Cleanup",
            "TikTok Cleanup could not open.\n\n" + str(exc),
            parent=root,
        )


def close_all() -> None:
    if status_after_id is not None:
        root.after_cancel(status_after_id)
    status_executor.shutdown(wait=False, cancel_futures=True)
    for proc in children:
        if proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
    root.destroy()


def button(parent, text, command, accent=False, danger=False):
    if accent:
        bg, active, border = ACCENT, ACCENT_2, ACCENT_2
    elif danger:
        bg, active, border = "#641629", "#85203a", "#85203a"
    else:
        bg, active, border = PANEL_2, "#1c2a3f", BORDER

    btn = tk.Button(
        parent,
        text=text,
        command=command,
        bg=bg,
        fg=TEXT,
        activebackground=active,
        activeforeground=TEXT,
        relief="flat",
        bd=0,
        padx=18,
        pady=10,
        font=("Segoe UI", 9, "bold"),
        cursor="hand2",
        highlightthickness=1,
        highlightbackground=border,
        highlightcolor=border,
    )

    def enter(_event):
        btn.configure(bg=active, highlightbackground=ACCENT_2 if accent else active)

    def leave(_event):
        btn.configure(bg=bg, highlightbackground=border)

    btn.bind("<Enter>", enter)
    btn.bind("<Leave>", leave)
    return btn


root = tk.Tk()
root.title("Pulse Social")
root.geometry("1180x720")
root.minsize(1040, 650)
root.maxsize(1280, 780)
root.configure(bg=BG)

# HEADER
header = tk.Frame(root, bg=BG)
header.pack(fill="x", padx=34, pady=(24, 10))

brand = tk.Frame(header, bg=BG)
brand.pack(side="left")

title_row = tk.Frame(brand, bg=BG)
title_row.pack(anchor="w")
tk.Label(
    title_row,
    text="PULSE",
    fg=TEXT,
    bg=BG,
    font=("Segoe UI Variable Display", 34, "bold"),
).pack(side="left")
tk.Label(
    title_row,
    text=" SOCIAL",
    fg=ACCENT_2,
    bg=BG,
    font=("Segoe UI Variable Display", 34, "bold"),
).pack(side="left")
tk.Label(
    title_row,
    text="/",
    fg=CYAN,
    bg=BG,
    font=("Segoe UI", 22),
).pack(side="left", padx=(18, 12), pady=(5, 0))
tk.Label(
    title_row,
    text="CONTROL DECK",
    fg=CYAN,
    bg=BG,
    font=("Segoe UI", 9, "bold"),
).pack(side="left", pady=(10, 0))

button(header, "✕  CLOSE ALL", close_all, danger=True).pack(side="right", pady=5)
button(header, "GET STARTED", lambda: open_get_started(root)).pack(
    side="right",
    padx=(0, 8),
    pady=5,
)

subtitle = tk.Frame(root, bg=BG)
subtitle.pack(fill="x", padx=36)
for index, label in enumerate(("SOCIAL AUTOMATION", "COMMERCE INTELLIGENCE", "LIVE BROWSER CONTROL")):
    if index:
        tk.Label(subtitle, text="•", fg=ACCENT, bg=BG, font=("Segoe UI", 9, "bold")).pack(side="left", padx=14)
    tk.Label(
        subtitle,
        text=label,
        fg=MUTED,
        bg=BG,
        font=("Segoe UI", 8),
    ).pack(side="left")

glow_line = tk.Frame(root, bg=ACCENT, height=2)
glow_line.pack(fill="x", padx=34, pady=(10, 0))

ensure_bridge_server()


def pdh_browser_status() -> str:
    running = running_browser_names()
    pdh_ready = bool(bridge_status().get("pdhConnected"))

    if pdh_ready:
        if len(running) == 1:
            return f"{running[0].upper()} OPEN  //  PDH CONNECTED"
        if len(running) > 1:
            return "PDH CONNECTED  //  " + " / ".join(name.upper() for name in running)
        return "PDH CONNECTED  //  BROWSER ACTIVE"

    if len(running) == 1:
        return f"{running[0].upper()} OPEN  //  WAITING FOR PDH"
    if len(running) > 1:
        return "WAITING FOR PDH  //  " + " / ".join(name.upper() for name in running)
    return "NO BROWSER OPEN  //  PDH WAITING"


browser_status_var = tk.StringVar(value=pdh_browser_status())

browser_outer = tk.Frame(
    root,
    bg=PANEL,
    highlightthickness=1,
    highlightbackground=CYAN,
)
browser_outer.pack(fill="x", padx=34, pady=(16, 14))

tk.Frame(browser_outer, bg=ACCENT, width=3).pack(side="left", fill="y")

browser_icon = tk.Frame(
    browser_outer,
    bg=SURFACE,
    width=38,
    height=38,
    highlightthickness=1,
    highlightbackground=BORDER,
)
browser_icon.pack(side="left", padx=(15, 12), pady=9)
browser_icon.pack_propagate(False)
tk.Label(
    browser_icon,
    text="▣",
    fg=CYAN,
    bg=SURFACE,
    font=("Segoe UI Symbol", 14, "bold"),
).pack(expand=True)

tk.Label(
    browser_outer,
    text="Pulse Browser / PDH",
    fg=TEXT,
    bg=PANEL,
    font=("Segoe UI Variable Text", 10, "bold"),
).pack(side="left")

tk.Label(
    browser_outer,
    text="●",
    fg=SUCCESS,
    bg=PANEL,
    font=("Segoe UI", 10, "bold"),
).pack(side="left", padx=(18, 8))

tk.Label(
    browser_outer,
    textvariable=browser_status_var,
    fg=MUTED,
    bg=PANEL,
    font=("Segoe UI Variable Text", 9),
).pack(side="left")


def refresh_pdh_browser() -> None:
    global status_future
    if status_future is None:
        status_future = status_executor.submit(pdh_browser_status)


def poll_pdh_browser_status() -> None:
    global status_future, status_after_id
    if status_future is not None and status_future.done():
        try:
            browser_status_var.set(status_future.result())
        except Exception:
            browser_status_var.set("PDH STATUS UNAVAILABLE")
        status_future = None
    refresh_pdh_browser()
    status_after_id = root.after(2000, poll_pdh_browser_status)


button(
    browser_outer,
    "↻  PDH / REFRESH",
    refresh_pdh_browser,
    accent=True,
).pack(side="right", padx=12, pady=8)

# PLATFORM CARDS
nav = tk.Frame(root, bg=BG)
nav.pack(fill="x", expand=False, padx=34, pady=(0, 16))
nav.grid_columnconfigure(0, weight=1, uniform="platform")
nav.grid_columnconfigure(1, weight=1, uniform="platform")
nav.grid_rowconfigure(0, weight=0)


def platform_card(
    parent,
    column,
    eyebrow,
    title,
    mark,
    subtitle,
    features,
    primary_text,
    primary_command,
    secondary=None,
    tertiary=None,
):
    glow_colour = ACCENT if column == 0 else CYAN
    card_bg = "#171323" if column == 0 else "#0d1b25"
    soft_colour = "#37152a" if column == 0 else "#10303a"

    outer = tk.Frame(
        parent,
        bg=soft_colour,
        padx=2,
        pady=2,
    )
    outer.grid(
        row=0,
        column=column,
        sticky="ew",
        padx=(0, 10) if column == 0 else (10, 0),
    )

    card = tk.Frame(
        outer,
        bg=card_bg,
        highlightthickness=1,
        highlightbackground=glow_colour,
    )
    card.pack(fill="x")

    tk.Frame(card, bg=glow_colour, height=2).pack(fill="x")

    top = tk.Frame(card, bg=card_bg)
    top.pack(fill="x", padx=22, pady=(20, 12))

    mark_box = tk.Frame(
        top,
        bg=SURFACE,
        width=72,
        height=72,
        highlightthickness=1,
        highlightbackground=glow_colour,
    )
    mark_box.pack(side="left", anchor="n")
    mark_box.pack_propagate(False)

    if title == "TikTok":
        tk.Label(mark_box, text="♪", fg=ACCENT_2, bg=SURFACE,
                 font=("Segoe UI Symbol", 31, "bold")).place(relx=.5, rely=.5, anchor="center", x=2, y=1)
        tk.Label(mark_box, text="♪", fg=CYAN, bg=SURFACE,
                 font=("Segoe UI Symbol", 31, "bold")).place(relx=.5, rely=.5, anchor="center", x=-2, y=-1)
        tk.Label(mark_box, text="♪", fg=TEXT, bg=SURFACE,
                 font=("Segoe UI Symbol", 29, "bold")).place(relx=.5, rely=.5, anchor="center")
    else:
        tk.Label(
            mark_box,
            text=mark,
            fg=TEXT,
            bg=SURFACE,
            font=("Segoe UI Variable Display", 28, "bold"),
        ).pack(expand=True)

    copy = tk.Frame(top, bg=card_bg)
    copy.pack(side="left", fill="x", expand=True, padx=(18, 0))
    tk.Label(
        copy,
        text=eyebrow,
        fg=glow_colour,
        bg=card_bg,
        font=("Segoe UI Variable Text", 8, "bold"),
    ).pack(anchor="w")
    tk.Label(
        copy,
        text=title,
        fg=TEXT,
        bg=card_bg,
        font=("Segoe UI Variable Display", 27, "bold"),
    ).pack(anchor="w", pady=(2, 4))
    tk.Label(
        copy,
        text=subtitle,
        fg=MUTED,
        bg=card_bg,
        font=("Segoe UI Variable Text", 10),
        justify="left",
        wraplength=340,
    ).pack(anchor="w")

    tk.Label(
        top,
        text=mark,
        fg=soft_colour,
        bg=card_bg,
        font=("Segoe UI Variable Display", 66, "bold"),
    ).pack(side="right", padx=(8, 2))

    feature_box = tk.Frame(
        card,
        bg=SURFACE,
        highlightthickness=1,
        highlightbackground=BORDER,
    )
    feature_box.pack(fill="x", padx=22, pady=(4, 14))

    glyphs = ("◌", "▣", "◉") if column == 0 else ("◇", "◉", "⚡")
    for index, feature in enumerate(features):
        row = tk.Frame(feature_box, bg=SURFACE)
        row.pack(fill="x", padx=13, pady=0)

        icon_box = tk.Frame(
            row,
            bg=card_bg,
            width=30,
            height=30,
            highlightthickness=1,
            highlightbackground=soft_colour,
        )
        icon_box.pack(side="left", pady=7)
        icon_box.pack_propagate(False)
        tk.Label(
            icon_box,
            text=glyphs[index],
            fg=glow_colour,
            bg=card_bg,
            font=("Segoe UI Symbol", 11, "bold"),
        ).pack(expand=True)

        tk.Label(
            row,
            text=feature,
            fg=TEXT,
            bg=SURFACE,
            font=("Segoe UI Variable Text", 9),
        ).pack(side="left", padx=(12, 0), pady=10)

        if index < len(features) - 1:
            tk.Frame(feature_box, bg=BORDER, height=1).pack(fill="x", padx=(55, 14))

    actions = tk.Frame(card, bg=card_bg)
    actions.pack(fill="x", padx=22, pady=(0, 20))

    primary = button(actions, primary_text, primary_command, accent=True)
    primary.configure(width=15)
    primary.pack(side="left")

    if secondary:
        text, command = secondary
        secondary_btn = button(actions, text, command)
        secondary_btn.configure(width=12)
        secondary_btn.pack(side="left", padx=(10, 0))

    if tertiary:
        text, command = tertiary
        tertiary_btn = button(actions, text, command)
        tertiary_btn.configure(width=10)
        tertiary_btn.pack(side="left", padx=(10, 0))


platform_card(
    nav,
    0,
    "PLATFORM 01",
    "X",
    "X",
    "Manage your own X account with cleanup tools and scheduled posting.",
    [
        "Cleanup posts, replies, reposts and likes",
        "Schedule queued posts",
        "Shared dedicated Pulse browser",
    ],
    "OPEN CLEANUP",
    lambda: launch("pulse_social_ui.py"),
    ("AUTO POST", lambda: launch("x_auto_post_ui.py")),
)

platform_card(
    nav,
    1,
    "PLATFORM 02",
    "TikTok",
    "T",
    "Commerce intelligence plus scheduled TikTok publishing.",
    [
        "Live category collection and deal intelligence",
        "Shared dedicated Pulse browser",
        "Auto post plus selective TikTok cleanup",
    ],
    "OPEN SHOP",
    lambda: launch("tiktok_shop_ui.py"),
    ("AUTO POST", lambda: launch("tiktok_auto_post_ui.py")),
    ("CLEANUP", open_tiktok_cleanup),
)

# FOOTER
spacer = tk.Frame(root, bg=BG)
spacer.pack(fill="both", expand=True)

footer_line = tk.Frame(root, bg=BORDER, height=1)
footer_line.pack(fill="x", padx=34, pady=(0, 10))

footer = tk.Frame(root, bg=BG)
footer.pack(fill="x", padx=36, pady=(0, 16))

tk.Label(
    footer,
    text="PULSE",
    fg=TEXT,
    bg=BG,
    font=("Segoe UI", 8, "bold"),
).pack(side="left")
tk.Label(
    footer,
    text=" SOCIAL",
    fg=ACCENT_2,
    bg=BG,
    font=("Segoe UI", 8, "bold"),
).pack(side="left")
tk.Label(
    footer,
    text="   |   Social automation workspace",
    fg=MUTED,
    bg=BG,
    font=("Segoe UI", 8),
).pack(side="left")

tk.Label(
    footer,
    text="●  Ready",
    fg=SUCCESS,
    bg=BG,
    font=("Segoe UI", 8, "bold"),
).pack(side="right")

root.protocol("WM_DELETE_WINDOW", close_all)
poll_pdh_browser_status()
root.mainloop()
