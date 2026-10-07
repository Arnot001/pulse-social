from __future__ import annotations

import math
import threading
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from platforms.common.emoji_picker import open_emoji_picker

from .auto_post import (
    MAX_CAPTION_UTF16,
    add_post,
    item_media_paths,
    load_queue,
    query_creator_info,
    remove_post,
    run_scheduler,
)
from .browser_post import (
    preview_tiktok_sound,
    search_tiktok_sounds,
    stop_tiktok_sound_preview,
)
from .browser_session import open_tiktok_browser, tiktok_browser_status
from .oauth import (
    DEFAULT_REDIRECT_URI,
    app_credentials_configured,
    backend_enabled,
    backend_health,
    connect,
    ensure_local_backend,
    local_backend_enabled,
    load_app_credentials,
    connection_status,
    disconnect,
    save_app_credentials,
)

BG = "#06070b"
SURFACE = "#0b0f17"
PANEL = "#101622"
PANEL_2 = "#151d2c"
PANEL_3 = "#0a0e15"
BORDER = "#242f43"
TEXT = "#f7f8fb"
MUTED = "#8e9aae"
ACCENT = "#25f4ee"
ACCENT_2 = "#fe2c55"
SUCCESS = "#35d07f"
DANGER = "#ff4d67"
SOFT_BORDER = "#3b2944"
SUBTLE = "#65758b"
TABLE_BG = "#0b111b"

_WAVE_TILE_WIDTH = 900
_WAVE_TILE_HEIGHT = 820
_WAVE_PPM_CACHE = None


def _wave_ppm():
    """Smooth local raster ambience matching the TikTok Shop visual language."""
    global _WAVE_PPM_CACHE
    if _WAVE_PPM_CACHE is not None:
        return _WAVE_PPM_CACHE

    width = _WAVE_TILE_WIDTH
    height = _WAVE_TILE_HEIGHT
    base = (6, 7, 11)
    centers = []
    for x in range(width):
        t = (x / width) * math.tau
        centers.append(
            (
                140 + 34 * math.sin(t + 0.25) + 12 * math.sin(t * 0.48 + 1.1),
                420 + 46 * math.sin(t * 0.84 + 1.95) + 18 * math.sin(t * 0.36 - 0.5),
                700 + 36 * math.sin(t * 1.06 + 3.1) + 14 * math.sin(t * 0.50 + 0.8),
            )
        )

    def gaussian_lookup(sigma):
        return [math.exp(-((distance / sigma) ** 2)) for distance in range(height + 1)]

    g1 = gaussian_lookup(86.0)
    g2 = gaussian_lookup(106.0)
    g3 = gaussian_lookup(92.0)
    pixels = bytearray(width * height * 3)
    index = 0
    for y in range(height):
        vertical = (1.0 - y / height) * 1.6
        for x in range(width):
            c1, c2, c3 = centers[x]
            a = g1[min(height, int(abs(y - c1)))]
            b = g2[min(height, int(abs(y - c2)))]
            d = g3[min(height, int(abs(y - c3)))]
            pixels[index] = min(255, int(base[0] + vertical + 46 * a + 18 * b + 40 * d))
            pixels[index + 1] = min(255, int(base[1] + vertical + 4 * a + 12 * b + 3 * d))
            pixels[index + 2] = min(255, int(base[2] + vertical + 32 * a + 50 * b + 30 * d))
            index += 3

    _WAVE_PPM_CACHE = (
        f"P6\n{width} {height}\n255\n".encode("ascii") + bytes(pixels)
    )
    return _WAVE_PPM_CACHE


AUTO_DELETE_PRESETS = {
    "OFF": 0,
    "30 MIN": 30,
    "1 HOUR": 60,
    "6 HOURS": 360,
    "12 HOURS": 720,
    "24 HOURS": 1440,
    "3 DAYS": 4320,
    "7 DAYS": 10080,
}


class TikTokAutoPostView(tk.Frame):
    def __init__(self, master, *, embedded=False, **kwargs):
        super().__init__(master, bg=BG, **kwargs)
        self.embedded = embedded
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.oauth_worker: threading.Thread | None = None
        self.selected_media: list[str] = []
        self.mapping = {}
        self.privacy_options = ["PUBLIC", "FRIENDS", "PRIVATE"]
        self._destroyed = False

        self.connection_var = tk.StringVar(value=tiktok_browser_status())
        self.status_var = tk.StringVar(value="STOPPED")
        self.char_var = tk.StringVar(value=f"0 / {MAX_CAPTION_UTF16}")
        self.media_var = tk.StringVar(value="NO MEDIA")
        self.music_query = ""
        self.music_search = ""
        self.music_var = tk.StringVar(value="NO MUSIC")
        self.next_var = tk.StringVar(value="No posts queued")
        self.schedule_mode = tk.StringVar(value="delay")
        self.delay_var = tk.StringVar(value="1")
        self.clock_var = tk.StringVar(value=(datetime.now() + timedelta(minutes=5)).strftime("%H:%M"))
        self.privacy_var = tk.StringVar(value="PUBLIC")
        self.auto_delete_var = tk.StringVar(value="OFF")
        self.comments_var = tk.BooleanVar(value=True)
        self.duet_var = tk.BooleanVar(value=True)
        self.stitch_var = tk.BooleanVar(value=True)
        self.brand_content_var = tk.BooleanVar(value=False)
        self.brand_organic_var = tk.BooleanVar(value=False)
        self.aigc_var = tk.BooleanVar(value=False)
        self.stats = {
            "queued": tk.StringVar(value="0"),
            "processing": tk.StringVar(value="0"),
            "posted": tk.StringVar(value="0"),
            "error": tk.StringVar(value="0"),
        }

        self._configure_style()
        self._build()
        self.refresh()
        self._refresh_connection_label()
        self.bind("<Destroy>", self._on_destroy, add="+")

    def _configure_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "TikTok.Treeview",
            background=TABLE_BG,
            fieldbackground=TABLE_BG,
            foreground=TEXT,
            rowheight=31,
            borderwidth=0,
            font=("Segoe UI", 9),
        )
        style.map(
            "TikTok.Treeview",
            background=[("selected", "#34203b")],
            foreground=[("selected", TEXT)],
        )
        style.configure(
            "TikTok.Treeview.Heading",
            background="#141c2a",
            foreground=MUTED,
            relief="flat",
            borderwidth=0,
            font=("Segoe UI", 8, "bold"),
            padding=(8, 9),
        )
        style.map(
            "TikTok.Treeview.Heading",
            background=[("active", "#1c2638")],
        )
        style.configure(
            "TikTok.TCombobox",
            fieldbackground=PANEL_2,
            background=PANEL_2,
            foreground=TEXT,
            arrowcolor=ACCENT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            padding=6,
        )
        style.map(
            "TikTok.TCombobox",
            fieldbackground=[("readonly", PANEL_2)],
            foreground=[("readonly", TEXT)],
            selectbackground=[("readonly", PANEL_2)],
            selectforeground=[("readonly", TEXT)],
        )
        for scrollbar_style in ("TikTok.Vertical.TScrollbar", "TikTok.Horizontal.TScrollbar"):
            style.configure(
                scrollbar_style,
                troughcolor=TABLE_BG,
                background="#151e2d",
                bordercolor=TABLE_BG,
                lightcolor="#151e2d",
                darkcolor="#151e2d",
                arrowcolor=SUBTLE,
                relief="flat",
                width=10,
                arrowsize=9,
            )
            style.map(
                scrollbar_style,
                background=[
                    ("pressed", "#31415a"),
                    ("active", "#26344a"),
                ],
                arrowcolor=[("active", TEXT)],
            )

    def _button(self, parent, text, command, accent=False, danger=False, compact=False):
        if accent:
            bg, active, border = ACCENT_2, "#ff5475", "#ff5a79"
        elif danger:
            bg, active, border = "#5b1623", "#7e2637", "#7e2637"
        else:
            bg, active, border = "#182235", "#223049", BORDER

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
            padx=11 if compact else 15,
            pady=6 if compact else 9,
            font=("Segoe UI", 8 if compact else 9, "bold"),
            cursor="hand2",
            highlightthickness=1,
            highlightbackground=border,
            highlightcolor=border,
        )

        def enter(_event):
            btn.configure(bg=active)

        def leave(_event):
            btn.configure(bg=bg)

        btn.bind("<Enter>", enter)
        btn.bind("<Leave>", leave)
        return btn

    def _build(self):
        # Same smooth raster ambience as the polished Shop screen. It stays
        # behind the controls and never changes posting behaviour.
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

        def animate_backdrop():
            if self._destroyed or not self.backdrop.winfo_exists():
                return
            self.wave_offset = (self.wave_offset + 1) % _WAVE_TILE_WIDTH
            x = -self.wave_offset
            for index, item in enumerate(self.wave_items):
                self.backdrop.coords(item, x + index * _WAVE_TILE_WIDTH, 0)
            self._ambient_after_id = self.after(135, animate_backdrop)

        self._ambient_after_id = self.after(135, animate_backdrop)

        outer_pad = 14 if self.embedded else 28
        section_gap = 7 if self.embedded else 9

        if not self.embedded:
            header = tk.Frame(self, bg=BG)
            header.pack(fill="x", padx=28, pady=(18, 6))

            badge = tk.Canvas(header, width=38, height=38, bg=BG, highlightthickness=0, bd=0)
            badge.pack(side="left", padx=(0, 12))
            badge.create_rectangle(3, 3, 35, 35, outline="#35243e", fill="#0b1018", width=1)
            badge.create_text(20, 20, text="♪", fill=ACCENT_2, font=("Segoe UI Symbol", 20, "bold"))
            badge.create_text(17, 17, text="♪", fill=ACCENT, font=("Segoe UI Symbol", 20, "bold"))
            badge.create_text(18.5, 18.5, text="♪", fill=TEXT, font=("Segoe UI Symbol", 18, "bold"))

            brand = tk.Frame(header, bg=BG)
            brand.pack(side="left")
            brand_row = tk.Frame(brand, bg=BG)
            brand_row.pack(anchor="w")
            tk.Label(
                brand_row,
                text="PULSE",
                fg=TEXT,
                bg=BG,
                font=("Segoe UI", 24, "bold"),
            ).pack(side="left")
            tk.Label(
                brand_row,
                text=" TIKTOK",
                fg=ACCENT_2,
                bg=BG,
                font=("Segoe UI", 24, "bold"),
            ).pack(side="left")
            tk.Label(
                brand,
                text="Create, schedule and manage TikTok posts from one workspace.",
                fg=MUTED,
                bg=BG,
                font=("Segoe UI", 9),
            ).pack(anchor="w", pady=(1, 0))
            tk.Label(
                header,
                text="AUTO POST",
                fg=ACCENT,
                bg=BG,
                font=("Segoe UI", 9, "bold"),
            ).pack(side="right", pady=12)

            tk.Frame(self, bg="#2a1834", height=1).pack(fill="x", padx=28, pady=(0, 7))

        connection_shell = tk.Frame(self, bg="#11303a", padx=1, pady=1)
        connection_shell.pack(fill="x", padx=outer_pad, pady=((8 if self.embedded else 0), section_gap))
        connection = tk.Frame(connection_shell, bg=PANEL)
        connection.pack(fill="x")
        tk.Frame(connection, bg=ACCENT_2, width=3).pack(side="left", fill="y")
        tk.Label(
            connection,
            text="●",
            fg=SUCCESS,
            bg=PANEL,
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left", padx=(13, 7), pady=9)
        tk.Label(
            connection,
            text="PULSE BROWSER / TIKTOK",
            fg=MUTED,
            bg=PANEL,
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left", pady=9)
        tk.Frame(connection, bg=BORDER, width=1, height=16).pack(side="left", padx=14)
        tk.Label(
            connection,
            textvariable=self.connection_var,
            fg=TEXT,
            bg=PANEL,
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left", pady=9)
        self._button(
            connection,
            "CONNECT / REFRESH",
            self._connect_tiktok_browser,
            accent=True,
            compact=True,
        ).pack(side="right", padx=10, pady=6)

        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=outer_pad, pady=(0, section_gap))
        top.grid_columnconfigure(0, weight=3, uniform="post")
        top.grid_columnconfigure(1, weight=2, uniform="post")

        compose_shell = tk.Frame(top, bg=SOFT_BORDER, padx=1, pady=1)
        compose_shell.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        compose = tk.Frame(compose_shell, bg="#121827")
        compose.pack(fill="both", expand=True)
        tk.Frame(compose, bg=ACCENT_2, height=2).pack(fill="x")

        compose_head = tk.Frame(compose, bg="#121827")
        compose_head.pack(fill="x", padx=16, pady=(11, 7))
        compose_copy = tk.Frame(compose_head, bg="#121827")
        compose_copy.pack(side="left")
        tk.Label(
            compose_copy,
            text="POST COMPOSER",
            fg=ACCENT_2,
            bg="#121827",
            font=("Segoe UI", 8, "bold"),
        ).pack(anchor="w")
        tk.Label(
            compose_copy,
            text="Build your post",
            fg=TEXT,
            bg="#121827",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w", pady=(1, 0))
        self._button(
            compose_head,
            "😀 EMOJI",
            lambda: open_emoji_picker(
                self.caption,
                on_insert=self._update_chars,
                accent=ACCENT_2,
            ),
            compact=True,
        ).pack(side="right", pady=3)

        caption_meta = tk.Frame(compose, bg="#121827")
        caption_meta.pack(fill="x", padx=16)
        tk.Label(
            caption_meta,
            text="CAPTION",
            fg=MUTED,
            bg="#121827",
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left")
        tk.Label(
            caption_meta,
            textvariable=self.char_var,
            fg=SUBTLE,
            bg="#121827",
            font=("Consolas", 8),
        ).pack(side="right")

        self.caption = tk.Text(
            compose,
            height=3 if self.embedded else 5,
            bg=SURFACE,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            wrap="word",
            padx=12,
            pady=10,
            font=("Segoe UI", 10),
            highlightthickness=1,
            highlightbackground="#1b2738",
        )
        self.caption.pack(fill="x", padx=16, pady=(5, 8))
        self.caption.bind("<KeyRelease>", self._update_chars)

        media_row = tk.Frame(compose, bg="#121827")
        media_row.pack(fill="x", padx=16, pady=(0, 8))
        self._button(media_row, "ADD VIDEO", self._choose_video, compact=True).pack(side="left")
        self._button(media_row, "ADD IMAGES", self._choose_images, compact=True).pack(side="left", padx=(6, 0))
        self._button(media_row, "ADD MUSIC", self._choose_music, compact=True).pack(side="left", padx=(6, 0))
        self._button(media_row, "CLEAR", self._clear_media, compact=True).pack(side="left", padx=(6, 0))

        media_state = tk.Frame(compose, bg=SURFACE, highlightthickness=1, highlightbackground="#1b2738")
        media_state.pack(fill="x", padx=16, pady=(0, 10))
        tk.Label(
            media_state,
            text="MEDIA",
            fg=MUTED,
            bg=SURFACE,
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left", padx=(10, 8), pady=7)
        tk.Label(
            media_state,
            textvariable=self.media_var,
            fg=TEXT,
            bg=SURFACE,
            font=("Segoe UI", 8),
        ).pack(side="left", pady=7)
        tk.Frame(media_state, bg=BORDER, width=1, height=14).pack(side="left", padx=10)
        tk.Label(
            media_state,
            text="SOUND",
            fg=MUTED,
            bg=SURFACE,
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left", pady=7)
        tk.Label(
            media_state,
            textvariable=self.music_var,
            fg=ACCENT,
            bg=SURFACE,
            font=("Segoe UI", 8),
        ).pack(side="left", padx=8, pady=7)
        self._button(media_state, "REMOVE MUSIC", self._clear_music, compact=True).pack(
            side="right", padx=7, pady=4
        )

        settings_shell = tk.Frame(top, bg="#17343d", padx=1, pady=1)
        settings_shell.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=(7, 0))
        options = tk.Frame(settings_shell, bg="#0f1a24")
        options.pack(fill="both", expand=True)
        tk.Frame(options, bg=ACCENT, height=2).pack(fill="x")

        settings_head = tk.Frame(options, bg="#0f1a24")
        settings_head.pack(fill="x", padx=16, pady=(11, 8))
        tk.Label(
            settings_head,
            text="POST SETTINGS",
            fg=ACCENT,
            bg="#0f1a24",
            font=("Segoe UI", 8, "bold"),
        ).pack(anchor="w")
        tk.Label(
            settings_head,
            text="Audience, safety and timing",
            fg=TEXT,
            bg="#0f1a24",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w", pady=(1, 0))

        privacy_row = tk.Frame(options, bg="#0f1a24")
        privacy_row.pack(fill="x", padx=16, pady=(0, 7))
        tk.Label(
            privacy_row,
            text="PRIVACY",
            fg=MUTED,
            bg="#0f1a24",
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left")
        self.privacy_menu = ttk.Combobox(
            privacy_row,
            textvariable=self.privacy_var,
            values=self.privacy_options,
            state="readonly",
            width=21,
            style="TikTok.TCombobox",
        )
        self.privacy_menu.pack(side="right")

        delete_row = tk.Frame(options, bg="#0f1a24")
        delete_row.pack(fill="x", padx=16, pady=(0, 7))
        tk.Label(
            delete_row,
            text="AUTO DELETE",
            fg=MUTED,
            bg="#0f1a24",
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left")
        self.auto_delete_menu = ttk.Combobox(
            delete_row,
            textvariable=self.auto_delete_var,
            values=list(AUTO_DELETE_PRESETS),
            state="readonly",
            width=21,
            style="TikTok.TCombobox",
        )
        self.auto_delete_menu.pack(side="right")

        checks = tk.Frame(options, bg="#0f1a24")
        checks.pack(fill="x", padx=12, pady=(1, 6))
        for label, variable in (
            ("Comments", self.comments_var),
            ("Duet", self.duet_var),
            ("Stitch", self.stitch_var),
            ("Paid partnership", self.brand_content_var),
            ("Own brand promo", self.brand_organic_var),
            ("AI-generated content", self.aigc_var),
        ):
            tk.Checkbutton(
                checks,
                text=label,
                variable=variable,
                bg="#0f1a24",
                fg=TEXT,
                activebackground="#0f1a24",
                activeforeground=TEXT,
                selectcolor=PANEL_2,
                font=("Segoe UI", 8),
            ).pack(anchor="w", pady=0 if self.embedded else 1)

        schedule = tk.Frame(options, bg=SURFACE, highlightthickness=1, highlightbackground="#1b2738")
        schedule.pack(fill="x", padx=16, pady=(1, 6 if self.embedded else 12))
        tk.Radiobutton(
            schedule,
            text="POST IN",
            variable=self.schedule_mode,
            value="delay",
            bg=SURFACE,
            fg=MUTED,
            selectcolor=PANEL_2,
            activebackground=SURFACE,
            activeforeground=TEXT,
            font=("Segoe UI", 8, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=(8, 2), pady=(7, 3))
        tk.Entry(
            schedule,
            textvariable=self.delay_var,
            width=5,
            bg=PANEL_2,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            justify="center",
        ).grid(row=0, column=1, padx=4, pady=(7, 3), ipady=4)
        tk.Label(
            schedule,
            text="minutes",
            fg=MUTED,
            bg=SURFACE,
            font=("Segoe UI", 8),
        ).grid(row=0, column=2, sticky="w", pady=(7, 3))

        tk.Radiobutton(
            schedule,
            text="AT",
            variable=self.schedule_mode,
            value="clock",
            bg=SURFACE,
            fg=MUTED,
            selectcolor=PANEL_2,
            activebackground=SURFACE,
            activeforeground=TEXT,
            font=("Segoe UI", 8, "bold"),
        ).grid(row=1, column=0, sticky="w", padx=(8, 2), pady=(3, 7))
        tk.Entry(
            schedule,
            textvariable=self.clock_var,
            width=7,
            bg=PANEL_2,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            justify="center",
        ).grid(row=1, column=1, padx=4, pady=(3, 7), ipady=4)
        tk.Label(
            schedule,
            text="HH:MM",
            fg=MUTED,
            bg=SURFACE,
            font=("Segoe UI", 8),
        ).grid(row=1, column=2, sticky="w", pady=(3, 7))
        self._button(
            schedule,
            "QUEUE POST",
            self._queue_post,
            accent=True,
            compact=True,
        ).grid(row=0, column=3, rowspan=2, padx=(12, 8), pady=7)

        stats_shell = tk.Frame(self, bg="#23152b", padx=1, pady=1)
        if not self.embedded:
            stats_shell.pack(fill="x", padx=outer_pad, pady=(0, section_gap))
        stats_row = tk.Frame(stats_shell, bg=PANEL)
        stats_row.pack(fill="x")
        tk.Label(
            stats_row,
            text="QUEUE STATUS",
            fg=MUTED,
            bg=PANEL,
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left", padx=(12, 14), pady=8)
        for key, label, colour in (
            ("queued", "QUEUED", ACCENT),
            ("processing", "PROCESSING", "#f0bd70"),
            ("posted", "POSTED", SUCCESS),
            ("error", "ERROR", DANGER),
        ):
            chip = tk.Frame(stats_row, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
            chip.pack(side="left", padx=(0, 7), pady=5)
            tk.Label(
                chip,
                textvariable=self.stats[key],
                fg=colour,
                bg=SURFACE,
                font=("Segoe UI", 9, "bold"),
            ).pack(side="left", padx=(8, 5), pady=3)
            tk.Label(
                chip,
                text=label,
                fg=MUTED,
                bg=SURFACE,
                font=("Segoe UI", 7, "bold"),
            ).pack(side="left", padx=(0, 8), pady=3)
        tk.Label(
            stats_row,
            textvariable=self.next_var,
            fg=SUBTLE,
            bg=PANEL,
            font=("Segoe UI", 8),
        ).pack(side="right", padx=12, pady=8)

        queue_card = tk.Frame(
            top,
            bg=TABLE_BG,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        queue_card.grid(row=1, column=0, sticky="nsew", padx=(0, 7), pady=(7, 0))

        queue_head = tk.Frame(queue_card, bg=PANEL)
        queue_head.grid(row=0, column=0, columnspan=2, sticky="ew")
        tk.Label(
            queue_head,
            text="POST QUEUE",
            fg=TEXT,
            bg=PANEL,
            font=("Segoe UI", 10, "bold"),
        ).pack(side="left", padx=12, pady=9)
        tk.Label(
            queue_head,
            text="Scheduled posts and delivery state",
            fg=SUBTLE,
            bg=PANEL,
            font=("Segoe UI", 8),
        ).pack(side="left")
        self._button(queue_head, "START", self.start, accent=True, compact=True).pack(
            side="right", padx=(6, 10), pady=5
        )
        self._button(queue_head, "STOP", self.stop, danger=True, compact=True).pack(
            side="right", padx=(6, 0), pady=5
        )
        self._button(queue_head, "REMOVE", self._remove_selected, compact=True).pack(
            side="right", pady=5
        )

        cols = ("due", "status", "privacy", "delete", "media", "music", "caption")
        self.tree = ttk.Treeview(
            queue_card,
            columns=cols,
            show="headings",
            style="TikTok.Treeview",
            height=1 if self.embedded else 3,
        )
        widths = {
            "due": 130,
            "status": 105,
            "privacy": 120,
            "delete": 120,
            "media": 170,
            "music": 190,
            "caption": 340,
        }
        for col in cols:
            self.tree.heading(col, text=col.upper())
            self.tree.column(col, width=widths[col], anchor="w", stretch=(col == "caption"))
        self.tree.tag_configure("posted", foreground=SUCCESS)
        self.tree.tag_configure("deleted", foreground=MUTED)
        self.tree.tag_configure("error", foreground=DANGER)
        self.tree.tag_configure("processing", foreground=ACCENT)
        queue_scroll = ttk.Scrollbar(
            queue_card,
            orient="vertical",
            command=self.tree.yview,
            style="TikTok.Vertical.TScrollbar",
        )
        queue_xscroll = ttk.Scrollbar(
            queue_card,
            orient="horizontal",
            command=self.tree.xview,
            style="TikTok.Horizontal.TScrollbar",
        )
        self.tree.configure(
            yscrollcommand=queue_scroll.set,
            xscrollcommand=queue_xscroll.set,
        )
        queue_card.rowconfigure(1, weight=1)
        queue_card.columnconfigure(0, weight=1)
        self.tree.grid(row=1, column=0, sticky="nsew")
        queue_scroll.grid(row=1, column=1, sticky="ns")
        queue_xscroll.grid(row=2, column=0, columnspan=2, sticky="ew")

        activity = tk.Frame(self, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        activity.pack(
            fill="both" if self.embedded else "x",
            expand=self.embedded,
            padx=outer_pad,
            pady=(0, 8 if self.embedded else 14),
        )
        if self.embedded:
            activity.configure(height=108)
            activity.pack_propagate(False)
        activity_head = tk.Frame(activity, bg=PANEL)
        activity_head.pack(
            fill="x",
            padx=12,
            pady=((6, 3) if self.embedded else (8, 5)),
        )
        tk.Label(
            activity_head,
            text="ACTIVITY",
            fg=TEXT,
            bg=PANEL,
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left")
        tk.Label(
            activity_head,
            text="Browser, queue and posting events",
            fg=SUBTLE,
            bg=PANEL,
            font=("Segoe UI", 8),
        ).pack(side="left", padx=(10, 0))
        if self.embedded:
            tk.Label(
                activity_head,
                textvariable=self.next_var,
                fg=SUBTLE,
                bg=PANEL,
                font=("Segoe UI", 8),
            ).pack(side="right", padx=(0, 12))
        tk.Label(
            activity_head,
            textvariable=self.status_var,
            fg=ACCENT,
            bg=PANEL,
            font=("Segoe UI", 8, "bold"),
        ).pack(side="right")

        log_body = tk.Frame(activity, bg=PANEL)
        log_body.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        self.log = tk.Text(
            log_body,
            height=3 if self.embedded else 3,
            bg=SURFACE,
            fg="#cbd3df",
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            wrap="word",
            padx=11,
            pady=8,
            font=("Consolas", 8),
            highlightthickness=1,
            highlightbackground="#1b2738",
        )
        activity_scroll = ttk.Scrollbar(
            log_body,
            orient="vertical",
            command=self.log.yview,
            style="TikTok.Vertical.TScrollbar",
        )
        self.log.configure(yscrollcommand=activity_scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        activity_scroll.pack(side="right", fill="y")

    def _update_chars(self, *_):
        value = self.caption.get("1.0", "end-1c")
        count = len(value.encode("utf-16-le")) // 2
        self.char_var.set(f"{count} / {MAX_CAPTION_UTF16}")

    def _choose_video(self):
        path = filedialog.askopenfilename(
            parent=self.winfo_toplevel(),
            title="Choose TikTok video",
            filetypes=[
                ("Videos", "*.mp4 *.mov *.m4v *.webm *.avi *.mkv"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.selected_media = [str(path)]
            self.media_var.set(f"VIDEO // {Path(path).name}")

    def _choose_images(self):
        paths = filedialog.askopenfilenames(
            parent=self.winfo_toplevel(),
            title="Choose TikTok images",
            filetypes=[
                ("Images", "*.jpg *.jpeg *.png *.webp"),
                ("All files", "*.*"),
            ],
        )
        if paths:
            self.selected_media = [str(path) for path in paths]
            names = [Path(path).name for path in self.selected_media]
            preview = ", ".join(names[:3])
            if len(names) > 3:
                preview += f" +{len(names) - 3} more"
            self.media_var.set(f"IMAGES {len(names)} // {preview}")

    def _clear_media(self):
        self.selected_media = []
        self.media_var.set("NO MEDIA")

    def _choose_music(self):
        if not self.selected_media:
            messagebox.showinfo(
                "TikTok sound",
                "Add the image/video first, then choose music. TikTok only exposes "
                "the post sound picker after media is loaded.",
                parent=self.winfo_toplevel(),
            )
            return

        dialog = tk.Toplevel(self.winfo_toplevel())
        dialog.title("Choose TikTok sound")
        dialog.configure(bg=PANEL)
        dialog.resizable(False, False)
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()

        search_var = tk.StringVar(value=self.music_search or self.music_query)
        result_var = tk.StringVar()
        status_var = tk.StringVar(value="Type a phrase, then search TikTok.")

        tk.Label(
            dialog,
            text="LIVE TIKTOK SOUND SEARCH",
            fg=ACCENT,
            bg=PANEL,
            font=("Consolas", 9, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=18, pady=(16, 4))

        tk.Label(
            dialog,
            text=(
                "Pulse loads your selected media into TikTok's real post sound picker, "
                "then returns the exact sounds TikTok offers for that post."
            ),
            fg=TEXT,
            bg=PANEL,
            justify="left",
            wraplength=520,
            font=("Segoe UI", 9),
        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=18, pady=(0, 12))

        search_entry = tk.Entry(
            dialog,
            textvariable=search_var,
            width=48,
            bg=PANEL_3,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=("Segoe UI", 10),
        )
        search_entry.grid(row=2, column=0, columnspan=2, sticky="ew", padx=(18, 8), pady=4, ipady=6)

        results_box = ttk.Combobox(
            dialog,
            textvariable=result_var,
            values=(),
            state="readonly",
            width=66,
        )
        results_box.grid(row=3, column=0, columnspan=3, sticky="ew", padx=18, pady=(10, 4))

        tk.Label(
            dialog,
            textvariable=status_var,
            fg=MUTED,
            bg=PANEL,
            font=("Consolas", 8),
        ).grid(row=4, column=0, columnspan=3, sticky="w", padx=18, pady=(2, 10))

        search_button = self._button(dialog, "SEARCH TIKTOK", lambda: None, accent=True, compact=True)
        search_button.grid(row=2, column=2, padx=(0, 18), pady=4)

        result_holder: dict[str, list[str]] = {"items": []}

        def apply_results(query: str, results: list[str]) -> None:
            if not dialog.winfo_exists():
                return
            result_holder["items"] = results
            results_box.configure(values=results)
            if results:
                result_var.set(results[0])
                status_var.set(f"{len(results)} sound(s) found for \"{query}\". Pick one below.")
            else:
                result_var.set("")
                status_var.set("No sounds found.")
            search_button.configure(state="normal")

        def apply_error(message: str) -> None:
            if not dialog.winfo_exists():
                return
            result_holder["items"] = []
            results_box.configure(values=())
            result_var.set("")
            status_var.set(message)
            search_button.configure(state="normal")

        def search_worker(query: str) -> None:
            try:
                results = search_tiktok_sounds(
                    query,
                    media_paths=list(self.selected_media),
                    log=self.write,
                )
                self.after(0, lambda q=query, r=results: apply_results(q, r))
            except Exception as exc:
                message = str(exc)
                self.write(f"SOUND SEARCH ERROR | {message}")
                self.after(0, lambda msg=message: apply_error(msg))

        def run_search(*_):
            query = search_var.get().strip()
            if not query:
                status_var.set("Type something to search for first.")
                return
            search_button.configure(state="disabled")
            status_var.set(f'Loading media + searching TikTok for "{query}"...')
            threading.Thread(target=search_worker, args=(query,), daemon=True).start()

        search_button.configure(command=run_search)

        preview_button = self._button(
            dialog,
            "▶ PREVIEW",
            lambda: None,
            compact=True,
        )
        preview_button.grid(row=5, column=0, sticky="w", padx=(18, 6), pady=(4, 16))

        stop_preview_button = self._button(
            dialog,
            "■ STOP",
            lambda: None,
            danger=True,
            compact=True,
        )
        stop_preview_button.grid(row=5, column=1, sticky="w", padx=(0, 6), pady=(4, 16))

        def apply_preview_status(message: str) -> None:
            if not dialog.winfo_exists():
                return
            status_var.set(message)
            preview_button.configure(state="normal")
            stop_preview_button.configure(state="normal")

        def preview_worker(selection: str, query: str) -> None:
            try:
                preview_tiktok_sound(
                    selection,
                    query,
                    list(self.selected_media),
                    log=self.write,
                )
                self.after(
                    0,
                    lambda name=selection: apply_preview_status(
                        f'Playing "{name}" in Brave. Try another or USE SELECTED.'
                    ),
                )
            except Exception as exc:
                message = str(exc)
                self.write(f"SOUND PREVIEW ERROR | {message}")
                self.after(0, lambda msg=message: apply_preview_status(msg))

        def run_preview():
            selection = result_var.get().strip()
            query = search_var.get().strip()
            if not selection:
                status_var.set("Choose a sound from the dropdown first.")
                return
            preview_button.configure(state="disabled")
            stop_preview_button.configure(state="disabled")
            status_var.set(f'Loading preview for "{selection}"...')
            threading.Thread(
                target=preview_worker,
                args=(selection, query),
                daemon=True,
            ).start()

        def stop_preview():
            def worker():
                stop_tiktok_sound_preview(log=self.write)
                self.after(
                    0,
                    lambda: apply_preview_status("Preview stopped."),
                )

            preview_button.configure(state="disabled")
            stop_preview_button.configure(state="disabled")
            threading.Thread(target=worker, daemon=True).start()

        def close_dialog():
            threading.Thread(
                target=stop_tiktok_sound_preview,
                kwargs={"log": self.write},
                daemon=True,
            ).start()
            dialog.destroy()

        def use_selected_and_close():
            selected = result_var.get().strip()
            query = search_var.get().strip()
            if not selected:
                status_var.set("Choose one of the TikTok results first.")
                return
            self.music_query = selected
            self.music_search = query
            self.music_var.set(f"TIKTOK SOUND // {selected}")
            self.write(f'TIKTOK SOUND CHOSEN | "{selected}" | search "{query}"')
            threading.Thread(
                target=stop_tiktok_sound_preview,
                kwargs={"log": self.write},
                daemon=True,
            ).start()
            dialog.destroy()

        preview_button.configure(command=run_preview)
        stop_preview_button.configure(command=stop_preview)

        actions = tk.Frame(dialog, bg=PANEL)
        actions.grid(row=5, column=2, sticky="e", padx=(6, 18), pady=(4, 16))
        self._button(actions, "CANCEL", close_dialog, compact=True).pack(side="right")
        self._button(
            actions,
            "USE SELECTED",
            use_selected_and_close,
            accent=True,
            compact=True,
        ).pack(side="right", padx=(0, 8))

        search_entry.focus_set()
        search_entry.bind("<Return>", run_search)
        dialog.bind("<Escape>", lambda _event: close_dialog())
        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        self.wait_window(dialog)

    def _clear_music(self):
        self.music_query = ""
        self.music_search = ""
        self.music_var.set("NO MUSIC")

    def _connect_tiktok_browser(self):
        ok, message = open_tiktok_browser()
        self.connection_var.set(tiktok_browser_status())
        if ok:
            self.write(f"TIKTOK BROWSER | {message}")
            return
        messagebox.showerror("TikTok Browser", message, parent=self.winfo_toplevel())

    def _ensure_local_credentials(self) -> bool:
        """One-time maintainer bootstrap hidden behind CONNECT TIKTOK.

        Normal/customer builds use the hosted Pulse backend and never see this.
        """
        if load_app_credentials():
            return True

        dialog = tk.Toplevel(self.winfo_toplevel())
        dialog.title("Connect TikTok")
        dialog.configure(bg=PANEL)
        dialog.resizable(False, False)
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()

        tk.Label(
            dialog,
            text="ONE-TIME PULSE SETUP",
            fg=ACCENT,
            bg=PANEL,
            font=("Consolas", 9, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=18, pady=(16, 4))
        tk.Label(
            dialog,
            text=(
                "This development PC needs the Pulse TikTok app credentials once. "
                "They are encrypted on this Windows account. People you send Pulse to "
                "will only press CONNECT TIKTOK."
            ),
            fg=TEXT,
            bg=PANEL,
            justify="left",
            wraplength=460,
            font=("Segoe UI", 9),
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=18, pady=(0, 14))

        key_var = tk.StringVar()
        secret_var = tk.StringVar()
        tk.Label(dialog, text="CLIENT KEY", fg=MUTED, bg=PANEL, font=("Consolas", 8, "bold")).grid(
            row=2, column=0, sticky="w", padx=(18, 10), pady=6
        )
        key_entry = tk.Entry(
            dialog,
            textvariable=key_var,
            width=48,
            bg=PANEL_3,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
        )
        key_entry.grid(row=2, column=1, sticky="ew", padx=(0, 18), pady=6, ipady=5)

        tk.Label(dialog, text="CLIENT SECRET", fg=MUTED, bg=PANEL, font=("Consolas", 8, "bold")).grid(
            row=3, column=0, sticky="w", padx=(18, 10), pady=6
        )
        secret_entry = tk.Entry(
            dialog,
            textvariable=secret_var,
            width=48,
            show="•",
            bg=PANEL_3,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
        )
        secret_entry.grid(row=3, column=1, sticky="ew", padx=(0, 18), pady=6, ipady=5)

        result = {"ok": False}

        def save_and_close():
            try:
                save_app_credentials(
                    key_var.get(),
                    secret_var.get(),
                    DEFAULT_REDIRECT_URI,
                )
            except Exception as exc:
                messagebox.showerror("TikTok setup", str(exc), parent=dialog)
                return
            result["ok"] = True
            dialog.destroy()

        actions = tk.Frame(dialog, bg=PANEL)
        actions.grid(row=4, column=0, columnspan=2, sticky="e", padx=18, pady=(10, 16))
        self._button(actions, "CANCEL", dialog.destroy, compact=True).pack(side="right")
        self._button(actions, "SAVE & CONNECT", save_and_close, accent=True, compact=True).pack(
            side="right", padx=(0, 8)
        )

        key_entry.focus_set()
        dialog.bind("<Return>", lambda _event: save_and_close())
        self.wait_window(dialog)
        return bool(result["ok"])


    def _set_app_credentials(self):
        current = connection_status()
        client_key = simpledialog.askstring(
            "TikTok Client Key",
            "Enter the Client Key from TikTok for Developers.",
            parent=self.winfo_toplevel(),
        )
        if not client_key:
            return

        client_secret = simpledialog.askstring(
            "TikTok Client Secret",
            "Enter the Client Secret from TikTok for Developers.\n\n"
            "Development mode: Pulse encrypts it with Windows DPAPI on this PC. "
            "A public Pulse release should move this secret to a backend service.",
            show="•",
            parent=self.winfo_toplevel(),
        )
        if not client_secret:
            return

        redirect_uri = simpledialog.askstring(
            "TikTok Redirect URI",
            "Enter the Desktop Login Kit redirect URI registered in TikTok.\n\n"
            "Default:",
            initialvalue=str(current.get("redirect_uri") or DEFAULT_REDIRECT_URI),
            parent=self.winfo_toplevel(),
        )
        if not redirect_uri:
            return

        try:
            save_app_credentials(client_key, client_secret, redirect_uri)
            self._refresh_connection_label()
            self.write(f"APP READY | redirect {redirect_uri}")
            if local_backend_enabled():
                threading.Thread(target=self._probe_backend_worker, daemon=True).start()
        except Exception as exc:
            messagebox.showerror("TikTok app setup", str(exc), parent=self.winfo_toplevel())

    def _connect_tiktok(self):
        # On our development machine, CONNECT TIKTOK performs the one-time
        # credential bootstrap itself. Customer builds use the hosted Pulse
        # backend, so end users never see this step.
        if not backend_enabled() and not self._ensure_local_credentials():
            self.connection_var.set("NOT CONNECTED")
            return

        if not app_credentials_configured():
            messagebox.showinfo(
                "TikTok",
                "TikTok is not ready on this build yet. Ask the Pulse administrator to configure the TikTok connection service.",
                parent=self.winfo_toplevel(),
            )
            return
        if self.oauth_worker and self.oauth_worker.is_alive():
            self.connection_var.set("CONNECTING...")
            return

        self.connection_var.set("CONNECTING...")
        self.status_var.set("AUTHORIZING")
        self.oauth_worker = threading.Thread(target=self._oauth_connect_worker, daemon=True)
        self.oauth_worker.start()

    def _oauth_connect_worker(self):
        try:
            if backend_enabled():
                if local_backend_enabled():
                    ok, detail = ensure_local_backend(log=self.write)
                else:
                    ok, detail = backend_health()
                if not ok:
                    raise RuntimeError(detail)
            connect(log=self.write)
            info = query_creator_info()
            self.after(0, lambda: self._apply_creator_info(info))
        except Exception as exc:
            message = str(exc)
            self.write(f"CONNECTION ERROR | {message}")
            self.after(0, lambda msg=message: self._oauth_error(msg))

    def _oauth_error(self, message: str):
        if self._destroyed:
            return
        self.connection_var.set("CONNECTION ERROR")
        self.status_var.set("STOPPED")
        messagebox.showerror("TikTok connection", message, parent=self.winfo_toplevel())

    def _apply_creator_info(self, info: dict):
        if self._destroyed:
            return
        # Browser posting uses the human-facing TikTok audience choices.
        # Keep these stable even if the legacy API returns internal privacy codes.
        self.privacy_options = ["PUBLIC", "FRIENDS", "PRIVATE"]
        self.privacy_menu.configure(values=self.privacy_options)
        if self.privacy_var.get() not in self.privacy_options:
            self.privacy_var.set("PUBLIC")

        # TikTok can disable these creator capabilities; reflect that immediately.
        if info.get("comment_disabled"):
            self.comments_var.set(False)
        if info.get("duet_disabled"):
            self.duet_var.set(False)
        if info.get("stitch_disabled"):
            self.stitch_var.set(False)

        nickname = info.get("creator_nickname") or info.get("creator_username") or "CONNECTED"
        self.connection_var.set(str(nickname).upper())
        self.status_var.set("STOPPED")
        self.write(f"CONNECTED | {nickname} | privacy: {', '.join(self.privacy_options)}")

    def _disconnect_tiktok(self):
        disconnect()
        if backend_enabled():
            self.connection_var.set("READY TO CONNECT")
        else:
            self.connection_var.set("READY TO CONNECT" if app_credentials_configured() else "NOT CONNECTED")
        self.privacy_options = ["PUBLIC", "FRIENDS", "PRIVATE"]
        self.privacy_menu.configure(values=self.privacy_options)
        self.privacy_var.set("PUBLIC")
        self.write("TIKTOK DISCONNECTED")

    def _refresh_connection_label(self):
        self.connection_var.set(tiktok_browser_status())

    def _probe_backend(self):
        if self._destroyed or not backend_enabled():
            return
        threading.Thread(target=self._probe_backend_worker, daemon=True).start()

    def _probe_backend_worker(self):
        if local_backend_enabled():
            ok, detail = ensure_local_backend(log=self.write)
        else:
            ok, detail = backend_health()

        def apply():
            if self._destroyed:
                return
            self.connection_var.set("READY TO CONNECT" if ok else "SERVICE OFFLINE")
            if not ok:
                self.write(f"TIKTOK SERVICE | {detail}")

        try:
            self.after(0, apply)
        except tk.TclError:
            pass

    def _test_connection(self):
        state = connection_status()
        if not state.get("connected"):
            messagebox.showinfo(
                "TikTok",
                "Connect TikTok first.",
                parent=self.winfo_toplevel(),
            )
            return
        if self.oauth_worker and self.oauth_worker.is_alive():
            return

        self.connection_var.set("CHECKING...")
        self.oauth_worker = threading.Thread(target=self._test_connection_worker, daemon=True)
        self.oauth_worker.start()

    def _test_connection_worker(self):
        try:
            info = query_creator_info()
            self.after(0, lambda: self._apply_creator_info(info))
        except Exception as exc:
            message = str(exc)
            self.write(f"CONNECTION ERROR | {message}")
            self.after(0, lambda msg=message: self._oauth_error(msg))

    def _delete_after_minutes(self) -> int:
        return int(AUTO_DELETE_PRESETS.get(self.auto_delete_var.get(), 0))

    def _due_time(self) -> tuple[datetime, str]:
        now = datetime.now()
        if self.schedule_mode.get() == "clock":
            try:
                hour_text, minute_text = self.clock_var.get().strip().split(":", 1)
                hour = int(hour_text)
                minute = int(minute_text)
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError
            except ValueError as exc:
                raise ValueError("Enter a 24-hour time in HH:MM format.") from exc
            due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if due <= now:
                due += timedelta(days=1)
            return due, f"AT {due:%H:%M}"

        try:
            minutes = int(self.delay_var.get())
            if minutes < 0:
                raise ValueError
        except ValueError as exc:
            raise ValueError("Post delay must be 0 or more whole minutes.") from exc
        due = now + timedelta(minutes=minutes)
        return due, f"IN {minutes}m"

    def _queue_post(self):
        if not self.selected_media:
            messagebox.showerror(
                "TikTok",
                "Choose a video or one/more images first.",
                parent=self.winfo_toplevel(),
            )
            return
        try:
            due, note = self._due_time()
            caption = self.caption.get("1.0", "end-1c")
            delete_after_minutes = self._delete_after_minutes()
            if delete_after_minutes > 0 and not caption.strip():
                raise ValueError(
                    "Auto delete needs a caption so Pulse can identify the exact TikTok post safely."
                )
            item = add_post(
                caption,
                due,
                self.selected_media,
                privacy_level=self.privacy_var.get(),
                disable_comment=not self.comments_var.get(),
                disable_duet=not self.duet_var.get(),
                disable_stitch=not self.stitch_var.get(),
                brand_content_toggle=self.brand_content_var.get(),
                brand_organic_toggle=self.brand_organic_var.get(),
                is_aigc=self.aigc_var.get(),
                music_query=self.music_query,
                music_search=self.music_search,
                delete_after_minutes=delete_after_minutes,
            )
        except Exception as exc:
            messagebox.showerror("TikTok queue", str(exc), parent=self.winfo_toplevel())
            return

        media = item_media_paths(item)
        image_count = sum(
            1 for path in media if Path(path).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        )
        media_note = (
            f"IMAGES {image_count}"
            if image_count
            else f"VIDEO {Path(media[0]).name if media else '<missing>'}"
        )
        sound_note = f' | SOUND "{item.music_query}"' if item.music_query else ""
        delete_note = (
            f" | AUTO DELETE {self.auto_delete_var.get()}"
            if item.delete_after_minutes > 0
            else ""
        )
        self.write(
            f"QUEUED | {note} | due {due:%d/%m %H:%M} | "
            f"{item.privacy_level}{delete_note} | {media_note}{sound_note} | "
            f"{item.caption[:100]}"
        )
        self.caption.delete("1.0", tk.END)
        self._clear_media()
        self._clear_music()
        self._update_chars()
        self.refresh()

    def _remove_selected(self):
        selected = self.tree.selection()
        if not selected:
            self.status_var.set("SELECT A POST")
            return
        item = self.mapping.get(selected[0])
        if item:
            remove_post(item.post_id)
            media = item_media_paths(item)
            media_name = Path(media[0]).name if media else "media"
            self.write(f"REMOVED | {item.caption[:80] or media_name}")
            self.refresh()

    def start(self):
        if self.worker and self.worker.is_alive():
            self.status_var.set("RUNNING")
            return
        self.stop_event.clear()
        self.worker = threading.Thread(
            target=run_scheduler,
            args=(self.stop_event, self.write),
            daemon=True,
        )
        self.worker.start()
        self.status_var.set("RUNNING")

    def stop(self):
        self.stop_event.set()
        self.status_var.set("STOPPED")

    def write(self, message: str):
        def apply():
            if self._destroyed or not self.winfo_exists():
                return
            self.log.insert(tk.END, message + "\n")
            self.log.see(tk.END)
            self.refresh()

        try:
            self.after(0, apply)
        except tk.TclError:
            pass

    def refresh(self):
        if self._destroyed:
            return
        selected = self.tree.selection()
        selected_id = self.mapping.get(selected[0]).post_id if selected and selected[0] in self.mapping else None

        items = load_queue()
        self.mapping.clear()
        for iid in self.tree.get_children():
            self.tree.delete(iid)

        counts = {"queued": 0, "processing": 0, "posted": 0, "error": 0}
        next_due = None
        pick = None

        for item in items:
            status = item.status.lower()
            if status in counts:
                counts[status] += 1
            elif status == "deleted":
                counts["posted"] += 1
            elif status == "delete_error":
                counts["error"] += 1
            try:
                due_dt = datetime.fromisoformat(item.due_at)
                due_text = due_dt.strftime("%d/%m/%Y %H:%M")
                if status == "queued" and (next_due is None or due_dt < next_due):
                    next_due = due_dt
            except ValueError:
                due_text = item.due_at

            iid = self.tree.insert(
                "",
                "end",
                values=(
                    due_text,
                    status.upper(),
                    item.privacy_level,
                    (
                        "DELETED"
                        if status == "deleted"
                        else "DELETE ERROR"
                        if status == "delete_error"
                        else (
                            datetime.fromisoformat(item.delete_due_at).strftime("%d/%m %H:%M")
                            if item.delete_due_at
                            else "OFF"
                        )
                    ),
                    (
                        f"{len(item_media_paths(item))} IMAGES"
                        if len(item_media_paths(item)) > 1
                        else (
                            Path(item_media_paths(item)[0]).name
                            if item_media_paths(item)
                            else "<missing>"
                        )
                    ),
                    item.music_query or "NONE",
                    item.caption.replace("\n", " "),
                ),
                tags=(
                    "error"
                    if status == "delete_error"
                    else status
                    if status in {"posted", "processing", "error", "deleted"}
                    else "",
                ),
            )
            self.mapping[iid] = item
            if item.post_id == selected_id:
                pick = iid

        if pick:
            self.tree.selection_set(pick)

        for key, value in counts.items():
            self.stats[key].set(str(value))
        self.next_var.set(f"NEXT // {next_due:%H:%M}" if next_due else "No posts queued")

    def _on_destroy(self, event):
        if event.widget is self:
            self._destroyed = True
            self.stop_event.set()
            if getattr(self, "_ambient_after_id", None) is not None:
                try:
                    self.after_cancel(self._ambient_after_id)
                except tk.TclError:
                    pass
                self._ambient_after_id = None


def open_auto_post_window(parent: tk.Misc) -> tk.Toplevel:
    window = tk.Toplevel(parent)
    window.title("Pulse Social — TikTok Auto Post")
    window.geometry("1180x800")
    window.minsize(980, 700)
    window.configure(bg=BG)

    view = TikTokAutoPostView(window)
    view.pack(fill="both", expand=True)

    def close():
        view.stop()
        window.destroy()

    window.protocol("WM_DELETE_WINDOW", close)
    return window
