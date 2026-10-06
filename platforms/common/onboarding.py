from __future__ import annotations

import tkinter as tk

BG = "#06070b"
PANEL = "#101622"
PANEL_2 = "#151d2c"
BORDER = "#28354b"
TEXT = "#f7f8fb"
MUTED = "#8e9aae"
ACCENT = "#ff0a8a"
ACCENT_2 = "#ff4bb0"
CYAN = "#33e6ff"
SUCCESS = "#35d07f"


def _button(parent, text, command, *, accent=False):
    bg = ACCENT if accent else PANEL_2
    active = ACCENT_2 if accent else "#202b3d"
    return tk.Button(
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
    )


def _step_card(parent, number: str, title: str, body: str, accent: str) -> tk.Frame:
    outer = tk.Frame(parent, bg=accent, padx=1, pady=1)
    card = tk.Frame(outer, bg=PANEL)
    card.pack(fill="both", expand=True)

    badge = tk.Frame(card, bg=PANEL_2)
    badge.pack(anchor="w", padx=16, pady=(14, 8))
    tk.Label(
        badge,
        text=number,
        bg=PANEL_2,
        fg=accent,
        font=("Consolas", 9, "bold"),
        padx=8,
        pady=4,
    ).pack()

    tk.Label(
        card,
        text=title,
        bg=PANEL,
        fg=TEXT,
        font=("Segoe UI", 12, "bold"),
    ).pack(anchor="w", padx=16)

    tk.Label(
        card,
        text=body,
        bg=PANEL,
        fg=MUTED,
        justify="left",
        wraplength=310,
        font=("Segoe UI", 9),
    ).pack(anchor="w", padx=16, pady=(6, 16))

    return outer


def open_get_started(parent: tk.Misc) -> tk.Toplevel:
    existing = getattr(parent, "_pulse_get_started", None)
    if existing is not None:
        try:
            if existing.winfo_exists():
                existing.lift()
                existing.focus_force()
                return existing
        except tk.TclError:
            pass

    window = tk.Toplevel(parent)
    parent._pulse_get_started = window
    window.title("Pulse Social — Get Started")
    window.geometry("820x610")
    window.minsize(760, 560)
    window.configure(bg=BG)
    window.transient(parent)

    header = tk.Frame(window, bg=BG)
    header.pack(fill="x", padx=28, pady=(24, 10))

    brand = tk.Frame(header, bg=BG)
    brand.pack(side="left")
    tk.Label(brand, text="PULSE", fg=TEXT, bg=BG, font=("Segoe UI", 25, "bold")).pack(side="left")
    tk.Label(brand, text=" // START HERE", fg=ACCENT_2, bg=BG, font=("Segoe UI", 25, "bold")).pack(side="left")

    tk.Label(
        header,
        text="BETA GUIDE",
        fg=CYAN,
        bg=BG,
        font=("Consolas", 9, "bold"),
    ).pack(side="right", pady=9)

    tk.Label(
        window,
        text="Everything you need to get moving. No terminal. No GitHub. No developer setup.",
        fg=MUTED,
        bg=BG,
        font=("Segoe UI", 10),
    ).pack(anchor="w", padx=30, pady=(0, 14))

    rule = tk.Frame(window, bg=ACCENT, height=2)
    rule.pack(fill="x", padx=28, pady=(0, 16))

    grid = tk.Frame(window, bg=BG)
    grid.pack(fill="both", expand=True, padx=28)
    grid.grid_columnconfigure(0, weight=1)
    grid.grid_columnconfigure(1, weight=1)
    grid.grid_rowconfigure(0, weight=1)
    grid.grid_rowconfigure(1, weight=1)

    cards = [
        (
            0,
            0,
            "01",
            "OPEN PULSE",
            "Start from the Pulse Social control deck. The browser strip at the top tells you whether the Pulse browser and PDH connection are ready.",
            ACCENT,
        ),
        (
            0,
            1,
            "02",
            "LOG IN NORMALLY",
            "Open the Pulse browser when a feature asks for it, then sign in to X or TikTok yourself. Pulse uses that dedicated browser session instead of asking for your account password.",
            CYAN,
        ),
        (
            1,
            0,
            "03",
            "CHOOSE A TOOL",
            "X Cleanup removes your own account activity. Auto Post queues posts. TikTok Shop watches products and prices. TikTok Cleanup only acts after you choose what to remove.",
            CYAN,
        ),
        (
            1,
            1,
            "04",
            "POST & CREATE",
            "Write your post, add media, choose a schedule and press QUEUE POST. Use the 😀 EMOJI button to insert local Unicode emoji exactly where your cursor is.",
            ACCENT,
        ),
    ]

    for row, column, number, title, body, colour in cards:
        card = _step_card(grid, number, title, body, colour)
        card.grid(
            row=row,
            column=column,
            sticky="nsew",
            padx=(0, 7) if column == 0 else (7, 0),
            pady=(0, 7) if row == 0 else (7, 0),
        )

    note = tk.Frame(window, bg=PANEL_2, highlightthickness=1, highlightbackground=BORDER)
    note.pack(fill="x", padx=28, pady=(16, 10))
    tk.Label(
        note,
        text="BETA SAFETY",
        fg=SUCCESS,
        bg=PANEL_2,
        font=("Consolas", 8, "bold"),
    ).pack(side="left", padx=(14, 10), pady=10)
    tk.Label(
        note,
        text="Cleanup actions stay manual and explicit. If Pulse is unsure, it should stop rather than guess.",
        fg=TEXT,
        bg=PANEL_2,
        font=("Segoe UI", 9),
    ).pack(side="left", pady=10)

    footer = tk.Frame(window, bg=BG)
    footer.pack(fill="x", padx=28, pady=(0, 20))
    tk.Label(
        footer,
        text="You can reopen this guide any time from GET STARTED on the control deck.",
        fg=MUTED,
        bg=BG,
        font=("Segoe UI", 9),
    ).pack(side="left")

    def close():
        try:
            if getattr(parent, "_pulse_get_started", None) is window:
                parent._pulse_get_started = None
        except tk.TclError:
            pass
        window.destroy()

    _button(footer, "GOT IT", close, accent=True).pack(side="right")
    window.bind("<Escape>", lambda _event: close())
    window.protocol("WM_DELETE_WINDOW", close)
    return window
