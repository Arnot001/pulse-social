"""Pulse Social multi-platform application shell.

The existing pulse_social_ui.py X Cleanup application is intentionally not
imported or modified here. Platform modules can be developed independently and
connected to this shell when they are ready.
"""

import tkinter as tk

from platforms.tiktok import TikTokModule

BG = "#07090f"
PANEL = "#0d111b"
PANEL_2 = "#121827"
BORDER = "#20283a"
TEXT = "#f5f7fb"
MUTED = "#8993a6"
ACCENT = "#ff008c"


class PulseSocialShell:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Pulse Social")
        self.root.geometry("920x720")
        self.root.minsize(780, 620)
        self.root.configure(bg=BG)
        self.active_platform = None
        self.platform_buttons = {}
        self.platform_host = None
        self._build()
        self.show_platform("tiktok")

    def _build(self):
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=26, pady=(22, 10))
        tk.Label(
            header,
            text="PULSE SOCIAL",
            bg=BG,
            fg=TEXT,
            font=("Segoe UI", 25, "bold"),
        ).pack(side="left")
        tk.Label(
            header,
            text="MULTI-PLATFORM CONTROL",
            bg=BG,
            fg=MUTED,
            font=("Consolas", 10, "bold"),
        ).pack(side="right", pady=(12, 0))

        nav = tk.Frame(self.root, bg=BG)
        nav.pack(fill="x", padx=26, pady=(0, 12))
        self._platform_button(nav, "x", "X")
        self._platform_button(nav, "tiktok", "TIKTOK")
        self._platform_button(nav, "future", "+ PLATFORM")

        self.platform_host = tk.Frame(
            self.root,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        self.platform_host.pack(fill="both", expand=True, padx=26, pady=(0, 24))

    def _platform_button(self, parent, key, label):
        button = tk.Button(
            parent,
            text=label,
            command=lambda: self.show_platform(key),
            bg=PANEL_2,
            fg=TEXT,
            activebackground=ACCENT,
            activeforeground="white",
            relief="flat",
            bd=0,
            padx=22,
            pady=10,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        )
        button.pack(side="left", padx=(0, 8))
        self.platform_buttons[key] = button

    def _clear_host(self):
        for child in self.platform_host.winfo_children():
            child.destroy()

    def _refresh_nav(self):
        for key, button in self.platform_buttons.items():
            button.configure(bg=ACCENT if key == self.active_platform else PANEL_2)

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
        box = tk.Frame(self.platform_host, bg=PANEL)
        box.pack(fill="both", expand=True, padx=28, pady=28)
        tk.Label(
            box,
            text=title,
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 20, "bold"),
        ).pack(anchor="w")
        tk.Label(
            box,
            text=message,
            bg=PANEL,
            fg=MUTED,
            justify="left",
            wraplength=700,
            font=("Segoe UI", 11),
        ).pack(anchor="w", pady=(10, 0))

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    PulseSocialShell().run()
