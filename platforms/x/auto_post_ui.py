from __future__ import annotations

import threading
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox, ttk

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


def open_auto_post_window(parent: tk.Misc) -> tk.Toplevel:
    window = tk.Toplevel(parent)
    window.title("Pulse Social — X Auto Post")
    window.geometry("1180x760")
    window.minsize(980, 680)
    window.configure(bg=BG)

    stop_event = threading.Event()
    worker = [None]
    status = tk.StringVar(value="STOPPED")
    browser_var = tk.StringVar(value=browser_status())
    char_var = tk.StringVar(value="0 chars")
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
        background=PANEL,
        fieldbackground=PANEL,
        foreground=TEXT,
        rowheight=32,
        borderwidth=0,
        font=("Segoe UI", 10),
    )
    style.map(
        "Pulse.Treeview",
        background=[("selected", "#281229")],
        foreground=[("selected", TEXT)],
    )
    style.configure(
        "Pulse.Treeview.Heading",
        background=PANEL_2,
        foreground=MUTED,
        relief="flat",
        font=("Segoe UI", 9, "bold"),
        padding=(10, 8),
    )

    def button(parent, text, command, accent=False, danger=False, compact=False):
        bg = ACCENT if accent else DANGER if danger else PANEL_2
        active = ACCENT_2 if accent else "#7e2637" if danger else "#202b3d"
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
            padx=12 if compact else 16,
            pady=7 if compact else 9,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )

    def pill(parent, variable, fg=SUCCESS):
        frame = tk.Frame(parent, bg=PANEL_2)
        tk.Label(frame, text="●", bg=PANEL_2, fg=fg, font=("Segoe UI", 9, "bold")).pack(side="left", padx=(8, 4), pady=6)
        tk.Label(frame, textvariable=variable, bg=PANEL_2, fg=TEXT, font=("Consolas", 9, "bold")).pack(side="left", padx=(0, 9), pady=6)
        return frame

    # HERO
    hero = tk.Frame(window, bg=BG)
    hero.pack(fill="x", padx=30, pady=(18, 10))
    brand = tk.Frame(hero, bg=BG)
    brand.pack(side="left")
    tk.Label(brand, text="PULSE", fg=TEXT, bg=BG, font=("Segoe UI", 28, "bold")).pack(side="left")
    tk.Label(brand, text=" SOCIAL", fg=ACCENT, bg=BG, font=("Segoe UI", 28, "bold")).pack(side="left")
    tk.Label(brand, text="  /  X AUTO POST", fg=MUTED, bg=BG, font=("Consolas", 10, "bold")).pack(side="left", padx=(8, 0), pady=(10, 0))

    hero_right = tk.Frame(hero, bg=BG)
    hero_right.pack(side="right")
    browser_pill = pill(hero_right, browser_var, SUCCESS)
    browser_pill.pack(side="left", padx=(0, 8))
    status_pill = pill(hero_right, status, ACCENT)
    status_pill.pack(side="left")

    # TOP GRID
    top = tk.Frame(window, bg=BG)
    top.pack(fill="x", padx=30, pady=(0, 8))
    top.grid_columnconfigure(0, weight=3)
    top.grid_columnconfigure(1, weight=1)

    compose = tk.Frame(top, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
    compose.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
    compose.grid_columnconfigure(0, weight=1)

    compose_head = tk.Frame(compose, bg=PANEL)
    compose_head.grid(row=0, column=0, sticky="ew", padx=18, pady=(12, 6))
    tk.Label(compose_head, text="COMPOSE", fg=TEXT, bg=PANEL, font=("Segoe UI", 12, "bold")).pack(side="left")
    tk.Label(compose_head, textvariable=char_var, fg=MUTED, bg=PANEL, font=("Consolas", 9)).pack(side="right")

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
    text.grid(row=1, column=0, sticky="ew", padx=18)

    schedule = tk.Frame(compose, bg=PANEL)
    schedule.grid(row=2, column=0, sticky="ew", padx=18, pady=(8, 12))
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
    stats = tk.Frame(top, bg=BG)
    stats.grid(row=0, column=1, sticky="nsew")
    stats.grid_columnconfigure(0, weight=1)

    def stat_card(row, label, variable, accent):
        card = tk.Frame(stats, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        card.grid(row=row, column=0, sticky="ew", pady=(0, 8 if row < 2 else 0))
        tk.Label(card, text=label, fg=MUTED, bg=PANEL, font=("Consolas", 8, "bold")).pack(anchor="w", padx=14, pady=(10, 0))
        tk.Label(card, textvariable=variable, fg=accent, bg=PANEL, font=("Segoe UI", 22, "bold")).pack(anchor="w", padx=14, pady=(0, 10))

    stat_card(0, "QUEUED", stats_var["queued"], ACCENT)
    stat_card(1, "POSTED", stats_var["posted"], SUCCESS)
    stat_card(2, "ERRORS", stats_var["error"], DANGER)

    # QUEUE
    queue_card = tk.Frame(window, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
    queue_card.pack(fill="both", expand=True, padx=30, pady=(0, 8))

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
    tree.pack(fill="both", expand=True, padx=14, pady=(0, 14))
    mapping = {}

    # ACTIVITY
    activity = tk.Frame(window, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
    activity.pack(fill="x", padx=30, pady=(0, 8))
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
    log.pack(fill="x", padx=14, pady=(0, 12))

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
                values=(due, item.status.upper(), item.text.replace("\n", " ")),
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
        if not body:
            messagebox.showerror("Empty post", "Write the post first.", parent=window)
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

        add_post(body, due)
        text.delete("1.0", tk.END)
        update_char_count()
        refresh()
        write(f"QUEUED | {schedule_note} | due {due:%d/%m %H:%M} | {body[:100]}")

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
        window.destroy()

    window.protocol("WM_DELETE_WINDOW", close)
    refresh()
    update_char_count()
    return window
