from __future__ import annotations

import json
import os
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from pulse_licensing import LicensingError, LicensingUnavailable, activate


APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Pulse Social"
LICENCE_FILE = APP_DIR / "licence.json"

BG = "#070910"
PANEL = "#101827"
BORDER = "#26354b"
TEXT = "#f8f9fc"
MUTED = "#93a0b4"
ACCENT = "#ff0a8a"
ACCENT_2 = "#ff48ad"
CYAN = "#27def5"
SUCCESS = "#31d27c"


def load_saved_licence_key() -> str:
    try:
        data = json.loads(LICENCE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return ""

    return str(data.get("licence_key") or "").strip()


def save_licence_key(licence_key: str) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    LICENCE_FILE.write_text(
        json.dumps({"licence_key": licence_key.strip()}, indent=2),
        encoding="utf-8",
    )


def clear_saved_licence_key() -> None:
    try:
        LICENCE_FILE.unlink()
    except FileNotFoundError:
        pass


def _friendly_error(exc: LicensingError) -> str:
    if exc.code == "LICENCE_ALREADY_ACTIVE":
        return "This licence is currently active on another device."
    if exc.code == "LICENCE_INVALID":
        return "That licence key is not valid for Pulse Social."
    if exc.code == "LICENCE_EXPIRED":
        return "This licence has expired."
    if exc.code in {"LICENCE_REVOKED", "LICENCE_DISABLED"}:
        return "This licence is no longer active."
    if exc.code == "DEVICE_ID_UNAVAILABLE":
        return "Pulse Social could not identify this Windows device."
    return "Pulse Social could not activate this licence."


def require_licence() -> bool:
    saved_key = load_saved_licence_key()

    if saved_key:
        try:
            activate(saved_key)
            return True
        except LicensingUnavailable:
            initial_error = "Pulse Licensing is temporarily unavailable."
        except LicensingError as exc:
            initial_error = _friendly_error(exc)
    else:
        initial_error = ""

    result = {"allowed": False}

    root = tk.Tk()
    root.title("Pulse Social // Licence")
    root.geometry("520x330")
    root.resizable(False, False)
    root.configure(bg=BG)

    frame = tk.Frame(
        root,
        bg=PANEL,
        highlightthickness=1,
        highlightbackground=BORDER,
    )
    frame.pack(fill="both", expand=True, padx=24, pady=24)

    tk.Label(
        frame,
        text="PULSE",
        fg=TEXT,
        bg=PANEL,
        font=("Segoe UI Variable Display", 26, "bold"),
    ).pack(pady=(26, 0))

    tk.Label(
        frame,
        text="SOCIAL // LICENCE",
        fg=ACCENT_2,
        bg=PANEL,
        font=("Segoe UI", 10, "bold"),
    ).pack(pady=(0, 18))

    status_var = tk.StringVar(
        value=initial_error or "Enter your Pulse Social licence key."
    )

    tk.Label(
        frame,
        textvariable=status_var,
        fg=MUTED,
        bg=PANEL,
        font=("Segoe UI", 9),
        wraplength=420,
        justify="center",
    ).pack(pady=(0, 14))

    key_var = tk.StringVar(value=saved_key)

    entry = tk.Entry(
        frame,
        textvariable=key_var,
        bg=BG,
        fg=TEXT,
        insertbackground=TEXT,
        relief="flat",
        font=("Consolas", 11),
        justify="center",
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=CYAN,
    )
    entry.pack(fill="x", padx=42, ipady=9)
    entry.focus_set()

    entry_menu = tk.Menu(entry, tearoff=False)
    entry_menu.add_command(label="Cut", command=lambda: entry.event_generate("<<Cut>>"))
    entry_menu.add_command(label="Copy", command=lambda: entry.event_generate("<<Copy>>"))
    entry_menu.add_command(label="Paste", command=lambda: entry.event_generate("<<Paste>>"))
    entry_menu.add_separator()

    def select_all() -> None:
        entry.selection_range(0, tk.END)
        entry.icursor(tk.END)

    entry_menu.add_command(label="Select All", command=select_all)

    def show_entry_menu(event) -> None:
        entry.focus_set()
        try:
            entry_menu.tk_popup(event.x_root, event.y_root)
        finally:
            entry_menu.grab_release()

    entry.bind("<Button-3>", show_entry_menu)

    def submit() -> None:
        licence_key = key_var.get().strip()
        if not licence_key:
            status_var.set("Enter your Pulse Social licence key.")
            return

        activate_button.configure(state="disabled")
        status_var.set("Checking licence...")
        root.update_idletasks()

        try:
            activate(licence_key)
        except LicensingUnavailable:
            status_var.set("Pulse Licensing is temporarily unavailable. Try again.")
        except LicensingError as exc:
            status_var.set(_friendly_error(exc))
        else:
            save_licence_key(licence_key)
            result["allowed"] = True
            root.destroy()
            return

        activate_button.configure(state="normal")

    activate_button = tk.Button(
        frame,
        text="ACTIVATE",
        command=submit,
        bg=ACCENT,
        fg=TEXT,
        activebackground=ACCENT_2,
        activeforeground=TEXT,
        relief="flat",
        bd=0,
        padx=24,
        pady=10,
        font=("Segoe UI", 9, "bold"),
        cursor="hand2",
    )
    activate_button.pack(pady=(18, 8))

    tk.Label(
        frame,
        text="One licence · One active device",
        fg=CYAN,
        bg=PANEL,
        font=("Segoe UI", 8, "bold"),
    ).pack()

    root.bind("<Return>", lambda _event: submit())
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()

    return bool(result["allowed"])
