from __future__ import annotations

import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from platforms.x.browser_session import browser_status, open_x_browser

BG = "#06070b"
SURFACE = "#0b0f17"
PANEL = "#101622"
PANEL_2 = "#151d2c"
BORDER = "#242f43"
TEXT = "#f7f8fb"
MUTED = "#8e9aae"
ACCENT = "#ff0a8a"
ACCENT_2 = "#ff4bb0"
GLOW = "#ff1493"
GLOW_SOFT = "#5b123d"
CYAN = "#33e6ff"
CYAN_SOFT = "#123c46"
SUCCESS = "#35d07f"
DANGER = "#ff4d67"
ROOT = Path(__file__).resolve().parent
children: list[subprocess.Popen] = []


def launch(script: str) -> None:
    proc = subprocess.Popen([sys.executable, str(ROOT / script)], cwd=str(ROOT))
    children.append(proc)


def close_all() -> None:
    for proc in children:
        if proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
    root.destroy()


def button(parent, text, command, accent=False, danger=False):
    bg = ACCENT if accent else "#5b1623" if danger else PANEL_2
    active = ACCENT_2 if accent else "#7a1d2e" if danger else "#202b3d"
    normal = bg
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
        padx=16,
        pady=9,
        font=("Segoe UI", 9, "bold"),
        cursor="hand2",
        highlightthickness=1 if accent else 0,
        highlightbackground=GLOW if accent else bg,
        highlightcolor=GLOW if accent else bg,
    )
    def enter(_event):
        btn.configure(bg=active, highlightbackground=ACCENT_2 if accent else active)
    def leave(_event):
        btn.configure(bg=normal, highlightbackground=GLOW if accent else normal)
    btn.bind("<Enter>", enter)
    btn.bind("<Leave>", leave)
    return btn


root = tk.Tk()
root.title("Pulse Social")
root.geometry("980x610")
root.minsize(900, 560)
root.configure(bg=BG)

# HEADER
header = tk.Frame(root, bg=BG)
header.pack(fill="x", padx=34, pady=(28, 12))

brand = tk.Frame(header, bg=BG)
brand.pack(side="left")
tk.Label(brand, text="PULSE", fg=TEXT, bg=BG, font=("Segoe UI", 30, "bold")).pack(side="left")
tk.Label(brand, text=" SOCIAL", fg=ACCENT_2, bg=BG, font=("Segoe UI", 30, "bold")).pack(side="left")
tk.Label(brand, text="  //  CONTROL DECK", fg=CYAN, bg=BG, font=("Consolas", 10, "bold")).pack(side="left", padx=(8, 0), pady=(11, 0))

button(header, "CLOSE ALL", close_all, danger=True).pack(side="right", pady=4)

glow_line = tk.Frame(root, bg=GLOW, height=2)
glow_line.pack(fill="x", padx=34, pady=(0, 8))

subtitle = tk.Frame(root, bg=BG)
subtitle.pack(fill="x", padx=36)
tk.Label(
    subtitle,
    text="SOCIAL AUTOMATION  •  COMMERCE INTELLIGENCE  •  LIVE BROWSER CONTROL",
    fg=MUTED,
    bg=BG,
    font=("Consolas", 9),
).pack(side="left")

browser_status_var = tk.StringVar(value=browser_status())
browser_glow = tk.Frame(root, bg=CYAN_SOFT, padx=2, pady=2)
browser_glow.pack(fill="x", padx=32, pady=(18, 14))
browser_strip = tk.Frame(browser_glow, bg=PANEL, highlightthickness=1, highlightbackground=CYAN)
browser_strip.pack(fill="x")

tk.Label(browser_strip, text="X BROWSER", fg=MUTED, bg=PANEL, font=("Consolas", 8, "bold")).pack(side="left", padx=(16, 8), pady=12)
tk.Label(browser_strip, text="●", fg=CYAN, bg=PANEL, font=("Segoe UI", 10, "bold")).pack(side="left")
tk.Label(browser_strip, textvariable=browser_status_var, fg=TEXT, bg=PANEL, font=("Consolas", 9, "bold")).pack(side="left", padx=(6, 12))


def connect_x_browser() -> None:
    ok, msg = open_x_browser(restart_existing=False)
    if not ok and "already open without Pulse control" in msg:
        if not messagebox.askyesno(
            "Restart browser for Pulse?",
            msg + "\n\nPulse needs to restart it with browser control enabled. "
            "Open tabs should be restorable by the browser. Restart now?",
            parent=root,
        ):
            browser_status_var.set(browser_status())
            return
        ok, msg = open_x_browser(restart_existing=True)
    browser_status_var.set(browser_status() if ok else msg.upper())
    if not ok:
        messagebox.showerror("X Browser", msg, parent=root)


button(browser_strip, "CONNECT / REFRESH", connect_x_browser, accent=True).pack(side="right", padx=12, pady=7)

# PLATFORM CARDS
nav = tk.Frame(root, bg=BG)
nav.pack(fill="both", expand=True, padx=34, pady=(0, 20))
nav.grid_columnconfigure(0, weight=1)
nav.grid_columnconfigure(1, weight=1)
nav.grid_rowconfigure(0, weight=1)


def platform_card(parent, column, eyebrow, title, subtitle, features, primary_text, primary_command, secondary=None):
    glow_colour = GLOW if column == 0 else CYAN
    soft_colour = GLOW_SOFT if column == 0 else CYAN_SOFT
    outer = tk.Frame(parent, bg=soft_colour, padx=3, pady=3)
    outer.grid(row=0, column=column, sticky="nsew", padx=(0, 10) if column == 0 else (10, 0))
    halo = tk.Frame(outer, bg=glow_colour, padx=1, pady=1)
    halo.pack(fill="both", expand=True)
    card = tk.Frame(halo, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
    card.pack(fill="both", expand=True)

    def glow_on(_event):
        outer.configure(bg=glow_colour)
    def glow_off(_event):
        outer.configure(bg=soft_colour)
    for widget in (outer, halo, card):
        widget.bind("<Enter>", glow_on)
        widget.bind("<Leave>", glow_off)

    top = tk.Frame(card, bg=PANEL)
    top.pack(fill="x", padx=22, pady=(22, 8))
    tk.Label(top, text=eyebrow, fg=glow_colour, bg=PANEL, font=("Consolas", 8, "bold")).pack(anchor="w")
    tk.Label(top, text=title, fg=TEXT, bg=PANEL, font=("Segoe UI", 24, "bold")).pack(anchor="w", pady=(2, 4))
    tk.Label(top, text=subtitle, fg=MUTED, bg=PANEL, font=("Segoe UI", 10), justify="left", wraplength=380).pack(anchor="w")

    feature_box = tk.Frame(card, bg=SURFACE)
    feature_box.pack(fill="x", padx=22, pady=14)
    for feature in features:
        row = tk.Frame(feature_box, bg=SURFACE)
        row.pack(fill="x", padx=12, pady=5)
        tk.Label(row, text="●", fg=glow_colour, bg=SURFACE, font=("Segoe UI", 8, "bold")).pack(side="left")
        tk.Label(row, text=feature, fg=TEXT, bg=SURFACE, font=("Segoe UI", 9)).pack(side="left", padx=8)

    actions = tk.Frame(card, bg=PANEL)
    actions.pack(fill="x", padx=22, pady=(4, 22))
    button(actions, primary_text, primary_command, accent=True).pack(side="left")
    if secondary:
        text, command = secondary
        button(actions, text, command).pack(side="left", padx=8)


platform_card(
    nav,
    0,
    "PLATFORM 01",
    "X",
    "Manage your own X account with cleanup tools and scheduled posting.",
    [
        "Cleanup posts, replies, reposts and likes",
        "Schedule queued posts",
        "Shared controlled-browser session",
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
    "Commerce intelligence built around TikTok Shop live category data.",
    [
        "Live category collection",
        "Price movement and watch alerts",
        "Market comparison intelligence",
    ],
    "OPEN SHOP",
    lambda: launch("tiktok_shop_ui.py"),
)

# FOOTER
footer_glow = tk.Frame(root, bg=GLOW_SOFT, height=1)
footer_glow.pack(fill="x", padx=34, pady=(0, 10))
footer = tk.Frame(root, bg=BG)
footer.pack(fill="x", padx=36, pady=(0, 20))
tk.Label(footer, text="PULSE SOCIAL", fg=MUTED, bg=BG, font=("Consolas", 8, "bold")).pack(side="left")
tk.Label(footer, text="X CLEANUP  •  X AUTO POST  •  TIKTOK SHOP", fg=MUTED, bg=BG, font=("Consolas", 8)).pack(side="right")

root.protocol("WM_DELETE_WINDOW", close_all)
root.mainloop()
