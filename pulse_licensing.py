from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass

try:
    import winreg
except ImportError:
    winreg = None


API_BASE = "https://pulse-licensing.pulse-iq.workers.dev"
PRODUCT = "pulse_social"
TIMEOUT_SECONDS = 10


class LicensingError(RuntimeError):
    def __init__(self, code: str, message: str | None = None, status: int | None = None):
        self.code = code
        self.status = status
        super().__init__(message or code)


class LicensingUnavailable(LicensingError):
    pass


@dataclass(frozen=True)
class ActivationResult:
    status: str
    licence_id: str
    activation_id: str
    reused: bool


def windows_device_id() -> str:
    if winreg is None:
        raise LicensingError("DEVICE_ID_UNAVAILABLE", "Windows registry is unavailable.")

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
        ) as key:
            machine_guid, _ = winreg.QueryValueEx(key, "MachineGuid")
    except OSError as exc:
        raise LicensingError(
            "DEVICE_ID_UNAVAILABLE",
            "Could not read the Windows device identity.",
        ) from exc

    machine_guid = str(machine_guid).strip().lower()
    if not machine_guid:
        raise LicensingError("DEVICE_ID_UNAVAILABLE", "Windows device identity is empty.")

    # Never send the raw Windows MachineGuid to Pulse Licensing.
    material = f"pulse-device-v1:{machine_guid}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _post(path: str, licence_key: str, device_id: str | None = None) -> dict:
    key = str(licence_key or "").strip()
    if not key:
        raise LicensingError("LICENCE_KEY_REQUIRED", "Enter your Pulse licence key.")

    payload = {
        "licence_key": key,
        "product": PRODUCT,
        "device_id": device_id or windows_device_id(),
    }

    request = urllib.request.Request(
        f"{API_BASE}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Pulse-Social/1.0 Windows",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8")
            data = json.loads(body)
    except urllib.error.HTTPError as exc:
        try:
            data = json.loads(exc.read().decode("utf-8"))
        except Exception:
            data = {}

        code = str(data.get("error") or f"HTTP_{exc.code}")
        raise LicensingError(code, code, exc.code) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LicensingUnavailable(
            "LICENSING_UNAVAILABLE",
            "Pulse Licensing could not be reached.",
        ) from exc
    except (json.JSONDecodeError, ValueError) as exc:
        raise LicensingUnavailable(
            "INVALID_SERVER_RESPONSE",
            "Pulse Licensing returned an invalid response.",
        ) from exc

    if not data.get("ok"):
        code = str(data.get("error") or "LICENSING_ERROR")
        raise LicensingError(code)

    return data


def activate(licence_key: str, device_id: str | None = None) -> ActivationResult:
    data = _post("/activate", licence_key, device_id)
    return ActivationResult(
        status=str(data["status"]),
        licence_id=str(data["licence_id"]),
        activation_id=str(data["activation_id"]),
        reused=bool(data.get("reused", False)),
    )


def deactivate(licence_key: str, device_id: str | None = None) -> dict:
    return _post("/deactivate", licence_key, device_id)
