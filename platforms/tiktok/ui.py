"""Standalone TikTok module UI.

This module deliberately has no dependency on pulse_social_ui.py.  The
existing X cleanup application stays isolated while TikTok features grow in
this package.
"""

import tkinter as tk

BG = "#07090f"
PANEL = "#0d111b"
PANEL_2 = "#121827"
BORDER = "#20283a"
TEXT = "#f5f7fb"
MUTED = "#8993a6"
ACCENT = "#ff008c"
SUCCESS = "#35d07f"


class TikTokModule(tk.Frame):
    """Root view for TikTok-specific Pulse Social features."""

    def __init__(self, master, **kwargs):
        super().__init__(master, bg=BG, **kwargs)
        self.active_feature = tk.StringVar(value="shop")
        self.content = None
        self._build()
        self.show_feature("shop")

    def _build(self):
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=24, pady=(22, 12))
        tk.Label(
            header,
            text="TIKTOK",
            bg=BG,
            fg=TEXT,
            font=("Segoe UI", 22, "bold"),
        ).pack(side="left")
        tk.Label(
            header,
            text="PLATFORM MODULE",
            bg=BG,
            fg=ACCENT,
            font=("Consolas", 10, "bold"),
        ).pack(side="right", pady=(9, 0))

        nav = tk.Frame(self, bg=BG)
        nav.pack(fill="x", padx=24, pady=(0, 12))
        for key, label in (
            ("shop", "SHOP"),
            ("autopost", "AUTO POST"),
            ("analytics", "ANALYTICS"),
        ):
            tk.Button(
                nav,
                text=label,
                command=lambda feature=key: self.show_feature(feature),
                bg=PANEL_2,
                fg=TEXT,
                activebackground=ACCENT,
                activeforeground="white",
                relief="flat",
                bd=0,
                padx=18,
                pady=9,
                font=("Segoe UI", 9, "bold"),
                cursor="hand2",
            ).pack(side="left", padx=(0, 8))

        self.content = tk.Frame(
            self,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        self.content.pack(fill="both", expand=True, padx=24, pady=(0, 24))

    def _clear_content(self):
        for child in self.content.winfo_children():
            child.destroy()

    def show_feature(self, feature):
        self.active_feature.set(feature)
        self._clear_content()

        if feature == "shop":
            self._show_shop()
        elif feature == "autopost":
            self._show_placeholder("AUTO POST", "TikTok publishing queue will live here.")
        else:
            self._show_placeholder("ANALYTICS", "TikTok account and content intelligence will live here.")

    def _show_shop(self):
        tk.Label(
            self.content,
            text="TIKTOK SHOP INTELLIGENCE",
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w", padx=22, pady=(22, 4))
        tk.Label(
            self.content,
            text="Commerce collector integration point",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 10),
        ).pack(anchor="w", padx=22)

        status = tk.Frame(self.content, bg=PANEL_2)
        status.pack(fill="x", padx=22, pady=22)
        tk.Label(
            status,
            text="●  MODULE READY",
            bg=PANEL_2,
            fg=SUCCESS,
            font=("Consolas", 10, "bold"),
        ).pack(anchor="w", padx=16, pady=(14, 5))
        tk.Label(
            status,
            text="Next: connect the existing TikTok Shop collector and deal intelligence without touching X Cleanup.",
            bg=PANEL_2,
            fg=MUTED,
            justify="left",
            wraplength=650,
            font=("Segoe UI", 10),
        ).pack(anchor="w", padx=16, pady=(0, 14))

    def _show_placeholder(self, title, message):
        tk.Label(
            self.content,
            text=title,
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w", padx=22, pady=(22, 5))
        tk.Label(
            self.content,
            text=message,
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 10),
        ).pack(anchor="w", padx=22)
