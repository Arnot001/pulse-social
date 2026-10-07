from __future__ import annotations

import math
import threading
import tkinter as tk
from pathlib import Path
from datetime import datetime, timedelta
from tkinter import filedialog, messagebox, ttk

from platforms.common.emoji_picker import open_emoji_picker

from .auto_post import add_post, load_queue, remove_post, run_scheduler
from .browser_session import browser_status

BG = "#06070b"
SURFACE = "#0b0f17"
PANEL = "#101622"
PANEL_2 = "#151d2c"
PANEL_3 = "#0a0e15"
BORDER = "#242f43"
TEXT = "#f7f8fb"
MUTED = "#8e9aae"
ACCENT = "#ff0a8a"
ACCENT_2 = "#ff4bb0"
SUCCESS = "#35d07f"
WARNING = "#f0b85a"
DANGER = "#ff4d67"
SOFT_BORDER = "#3b2944"
SUBTLE = "#65758b"
TABLE_BG = "#0b111b"

_WAVE_TILE_WIDTH = 900
_WAVE_TILE_HEIGHT = 820
_WAVE_PPM_CACHE = None


def _wave_ppm():
    """Smooth local raster ambience matching the polished Pulse Social surfaces."""
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
                145 + 34 * math.sin(t + 0.35) + 12 * math.sin(t * 0.48 + 1.1),
                435 + 48 * math.sin(t * 0.82 + 1.9) + 18 * math.sin(t * 0.36 - 0.5),
                710 + 38 * math.sin(t * 1.05 + 3.0) + 14 * math.sin(t * 0.50 + 0.8),
            )
        )

    def gaussian_lookup(sigma):
        return [math.exp(-((distance / sigma) ** 2)) for distance in range(height + 1)]

    g1 = gaussian_lookup(88.0)
    g2 = gaussian_lookup(110.0)
    g3 = gaussian_lookup(94.0)
    pixels = bytearray(width * height * 3)
    index = 0
    for y in range(height):
        vertical = (1.0 - y / height) * 1.6
        for x in range(width):
            c1, c2, c3 = centers[x]
            a = g1[min(height, int(abs(y - c1)))]
            b = g2[min(height, int(abs(y - c2)))]
            d = g3[min(height, int(abs(y - c3)))]
            pixels[index] = min(255, int(base[0] + vertical + 44 * a + 18 * b + 38 * d))
            pixels[index + 1] = min(255, int(base[1] + vertical + 4 * a + 9 * b + 3 * d))
            pixels[index + 2] = min(255, int(base[2] + vertical + 35 * a + 46 * b + 28 * d))
            index += 3

    _WAVE_PPM_CACHE = f"P6\n{width} {height}\n255\n".encode("ascii") + bytes(pixels)
    return _WAVE_PPM_CACHE


def open_auto_post_window(parent: tk.Misc) -> tk.Toplevel:
    window = tk.Toplevel(parent)
    window.title("Pulse Social — X Auto Post")
    window.geometry("1180x800")
    window.minsize(980, 700)
    window.configure(bg=BG)

    stop_event = threading.Event()
    worker = [None]
    status = tk.StringVar(value="STOPPED")
    browser_var = tk.StringVar(value=browser_status())
    char_var = tk.StringVar(value="0 chars")
    media_var = tk.StringVar(value="NO MEDIA")
    selected_media: list[str] = []
    next_var = tk.StringVar(value="No posts queued")
    schedule_mode = tk.StringVar(value="delay")
    clock_time = tk.StringVar(value=(datetime.now() + timedelta(minutes=5)).strftime("%H:%M"))
    stats_var = {
        "queued": tk.StringVar(value="0"),
        "posted": tk.StringVar(value="0"),
        "error": tk.StringVar(value="0"),
    }

    style = ttk.Style(window)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(
        "Pulse.Treeview",
        background=TABLE_BG,
        fieldbackground=TABLE_BG,
        foreground=TEXT,
        rowheight=31,
        borderwidth=0,
        font=("Segoe UI", 9),
    )
    style.map(
        "Pulse.Treeview",
        background=[("selected", "#34203b")],
        foreground=[("selected", TEXT)],
    )
    style.configure(
        "Pulse.Treeview.Heading",
        background="#141c2a",
        foreground=MUTED,
        relief="flat",
        borderwidth=0,
        font=("Segoe UI", 8, "bold"),
        padding=(8, 9),
    )
    for scrollbar_style in ("Pulse.Vertical.TScrollbar", "Pulse.Horizontal.TScrollbar"):
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

    def button(parent, text, command, accent=False, danger=False, compact=False):
        if accent:
            bg, active, border = ACCENT, ACCENT_2, "#ff5abb"
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
        btn.bind("<Enter>", lambda _event: btn.configure(bg=active))
        btn.bind("<Leave>", lambda _event: btn.configure(bg=bg))
        return btn

    # Ambient Pulse backdrop.
    backdrop = tk.Canvas(window, bg=BG, highlightthickness=0, bd=0)
    backdrop.place(x=0, y=0, relwidth=1, relheight=1)
    wave_photo = tk.PhotoImage(data=_wave_ppm(), format="PPM")
    backdrop.wave_photo = wave_photo
    wave_items = [
        backdrop.create_image(0, 0, image=wave_photo, anchor="nw"),
        backdrop.create_image(_WAVE_TILE_WIDTH, 0, image=wave_photo, anchor="nw"),
        backdrop.create_image(_WAVE_TILE_WIDTH * 2, 0, image=wave_photo, anchor="nw"),
    ]
    wave_offset = [0]
    ambient_after = [None]

    def animate_backdrop():
        if not backdrop.winfo_exists():
            return
        wave_offset[0] = (wave_offset[0] + 1) % _WAVE_TILE_WIDTH
        x = -wave_offset[0]
        for index, item in enumerate(wave_items):
            backdrop.coords(item, x + index * _WAVE_TILE_WIDTH, 0)
        ambient_after[0] = window.after(140, animate_backdrop)

    ambient_after[0] = window.after(140, animate_backdrop)

    # HERO
    hero = tk.Frame(window, bg=BG)
    hero.pack(fill="x", padx=28, pady=(18, 6))

    badge = tk.Canvas(hero, width=38, height=38, bg=BG, highlightthickness=0, bd=0)
    badge.pack(side="left", padx=(0, 12))
    badge.create_rectangle(3, 3, 35, 35, outline="#35243e", fill="#0b1018", width=1)
    badge.create_text(19, 19, text="X", fill=TEXT, font=("Segoe UI", 17, "bold"))

    brand = tk.Frame(hero, bg=BG)
    brand.pack(side="left")
    brand_row = tk.Frame(brand, bg=BG)
    brand_row.pack(anchor="w")
    tk.Label(brand_row, text="PULSE", fg=TEXT, bg=BG, font=("Segoe UI", 24, "bold")).pack(side="left")
    tk.Label(brand_row, text=" X", fg=ACCENT, bg=BG, font=("Segoe UI", 24, "bold")).pack(side="left")
    tk.Label(
        brand,
        text="Create, schedule and manage X posts from one workspace.",
        fg=MUTED,
        bg=BG,
        font=("Segoe UI", 9),
    ).pack(anchor="w", pady=(1, 0))
    tk.Label(
        hero,
        text="AUTO POST",
        fg=ACCENT,
        bg=BG,
        font=("Segoe UI", 9, "bold"),
    ).pack(side="right", pady=12)

    tk.Frame(window, bg="#2a1834", height=1).pack(fill="x", padx=28, pady=(0, 7))

    connection_shell = tk.Frame(window, bg="#351431", padx=1, pady=1)
    connection_shell.pack(fill="x", padx=28, pady=(0, 9))
    connection = tk.Frame(connection_shell, bg=PANEL)
    connection.pack(fill="x")
    tk.Frame(connection, bg=ACCENT, width=3).pack(side="left", fill="y")
    tk.Label(connection, text="●", fg=SUCCESS, bg=PANEL, font=("Segoe UI", 9, "bold")).pack(
        side="left", padx=(13, 7), pady=9
    )
    tk.Label(
        connection,
        text="PULSE BROWSER / X",
        fg=MUTED,
        bg=PANEL,
        font=("Segoe UI", 8, "bold"),
    ).pack(side="left", pady=9)
    tk.Frame(connection, bg=BORDER, width=1, height=16).pack(side="left", padx=14)
    tk.Label(
        connection,
        textvariable=browser_var,
        fg=TEXT,
        bg=PANEL,
        font=("Segoe UI", 9, "bold"),
    ).pack(side="left", pady=9)
    tk.Label(
        connection,
        textvariable=status,
        fg=ACCENT,
        bg=PANEL,
        font=("Segoe UI", 8, "bold"),
    ).pack(side="right", padx=13, pady=9)

    # TOP GRID
    top = tk.Frame(window, bg=BG)
    top.pack(fill="x", padx=28, pady=(0, 9))
    top.grid_columnconfigure(0, weight=3, uniform="xpost")
    top.grid_columnconfigure(1, weight=2, uniform="xpost")

    compose_shell = tk.Frame(top, bg=SOFT_BORDER, padx=1, pady=1)
    compose_shell.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
    compose = tk.Frame(compose_shell, bg="#121827")
    compose.pack(fill="both", expand=True)
    compose.grid_columnconfigure(0, weight=1)
    tk.Frame(compose, bg=ACCENT, height=2).grid(row=0, column=0, sticky="ew")

    compose_head = tk.Frame(compose, bg=PANEL)
    compose_head.configure(bg="#121827")
    compose_head.grid(row=1, column=0, sticky="ew", padx=16, pady=(11, 7))
    compose_copy = tk.Frame(compose_head, bg="#121827")
    compose_copy.pack(side="left")
    tk.Label(compose_copy, text="POST COMPOSER", fg=ACCENT, bg="#121827", font=("Segoe UI", 8, "bold")).pack(anchor="w")
    tk.Label(compose_copy, text="Build your post", fg=TEXT, bg="#121827", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(1, 0))
    tk.Label(compose_head, textvariable=char_var, fg=SUBTLE, bg="#121827", font=("Consolas", 8)).pack(side="right", padx=(0, 10))
    button(
        compose_head,
        "😀 EMOJI",
        lambda: open_emoji_picker(text, on_insert=update_char_count, accent=ACCENT),
        compact=True,
    ).pack(side="right", padx=(0, 10))

    text = tk.Text(
        compose,
        height=5,
        bg=PANEL_3,
        fg=TEXT,
        insertbackground=TEXT,
        relief="flat",
        bd=0,
        font=("Segoe UI", 11),
        wrap="word",
        padx=14,
        pady=12,
        undo=True,
    )
    text.configure(highlightthickness=1, highlightbackground="#1b2738")
    text.grid(row=2, column=0, sticky="ew", padx=16)

    media_row = tk.Frame(compose, bg=PANEL)
    media_row.configure(bg="#121827")
    media_row.grid(row=3, column=0, sticky="ew", padx=16, pady=(8, 0))

    def refresh_media_label():
        if not selected_media:
            media_var.set("NO MEDIA")
            return
        names = [Path(path).name for path in selected_media]
        summary = ", ".join(names[:2])
        if len(names) > 2:
            summary += f" +{len(names)-2} more"
        media_var.set(summary)

    def add_images():
        paths = filedialog.askopenfilenames(
            parent=window,
            title="Add images",
            filetypes=[
                ("Images", "*.jpg *.jpeg *.png *.gif *.webp"),
                ("All files", "*.*"),
            ],
        )
        if paths:
            selected_media.extend(str(path) for path in paths)
            refresh_media_label()

    def add_video():
        path = filedialog.askopenfilename(
            parent=window,
            title="Add video",
            filetypes=[
                ("Video", "*.mp4 *.mov *.m4v *.webm"),
                ("All files", "*.*"),
            ],
        )
        if path:
            selected_media.clear()
            selected_media.append(str(path))
            refresh_media_label()

    def clear_media():
        selected_media.clear()
        refresh_media_label()

    button(media_row, "ADD IMAGES", add_images, compact=True).pack(side="left")
    button(media_row, "ADD VIDEO", add_video, compact=True).pack(side="left", padx=6)
    button(media_row, "CLEAR MEDIA", clear_media, compact=True).pack(side="left")
    tk.Label(media_row, textvariable=media_var, fg=MUTED, bg="#121827", font=("Consolas", 8)).pack(side="left", padx=12)

    schedule = tk.Frame(compose, bg="#121827")
    schedule.grid(row=4, column=0, sticky="ew", padx=16, pady=(8, 12))
    delay = tk.StringVar(value="1")

    delay_mode = tk.Radiobutton(
        schedule,
        text="POST IN",
        variable=schedule_mode,
        value="delay",
        bg=PANEL,
        fg=MUTED,
        selectcolor=PANEL_2,
        activebackground=PANEL,
        activeforeground=TEXT,
        font=("Consolas", 8, "bold"),
        cursor="hand2",
    )
    delay_mode.pack(side="left")

    delay_entry = tk.Entry(
        schedule,
        textvariable=delay,
        width=6,
        bg=PANEL_2,
        fg=TEXT,
        insertbackground=TEXT,
        relief="flat",
        justify="center",
        font=("Segoe UI", 10, "bold"),
    )
    delay_entry.pack(side="left", padx=(6, 4), ipady=6)
    tk.Label(schedule, text="minutes", fg=MUTED, bg=PANEL, font=("Segoe UI", 9)).pack(side="left", padx=(0, 8))

    def set_delay(value):
        schedule_mode.set("delay")
        delay.set(str(value))

    for value in (1, 5, 15, 30, 60):
        button(schedule, f"{value}m", lambda v=value: set_delay(v), compact=True).pack(side="left", padx=2)

    tk.Frame(schedule, bg=BORDER, width=1, height=28).pack(side="left", padx=9)

    clock_mode_btn = tk.Radiobutton(
        schedule,
        text="AT",
        variable=schedule_mode,
        value="clock",
        bg=PANEL,
        fg=MUTED,
        selectcolor=PANEL_2,
        activebackground=PANEL,
        activeforeground=TEXT,
        font=("Consolas", 8, "bold"),
        cursor="hand2",
    )
    clock_mode_btn.pack(side="left")
    clock_entry = tk.Entry(
        schedule,
        textvariable=clock_time,
        width=7,
        bg=PANEL_2,
        fg=TEXT,
        insertbackground=TEXT,
        relief="flat",
        justify="center",
        font=("Consolas", 10, "bold"),
    )
    clock_entry.pack(side="left", padx=(6, 4), ipady=6)
    tk.Label(schedule, text="HH:MM", fg=MUTED, bg=PANEL, font=("Segoe UI", 8)).pack(side="left")

    # Main queue action lives beside the schedule controls so it is always visible.
    queue_button_holder = tk.Frame(schedule, bg=PANEL)
    queue_button_holder.pack(side="right")

    # STATS
    stats_shell = tk.Frame(top, bg="#351431", padx=1, pady=1)
    stats_shell.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
    stats = tk.Frame(stats_shell, bg="#0f1723")
    stats.pack(fill="both", expand=True)
    tk.Frame(stats, bg=ACCENT, height=2).grid(row=0, column=0, sticky="ew")
    stats.grid_columnconfigure(0, weight=1)

    def stat_card(row, label, variable, accent):
        card = tk.Frame(stats, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        card.grid(row=row + 1, column=0, sticky="ew", padx=14, pady=(10 if row == 0 else 0, 8))
        tk.Label(card, text=label, fg=MUTED, bg=PANEL, font=("Consolas", 8, "bold")).pack(anchor="w", padx=14, pady=(10, 0))
        tk.Label(card, textvariable=variable, fg=accent, bg=PANEL, font=("Segoe UI", 22, "bold")).pack(anchor="w", padx=14, pady=(0, 10))

    stat_card(0, "QUEUED", stats_var["queued"], ACCENT)
    stat_card(1, "POSTED", stats_var["posted"], SUCCESS)
    stat_card(2, "ERRORS", stats_var["error"], DANGER)

    # QUEUE
    queue_card = tk.Frame(window, bg=TABLE_BG, highlightthickness=1, highlightbackground=BORDER)
    queue_card.pack(fill="both", expand=True, padx=28, pady=(0, 8))

    queue_head = tk.Frame(queue_card, bg=PANEL)
    queue_head.pack(fill="x", padx=16, pady=(12, 8))
    tk.Label(queue_head, text="POST QUEUE", fg=TEXT, bg=PANEL, font=("Segoe UI", 12, "bold")).pack(side="left")
    queue_actions = tk.Frame(queue_head, bg=PANEL)
    queue_actions.pack(side="right")
    tk.Label(queue_actions, textvariable=next_var, fg=MUTED, bg=PANEL, font=("Consolas", 9)).pack(side="left", padx=(0, 12))

    cols = ("due", "status", "post")
    tree = ttk.Treeview(queue_card, columns=cols, show="headings", style="Pulse.Treeview", height=5)
    for col, title, width in (
        ("due", "DUE", 150),
        ("status", "STATUS", 100),
        ("post", "POST", 760),
    ):
        tree.heading(col, text=title)
        tree.column(col, width=width, anchor="w", stretch=(col == "post"))
    tree.tag_configure("posted", foreground=SUCCESS)
    tree.tag_configure("error", foreground=DANGER)
    tree.tag_configure("queued", foreground=TEXT)

    queue_body = tk.Frame(queue_card, bg=TABLE_BG)
    queue_body.pack(fill="both", expand=True, padx=14, pady=(0, 12))
    queue_scroll = ttk.Scrollbar(
        queue_body,
        orient="vertical",
        command=tree.yview,
        style="Pulse.Vertical.TScrollbar",
    )
    queue_xscroll = ttk.Scrollbar(
        queue_body,
        orient="horizontal",
        command=tree.xview,
        style="Pulse.Horizontal.TScrollbar",
    )
    tree.configure(yscrollcommand=queue_scroll.set, xscrollcommand=queue_xscroll.set)
    tree.grid(in_=queue_body, row=0, column=0, sticky="nsew")
    queue_scroll.grid(row=0, column=1, sticky="ns")
    queue_xscroll.grid(row=1, column=0, columnspan=2, sticky="ew")
    queue_body.rowconfigure(0, weight=1)
    queue_body.columnconfigure(0, weight=1)
    mapping = {}

    # ACTIVITY
    activity = tk.Frame(window, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
    activity.pack(fill="x", padx=28, pady=(0, 14))
    activity_head = tk.Frame(activity, bg=PANEL)
    activity_head.pack(fill="x", padx=14, pady=(10, 6))
    tk.Label(activity_head, text="ACTIVITY", fg=TEXT, bg=PANEL, font=("Segoe UI", 10, "bold")).pack(side="left")

    log = tk.Text(
        activity,
        height=4,
        bg=PANEL_3,
        fg="#cbd3df",
        insertbackground=TEXT,
        relief="flat",
        bd=0,
        font=("Consolas", 9),
        wrap="word",
        padx=10,
        pady=8,
    )

    def copy_log():
        value = log.get("1.0", tk.END).strip()
        window.clipboard_clear()
        window.clipboard_append(value)
        window.update()
        status.set("LOG COPIED")

    def clear_log():
        log.delete("1.0", tk.END)
        status.set("LOG CLEARED")

    button(activity_head, "COPY LOG", copy_log, compact=True).pack(side="right", padx=(6, 0))
    button(activity_head, "CLEAR", clear_log, compact=True).pack(side="right")

    log_body = tk.Frame(activity, bg=PANEL)
    log_body.pack(fill="both", expand=True, padx=14, pady=(0, 12))
    activity_scroll = ttk.Scrollbar(
        log_body,
        orient="vertical",
        command=log.yview,
        style="Pulse.Vertical.TScrollbar",
    )
    log.configure(yscrollcommand=activity_scroll.set)
    log.pack(in_=log_body, side="left", fill="both", expand=True)
    activity_scroll.pack(side="right", fill="y")

    def update_char_count(*_):
        count = len(text.get("1.0", "end-1c"))
        char_var.set(f"{count} chars")

    text.bind("<KeyRelease>", update_char_count)

    def refresh():
        selected = tree.selection()
        selected_id = mapping.get(selected[0]).post_id if selected and selected[0] in mapping else None
        items = load_queue()
        mapping.clear()
        for iid in tree.get_children():
            tree.delete(iid)

        queued = posted = errors = 0
        next_due = None
        pick = None

        for item in items:
            status_name = item.status.lower()
            if status_name == "queued":
                queued += 1
            elif status_name == "posted":
                posted += 1
            elif status_name == "error":
                errors += 1

            try:
                due_dt = datetime.fromisoformat(item.due_at)
                due = due_dt.strftime("%d/%m/%Y %H:%M")
                if status_name == "queued" and (next_due is None or due_dt < next_due):
                    next_due = due_dt
            except ValueError:
                due = item.due_at

            iid = tree.insert(
                "",
                "end",
                values=(
                    due,
                    item.status.upper(),
                    ((f"[MEDIA {len(item.media_paths)}] " if item.media_paths else "") + item.text.replace("\n", " ")).strip(),
                ),
                tags=(status_name if status_name in {"queued", "posted", "error"} else "queued",),
            )
            mapping[iid] = item
            if item.post_id == selected_id:
                pick = iid

        if pick:
            tree.selection_set(pick)

        stats_var["queued"].set(str(queued))
        stats_var["posted"].set(str(posted))
        stats_var["error"].set(str(errors))
        next_var.set(f"NEXT // {next_due:%H:%M}" if next_due else "No posts queued")
        browser_var.set(browser_status())

    def write(msg):
        def apply():
            if not log.winfo_exists():
                return
            log.insert(tk.END, msg + "\n")
            log.see(tk.END)
            refresh()
        window.after(0, apply)

    def queue_post():
        body = text.get("1.0", tk.END).strip()
        if not body and not selected_media:
            messagebox.showerror("Empty post", "Write some text or add media first.", parent=window)
            return

        now = datetime.now()
        if schedule_mode.get() == "clock":
            try:
                hour_text, minute_text = clock_time.get().strip().split(":", 1)
                hour = int(hour_text)
                minute = int(minute_text)
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError
            except ValueError:
                messagebox.showerror("Invalid time", "Enter a 24-hour time in HH:MM format, for example 18:30.", parent=window)
                return
            due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if due <= now:
                due += timedelta(days=1)
            schedule_note = f"AT {due:%H:%M}"
        else:
            try:
                minutes = int(delay.get())
                if minutes < 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Invalid delay", "Post delay must be 0 or more whole minutes.", parent=window)
                return
            due = now + timedelta(minutes=minutes)
            schedule_note = f"IN {minutes}m"

        media_copy = list(selected_media)
        add_post(body, due, media_copy)
        text.delete("1.0", tk.END)
        selected_media.clear()
        refresh_media_label()
        update_char_count()
        refresh()
        media_note = f" | MEDIA {len(media_copy)}" if media_copy else ""
        write(f"QUEUED | {schedule_note} | due {due:%d/%m %H:%M}{media_note} | {body[:100]}")

    def remove_selected():
        sel = tree.selection()
        if not sel:
            status.set("SELECT A POST")
            return
        item = mapping.get(sel[0])
        if item:
            remove_post(item.post_id)
            refresh()
            write(f"REMOVED | {item.text[:80]}")

    def start():
        if worker[0] and worker[0].is_alive():
            status.set("RUNNING")
            return
        stop_event.clear()
        worker[0] = threading.Thread(target=run_scheduler, args=(stop_event, write), daemon=True)
        worker[0].start()
        status.set("RUNNING")

    def stop():
        stop_event.set()
        status.set("STOPPED")

    # Always-visible actions.
    button(queue_button_holder, "QUEUE POST", queue_post, accent=True, compact=True).pack(side="right")
    button(queue_actions, "REMOVE", remove_selected, compact=True).pack(side="left", padx=(0, 6))
    button(queue_actions, "STOP", stop, danger=True, compact=True).pack(side="left", padx=(0, 6))
    button(queue_actions, "START", start, accent=True, compact=True).pack(side="left")

    def close():
        stop_event.set()
        if ambient_after[0] is not None:
            try:
                window.after_cancel(ambient_after[0])
            except tk.TclError:
                pass
            ambient_after[0] = None
        window.destroy()

    window.protocol("WM_DELETE_WINDOW", close)
    refresh()
    update_char_count()
    return window
