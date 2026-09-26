from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox

from platforms.browser_control import browser_status

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
        self.browser_var = tk.StringVar(value=browser_status())

        self._build()
        self.bind("<Destroy>", self._on_destroy, add="+")

    def _button(self, parent, text, command, *, accent=False, danger=False, width=None):
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
            padx=14,
            pady=8,
            width=width,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )

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
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=26, pady=(22, 12))
        tk.Label(header, text="PULSE", fg=TEXT, bg=BG, font=("Segoe UI", 24, "bold")).pack(side="left")
        tk.Label(header, text=" SOCIAL", fg=ACCENT_2, bg=BG, font=("Segoe UI", 24, "bold")).pack(side="left")
        tk.Label(
            header,
            text="TIKTOK CLEANUP  //  NUKE CONTROL",
            fg=MUTED,
            bg=BG,
            font=("Consolas", 9),
        ).pack(side="right", pady=10)

        browser = tk.Frame(self, bg=PANEL_2)
        browser.pack(fill="x", padx=26, pady=(0, 10))
        tk.Label(browser, text="●", fg=ACCENT, bg=PANEL_2, font=("Segoe UI", 9, "bold")).pack(
            side="left", padx=(12, 4), pady=8
        )
        tk.Label(
            browser,
            textvariable=self.browser_var,
            fg=TEXT,
            bg=PANEL_2,
            font=("Consolas", 8, "bold"),
        ).pack(side="left", padx=(0, 12), pady=8)
        tk.Label(
            browser,
            text="USES YOUR TIKTOK STUDIO LOGIN",
            fg=MUTED,
            bg=PANEL_2,
            font=("Consolas", 8),
        ).pack(side="right", padx=12)

        card = tk.Frame(self, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill="x", padx=26, pady=8)
        tk.Label(card, text="CLEANUP CONTROL", fg=TEXT, bg=PANEL, font=("Segoe UI", 12, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", padx=18, pady=(14, 12)
        )

        for label, row in (
            ("MODE", 1),
            ("DELETE COUNT", 2),
            ("DELAY / SEC", 3),
        ):
            tk.Label(card, text=label, fg=MUTED, bg=PANEL, font=("Consolas", 8, "bold")).grid(
                row=row, column=0, sticky="w", padx=18, pady=7
            )

        self.mode_menu = tk.OptionMenu(card, self.mode_var, "videos", "photos", "everything")
        self.mode_menu.config(
            bg=PANEL_2,
            fg=TEXT,
            activebackground=ACCENT_2,
            activeforeground=TEXT,
            relief="flat",
            width=16,
            highlightthickness=0,
        )
        self.mode_menu["menu"].config(bg=PANEL_2, fg=TEXT)
        self.mode_menu.grid(row=1, column=1, sticky="w", pady=7)

        self.count_entry = self._field(card, self.count_var)
        self.count_entry.grid(row=2, column=1, sticky="w", pady=7)
        self.delay_entry = self._field(card, self.delay_var)
        self.delay_entry.grid(row=3, column=1, sticky="w", pady=7)

        self.delete_all_check = tk.Checkbutton(
            card,
            text="  DELETE ALL MATCHING POSTS",
            variable=self.delete_all_var,
            command=self._toggle_delete_all,
            fg=DANGER,
            bg=PANEL,
            activebackground=PANEL,
            activeforeground=DANGER,
            selectcolor=PANEL_2,
            font=("Segoe UI", 9, "bold"),
        )
        self.delete_all_check.grid(row=4, column=0, columnspan=3, sticky="w", padx=14, pady=(8, 2))

        self.dry_check = tk.Checkbutton(
            card,
            text="  DRY RUN / PREVIEW ONLY",
            variable=self.dry_run_var,
            fg=SUCCESS,
            bg=PANEL,
            activebackground=PANEL,
            activeforeground=SUCCESS,
            selectcolor=PANEL_2,
            font=("Segoe UI", 9, "bold"),
        )
        self.dry_check.grid(row=5, column=0, columnspan=3, sticky="w", padx=14, pady=(2, 15))

        actions = tk.Frame(self, bg=BG)
        actions.pack(fill="x", padx=26, pady=8)
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
        self.arm_btn.pack(side="left", padx=8)
        self.stop_btn = self._button(
            actions,
            "STOP",
            self.stop,
            danger=True,
            width=10,
        )
        self.stop_btn.pack(side="right")

        status = tk.Frame(self, bg=PANEL_2)
        status.pack(fill="x", padx=26, pady=(4, 10))
        self.status_label = tk.Label(
            status,
            textvariable=self.status_var,
            fg=SUCCESS,
            bg=PANEL_2,
            font=("Consolas", 9, "bold"),
        )
        self.status_label.pack(side="left", padx=14, pady=8)
        tk.Label(
            status,
            text="STUDIO INVENTORY  •  EXACT DELETE CONFIRMATION REQUIRED",
            fg=MUTED,
            bg=PANEL_2,
            font=("Consolas", 8),
        ).pack(side="right", padx=14)

        log_card = tk.Frame(self, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        log_card.pack(fill="both", expand=True, padx=26, pady=(0, 22))
        log_head = tk.Frame(log_card, bg=PANEL)
        log_head.pack(fill="x", padx=14, pady=(12, 6))
        tk.Label(log_head, text="ACTIVITY STREAM", fg=TEXT, bg=PANEL, font=("Segoe UI", 11, "bold")).pack(
            side="left"
        )
        self._button(log_head, "CLEAR VIEW", self._clear_log).pack(side="right")

        self.log_box = tk.Text(
            log_card,
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
        self.log_box.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        tk.Label(
            log_card,
            text=f"DELETE LOG  //  {CLEANUP_LOG_FILE}",
            fg=MUTED,
            bg=PANEL,
            font=("Consolas", 8),
        ).pack(anchor="w", padx=14, pady=(0, 10))

        self.arm_btn.config(state="disabled")
        self.stop_btn.config(state="disabled")

    def _toggle_delete_all(self):
        self.count_entry.config(state="disabled" if self.delete_all_var.get() else "normal")

    def _options(self) -> CleanupOptions:
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
            options = self._options()
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
        self.browser_var.set(browser_status())
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
            self.browser_var.set(browser_status())

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


def open_cleanup_window(parent: tk.Misc) -> tk.Toplevel:
    window = tk.Toplevel(parent)
    window.title("Pulse Social — TikTok Cleanup")
    window.geometry("820x760")
    window.minsize(760, 690)
    window.configure(bg=BG)

    view = TikTokCleanupView(window)
    view.pack(fill="both", expand=True)

    def close():
        view.stop()
        window.destroy()

    window.protocol("WM_DELETE_WINDOW", close)
    return window
