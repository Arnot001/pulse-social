from __future__ import annotations

import json
import secrets
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from platforms.browser_control import APP_DIR

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 8766
BRIDGE_URL = f"http://{BRIDGE_HOST}:{BRIDGE_PORT}"
# Allow a 30-second MV3 alarm interval plus scheduling jitter.
PDH_WAKE_ALLOWANCE_SECONDS = 35.0
PDH_HEARTBEAT_SECONDS = 75.0
TOKEN_FILE = APP_DIR / "pdh_bridge_token.txt"

_lock = threading.Condition()
_commands: deque[dict[str, Any]] = deque()
_results: dict[str, dict[str, Any]] = {}
_claims: dict[str, str] = {}
_pdh_last_seen = 0.0
_server: ThreadingHTTPServer | None = None
_server_thread: threading.Thread | None = None


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _token() -> str:
    if TOKEN_FILE.exists():
        value = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(value, encoding="utf-8")
    return value


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    try:
        size = int(handler.headers.get("Content-Length") or "0")
    except ValueError:
        size = 0
    if size <= 0 or size > 1_000_000:
        return {}
    try:
        payload = json.loads(handler.rfile.read(size).decode("utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


class _Handler(BaseHTTPRequestHandler):
    server_version = "PulsePDHBridge/1.0"

    def log_message(self, _format: str, *_args) -> None:
        return

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        global _pdh_last_seen

        if self.path == "/status":
            with _lock:
                age = time.time() - _pdh_last_seen if _pdh_last_seen else None
            self._send(
                200,
                {
                    "running": True,
                    "pdhConnected": bool(age is not None and age < PDH_HEARTBEAT_SECONDS),
                    "pdhAgeSeconds": age,
                },
            )
            return

        if self.path.startswith("/pdh/next"):
            with _lock:
                _pdh_last_seen = time.time()
                deadline = time.time() + 20.0
                while not _commands and time.time() < deadline:
                    _lock.wait(timeout=max(0.0, deadline - time.time()))
                _pdh_last_seen = time.time()
                if not _commands:
                    self._send(200, {"command": None})
                    return
                command = _commands.popleft()
                request_id = str(command.get("requestId") or "")
                claim = secrets.token_urlsafe(18)
                _claims[request_id] = claim
            self._send(200, {"command": command, "claim": claim})
            return

        self._send(404, {"error": "not_found"})

    def do_POST(self) -> None:
        global _pdh_last_seen
        payload = _read_json(self)

        if self.path == "/command":
            if self.headers.get("X-Pulse-Token") != _token():
                self._send(403, {"error": "forbidden"})
                return

            request_id = str(payload.get("requestId") or "").strip()
            operation = str(payload.get("operation") or "").strip()
            if not request_id or not operation:
                self._send(400, {"error": "invalid_command"})
                return

            timeout_seconds = float(payload.pop("_timeoutSeconds", 20.0) or 20.0)
            timeout_seconds = max(1.0, min(timeout_seconds, 60.0))

            with _lock:
                _commands.append(payload)
                _lock.notify_all()
                deadline = time.time() + timeout_seconds
                while request_id not in _results and time.time() < deadline:
                    _lock.wait(timeout=max(0.0, deadline - time.time()))
                result = _results.pop(request_id, None)
                if result is None:
                    # Never execute a queued command after its caller timed out.
                    try:
                        _commands.remove(payload)
                    except ValueError:
                        pass  # Already claimed; never enqueue/replay it.

            if result is None:
                self._send(504, {"error": "pdh_timeout", "requestId": request_id})
                return

            self._send(200, result)
            return

        if self.path == "/pdh/result":
            request_id = str(payload.get("requestId") or "").strip()
            claim = str(payload.get("claim") or "").strip()
            result = payload.get("result")
            with _lock:
                expected = _claims.get(request_id)
                if not request_id or not expected or not secrets.compare_digest(claim, expected):
                    self._send(403, {"error": "invalid_claim"})
                    return
                _claims.pop(request_id, None)
                _pdh_last_seen = time.time()
                _results[request_id] = result if isinstance(result, dict) else {
                    "handled": True,
                    "successful": False,
                    "mutated": False,
                    "verified": False,
                    "status": "INVALID_PDH_RESULT",
                }
                _lock.notify_all()
            self._send(200, {"ok": True})
            return

        self._send(404, {"error": "not_found"})


def bridge_status() -> dict[str, Any]:
    try:
        with urllib.request.urlopen(f"{BRIDGE_URL}/status", timeout=0.6) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def ensure_bridge_server() -> bool:
    global _server, _server_thread

    if bridge_status().get("running"):
        return True

    if _server_thread and _server_thread.is_alive():
        return True

    try:
        _token()
        _server = ThreadingHTTPServer((BRIDGE_HOST, BRIDGE_PORT), _Handler)
    except OSError:
        return bool(bridge_status().get("running"))

    _server_thread = threading.Thread(
        target=_server.serve_forever,
        name="pulse-pdh-bridge",
        daemon=True,
    )
    _server_thread.start()
    return True


def pdh_connected() -> bool:
    status = bridge_status()
    return bool(status.get("pdhConnected"))


def pdh_request(
    operation: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 20.0,
) -> dict[str, Any] | None:
    if not ensure_bridge_server():
        return None

    request_id = f"pulse-social-{int(time.time() * 1000)}-{secrets.token_hex(4)}"
    wait_timeout = max(1.0, min(float(timeout) + PDH_WAKE_ALLOWANCE_SECONDS, 60.0))
    command = {
        "requestId": request_id,
        "operation": str(operation or "").strip(),
        "payload": dict(payload or {}),
        "_timeoutSeconds": wait_timeout,
    }

    request = urllib.request.Request(
        f"{BRIDGE_URL}/command",
        data=_json_bytes(command),
        headers={
            "Content-Type": "application/json",
            "X-Pulse-Token": _token(),
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=wait_timeout + 2.0) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None

    return result if isinstance(result, dict) else None
