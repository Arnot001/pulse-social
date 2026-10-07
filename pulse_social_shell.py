"""Pulse Social multi-platform application shell.

The existing pulse_social_ui.py X Cleanup application is intentionally not
imported or modified here. Platform modules can be developed independently and
connected to this shell when they are ready.
"""

import math
import tkinter as tk

from platforms.tiktok import TikTokModule

BG = "#07090f"
PANEL = "#0d111b"
PANEL_2 = "#121827"
BORDER = "#20283a"
TEXT = "#f5f7fb"
MUTED = "#8993a6"
ACCENT = "#ff0a8a"
ACCENT_2 = "#25f4ee"
SUCCESS = "#35d07f"
SUBTLE = "#65758b"

_WAVE_TILE_WIDTH = 900
_WAVE_TILE_HEIGHT = 900
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
                145 + 34 * math.sin(t + 0.2),
                455 + 48 * math.sin(t * 0.82 + 1.7),
                760 + 34 * math.sin(t * 1.05 + 2.8),
            )
        )

    def gaussian(distance, sigma):
        return math.exp(-((distance / sigma) ** 2))

    index = 0
    for y in range(height):
        for x in range(width):
            a, b, c = centres[x]
            p1 = gaussian(abs(y - a), 92.0)
            p2 = gaussian(abs(y - b), 118.0)
            p3 = gaussian(abs(y - c), 100.0)
            pixels[index] = min(255, int(base[0] + 42 * p1 + 18 * p2 + 34 * p3))
            pixels[index + 1] = min(255, int(base[1] + 4 * p1 + 10 * p2 + 4 * p3))
            pixels[index + 2] = min(255, int(base[2] + 36 * p1 + 48 * p2 + 30 * p3))
            index += 3

    _WAVE_PPM_CACHE = f"P6\n{width} {height}\n255\n".encode("ascii") + bytes(pixels)
    return _WAVE_PPM_CACHE


class PulseSocialShell:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Pulse Social")
        self.root.geometry("1280x860")
        self.root.minsize(1040, 720)
        self.root.configure(bg=BG)
        self.active_platform = None
        self.platform_buttons = {}
        self.platform_host = None
        self._build()
        self.show_platform("tiktok")

    def _build(self):
        self.backdrop = tk.Canvas(self.root, bg=BG, highlightthickness=0, bd=0)
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
            if not self.backdrop.winfo_exists():
                return
            self.wave_offset = (self.wave_offset + 1) % _WAVE_TILE_WIDTH
            x = -self.wave_offset
            for index, item in enumerate(self.wave_items):
                self.backdrop.coords(item, x + index * _WAVE_TILE_WIDTH, 0)
            self.root.after(150, animate)

        self.root.after(150, animate)

        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=30, pady=(20, 7))

        badge = tk.Canvas(header, width=42, height=42, bg=BG, highlightthickness=0, bd=0)
        badge.pack(side="left", padx=(0, 13))
        badge.create_rectangle(3, 3, 39, 39, outline="#3b2944", fill="#0b1018", width=1)
        badge.create_line(11, 27, 19, 17, 25, 22, 32, 12, fill=ACCENT, width=3, smooth=True)
        badge.create_line(11, 30, 19, 20, 25, 25, 32, 15, fill=ACCENT_2, width=1, smooth=True)

        brand = tk.Frame(header, bg=BG)
        brand.pack(side="left")
        title_row = tk.Frame(brand, bg=BG)
        title_row.pack(anchor="w")
        tk.Label(title_row, text="PULSE", bg=BG, fg=TEXT, font=("Segoe UI", 25, "bold")).pack(side="left")
        tk.Label(title_row, text=" SOCIAL", bg=BG, fg=ACCENT, font=("Segoe UI", 25, "bold")).pack(side="left")
        tk.Label(
            brand,
            text="One workspace for your social tools, queues and platform modules.",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(1, 0))

        tk.Label(
            header,
            text="CONTROL CENTRE",
            bg=BG,
            fg=ACCENT_2,
            font=("Segoe UI", 9, "bold"),
        ).pack(side="right", pady=13)

        tk.Frame(self.root, bg="#2a1834", height=1).pack(fill="x", padx=30, pady=(0, 8))

        nav_shell = tk.Frame(self.root, bg="#351431", padx=1, pady=1)
        nav_shell.pack(fill="x", padx=30, pady=(0, 10))
        nav = tk.Frame(nav_shell, bg=PANEL)
        nav.pack(fill="x")
        tk.Label(nav, text="PLATFORMS", bg=PANEL, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(
            side="left", padx=(14, 12), pady=10
        )
        self._platform_button(nav, "x", "X")
        self._platform_button(nav, "tiktok", "TIKTOK")
        self._platform_button(nav, "future", "+ PLATFORM")

        self.platform_host = tk.Frame(
            self.root,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        self.platform_host.pack(fill="both", expand=True, padx=30, pady=(0, 24))

    def _platform_button(self, parent, key, label):
        button = tk.Button(
            parent,
            text=label,
            command=lambda: self.show_platform(key),
            bg="#182235",
            fg=TEXT,
            activebackground="#28364d",
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            padx=20,
            pady=7,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        button.pack(side="left", padx=(0, 7), pady=5)
        self.platform_buttons[key] = button

    def _clear_host(self):
        for child in self.platform_host.winfo_children():
            child.destroy()

    def _refresh_nav(self):
        for key, button in self.platform_buttons.items():
            selected = key == self.active_platform
            button.configure(
                bg=ACCENT if selected else "#182235",
                fg=TEXT,
                highlightbackground="#ff5abb" if selected else BORDER,
            )

    def show_platform(self, platform):
        self.active_platform = platform
        self._refresh_nav()
        self._clear_host()

        if platform == "tiktok":
            TikTokModule(self.platform_host).pack(fill="both", expand=True)
            return

        if platform == "x":
            self._placeholder(
                "X",
                "X Cleanup remains isolated in pulse_social_ui.py and has not been changed.\n\n"
                "It can be connected to this shell later without rewriting its working cleanup engine.",
            )
            return

        self._placeholder(
            "FUTURE PLATFORM",
            "This slot is reserved for future social platforms.\n\n"
            "New platforms get their own package under platforms/ rather than being built into X or TikTok.",
        )

    def _placeholder(self, title, message):
        box = tk.Frame(self.platform_host, bg="#0f1520", highlightthickness=1, highlightbackground=BORDER)
        box.pack(fill="both", expand=True, padx=22, pady=22)
        tk.Frame(box, bg=ACCENT, height=2).pack(fill="x")
        content = tk.Frame(box, bg="#0f1520")
        content.pack(fill="both", expand=True, padx=22, pady=20)
        tk.Label(
            content,
            text=title,
            bg="#0f1520",
            fg=TEXT,
            font=("Segoe UI", 20, "bold"),
        ).pack(anchor="w")
        tk.Label(
            content,
            text=message,
            bg="#0f1520",
            fg=MUTED,
            justify="left",
            wraplength=700,
            font=("Segoe UI", 11),
        ).pack(anchor="w", pady=(10, 0))

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    PulseSocialShell().run()
