from __future__ import annotations

import subprocess
import sys
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import messagebox

from platforms.browser_control import running_browser_names
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
root.geometry("1060x680")
root.minsize(940, 610)
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
    font=("Segoe UI", 31, "bold"),
).pack(side="left")
tk.Label(
    title_row,
    text=" SOCIAL",
    fg=ACCENT_2,
    bg=BG,
    font=("Segoe UI", 31, "bold"),
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

browser_accent = tk.Frame(browser_outer, bg=ACCENT, width=3)
browser_accent.pack(side="left", fill="y")

browser_identity = tk.Frame(browser_outer, bg=PANEL)
browser_identity.pack(side="left", padx=(16, 18), pady=10)

tk.Label(
    browser_identity,
    text="▣",
    fg=CYAN,
    bg=PANEL,
    font=("Segoe UI Symbol", 13, "bold"),
).pack(side="left")

browser_copy = tk.Frame(browser_identity, bg=PANEL)
browser_copy.pack(side="left", padx=(10, 0))
tk.Label(
    browser_copy,
    text="Pulse Browser / PDH",
    fg=TEXT,
    bg=PANEL,
    font=("Segoe UI", 9, "bold"),
).pack(anchor="w")
tk.Label(
    browser_copy,
    textvariable=browser_status_var,
    fg=MUTED,
    bg=PANEL,
    font=("Segoe UI", 8),
).pack(anchor="w", pady=(1, 0))

tk.Label(
    browser_outer,
    text="●",
    fg=SUCCESS,
    bg=PANEL,
    font=("Segoe UI", 10, "bold"),
).pack(side="left", padx=(2, 8))


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
nav.pack(fill="both", expand=True, padx=34, pady=(0, 18))
nav.grid_columnconfigure(0, weight=1, uniform="platform")
nav.grid_columnconfigure(1, weight=1, uniform="platform")
nav.grid_rowconfigure(0, weight=1)


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
    soft_colour = GLOW_SOFT if column == 0 else CYAN_SOFT

    outer = tk.Frame(
        parent,
        bg=PANEL,
        highlightthickness=1,
        highlightbackground=glow_colour,
    )
    outer.grid(
        row=0,
        column=column,
        sticky="nsew",
        padx=(0, 9) if column == 0 else (9, 0),
    )

    top_line = tk.Frame(outer, bg=glow_colour, height=2)
    top_line.pack(fill="x")

    body = tk.Frame(outer, bg=PANEL)
    body.pack(fill="both", expand=True)

    top = tk.Frame(body, bg=PANEL)
    top.pack(fill="x", padx=20, pady=(20, 10))

    mark_box = tk.Frame(
        top,
        bg=SURFACE,
        highlightthickness=1,
        highlightbackground=glow_colour,
        width=60,
        height=60,
    )
    mark_box.pack(side="left", anchor="n")
    mark_box.pack_propagate(False)
    tk.Label(
        mark_box,
        text=mark,
        fg=TEXT,
        bg=SURFACE,
        font=("Segoe UI", 25, "bold"),
    ).pack(expand=True)

    copy = tk.Frame(top, bg=PANEL)
    copy.pack(side="left", fill="x", expand=True, padx=(16, 0))
    tk.Label(
        copy,
        text=eyebrow,
        fg=glow_colour,
        bg=PANEL,
        font=("Segoe UI", 8, "bold"),
    ).pack(anchor="w")
    tk.Label(
        copy,
        text=title,
        fg=TEXT,
        bg=PANEL,
        font=("Segoe UI", 24, "bold"),
    ).pack(anchor="w", pady=(2, 3))
    tk.Label(
        copy,
        text=subtitle,
        fg=MUTED,
        bg=PANEL,
        font=("Segoe UI", 9),
        justify="left",
        wraplength=330,
    ).pack(anchor="w")

    watermark = tk.Label(
        top,
        text=mark,
        fg=soft_colour,
        bg=PANEL,
        font=("Segoe UI", 58, "bold"),
    )
    watermark.pack(side="right", padx=(6, 0))

    feature_box = tk.Frame(
        body,
        bg=SURFACE,
        highlightthickness=1,
        highlightbackground=BORDER,
    )
    feature_box.pack(fill="x", padx=20, pady=(6, 14))

    for index, feature in enumerate(features):
        row = tk.Frame(feature_box, bg=SURFACE)
        row.pack(fill="x", padx=13, pady=0)

        icon = tk.Label(
            row,
            text="●",
            fg=glow_colour,
            bg=SURFACE,
            font=("Segoe UI", 8, "bold"),
            width=2,
        )
        icon.pack(side="left", pady=9)

        tk.Label(
            row,
            text=feature,
            fg=TEXT,
            bg=SURFACE,
            font=("Segoe UI", 9),
        ).pack(side="left", padx=(8, 0), pady=9)

        if index < len(features) - 1:
            tk.Frame(feature_box, bg=BORDER, height=1).pack(fill="x", padx=44)

    actions = tk.Frame(body, bg=PANEL)
    actions.pack(fill="x", padx=20, pady=(0, 20))

    primary = button(actions, primary_text, primary_command, accent=True)
    primary.pack(side="left")

    if secondary:
        text, command = secondary
        button(actions, text, command).pack(side="left", padx=(10, 0))

    if tertiary:
        text, command = tertiary
        button(actions, text, command).pack(side="left", padx=(10, 0))


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
    "♪",
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
