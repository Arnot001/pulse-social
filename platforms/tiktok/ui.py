"""Standalone TikTok module UI.

This module deliberately has no dependency on pulse_social_ui.py. The existing
X cleanup application stays isolated while TikTok features grow here.
"""

import math
import tkinter as tk

from .auto_post_ui import TikTokAutoPostView
from .shop_ui import TikTokShopView

BG = "#07090f"
PANEL = "#0d111b"
PANEL_2 = "#121827"
BORDER = "#20283a"
TEXT = "#f5f7fb"
MUTED = "#8993a6"
ACCENT = "#fe2c55"
ACCENT_2 = "#25f4ee"
SUBTLE = "#65758b"

_WAVE_TILE_WIDTH = 900
_WAVE_TILE_HEIGHT = 760
_WAVE_PPM_CACHE = None


def _wave_ppm():
    global _WAVE_PPM_CACHE
    if _WAVE_PPM_CACHE is not None:
        return _WAVE_PPM_CACHE

    width = _WAVE_TILE_WIDTH
    height = _WAVE_TILE_HEIGHT
    base = (7, 8, 12)
    pixels = bytearray(width * height * 3)
    centres = []
    for x in range(width):
        t = (x / width) * math.tau
        centres.append(
            (
                130 + 32 * math.sin(t + 0.25),
                390 + 44 * math.sin(t * 0.84 + 1.9),
                650 + 34 * math.sin(t * 1.06 + 3.0),
            )
        )

    def gaussian(distance, sigma):
        return math.exp(-((distance / sigma) ** 2))

    index = 0
    for y in range(height):
        for x in range(width):
            a, b, c = centres[x]
            p1 = gaussian(abs(y - a), 86.0)
            p2 = gaussian(abs(y - b), 106.0)
            p3 = gaussian(abs(y - c), 92.0)
            pixels[index] = min(255, int(base[0] + 44 * p1 + 18 * p2 + 38 * p3))
            pixels[index + 1] = min(255, int(base[1] + 4 * p1 + 12 * p2 + 3 * p3))
            pixels[index + 2] = min(255, int(base[2] + 32 * p1 + 48 * p2 + 30 * p3))
            index += 3

    _WAVE_PPM_CACHE = f"P6\n{width} {height}\n255\n".encode("ascii") + bytes(pixels)
    return _WAVE_PPM_CACHE


class TikTokModule(tk.Frame):
    """Root view for TikTok-specific Pulse Social features."""

    def __init__(self, master, **kwargs):
        super().__init__(master, bg=BG, **kwargs)
        self.active_feature = tk.StringVar(value="shop")
        self.content = None
        self.feature_buttons = {}
        self._destroyed = False
        self._build()
        self.show_feature("shop")

    def _build(self):
        self.backdrop = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0)
        self.backdrop.place(x=0, y=0, relwidth=1, relheight=1)
        self.wave_photo = tk.PhotoImage(data=_wave_ppm(), format="PPM")
        self.backdrop.wave_photo = self.wave_photo
        self.wave_items = [
            self.backdrop.create_image(0, 0, image=self.wave_photo, anchor="nw"),
            self.backdrop.create_image(_WAVE_TILE_WIDTH, 0, image=self.wave_photo, anchor="nw"),
            self.backdrop.create_image(_WAVE_TILE_WIDTH * 2, 0, image=self.wave_photo, anchor="nw"),
        ]
        self.wave_offset = 0

        def animate():
            if self._destroyed or not self.backdrop.winfo_exists():
                return
            self.wave_offset = (self.wave_offset + 1) % _WAVE_TILE_WIDTH
            x = -self.wave_offset
            for index, item in enumerate(self.wave_items):
                self.backdrop.coords(item, x + index * _WAVE_TILE_WIDTH, 0)
            self._ambient_after_id = self.after(150, animate)

        self._ambient_after_id = self.after(150, animate)
        self.bind("<Destroy>", self._on_destroy, add="+")

        nav_shell = tk.Frame(self, bg="#11303a", padx=1, pady=1)
        nav_shell.pack(fill="x", padx=14, pady=(14, 8))
        nav = tk.Frame(nav_shell, bg=PANEL)
        nav.pack(fill="x")
        tk.Label(nav, text="TOOLS", bg=PANEL, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(
            side="left", padx=(13, 11), pady=9
        )
        for key, label in (("shop", "SHOP"), ("autopost", "AUTO POST")):
            button = tk.Button(
                nav,
                text=label,
                command=lambda feature=key: self.show_feature(feature),
                bg="#182235",
                fg=TEXT,
                activebackground="#26344a",
                activeforeground=TEXT,
                relief="flat",
                bd=0,
                padx=16,
                pady=6,
                font=("Segoe UI", 8, "bold"),
                cursor="hand2",
                highlightthickness=1,
                highlightbackground=BORDER,
            )
            button.pack(side="left", padx=(0, 7), pady=5)
            self.feature_buttons[key] = button

        self.content = tk.Frame(self, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        self.content.pack(fill="both", expand=True, padx=14, pady=(0, 14))

    def _clear_content(self):
        for child in self.content.winfo_children():
            child.destroy()

    def show_feature(self, feature):
        self.active_feature.set(feature)
        for key, button in self.feature_buttons.items():
            selected = key == feature
            button.configure(
                bg=ACCENT if selected else "#182235",
                highlightbackground="#ff5a79" if selected else BORDER,
            )
        self._clear_content()

        if feature == "shop":
            TikTokShopView(self.content).pack(fill="both", expand=True)
        elif feature == "autopost":
            TikTokAutoPostView(self.content, embedded=True).pack(fill="both", expand=True)
        else:
            self._show_placeholder("ANALYTICS", "TikTok account and content intelligence will live here.")

    def _show_placeholder(self, title, message):
        box = tk.Frame(self.content, bg="#0f1520", highlightthickness=1, highlightbackground=BORDER)
        box.pack(fill="both", expand=True, padx=20, pady=20)
        tk.Frame(box, bg=ACCENT, height=2).pack(fill="x")
        tk.Label(box, text=title, bg="#0f1520", fg=TEXT,
                 font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=22, pady=(22, 5))
        tk.Label(box, text=message, bg="#0f1520", fg=MUTED,
                 font=("Segoe UI", 10)).pack(anchor="w", padx=22)

    def _on_destroy(self, event):
        if event.widget is self:
            self._destroyed = True
            if getattr(self, "_ambient_after_id", None) is not None:
                try:
                    self.after_cancel(self._ambient_after_id)
                except tk.TclError:
                    pass
                self._ambient_after_id = None
