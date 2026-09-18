from __future__ import annotations

import os
import socket
import subprocess
import time
from pathlib import Path

CDP_PORT = 9222
X_URL = "https://x.com/home"


def _port_open(port: int = CDP_PORT) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.35)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _running(image_name: str) -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}"],
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=3,
        )
        return image_name.lower() in result.stdout.lower()
    except Exception:
        return False


def _browser_candidates() -> list[tuple[str, str, Path]]:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    program_files = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    program_files_x86 = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
    return [
        ("Brave", "brave.exe", program_files / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"),
        ("Brave", "brave.exe", local / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"),
        ("Chrome", "chrome.exe", program_files / "Google" / "Chrome" / "Application" / "chrome.exe"),
        ("Chrome", "chrome.exe", program_files_x86 / "Google" / "Chrome" / "Application" / "chrome.exe"),
    ]


def preferred_browser() -> tuple[str, str, Path] | None:
    for item in _browser_candidates():
        if item[2].exists():
            return item
    return None


def browser_status() -> str:
    if _port_open():
        return "CONNECTED // CDP :9222"
    found = preferred_browser()
    if not found:
        return "NO SUPPORTED BROWSER FOUND"
    name, image, _path = found
    if _running(image):
        return f"{name.upper()} OPEN // NOT CONTROLLABLE"
    return f"{name.upper()} READY TO LAUNCH"


def open_x_browser(restart_existing: bool = False) -> tuple[bool, str]:
    if _port_open():
        return True, "CONNECTED // CDP :9222"

    found = preferred_browser()
    if not found:
        return False, "No supported Brave/Chrome installation was found."

    name, image, exe = found
    if _running(image):
        if not restart_existing:
            return False, f"{name} is already open without Pulse control."
        try:
            subprocess.run(
                ["taskkill", "/IM", image, "/F"],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=8,
            )
            time.sleep(1.5)
        except Exception as exc:
            return False, f"Could not restart {name}: {exc}"

    args = [
        str(exe),
        f"--remote-debugging-port={CDP_PORT}",
        "--restore-last-session",
        X_URL,
    ]
    try:
        subprocess.Popen(args)
    except Exception as exc:
        return False, f"Could not start {name}: {exc}"

    deadline = time.time() + 10
    while time.time() < deadline:
        if _port_open():
            return True, f"CONNECTED // {name.upper()} CDP :{CDP_PORT}"
        time.sleep(0.4)

    return False, f"{name} opened, but CDP :{CDP_PORT} did not become available."
