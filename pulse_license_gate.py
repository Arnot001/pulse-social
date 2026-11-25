from __future__ import annotations

import json
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from pulse_licensing import (LicensingError, LicensingUnavailable, activate,
                             start_registration, verify_registration)


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

    return str(data.get("licence_key") or "").strip() if isinstance(data, dict) else ""


def save_licence_key(licence_key: str) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    temporary = LICENCE_FILE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"licence_key": licence_key.strip()}, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, LICENCE_FILE)


def clear_saved_licence_key() -> None:
    try:
        LICENCE_FILE.unlink()
    except FileNotFoundError:
        pass


def _friendly_error(exc: LicensingError) -> str:
    messages = {
        "INVALID_EMAIL": "Enter a valid email address.",
        "INVALID_CODE": "That code is incorrect, expired or already used. Try again or request a new code.",
        "RATE_LIMITED": "Too many requests or today's email limit has been reached. Please try later.",
        "TRANSFER_LIMITED": "Recovery transfers are limited to once every 24 hours. Please try later.",
        "RECOVERY_NOT_FOUND": "No licence is linked to this email. Use free beta access, or link your existing key from Licence / Account.",
        "LINK_UNAVAILABLE": "This key could not be linked. Use its active PC and an email not linked to another licence.",
        "EMAIL_UNAVAILABLE": "Email delivery is temporarily unavailable. Wait a minute before requesting another code.",
        "REGISTRATION_UNAVAILABLE": "Email registration is not available yet. Please try later or enter an existing key.",
    }
    if exc.code in messages:
        return messages[exc.code]
    if isinstance(exc, LicensingUnavailable) or (exc.status is not None and exc.status >= 500):
        return "Pulse Licensing is temporarily unavailable. Please try again."
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


class LicenceScreen:
    """Tk only touches controls on its main thread; workers return through a queue."""

    def __init__(self, root, on_active, *, saved_key="", link_key=""):
        self.root, self.on_active = root, on_active
        self.busy = False
        self.timer = None
        self.results = queue.Queue()
        self.challenge = ""
        self.link_key = link_key
        self.intent = "access"
        root.title("Pulse Social // Licence")
        root.geometry("560x600")
        root.resizable(False, False)
        root.configure(bg=BG)
        self.panel = tk.Frame(root, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        self.panel.pack(fill="both", expand=True, padx=24, pady=24)
        tk.Label(self.panel, text="PULSE", fg=TEXT, bg=PANEL,
                 font=("Segoe UI Variable Display", 26, "bold")).pack(pady=(24, 0))
        tk.Label(self.panel, text="SOCIAL // BETA ACCESS", fg=ACCENT_2, bg=PANEL,
                 font=("Segoe UI", 10, "bold")).pack(pady=(0, 18))
        self.status = tk.StringVar(root, value="One licence · One active device")
        tk.Label(self.panel, textvariable=self.status, fg=MUTED, bg=PANEL,
                 font=("Segoe UI", 10), wraplength=440, justify="center").pack(padx=24, pady=(0, 14))
        self.content = tk.Frame(self.panel, bg=PANEL)
        self.content.pack(fill="both", expand=True, padx=30)
        self.controls = []
        self.primary = None
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Return>", lambda _event: self.primary.invoke() if self.primary and not self.busy else None)
        root.bind("<Destroy>", self.destroyed, add="+")
        self.home()
        if link_key:
            self.email_form("link")
        elif saved_key:
            self.run(lambda: self.activate_and_save(saved_key), self.finished, "Checking saved activation...")

    def reset(self):
        for widget in self.content.winfo_children():
            widget.destroy()
        self.controls = []
        self.primary = None

    def label(self, text):
        tk.Label(self.content, text=text, bg=PANEL, fg=MUTED, wraplength=420,
                 font=("Segoe UI", 10), justify="center").pack(pady=(4, 8))

    def button(self, text, command, primary=False):
        button = tk.Button(self.content, text=text, command=command, bg=ACCENT if primary else BG,
                           fg=TEXT, activebackground=ACCENT_2, activeforeground=TEXT, relief="flat",
                           font=("Segoe UI", 10, "bold"), cursor="hand2", pady=11)
        button.pack(fill="x", pady=6)
        self.controls.append(button)
        if primary:
            self.primary = button
        return button

    def entry(self, secret=False):
        value = tk.StringVar(self.root)
        entry = tk.Entry(self.content, textvariable=value, bg=BG, fg=TEXT, insertbackground=TEXT,
                         relief="flat", font=("Consolas", 12), justify="center", show="•" if secret else "",
                         highlightthickness=1, highlightbackground=BORDER, highlightcolor=CYAN)
        entry.pack(fill="x", ipady=9, pady=8)
        menu = tk.Menu(entry, tearoff=False)
        for label, event in [("Cut", "<<Cut>>"), ("Copy", "<<Copy>>"), ("Paste", "<<Paste>>")]:
            menu.add_command(label=label, command=lambda event=event: entry.event_generate(event))
        menu.add_command(label="Select All", command=lambda: entry.selection_range(0, tk.END))
        def popup(event):
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()
        entry.bind("<Button-3>", popup)
        self.controls.append(entry)
        entry.focus_set()
        return value

    def home(self):
        if self.busy:
            return
        self.reset()
        self.button("GET FREE BETA ACCESS", lambda: self.email_form("access"), True)
        self.label("ALREADY HAVE A KEY?")
        self.button("ENTER EXISTING LICENCE KEY", self.manual_form)
        self.button("RECOVER ACCESS / REPLACED PC", lambda: self.email_form("transfer"))
        self.label("Returning on the same PC? Use your email to restore access.\n"
                   "To move normally, deactivate your old PC in Licence / Account first.")

    def manual_form(self):
        self.reset()
        self.label("Enter your existing Pulse Social licence key.")
        self.key = self.entry(secret=True)
        def submit():
            key = self.key.get().strip()
            if not key:
                self.status.set("Enter your Pulse Social licence key.")
                return
            self.run(lambda: self.activate_and_save(key), self.finished, "Checking licence...")
        self.button("ACTIVATE", submit, True)
        self.button("BACK", self.home)

    def email_form(self, intent):
        self.reset()
        self.intent, self.challenge = intent, ""
        self.label("LINK EMAIL FOR RECOVERY" if intent == "link" else
                   "RECOVER ON A REPLACEMENT PC" if intent == "transfer" else "GET FREE BETA ACCESS")
        self.label("Enter the email address you want to use for Pulse Social.")
        self.email = self.entry()
        if intent == "transfer":
            self.label("Verifying will disconnect the old PC and move its licence here.\n"
                       "Recovery transfers are limited to once every 24 hours.")
        else:
            self.label("We'll send an 8-digit code. It expires in 10 minutes.")
        self.button("SEND VERIFICATION CODE", self.send_code, True)
        self.button("BACK", self.home)

    def send_code(self):
        if self.busy:
            return
        email = self.email.get().strip()
        if not email or "@" not in email:
            self.status.set("Enter a valid email address.")
            return
        if self.intent == "transfer":
            self.busy = True  # Guard the confirmation dialog's nested Tk event loop.
            try:
                confirmed = messagebox.askyesno(
                    "Recover on this PC?", "After email verification, the old PC will lose access. Continue?",
                    parent=self.root, default="no")
            finally:
                self.busy = False
            if not confirmed:
                return
        intent, key = self.intent, self.link_key
        self.run(lambda: start_registration(email, intent, key), self.code_form, "Sending verification code...")

    def code_form(self, challenge):
        self.challenge = challenge
        self.reset()
        self.status.set("Code sent. Check your inbox and spam folder.")
        self.label("Enter your 8-digit verification code.")
        self.code = self.entry()
        self.button("VERIFY & ACTIVATE", self.verify, True)
        self.button("REQUEST A NEW CODE", lambda: self.email_form(self.intent))
        self.button("BACK", self.home)

    def verify(self):
        code = self.code.get().strip()
        if len(code) != 8 or not code.isascii() or not code.isdigit():
            self.status.set("Enter the 8-digit code from your email.")
            return
        challenge, key = self.challenge, self.link_key
        def work():
            recovered = verify_registration(challenge, code, key)
            save_licence_key(recovered)
        self.run(work, self.finished, "Verifying email and activating this PC...")

    @staticmethod
    def activate_and_save(key):
        activate(key)
        save_licence_key(key)

    def finished(self, _value):
        self.on_active()

    def run(self, work, done, message):
        if self.busy:
            return
        self.busy = True
        self.status.set(message)
        for control in self.controls:
            control.configure(state="disabled")
        def worker():
            try:
                self.results.put((True, work()))
            except Exception as exc:
                self.results.put((False, exc))
        threading.Thread(target=worker, daemon=True).start()
        def poll():
            self.timer = None
            try:
                success, value = self.results.get_nowait()
            except queue.Empty:
                self.timer = self.root.after(100, poll)
                return
            self.busy = False
            for control in self.controls:
                control.configure(state="normal")
            if success:
                done(value)
            elif isinstance(value, LicensingError):
                self.status.set(_friendly_error(value))
            elif isinstance(value, OSError):
                self.status.set("Activation succeeded, but access could not be saved on this PC. Check folder permissions, then recover using your email.")
            else:
                self.status.set("Pulse Social could not complete this request. Please try again.")
        self.timer = self.root.after(100, poll)

    def close(self):
        if not self.busy:
            self.root.destroy()

    def destroyed(self, event):
        if event.widget == self.root and self.timer is not None:
            self.root.after_cancel(self.timer)
            self.timer = None


def require_licence() -> bool:
    result = {"allowed": False}
    root = tk.Tk()
    def allowed():
        result["allowed"] = True
        root.destroy()
    LicenceScreen(root, allowed, saved_key=load_saved_licence_key())
    root.mainloop()
    return result["allowed"]


def link_recovery_email(parent):
    window = tk.Toplevel(parent)
    window.transient(parent)
    window.grab_set()
    def linked():
        messagebox.showinfo("Email linked", "Your email is verified and linked. Use it to recover access after reinstalling or replacing this PC.", parent=window)
        window.destroy()
    LicenceScreen(window, linked, link_key=load_saved_licence_key())
    def restore_grab(event):
        if event.widget == window and parent.winfo_exists():
            parent.grab_set()
    window.bind("<Destroy>", restore_grab, add="+")
    return window
