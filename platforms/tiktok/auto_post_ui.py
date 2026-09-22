from __future__ import annotations

import threading
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .auto_post import (
    MAX_CAPTION_UTF16,
    add_post,
    clear_access_token,
    load_access_token,
    load_queue,
    query_creator_info,
    remove_post,
    run_scheduler,
    save_access_token,
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


class TikTokAutoPostView(tk.Frame):
    def __init__(self, master, **kwargs):
        super().__init__(master, bg=BG, **kwargs)
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.selected_video = ""
        self.mapping = {}
        self.privacy_options = ["SELF_ONLY"]
        self._destroyed = False

        self.connection_var = tk.StringVar(value="NOT CONNECTED")
        self.status_var = tk.StringVar(value="STOPPED")
        self.char_var = tk.StringVar(value=f"0 / {MAX_CAPTION_UTF16}")
        self.media_var = tk.StringVar(value="NO VIDEO")
        self.next_var = tk.StringVar(value="No posts queued")
        self.schedule_mode = tk.StringVar(value="delay")
        self.delay_var = tk.StringVar(value="1")
        self.clock_var = tk.StringVar(value=(datetime.now() + timedelta(minutes=5)).strftime("%H:%M"))
        self.privacy_var = tk.StringVar(value="SELF_ONLY")
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
            background=PANEL,
            fieldbackground=PANEL,
            foreground=TEXT,
            rowheight=31,
            borderwidth=0,
            font=("Segoe UI", 9),
        )
        style.map(
            "TikTok.Treeview",
            background=[("selected", "#12363a")],
            foreground=[("selected", TEXT)],
        )
        style.configure(
            "TikTok.Treeview.Heading",
            background=PANEL_2,
            foreground=MUTED,
            relief="flat",
            font=("Segoe UI", 8, "bold"),
            padding=(8, 8),
        )

    def _button(self, parent, text, command, accent=False, danger=False, compact=False):
        bg = ACCENT_2 if accent else "#5b1623" if danger else PANEL_2
        active = "#ff5878" if accent else "#7e2637" if danger else "#202b3d"
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
            padx=11 if compact else 15,
            pady=6 if compact else 9,
            font=("Segoe UI", 8 if compact else 9, "bold"),
            cursor="hand2",
        )

    def _build(self):
        hero = tk.Frame(self, bg=BG)
        hero.pack(fill="x", padx=26, pady=(18, 10))
        brand = tk.Frame(hero, bg=BG)
        brand.pack(side="left")
        tk.Label(brand, text="PULSE", fg=TEXT, bg=BG, font=("Segoe UI", 25, "bold")).pack(side="left")
        tk.Label(brand, text=" SOCIAL", fg=ACCENT_2, bg=BG, font=("Segoe UI", 25, "bold")).pack(side="left")
        tk.Label(
            brand,
            text="  /  TIKTOK AUTO POST",
            fg=ACCENT,
            bg=BG,
            font=("Consolas", 9, "bold"),
        ).pack(side="left", padx=(8, 0), pady=(9, 0))

        connection = tk.Frame(hero, bg=PANEL_2)
        connection.pack(side="right")
        tk.Label(connection, text="●", fg=ACCENT, bg=PANEL_2, font=("Segoe UI", 9, "bold")).pack(
            side="left", padx=(8, 4), pady=6
        )
        tk.Label(
            connection,
            textvariable=self.connection_var,
            fg=TEXT,
            bg=PANEL_2,
            font=("Consolas", 8, "bold"),
        ).pack(side="left", padx=(0, 9), pady=6)

        connect_row = tk.Frame(self, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        connect_row.pack(fill="x", padx=26, pady=(0, 10))
        tk.Label(
            connect_row,
            text="OFFICIAL TIKTOK CONTENT POSTING API",
            fg=MUTED,
            bg=PANEL,
            font=("Consolas", 8, "bold"),
        ).pack(side="left", padx=14, pady=10)
        self._button(connect_row, "CLEAR TOKEN", self._clear_token, danger=True, compact=True).pack(
            side="right", padx=(4, 10), pady=6
        )
        self._button(connect_row, "TEST", self._test_connection, compact=True).pack(
            side="right", padx=4, pady=6
        )
        self._button(connect_row, "SET ACCESS TOKEN", self._set_token, accent=True, compact=True).pack(
            side="right", padx=4, pady=6
        )

        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=26, pady=(0, 10))
        top.grid_columnconfigure(0, weight=3)
        top.grid_columnconfigure(1, weight=2)

        compose = tk.Frame(top, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        compose.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        compose.grid_columnconfigure(0, weight=1)

        head = tk.Frame(compose, bg=PANEL)
        head.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 6))
        tk.Label(head, text="CAPTION", fg=TEXT, bg=PANEL, font=("Segoe UI", 11, "bold")).pack(side="left")
        tk.Label(head, textvariable=self.char_var, fg=MUTED, bg=PANEL, font=("Consolas", 8)).pack(side="right")

        self.caption = tk.Text(
            compose,
            height=5,
            bg=PANEL_3,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            wrap="word",
            padx=12,
            pady=10,
            font=("Segoe UI", 10),
        )
        self.caption.grid(row=1, column=0, sticky="ew", padx=16)
        self.caption.bind("<KeyRelease>", self._update_chars)

        media_row = tk.Frame(compose, bg=PANEL)
        media_row.grid(row=2, column=0, sticky="ew", padx=16, pady=(8, 12))
        self._button(media_row, "ADD VIDEO", self._choose_video, compact=True).pack(side="left")
        self._button(media_row, "CLEAR", self._clear_video, compact=True).pack(side="left", padx=6)
        tk.Label(
            media_row,
            textvariable=self.media_var,
            fg=MUTED,
            bg=PANEL,
            font=("Consolas", 8),
        ).pack(side="left", padx=8)

        options = tk.Frame(top, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        options.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        tk.Label(options, text="POST SETTINGS", fg=TEXT, bg=PANEL, font=("Segoe UI", 11, "bold")).pack(
            anchor="w", padx=16, pady=(12, 8)
        )

        privacy_row = tk.Frame(options, bg=PANEL)
        privacy_row.pack(fill="x", padx=16, pady=(0, 6))
        tk.Label(privacy_row, text="PRIVACY", fg=MUTED, bg=PANEL, font=("Consolas", 8, "bold")).pack(
            side="left"
        )
        self.privacy_menu = ttk.Combobox(
            privacy_row,
            textvariable=self.privacy_var,
            values=self.privacy_options,
            state="readonly",
            width=24,
        )
        self.privacy_menu.pack(side="right")

        checks = tk.Frame(options, bg=PANEL)
        checks.pack(fill="x", padx=12, pady=(2, 8))
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
                bg=PANEL,
                fg=TEXT,
                activebackground=PANEL,
                activeforeground=TEXT,
                selectcolor=PANEL_2,
                font=("Segoe UI", 8),
            ).pack(anchor="w", pady=1)

        schedule = tk.Frame(options, bg=PANEL)
        schedule.pack(fill="x", padx=16, pady=(2, 12))
        tk.Radiobutton(
            schedule,
            text="POST IN",
            variable=self.schedule_mode,
            value="delay",
            bg=PANEL,
            fg=MUTED,
            selectcolor=PANEL_2,
            activebackground=PANEL,
            activeforeground=TEXT,
            font=("Consolas", 8, "bold"),
        ).grid(row=0, column=0, sticky="w")
        tk.Entry(
            schedule,
            textvariable=self.delay_var,
            width=5,
            bg=PANEL_2,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            justify="center",
        ).grid(row=0, column=1, padx=4, ipady=4)
        tk.Label(schedule, text="minutes", fg=MUTED, bg=PANEL, font=("Segoe UI", 8)).grid(
            row=0, column=2, sticky="w"
        )

        tk.Radiobutton(
            schedule,
            text="AT",
            variable=self.schedule_mode,
            value="clock",
            bg=PANEL,
            fg=MUTED,
            selectcolor=PANEL_2,
            activebackground=PANEL,
            activeforeground=TEXT,
            font=("Consolas", 8, "bold"),
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))
        tk.Entry(
            schedule,
            textvariable=self.clock_var,
            width=7,
            bg=PANEL_2,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            justify="center",
        ).grid(row=1, column=1, padx=4, pady=(6, 0), ipady=4)
        tk.Label(schedule, text="HH:MM", fg=MUTED, bg=PANEL, font=("Segoe UI", 8)).grid(
            row=1, column=2, sticky="w", pady=(6, 0)
        )
        self._button(schedule, "QUEUE POST", self._queue_post, accent=True, compact=True).grid(
            row=0, column=3, rowspan=2, padx=(14, 0)
        )

        queue_card = tk.Frame(self, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        queue_card.pack(fill="both", expand=True, padx=26, pady=(0, 10))

        queue_head = tk.Frame(queue_card, bg=PANEL)
        queue_head.pack(fill="x", padx=14, pady=(10, 6))
        tk.Label(queue_head, text="POST QUEUE", fg=TEXT, bg=PANEL, font=("Segoe UI", 11, "bold")).pack(
            side="left"
        )
        tk.Label(queue_head, textvariable=self.next_var, fg=MUTED, bg=PANEL, font=("Consolas", 8)).pack(
            side="left", padx=12
        )
        self._button(queue_head, "START", self.start, accent=True, compact=True).pack(side="right")
        self._button(queue_head, "STOP", self.stop, danger=True, compact=True).pack(side="right", padx=6)
        self._button(queue_head, "REMOVE", self._remove_selected, compact=True).pack(side="right")

        cols = ("due", "status", "privacy", "video", "caption")
        self.tree = ttk.Treeview(
            queue_card,
            columns=cols,
            show="headings",
            style="TikTok.Treeview",
            height=6,
        )
        widths = {
            "due": 130,
            "status": 105,
            "privacy": 155,
            "video": 180,
            "caption": 420,
        }
        for col in cols:
            self.tree.heading(col, text=col.upper())
            self.tree.column(col, width=widths[col], anchor="w", stretch=(col == "caption"))
        self.tree.tag_configure("posted", foreground=SUCCESS)
        self.tree.tag_configure("error", foreground=DANGER)
        self.tree.tag_configure("processing", foreground=ACCENT)
        self.tree.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        activity = tk.Frame(self, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        activity.pack(fill="x", padx=26, pady=(0, 18))
        activity_head = tk.Frame(activity, bg=PANEL)
        activity_head.pack(fill="x", padx=12, pady=(8, 5))
        tk.Label(activity_head, text="ACTIVITY", fg=TEXT, bg=PANEL, font=("Segoe UI", 9, "bold")).pack(
            side="left"
        )
        tk.Label(
            activity_head,
            textvariable=self.status_var,
            fg=ACCENT,
            bg=PANEL,
            font=("Consolas", 8, "bold"),
        ).pack(side="right")

        self.log = tk.Text(
            activity,
            height=4,
            bg=PANEL_3,
            fg="#cbd3df",
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            wrap="word",
            padx=9,
            pady=7,
            font=("Consolas", 8),
        )
        self.log.pack(fill="x", padx=12, pady=(0, 10))

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
            self.selected_video = str(path)
            self.media_var.set(Path(path).name)

    def _clear_video(self):
        self.selected_video = ""
        self.media_var.set("NO VIDEO")

    def _set_token(self):
        token = simpledialog.askstring(
            "TikTok access token",
            "Paste a TikTok user access token with video.publish permission.\n\n"
            "Pulse stores it encrypted with Windows DPAPI.",
            show="•",
            parent=self.winfo_toplevel(),
        )
        if not token:
            return
        try:
            save_access_token(token)
            self._refresh_connection_label()
            self._test_connection()
        except Exception as exc:
            messagebox.showerror("TikTok", str(exc), parent=self.winfo_toplevel())

    def _clear_token(self):
        clear_access_token()
        self.connection_var.set("NOT CONNECTED")
        self.privacy_options = ["SELF_ONLY"]
        self.privacy_menu.configure(values=self.privacy_options)
        self.privacy_var.set("SELF_ONLY")

    def _refresh_connection_label(self):
        self.connection_var.set("TOKEN SAVED" if load_access_token() else "NOT CONNECTED")

    def _test_connection(self):
        if not load_access_token():
            messagebox.showinfo(
                "TikTok",
                "Set a TikTok access token first.",
                parent=self.winfo_toplevel(),
            )
            return

        self.connection_var.set("CHECKING...")
        self.update_idletasks()
        try:
            info = query_creator_info()
            options = list(info.get("privacy_level_options") or [])
            if options:
                self.privacy_options = options
                self.privacy_menu.configure(values=options)
                if self.privacy_var.get() not in options:
                    self.privacy_var.set(options[0])
            nickname = info.get("creator_nickname") or info.get("creator_username") or "CONNECTED"
            self.connection_var.set(str(nickname).upper())
            self.write(
                f"CONNECTED | {nickname} | privacy: {', '.join(self.privacy_options)}"
            )
        except Exception as exc:
            self.connection_var.set("CONNECTION ERROR")
            self.write(f"CONNECTION ERROR | {exc}")
            messagebox.showerror("TikTok connection", str(exc), parent=self.winfo_toplevel())

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
        if not self.selected_video:
            messagebox.showerror("TikTok", "Choose a video first.", parent=self.winfo_toplevel())
            return
        try:
            due, note = self._due_time()
            caption = self.caption.get("1.0", "end-1c")
            item = add_post(
                caption,
                due,
                self.selected_video,
                privacy_level=self.privacy_var.get(),
                disable_comment=not self.comments_var.get(),
                disable_duet=not self.duet_var.get(),
                disable_stitch=not self.stitch_var.get(),
                brand_content_toggle=self.brand_content_var.get(),
                brand_organic_toggle=self.brand_organic_var.get(),
                is_aigc=self.aigc_var.get(),
            )
        except Exception as exc:
            messagebox.showerror("TikTok queue", str(exc), parent=self.winfo_toplevel())
            return

        self.write(
            f"QUEUED | {note} | due {due:%d/%m %H:%M} | "
            f"{Path(item.video_path).name} | {item.caption[:100]}"
        )
        self.caption.delete("1.0", tk.END)
        self._clear_video()
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
            self.write(f"REMOVED | {item.caption[:80] or Path(item.video_path).name}")
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
                    Path(item.video_path).name,
                    item.caption.replace("\n", " "),
                ),
                tags=(status if status in {"posted", "processing", "error"} else "",),
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
