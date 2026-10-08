from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Pulse Social"
APP_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = APP_DIR / "browser_control.json"
BROWSER_PROFILE_ROOT = APP_DIR / "BrowserProfiles"

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


def _profile_dir(spec: BrowserSpec) -> Path:
    return BROWSER_PROFILE_ROOT / spec.name.casefold()


def bundled_pdh_extension_dir() -> Path | None:
    """Return the release-bundled PDH extension when it is available."""
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "pdh_extension")

    override = os.environ.get("PULSE_PDH_EXTENSION_DIR", "").strip()
    if override:
        candidates.append(Path(override).expanduser())

    for candidate in candidates:
        if (candidate / "manifest.json").is_file():
            return candidate.resolve()
    return None


def _launch_args(spec: BrowserSpec, exe: Path, start_url: str | None = None) -> list[str]:
    profile_dir = _profile_dir(spec)
    args = [
        str(exe),
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={profile_dir}",
        "--restore-last-session",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    pdh_extension = bundled_pdh_extension_dir()
    if pdh_extension is not None:
        args.append(f"--load-extension={pdh_extension}")
    if start_url:
        args.append(start_url)
    return args


def _save_state(name: str) -> None:
    spec = browser_spec(name)
    STATE_FILE.write_text(
        json.dumps(
            {
                "browser": name,
                "port": CDP_PORT,
                "profile": str(_profile_dir(spec)) if spec is not None else None,
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
    return None


def choose_browser_name(preferred: str | None = None) -> str | None:
    if browser_spec(preferred) is not None:
        return browser_spec(preferred).name

    # What the user is actually running now wins over an old saved choice.
    running = running_browser_names()
    if running:
        return running[0]

    saved = dedicated_browser_name()
    if saved:
        return saved

    installed = installed_browser_names()
    return installed[0] if installed else None


def browser_status() -> str:
    dedicated = dedicated_browser_name()

    if cdp_responding():
        name = dedicated or "PULSE BROWSER"
        return f"{name.upper()} // CONNECTED // CDP :{CDP_PORT}"

    running = running_browser_names()
    if len(running) == 1:
        return f"{running[0].upper()} OPEN // READY TO ATTACH"

    if len(running) > 1:
        return "CHOOSE OPEN BROWSER // " + " / ".join(name.upper() for name in running)

    installed = installed_browser_names()
    if dedicated and dedicated in installed:
        return f"{dedicated.upper()} // PULSE PROFILE READY TO LAUNCH"

    if installed:
        return f"{installed[0].upper()} READY TO LAUNCH"

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


def _pulse_browser_pids(spec: BrowserSpec) -> list[int]:
    """Find only the browser root processes launched with Pulse's dedicated profile."""
    env = os.environ.copy()
    env["PULSE_PROFILE_MATCH"] = str(_profile_dir(spec))
    env["PULSE_BROWSER_IMAGE"] = spec.image
    script = (
        "$profile=$env:PULSE_PROFILE_MATCH; "
        "$image=$env:PULSE_BROWSER_IMAGE; "
        "Get-CimInstance Win32_Process | Where-Object { "
        "$_.Name -ieq $image -and $_.CommandLine -and "
        "$_.CommandLine -like '*--remote-debugging-port=9222*' -and "
        "$_.CommandLine -like ('*--user-data-dir=' + $profile + '*') "
        "} | ForEach-Object { $_.ProcessId }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=10,
        )
        if result.returncode != 0:
            return []
        pids = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.isdigit():
                pids.append(int(line))
        return pids
    except Exception:
        return []


def stop_pulse_browser(browser_name: str | None = None) -> tuple[bool, str]:
    """Stop only the dedicated Pulse-profile browser, never the user's normal browser."""
    chosen = browser_name or dedicated_browser_name()
    spec = browser_spec(chosen)
    if spec is None:
        return False, "No dedicated Pulse browser is recorded."

    pids = _pulse_browser_pids(spec)
    if not pids:
        if not cdp_responding():
            return True, "Pulse browser is already stopped."
        return False, "Pulse browser control is responding, but its dedicated profile process could not be identified safely."

    errors = []
    for pid in pids:
        try:
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=10,
            )
            if result.returncode not in (0, 128):
                detail = (result.stderr or result.stdout or "").strip()
                errors.append(detail or f"taskkill returned {result.returncode} for PID {pid}")
        except Exception as exc:
            errors.append(str(exc))

    if errors:
        return False, "; ".join(errors)

    deadline = time.time() + 8
    while time.time() < deadline:
        if not cdp_responding():
            return True, "Dedicated Pulse browser stopped."
        time.sleep(0.25)
    return False, "Dedicated Pulse browser process stopped, but CDP :9222 is still responding."


def restart_pulse_browser(
    browser_name: str | None = None,
    *,
    start_url: str | None = None,
) -> tuple[bool, str]:
    """Recover a wedged CDP session by restarting only Pulse's dedicated profile."""
    chosen = browser_name or dedicated_browser_name()
    if not chosen:
        return False, "No dedicated Pulse browser is recorded."
    ok, message = stop_pulse_browser(chosen)
    if not ok:
        return False, message
    return connect_browser(chosen, start_url=start_url)


def connect_browser(
    browser_name: str | None = None,
    *,
    restart_existing: bool = False,
    start_url: str | None = None,
) -> tuple[bool, str]:
    """Make one supported Chromium browser the persistent Pulse browser.

    Pulse launches a dedicated persistent user-data directory. Modern Chrome
    ignores remote-debugging flags against the normal default profile, and the
    separate Pulse profile lets the user's everyday browser remain open.

    If a working CDP endpoint already exists on :9222, Pulse simply adopts it.
    restart_existing is retained for caller compatibility and no longer means
    the user's normal browser process must be killed.
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

    # Use a separate Pulse profile so CDP works on modern Chromium builds and
    # the user's everyday browser profile can remain open at the same time.
    profile_dir = _profile_dir(spec)
    profile_dir.mkdir(parents=True, exist_ok=True)

    _save_state(spec.name)
    args = _launch_args(spec, exe, start_url)

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
        f"{spec.name} Pulse profile opened, but browser control on CDP :{CDP_PORT} "
        "did not become ready.",
    )
