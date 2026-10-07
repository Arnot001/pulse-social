from __future__ import annotations

import math
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from platforms.browser_control import browser_status
from platforms.pdh_bridge import ensure_bridge_server, pdh_connected

from .cleanup import CLEANUP_LOG_FILE, CleanupOptions, run_cleanup

BG = "#06070b"
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
                142 + 34 * math.sin(t + 0.28) + 12 * math.sin(t * 0.48 + 1.0),
                430 + 46 * math.sin(t * 0.84 + 1.9) + 18 * math.sin(t * 0.36 - 0.5),
                705 + 36 * math.sin(t * 1.06 + 3.0) + 14 * math.sin(t * 0.50 + 0.8),
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

    _WAVE_PPM_CACHE = f"P6\n{width} {height}\n255\n".encode("ascii") + bytes(pixels)
    return _WAVE_PPM_CACHE


def _cleanup_browser_status() -> str:
    ensure_bridge_server()
    if pdh_connected():
        return "PDH CONNECTED // EXISTING BROWSER"
    return browser_status()


class TikTokCleanupView(tk.Frame):
    def __init__(self, master, **kwargs):
        super().__init__(master, bg=BG, **kwargs)
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.arm_event = threading.Event()
        self._destroyed = False

        self.mode_var = tk.StringVar(value="videos")
        self.count_var = tk.StringVar(value="10")
        self.delete_all_var = tk.BooleanVar(value=False)
        self.dry_run_var = tk.BooleanVar(value=True)
        self.delay_var = tk.StringVar(value="1.25")
        self.status_var = tk.StringVar(value="READY // SAFE MODE")
        self.browser_var = tk.StringVar(value=_cleanup_browser_status())

        self._build()
        self.bind("<Destroy>", self._on_destroy, add="+")

    def _button(self, parent, text, command, *, accent=False, danger=False, width=None):
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
            padx=14,
            pady=8,
            width=width,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
            highlightthickness=1,
            highlightbackground=border,
            highlightcolor=border,
        )
        btn.bind("<Enter>", lambda _event: btn.configure(bg=active))
        btn.bind("<Leave>", lambda _event: btn.configure(bg=bg))
        return btn

    def _field(self, parent, variable, width=12):
        return tk.Entry(
            parent,
            textvariable=variable,
            width=width,
            bg=PANEL_3,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            font=("Segoe UI", 10),
        )

    def _build(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Cleanup.Vertical.TScrollbar",
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
            "Cleanup.Vertical.TScrollbar",
            background=[("pressed", "#31415a"), ("active", "#26344a")],
            arrowcolor=[("active", TEXT)],
        )

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
            self._ambient_after_id = self.after(140, animate_backdrop)

        self._ambient_after_id = self.after(140, animate_backdrop)

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
        tk.Label(brand_row, text="PULSE", fg=TEXT, bg=BG, font=("Segoe UI", 24, "bold")).pack(side="left")
        tk.Label(brand_row, text=" TIKTOK", fg=ACCENT_2, bg=BG, font=("Segoe UI", 24, "bold")).pack(side="left")
        tk.Label(
            brand,
            text="Review and clean your own TikTok content with explicit confirmation.",
            fg=MUTED,
            bg=BG,
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(1, 0))
        tk.Label(
            header,
            text="CLEANUP",
            fg=ACCENT,
            bg=BG,
            font=("Segoe UI", 9, "bold"),
        ).pack(side="right", pady=12)

        tk.Frame(self, bg="#2a1834", height=1).pack(fill="x", padx=28, pady=(0, 7))

        browser_shell = tk.Frame(self, bg="#11303a", padx=1, pady=1)
        browser_shell.pack(fill="x", padx=28, pady=(0, 9))
        browser = tk.Frame(browser_shell, bg=PANEL)
        browser.pack(fill="x")
        tk.Frame(browser, bg=ACCENT_2, width=3).pack(side="left", fill="y")
        tk.Label(browser, text="●", fg=SUCCESS, bg=PANEL, font=("Segoe UI", 9, "bold")).pack(
            side="left", padx=(13, 7), pady=9
        )
        tk.Label(
            browser,
            text="PULSE BROWSER / TIKTOK",
            fg=MUTED,
            bg=PANEL,
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left", pady=9)
        tk.Frame(browser, bg=BORDER, width=1, height=16).pack(side="left", padx=14)
        tk.Label(
            browser,
            textvariable=self.browser_var,
            fg=TEXT,
            bg=PANEL,
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left", pady=9)
        tk.Label(
            browser,
            text="EXISTING LOGIN",
            fg=SUBTLE,
            bg=PANEL,
            font=("Segoe UI", 8, "bold"),
        ).pack(side="right", padx=13, pady=9)

        control_shell = tk.Frame(self, bg=SOFT_BORDER, padx=1, pady=1)
        control_shell.pack(fill="x", padx=28, pady=(0, 9))
        card = tk.Frame(control_shell, bg="#121827")
        card.pack(fill="x")
        tk.Frame(card, bg=ACCENT_2, height=2).pack(fill="x")

        control_head = tk.Frame(card, bg="#121827")
        control_head.pack(fill="x", padx=16, pady=(11, 9))
        copy = tk.Frame(control_head, bg="#121827")
        copy.pack(side="left")
        tk.Label(
            copy,
            text="CLEANUP CONTROL",
            fg=ACCENT_2,
            bg="#121827",
            font=("Segoe UI", 8, "bold"),
        ).pack(anchor="w")
        tk.Label(
            copy,
            text="Choose the scope, then scan before anything can run.",
            fg=TEXT,
            bg="#121827",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", pady=(1, 0))
        tk.Label(
            control_head,
            text="SAFE BY DEFAULT",
            fg=SUCCESS,
            bg="#121827",
            font=("Segoe UI", 8, "bold"),
        ).pack(side="right", pady=7)

        controls = tk.Frame(card, bg="#121827")
        controls.pack(fill="x", padx=16, pady=(0, 8))
        for column in range(6):
            controls.grid_columnconfigure(column, weight=1 if column in {1, 3, 5} else 0)

        tk.Label(controls, text="MODE", fg=MUTED, bg="#121827", font=("Segoe UI", 8, "bold")).grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=6
        )
        self.mode_menu = tk.OptionMenu(controls, self.mode_var, "videos", "photos", "everything")
        self.mode_menu.config(
            bg=PANEL_2,
            fg=TEXT,
            activebackground=ACCENT_2,
            activeforeground=TEXT,
            relief="flat",
            width=15,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        self.mode_menu["menu"].config(bg=PANEL_2, fg=TEXT)
        self.mode_menu.grid(row=0, column=1, sticky="w", padx=(0, 18), pady=6)

        tk.Label(controls, text="DELETE COUNT", fg=MUTED, bg="#121827", font=("Segoe UI", 8, "bold")).grid(
            row=0, column=2, sticky="w", padx=(0, 8), pady=6
        )
        self.count_entry = self._field(controls, self.count_var, width=10)
        self.count_entry.grid(row=0, column=3, sticky="w", padx=(0, 18), pady=6, ipady=5)

        tk.Label(controls, text="DELAY / SEC", fg=MUTED, bg="#121827", font=("Segoe UI", 8, "bold")).grid(
            row=0, column=4, sticky="w", padx=(0, 8), pady=6
        )
        self.delay_entry = self._field(controls, self.delay_var, width=10)
        self.delay_entry.grid(row=0, column=5, sticky="w", pady=6, ipady=5)

        toggles = tk.Frame(card, bg=SURFACE, highlightthickness=1, highlightbackground="#1b2738")
        toggles.pack(fill="x", padx=16, pady=(0, 10))
        self.delete_all_check = tk.Checkbutton(
            toggles,
            text="DELETE ALL MATCHING POSTS",
            variable=self.delete_all_var,
            command=self._toggle_delete_all,
            fg=DANGER,
            bg=SURFACE,
            activebackground=SURFACE,
            activeforeground=DANGER,
            selectcolor=PANEL_2,
            font=("Segoe UI", 8, "bold"),
        )
        self.delete_all_check.pack(side="left", padx=(10, 18), pady=8)

        self.dry_check = tk.Checkbutton(
            toggles,
            text="DRY RUN / PREVIEW ONLY",
            variable=self.dry_run_var,
            fg=SUCCESS,
            bg=SURFACE,
            activebackground=SURFACE,
            activeforeground=SUCCESS,
            selectcolor=PANEL_2,
            font=("Segoe UI", 8, "bold"),
        )
        self.dry_check.pack(side="left", padx=(0, 10), pady=8)

        actions = tk.Frame(self, bg=BG)
        actions.pack(fill="x", padx=28, pady=(0, 9))
        self.scan_btn = self._button(
            actions,
            "01  SCAN / ATTACH",
            self.start,
            accent=True,
            width=18,
        )
        self.scan_btn.pack(side="left", padx=(0, 8))
        self.arm_btn = self._button(
            actions,
            "02  ARM / CONTINUE",
            self.arm,
            width=18,
        )
        self.arm_btn.pack(side="left", padx=(0, 8))
        self.stop_btn = self._button(
            actions,
            "STOP",
            self.stop,
            danger=True,
            width=10,
        )
        self.stop_btn.pack(side="right")

        status_shell = tk.Frame(self, bg="#23152b", padx=1, pady=1)
        status_shell.pack(fill="x", padx=28, pady=(0, 9))
        status = tk.Frame(status_shell, bg=PANEL)
        status.pack(fill="x")
        tk.Label(
            status,
            text="STATUS",
            fg=MUTED,
            bg=PANEL,
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left", padx=(12, 10), pady=8)
        self.status_label = tk.Label(
            status,
            textvariable=self.status_var,
            fg=SUCCESS,
            bg=PANEL,
            font=("Consolas", 9, "bold"),
        )
        self.status_label.pack(side="left", pady=8)
        tk.Label(
            status,
            text="EXACT DELETE CONFIRMATION REQUIRED",
            fg=SUBTLE,
            bg=PANEL,
            font=("Segoe UI", 8, "bold"),
        ).pack(side="right", padx=12, pady=8)

        log_card = tk.Frame(self, bg=TABLE_BG, highlightthickness=1, highlightbackground=BORDER)
        log_card.pack(fill="both", expand=True, padx=28, pady=(0, 14))
        log_head = tk.Frame(log_card, bg=PANEL)
        log_head.pack(fill="x", padx=14, pady=(10, 6))
        tk.Label(
            log_head,
            text="ACTIVITY",
            fg=TEXT,
            bg=PANEL,
            font=("Segoe UI", 10, "bold"),
        ).pack(side="left")
        tk.Label(
            log_head,
            text="Scan, arm and cleanup events",
            fg=SUBTLE,
            bg=PANEL,
            font=("Segoe UI", 8),
        ).pack(side="left", padx=(10, 0))
        self._button(log_head, "CLEAR VIEW", self._clear_log).pack(side="right")

        log_body = tk.Frame(log_card, bg=TABLE_BG)
        log_body.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        self.log_box = tk.Text(
            log_body,
            bg="#080c13",
            fg="#cbd3df",
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            font=("Consolas", 9),
            padx=12,
            pady=10,
            wrap="word",
        )
        log_scroll = ttk.Scrollbar(
            log_body,
            orient="vertical",
            command=self.log_box.yview,
            style="Cleanup.Vertical.TScrollbar",
        )
        self.log_box.configure(yscrollcommand=log_scroll.set)
        self.log_box.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

        tk.Label(
            log_card,
            text=f"DELETE LOG  //  {CLEANUP_LOG_FILE}",
            fg=MUTED,
            bg=TABLE_BG,
            font=("Consolas", 8),
        ).pack(anchor="w", padx=14, pady=(0, 10))

        self.arm_btn.config(state="disabled")
        self.stop_btn.config(state="disabled")

    def _toggle_delete_all(self):
        self.count_entry.config(state="disabled" if self.delete_all_var.get() else "normal")

    def _cleanup_options(self) -> CleanupOptions:
        delete_all = self.delete_all_var.get()
        try:
            count = int(self.count_var.get())
        except ValueError as exc:
            raise ValueError("Delete count must be a whole number.") from exc
        try:
            delay = float(self.delay_var.get())
        except ValueError as exc:
            raise ValueError("Delay must be a number of seconds.") from exc
        if not delete_all and count <= 0:
            raise ValueError("Delete count must be at least 1, or tick DELETE ALL.")
        if delay < 0:
            raise ValueError("Delay cannot be negative.")
        return CleanupOptions(
            mode=self.mode_var.get(),
            delete_all=delete_all,
            max_actions=max(1, count),
            dry_run=self.dry_run_var.get(),
            delay_seconds=delay,
        )

    def start(self):
        if self.worker and self.worker.is_alive():
            self.write("A cleanup run is already active.")
            return
        try:
            options = self._cleanup_options()
        except Exception as exc:
            messagebox.showerror("TikTok Cleanup", str(exc), parent=self.winfo_toplevel())
            return

        if not options.dry_run:
            if options.delete_all:
                prompt = (
                    f"DELETE ALL matching {options.mode.upper()} from this TikTok account?\n\n"
                    "This cannot be undone. Pulse will continue batch-by-batch until none remain."
                )
            else:
                prompt = (
                    f"Delete up to {options.max_actions} matching {options.mode.upper()} "
                    "from this TikTok account?\n\nThis cannot be undone."
                )
            if not messagebox.askyesno("LIVE TIKTOK CLEANUP", prompt, parent=self.winfo_toplevel()):
                return

        self.stop_event.clear()
        self.arm_event.clear()
        self._set_locked(True)
        self.stop_btn.config(state="normal")
        self.browser_var.set(_cleanup_browser_status())
        self.worker = threading.Thread(
            target=self._worker,
            args=(options,),
            daemon=True,
        )
        self.worker.start()

    def _worker(self, options: CleanupOptions):
        try:
            run_cleanup(
                options,
                log=self.write,
                stop_event=self.stop_event,
                arm_event=self.arm_event,
                state=self._set_state_from_worker,
            )
        except Exception as exc:
            self.write(f"ERROR | {exc}")
        finally:
            self._set_state_from_worker("idle")

    def arm(self):
        self.arm_event.set()

    def stop(self):
        if not (self.worker and self.worker.is_alive()):
            return
        self.stop_event.set()
        self.arm_event.set()
        self.write("STOP REQUESTED | waiting for the current safe action boundary.")
        self.status_var.set("STOP REQUESTED")

    def _set_state_from_worker(self, state: str):
        try:
            self.after(0, lambda: self._apply_state(state))
        except tk.TclError:
            pass

    def _apply_state(self, state: str):
        if self._destroyed:
            return
        if state == "attaching":
            self.status_var.set("ATTACHING // SCANNING TIKTOK STUDIO")
            self.status_label.config(fg=ACCENT)
            self.arm_btn.config(state="disabled")
            self.stop_btn.config(state="normal")
        elif state == "armed":
            mode = "PREVIEW" if self.dry_run_var.get() else "LIVE DELETE"
            target = "ALL" if self.delete_all_var.get() else self.count_var.get()
            self.status_var.set(f"ARMED // {mode} // {self.mode_var.get().upper()} // {target}")
            self.status_label.config(fg=SUCCESS if self.dry_run_var.get() else DANGER)
            self.arm_btn.config(state="normal")
        elif state == "running":
            self.status_var.set("RUNNING // " + ("PREVIEW ONLY" if self.dry_run_var.get() else "REAL DELETES"))
            self.status_label.config(fg=SUCCESS if self.dry_run_var.get() else DANGER)
            self.arm_btn.config(state="disabled")
        else:
            self.status_var.set("READY // SAFE MODE")
            self.status_label.config(fg=SUCCESS)
            self.arm_btn.config(state="disabled")
            self.stop_btn.config(state="disabled")
            self._set_locked(False)
            self._toggle_delete_all()
            self.browser_var.set(_cleanup_browser_status())

    def _set_locked(self, locked: bool):
        state = "disabled" if locked else "normal"
        for widget in (
            self.mode_menu,
            self.count_entry,
            self.delay_entry,
            self.delete_all_check,
            self.dry_check,
            self.scan_btn,
        ):
            try:
                widget.config(state=state)
            except Exception:
                pass

    def write(self, message: str):
        def apply():
            if self._destroyed or not self.winfo_exists():
                return
            self.log_box.insert(tk.END, message + "\n")
            self.log_box.see(tk.END)

        try:
            self.after(0, apply)
        except tk.TclError:
            pass

    def _clear_log(self):
        self.log_box.delete("1.0", tk.END)

    def _on_destroy(self, event):
        if event.widget is self:
            self._destroyed = True
            self.stop_event.set()
            self.arm_event.set()
            if getattr(self, "_ambient_after_id", None) is not None:
                try:
                    self.after_cancel(self._ambient_after_id)
                except tk.TclError:
                    pass
                self._ambient_after_id = None


def open_cleanup_window(parent: tk.Misc) -> tk.Toplevel:
    window = tk.Toplevel(parent)
    window.title("Pulse Social — TikTok Cleanup")
    window.geometry("980x780")
    window.minsize(860, 700)
    window.configure(bg=BG)

    view = TikTokCleanupView(window)
    view.pack(fill="both", expand=True)

    def close():
        view.stop()
        window.destroy()

    window.protocol("WM_DELETE_WINDOW", close)
    return window
