from __future__ import annotations

import math
import subprocess
import sys
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import messagebox

from platforms.browser_control import connect_browser, running_browser_names
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
browser_future = None
status_after_id = None


def blend_colour(base, tint, amount):
    return "#" + "".join(
        f"{round(int(base[i:i + 2], 16) * (1 - amount) + int(tint[i:i + 2], 16) * amount):02x}"
        for i in (1, 3, 5)
    )


def rounded_shape(canvas, x1, y1, x2, y2, radius, **options):
    return canvas.create_polygon(
        x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
        x2, y2 - radius, x2, y2, x2 - radius, y2,
        x1 + radius, y2, x1, y2, x1, y2 - radius,
        x1, y1 + radius, x1, y1,
        smooth=True, splinesteps=24, **options,
    )


class AmbientWaves:
    """One UI-only clock; every canvas paints the same continuous backdrop."""

    def __init__(self, window, background):
        self.window = window
        self.background = background
        self.surfaces = []
        self.details = []
        self.after_id = None
        self.started = time.monotonic()
        self.stopped = False
        window.bind("<Destroy>", self._destroy, add="+")

    def add_surface(self, canvas):
        bands = []
        for colour in ("#9c50ef", "#e44ea5", "#7652d8"):
            # Broad, dim outer strokes blend into a gently brighter core.
            bands.append([
                canvas.create_line(
                    0, 0, 1, 1, fill=blend_colour(BG, colour, .014 + layer * .021),
                    width=96 - layer * 17, smooth=True, splinesteps=3, tags="waves",
                )
                for layer in range(6)
            ])
        canvas.tag_lower("waves")
        self.surfaces.append((canvas, bands))

    def start(self):
        if self.after_id is None and not self.stopped:
            self.after_id = self.window.after(125, self._tick)

    def _tick(self):
        self.after_id = None
        if self.stopped:
            return
        if self.window.state() != "iconic":
            phase = (time.monotonic() - self.started) * .13
            width = max(1, self.background.winfo_width())
            height = max(1, self.background.winfo_height())
            origin_x = self.background.winfo_rootx()
            origin_y = self.background.winfo_rooty()
            for canvas, bands in self.surfaces:
                if not canvas.winfo_ismapped():
                    continue
                offset_x = canvas.winfo_rootx() - origin_x
                offset_y = canvas.winfo_rooty() - origin_y
                for band, items in enumerate(bands):
                    points = []
                    for step in range(25):
                        x = -100 + (width + 200) * step / 24
                        y = height * (.40 + band * .22)
                        y += math.sin(x / width * 5.0 + phase + band * 1.8) * 53
                        y += math.sin(x / width * 2.8 - phase * .7 + band) * 25
                        points.extend((x - offset_x, y - offset_y))
                    for item in items:
                        canvas.coords(item, *points)
            for detail in self.details:
                detail(phase)
        # Minimized windows keep a cheap wake-up only; no canvas redraws.
        self.after_id = self.window.after(250 if self.window.state() == "iconic" else 125, self._tick)

    def _destroy(self, event):
        if event.widget == self.window:
            self.stopped = True
            if self.after_id is not None:
                self.window.after_cancel(self.after_id)
                self.after_id = None


class SoftCard:
    def __init__(self, parent, colour, accent):
        self.canvas = tk.Canvas(parent, bg=BG, bd=0, highlightthickness=0, height=340)
        ambient.add_surface(self.canvas)
        self.colour = colour
        self.accent = accent
        self.content = tk.Frame(self.canvas, bg=colour)
        self.window_item = self.canvas.create_window(24, 24, anchor="nw", window=self.content)
        self.edge = None
        self.canvas.bind("<Configure>", self._layout)
        self.content.bind("<Configure>", self._content_size)
        ambient.details.append(self._breathe)

    def _content_size(self, _event):
        height = self.content.winfo_reqheight() + 48
        if int(self.canvas.cget("height")) != height:
            self.canvas.configure(height=height)

    def _layout(self, event):
        self.canvas.itemconfigure(self.window_item, width=max(1, event.width - 48))
        self.canvas.delete("shell")
        for inset, amount in ((3, .035), (5, .06), (7, .10)):
            rounded_shape(
                self.canvas, inset, inset + 3, event.width - inset, event.height - inset,
                30, fill=blend_colour(BG, self.accent, amount), outline="", tags="shell",
            )
        self.edge = rounded_shape(
            self.canvas, 9, 9, event.width - 9, event.height - 11, 26,
            fill=self.colour, outline=blend_colour(self.colour, self.accent, .20),
            width=1, tags="shell",
        )
        self.canvas.tag_raise("shell", "waves")
        self.canvas.tag_raise(self.window_item)

    def _breathe(self, phase):
        if self.edge is not None:
            strength = .18 + .035 * math.sin(phase * 1.4)
            self.canvas.itemconfigure(self.edge, outline=blend_colour(self.colour, self.accent, strength))


def platform_badge(parent, title, card_bg, accent):
    canvas = tk.Canvas(parent, width=76, height=80, bg=card_bg, bd=0, highlightthickness=0)
    rounded_shape(canvas, 1, 4, 75, 78, 20, fill=blend_colour(card_bg, accent, .08), outline="")
    rounded_shape(canvas, 4, 3, 72, 71, 18, fill=SURFACE,
                  outline=blend_colour(SURFACE, accent, .28), tags="badge")
    canvas.create_line(19, 8, 55, 8, fill=blend_colour(SURFACE, TEXT, .10), tags="badge")
    if title == "TikTok":
        # Draw one silhouette per colour, without opaque overlapping text labels.
        # The bent shoulder, upright stem and open bowl read as a branded badge.
        for dx, dy, colour in ((-3, -2, CYAN), (3, 2, ACCENT_2), (0, 0, TEXT)):
            canvas.create_line(
                42 + dx, 21 + dy, 47 + dx, 29 + dy, 57 + dx, 32 + dy,
                smooth=True, width=7, fill=colour, tags="badge",
            )
            canvas.create_line(42 + dx, 20 + dy, 42 + dx, 48 + dy,
                               width=8, fill=colour, tags="badge")
            canvas.create_arc(22 + dx, 37 + dy, 43 + dx, 58 + dy,
                              start=85, extent=280, style="arc", width=7,
                              outline=colour, tags="badge")
    else:
        canvas.create_text(38, 36, text="X", fill=TEXT,
                           font=("Segoe UI Variable Display", 28, "bold"), tags="badge")
    previous = 0.0

    def float_badge(phase):
        nonlocal previous
        offset = math.sin(phase * 1.6 + (1.2 if title == "TikTok" else 0)) * 1.5
        canvas.move("badge", 0, offset - previous)
        previous = offset

    ambient.details.append(float_badge)
    return canvas


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

backdrop = tk.Canvas(root, bg=BG, bd=0, highlightthickness=0)
backdrop.pack(fill="both", expand=True)
ambient = AmbientWaves(root, backdrop)
ambient.add_surface(backdrop)

# HEADER
header = tk.Frame(backdrop, bg=BG)
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

subtitle = tk.Frame(backdrop, bg=BG)
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

glow_line = tk.Frame(backdrop, bg=ACCENT, height=2)
glow_line.pack(fill="x", padx=34, pady=(10, 0))

ensure_bridge_server()


def pdh_browser_status() -> str:
    running = running_browser_names()
    pdh_ready = bool(bridge_status().get("pdhConnected"))

    if pdh_ready:
        if len(running) == 1:
            return f"{running[0].upper()} OPEN // PDH CONNECTED"
        if len(running) > 1:
            return "PDH CONNECTED // " + " / ".join(name.upper() for name in running)
        return "PDH CONNECTED // BROWSER ACTIVE"

    if len(running) == 1:
        return f"{running[0].upper()} OPEN // WAITING FOR PDH"
    if len(running) > 1:
        return "WAITING FOR PDH // " + " / ".join(name.upper() for name in running)
    return "NO BROWSER OPEN // PDH WAITING"


browser_status_var = tk.StringVar(value=pdh_browser_status())

browser_outer = tk.Frame(
    backdrop,
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

def refresh_pdh_browser() -> None:
    global status_future
    if status_future is None and browser_future is None:
        status_future = status_executor.submit(pdh_browser_status)


def open_pulse_browser() -> None:
    global browser_future
    if browser_future is not None:
        return
    open_browser_button.configure(state="disabled")
    browser_status_var.set("OPENING PULSE BROWSER...")
    # Share the worker with status checks; never block Tk or launch twice.
    browser_future = status_executor.submit(connect_browser)


def poll_pdh_browser_status() -> None:
    global status_future, browser_future, status_after_id
    if status_future is not None and status_future.done():
        try:
            status = status_future.result()
        except Exception:
            status = "PDH STATUS UNAVAILABLE"
        if browser_future is None:
            browser_status_var.set(status)
        status_future = None
    if browser_future is not None and browser_future.done():
        try:
            ok, detail = browser_future.result()
        except Exception as exc:
            ok, detail = False, str(exc)
        browser_future = None
        open_browser_button.configure(state="normal")
        browser_status_var.set(
            "PULSE BROWSER OPEN // CHECKING PDH" if ok else "PULSE BROWSER COULD NOT OPEN"
        )
        if not ok:
            messagebox.showerror("Pulse Browser", detail, parent=root)
    refresh_pdh_browser()
    status_after_id = root.after(2000, poll_pdh_browser_status)


button(
    browser_outer,
    "↻  PDH / REFRESH",
    refresh_pdh_browser,
    accent=True,
).pack(side="right", padx=12, pady=8)

open_browser_button = button(browser_outer, "OPEN PULSE BROWSER", open_pulse_browser)
open_browser_button.pack(side="right", padx=(8, 0), pady=8)

# Reserve room for both actions even when the status text is long.
tk.Label(
    browser_outer,
    textvariable=browser_status_var,
    fg=MUTED,
    bg=PANEL,
    font=("Segoe UI Variable Text", 9),
    anchor="w",
).pack(side="left", fill="x", expand=True)

# PLATFORM CARDS
nav = tk.Canvas(backdrop, bg=BG, bd=0, highlightthickness=0)
ambient.add_surface(nav)
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

    shell = SoftCard(parent, card_bg, glow_colour)
    shell.canvas.grid(
        row=0,
        column=column,
        sticky="ew",
        padx=(0, 3) if column == 0 else (3, 0),
    )
    card = shell.content

    top = tk.Frame(card, bg=card_bg)
    top.pack(fill="x", padx=6, pady=(0, 10))

    mark_box = platform_badge(top, title, card_bg, glow_colour)
    mark_box.pack(side="left", anchor="n")

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
    description = tk.Label(
        copy,
        text=subtitle,
        fg=MUTED,
        bg=card_bg,
        font=("Segoe UI Variable Text", 10),
        justify="left",
        wraplength=270,
        height=2,
        anchor="nw",
    )
    description.pack(anchor="w", fill="x")
    def wrap_description(event):
        width = max(1, event.width)
        if int(description.cget("wraplength")) != width:
            description.configure(wraplength=width)

    copy.bind("<Configure>", wrap_description)

    feature_box = tk.Frame(
        card,
        bg=card_bg,
    )
    feature_box.pack(fill="x", padx=6, pady=(0, 10))

    glyphs = ("◌", "▣", "◉") if column == 0 else ("◇", "◉", "⚡")
    for index, feature in enumerate(features):
        row = tk.Frame(feature_box, bg=card_bg)
        row.pack(fill="x", pady=0)

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
            bg=card_bg,
            font=("Segoe UI Variable Text", 9),
        ).pack(side="left", padx=(12, 0), pady=10)

        if index < len(features) - 1:
            tk.Frame(feature_box, bg=blend_colour(card_bg, glow_colour, .09), height=1).pack(fill="x", padx=(42, 0))

    actions = tk.Frame(card, bg=card_bg)
    actions.pack(fill="x", padx=6, pady=(0, 2))

    primary = button(actions, primary_text, primary_command, accent=True)
    primary.configure(padx=12)
    primary.pack(side="left")

    if secondary:
        text, command = secondary
        secondary_btn = button(actions, text, command)
        secondary_btn.configure(padx=11)
        secondary_btn.pack(side="left", padx=(8, 0))

    if tertiary:
        text, command = tertiary
        tertiary_btn = button(actions, text, command)
        tertiary_btn.configure(padx=11)
        tertiary_btn.pack(side="left", padx=(8, 0))


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
spacer = tk.Canvas(backdrop, bg=BG, bd=0, highlightthickness=0, height=0)
ambient.add_surface(spacer)
spacer.pack(fill="both", expand=True)

footer_line = tk.Frame(backdrop, bg=BORDER, height=1)
footer_line.pack(fill="x", padx=34, pady=(0, 10))

footer = tk.Frame(backdrop, bg=BG)
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
ambient.start()
poll_pdh_browser_status()
root.mainloop()
