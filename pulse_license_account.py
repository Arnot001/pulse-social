"""Customer device release UI; the licensing server remains authoritative."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox

from pulse_license_gate import (ACCENT, ACCENT_2, BG, MUTED, PANEL, TEXT,
                                clear_saved_licence_key, load_saved_licence_key)
from pulse_licensing import LicensingError, LicensingUnavailable, deactivate

RELEASED_MESSAGE = "Licence released. You can now activate Pulse Social on another PC."


@dataclass(frozen=True)
class ReleaseResult:
    released: bool
    message: str
    local_cleared: bool = False


def release_this_device() -> ReleaseResult:
    """Clear the local key only after an explicit server-confirmed release."""
    try:
        key = load_saved_licence_key()
        if not key:
            return ReleaseResult(False, "No saved licence key was found on this PC.")
        response = deactivate(key)
        if (not isinstance(response, dict) or response.get("ok") is not True
                or response.get("status") != "DEACTIVATED"
                or response.get("transfer_ready") is not True):
            return ReleaseResult(False, "The licensing service did not confirm release. Your saved key has been kept.")
    except LicensingUnavailable:
        return ReleaseResult(False, "Pulse Licensing is temporarily unavailable. Your saved key has been kept. Try again.")
    except LicensingError as exc:
        errors = {
            "DEVICE_MISMATCH": "This licence is active on another device. It cannot be released from this PC.",
            "LICENCE_NOT_ACTIVE": "This licence is already inactive on the server.",
            "LICENCE_INVALID": "The saved licence key is not valid for Pulse Social.",
            "LICENCE_REVOKED": "This licence has been revoked.",
            "LICENCE_DISABLED": "This licence has been disabled.",
            "LICENCE_EXPIRED": "This licence has expired.",
            "DEVICE_ID_UNAVAILABLE": "Pulse Social could not identify this Windows device.",
        }
        message = errors.get(exc.code, "Pulse Social could not release this licence.")
        if exc.status is not None and exc.status >= 500:
            message = "Pulse Licensing is temporarily unavailable. Try again."
        return ReleaseResult(False, message + " Your saved key has been kept.")
    except Exception:
        # Do not expose server bodies, licence keys or device identifiers in UI.
        return ReleaseResult(False, "Pulse Social could not release this licence. Your saved key has been kept.")

    try:
        clear_saved_licence_key()
    except OSError:
        return ReleaseResult(True, "The server released this licence, but Pulse Social could not remove the saved key. "
                             "Pulse Social will close. Remove the saved key before reopening on this PC to avoid reactivation.")
    return ReleaseResult(True, RELEASED_MESSAGE, True)


def open_licence_account(parent: tk.Misc, on_released) -> tk.Toplevel:
    """One modal account dialog; network/file work never runs on the Tk thread."""
    existing = getattr(parent, "_pulse_licence_account", None)
    if existing is not None and existing.winfo_exists():
        existing.lift()
        return existing
    window = tk.Toplevel(parent)
    parent._pulse_licence_account = window
    window.title("Pulse Social // Licence")
    window.geometry("500x280")
    window.resizable(False, False)
    window.configure(bg=BG)
    window.transient(parent)
    window.grab_set()
    panel = tk.Frame(window, bg=PANEL)
    panel.pack(fill="both", expand=True, padx=20, pady=20)
    tk.Label(panel, text="LICENCE / ACCOUNT", bg=PANEL, fg=TEXT,
             font=("Segoe UI", 14, "bold")).pack(pady=(18, 10))
    tk.Label(panel, text="Device: THIS PC", bg=PANEL, fg=MUTED,
             font=("Segoe UI", 10)).pack()
    status = tk.StringVar(window, value="Release this device to move your licence to another PC.")
    tk.Label(panel, textvariable=status, bg=PANEL, fg=MUTED, wraplength=420,
             font=("Segoe UI", 9)).pack(padx=16, pady=12)
    results = queue.Queue()
    busy = False
    timer = None

    def close():
        if not busy:
            window.destroy()

    def destroyed(event):
        nonlocal timer
        if event.widget == window:
            if timer is not None:
                window.after_cancel(timer)
                timer = None
            parent._pulse_licence_account = None

    def poll():
        nonlocal busy, timer
        timer = None
        try:
            result = results.get_nowait()
        except queue.Empty:
            timer = window.after(100, poll)
            return
        if result.released:
            # Keep the dialog modal until all launcher-owned app windows close.
            try:
                notify = messagebox.showinfo if result.local_cleared else messagebox.showwarning
                notify("Pulse Social Licence", result.message, parent=window)
            finally:
                window.destroy()
                on_released()
            return
        busy = False
        status.set(result.message)
        deactivate_button.configure(state="normal")

    def submit():
        nonlocal busy, timer
        if busy:
            return
        # Lock even while the confirmation's nested Tk event loop is running.
        busy = True
        if not messagebox.askyesno(
            "Deactivate this device?",
            "Release your licence from this PC? Pulse Social and its open tool windows will close. "
            "Finish any running work first.", parent=window, default="no",
        ):
            busy = False
            return
        deactivate_button.configure(state="disabled")
        status.set("Releasing this device...")
        threading.Thread(target=lambda: results.put(release_this_device()), daemon=True).start()
        timer = window.after(100, poll)

    deactivate_button = tk.Button(panel, text="DEACTIVATE THIS DEVICE", command=submit,
                                  bg=ACCENT, fg=TEXT, activebackground=ACCENT_2,
                                  activeforeground=TEXT, relief="flat", padx=18, pady=10,
                                  font=("Segoe UI", 9, "bold"), cursor="hand2")
    deactivate_button.pack(pady=(4, 14))
    window.protocol("WM_DELETE_WINDOW", close)
    window.bind("<Destroy>", destroyed, add="+")
    return window
