from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Pulse Social"
APP_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = APP_DIR / "browser_control.json"

CDP_PORT = 9222
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"


@dataclass(frozen=True)
class BrowserSpec:
    name: str
    image: str
    paths: tuple[Path, ...]


def _browser_specs() -> tuple[BrowserSpec, ...]:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    program_files = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    program_files_x86 = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))

    return (
        BrowserSpec(
            "Brave",
            "brave.exe",
            (
                program_files / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
                local / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
            ),
        ),
        BrowserSpec(
            "Chrome",
            "chrome.exe",
            (
                program_files / "Google" / "Chrome" / "Application" / "chrome.exe",
                program_files_x86 / "Google" / "Chrome" / "Application" / "chrome.exe",
                local / "Google" / "Chrome" / "Application" / "chrome.exe",
            ),
        ),
        BrowserSpec(
            "Edge",
            "msedge.exe",
            (
                program_files / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                program_files_x86 / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            ),
        ),
    )


def _installed_exe(spec: BrowserSpec) -> Path | None:
    for path in spec.paths:
        if path.exists():
            return path
    return None


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


def port_open(port: int = CDP_PORT) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.35)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def cdp_responding() -> bool:
    if not port_open():
        return False
    try:
        with urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return bool(payload.get("webSocketDebuggerUrl"))
    except Exception:
        return False


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _save_state(name: str) -> None:
    STATE_FILE.write_text(
        json.dumps(
            {
                "browser": name,
                "port": CDP_PORT,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def browser_spec(name: str | None) -> BrowserSpec | None:
    clean = (name or "").strip().casefold()
    if not clean:
        return None
    for spec in _browser_specs():
        if spec.name.casefold() == clean:
            return spec
    return None


def installed_browser_names() -> list[str]:
    return [
        spec.name
        for spec in _browser_specs()
        if _installed_exe(spec) is not None
    ]


def running_browser_names() -> list[str]:
    return [
        spec.name
        for spec in _browser_specs()
        if _installed_exe(spec) is not None and _running(spec.image)
    ]


def dedicated_browser_name() -> str | None:
    saved = str(_load_state().get("browser") or "").strip()
    if browser_spec(saved) is not None:
        return saved

    running = running_browser_names()
    if len(running) == 1:
        return running[0]
    return None


def choose_browser_name(preferred: str | None = None) -> str | None:
    if browser_spec(preferred) is not None:
        return browser_spec(preferred).name

    saved = dedicated_browser_name()
    if saved:
        return saved

    running = running_browser_names()
    if running:
        return running[0]

    installed = installed_browser_names()
    return installed[0] if installed else None


def browser_status() -> str:
    dedicated = dedicated_browser_name()

    if cdp_responding():
        name = dedicated or choose_browser_name() or "BROWSER"
        if dedicated is None and name != "BROWSER":
            _save_state(name)
        return f"{name.upper()} // CONNECTED // CDP :{CDP_PORT}"

    running = running_browser_names()
    if dedicated and dedicated in running:
        return f"{dedicated.upper()} OPEN // NEEDS PULSE ATTACH"

    if len(running) == 1:
        return f"{running[0].upper()} OPEN // READY TO ATTACH"

    if len(running) > 1:
        return "CHOOSE OPEN BROWSER // " + " / ".join(name.upper() for name in running)

    installed = installed_browser_names()
    if installed:
        name = dedicated if dedicated in installed else installed[0]
        return f"{name.upper()} READY TO LAUNCH"

    return "NO SUPPORTED CHROMIUM BROWSER FOUND"


def _kill_browser(spec: BrowserSpec) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["taskkill", "/IM", spec.image, "/F"],
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=10,
        )
        if result.returncode not in (0, 128):
            detail = (result.stderr or result.stdout or "").strip()
            return False, detail or f"taskkill returned {result.returncode}"
        return True, ""
    except Exception as exc:
        return False, str(exc)


def connect_browser(
    browser_name: str | None = None,
    *,
    restart_existing: bool = False,
    start_url: str | None = None,
) -> tuple[bool, str]:
    """Make one supported Chromium browser the persistent Pulse browser.

    If a working CDP endpoint already exists on :9222, Pulse simply adopts it.
    If the chosen browser is open normally, a restart is required because CDP
    cannot be added to an already-running Chromium process.
    """
    chosen = choose_browser_name(browser_name)

    if cdp_responding():
        if chosen:
            _save_state(chosen)
            return True, f"{chosen.upper()} // CONNECTED // CDP :{CDP_PORT}"
        return True, f"CONNECTED // CDP :{CDP_PORT}"

    if not chosen:
        return False, "No supported Brave, Chrome or Edge installation was found."

    spec = browser_spec(chosen)
    if spec is None:
        return False, f"Unsupported browser: {chosen}"

    exe = _installed_exe(spec)
    if exe is None:
        return False, f"{spec.name} is not installed in a supported location."

    if _running(spec.image):
        if not restart_existing:
            return (
                False,
                f"{spec.name} is already open without Pulse control. "
                "Pulse needs to restart this browser once to enable its dedicated CDP session.",
            )
        ok, detail = _kill_browser(spec)
        if not ok:
            return False, f"Could not restart {spec.name}: {detail}"
        time.sleep(1.5)

    _save_state(spec.name)

    args = [
        str(exe),
        f"--remote-debugging-port={CDP_PORT}",
        "--restore-last-session",
    ]
    if start_url:
        args.append(start_url)

    try:
        subprocess.Popen(
            args,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        return False, f"Could not start {spec.name}: {exc}"

    deadline = time.time() + 15
    while time.time() < deadline:
        if cdp_responding():
            return True, f"{spec.name.upper()} // CONNECTED // CDP :{CDP_PORT}"
        time.sleep(0.4)

    return (
        False,
        f"{spec.name} opened, but Pulse browser control on CDP :{CDP_PORT} "
        "did not become ready.",
    )
