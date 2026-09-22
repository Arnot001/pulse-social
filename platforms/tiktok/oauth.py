from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import string
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

import requests

APP_DIR = Path(os.environ["LOCALAPPDATA"]) / "Pulse Social"
APP_DIR.mkdir(parents=True, exist_ok=True)
OAUTH_SETTINGS_FILE = APP_DIR / "tiktok_oauth.json"

AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:3455/callback/"
DEFAULT_SCOPES = ("user.info.basic", "video.publish")
REQUEST_TIMEOUT = 45
TOKEN_REFRESH_SKEW_SECONDS = 300

_TOKEN_LOCK = threading.Lock()
_UNRESERVED = string.ascii_letters + string.digits + "-._~"


def _protect_secret(value: str) -> str:
    if os.name != "nt":
        raise RuntimeError("TikTok OAuth storage currently requires Windows.")
    try:
        import win32crypt
    except ImportError as exc:
        raise RuntimeError("pywin32 is required for secure TikTok OAuth storage.") from exc

    encrypted = win32crypt.CryptProtectData(
        value.encode("utf-8"),
        "Pulse Social TikTok OAuth",
        None,
        None,
        None,
        0,
    )[1]
    return base64.b64encode(encrypted).decode("ascii")


def _unprotect_secret(value: str) -> str:
    if os.name != "nt":
        raise RuntimeError("TikTok OAuth storage currently requires Windows.")
    try:
        import win32crypt
    except ImportError as exc:
        raise RuntimeError("pywin32 is required for secure TikTok OAuth storage.") from exc

    encrypted = base64.b64decode(value.encode("ascii"))
    clear = win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)[1]
    return clear.decode("utf-8")


def _load_settings() -> dict:
    if not OAUTH_SETTINGS_FILE.exists():
        return {}
    try:
        data = json.loads(OAUTH_SETTINGS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_settings(data: dict) -> None:
    OAUTH_SETTINGS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def save_app_credentials(
    client_key: str,
    client_secret: str,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
) -> None:
    key = client_key.strip()
    secret = client_secret.strip()
    redirect = redirect_uri.strip()
    if not key or not secret:
        raise ValueError("TikTok Client Key and Client Secret are both required.")
    parsed = urllib.parse.urlparse(redirect)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("Desktop redirect URI must use localhost or 127.0.0.1.")
    if parsed.port is None:
        raise ValueError("Desktop redirect URI must include a port number.")
    if not parsed.path:
        raise ValueError("Desktop redirect URI must include a callback path.")

    current = _load_settings()
    current.update(
        {
            "client_key": key,
            "client_secret_dpapi": _protect_secret(secret),
            "redirect_uri": redirect,
        }
    )
    _save_settings(current)


def load_app_credentials() -> dict:
    data = _load_settings()
    key = str(data.get("client_key") or "")
    encrypted = str(data.get("client_secret_dpapi") or "")
    redirect = str(data.get("redirect_uri") or DEFAULT_REDIRECT_URI)
    if not key or not encrypted:
        return {}
    try:
        secret = _unprotect_secret(encrypted)
    except Exception:
        return {}
    return {
        "client_key": key,
        "client_secret": secret,
        "redirect_uri": redirect,
    }


def app_credentials_configured() -> bool:
    return bool(load_app_credentials())


def _generate_code_verifier(length: int = 64) -> str:
    if not 43 <= length <= 128:
        raise ValueError("PKCE code verifier length must be between 43 and 128 characters.")
    return "".join(secrets.choice(_UNRESERVED) for _ in range(length))


def _code_challenge(verifier: str) -> str:
    # TikTok Desktop Login Kit explicitly requires the SHA256 digest encoded as hex.
    return hashlib.sha256(verifier.encode("utf-8")).hexdigest()


def _store_token_bundle(payload: dict) -> None:
    access_token = str(payload.get("access_token") or "")
    refresh_token = str(payload.get("refresh_token") or "")
    if not access_token or not refresh_token:
        raise RuntimeError("TikTok token response did not include access and refresh tokens.")

    current = _load_settings()
    now = int(time.time())
    current.update(
        {
            "access_token_dpapi": _protect_secret(access_token),
            "refresh_token_dpapi": _protect_secret(refresh_token),
            "access_expires_at": now + int(payload.get("expires_in") or 0),
            "refresh_expires_at": now + int(payload.get("refresh_expires_in") or 0),
            "open_id": str(payload.get("open_id") or ""),
            "scope": str(payload.get("scope") or ""),
            "token_type": str(payload.get("token_type") or "Bearer"),
        }
    )
    _save_settings(current)


def _token_snapshot() -> dict:
    data = _load_settings()
    access_encrypted = str(data.get("access_token_dpapi") or "")
    refresh_encrypted = str(data.get("refresh_token_dpapi") or "")
    try:
        access = _unprotect_secret(access_encrypted) if access_encrypted else ""
        refresh = _unprotect_secret(refresh_encrypted) if refresh_encrypted else ""
    except Exception:
        access = ""
        refresh = ""
    return {
        "access_token": access,
        "refresh_token": refresh,
        "access_expires_at": int(data.get("access_expires_at") or 0),
        "refresh_expires_at": int(data.get("refresh_expires_at") or 0),
        "open_id": str(data.get("open_id") or ""),
        "scope": str(data.get("scope") or ""),
    }


def connection_status() -> dict:
    credentials = load_app_credentials()
    tokens = _token_snapshot()
    return {
        "app_configured": bool(credentials),
        "connected": bool(tokens.get("access_token") and tokens.get("refresh_token")),
        "open_id": tokens.get("open_id") or "",
        "scope": tokens.get("scope") or "",
        "access_expires_at": tokens.get("access_expires_at") or 0,
        "redirect_uri": credentials.get("redirect_uri") if credentials else DEFAULT_REDIRECT_URI,
    }


def _parse_token_response(response: requests.Response, action: str) -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"TikTok {action} returned invalid JSON (HTTP {response.status_code}).") from exc

    if response.status_code >= 400 or payload.get("error"):
        message = payload.get("error_description") or payload.get("error") or payload
        raise RuntimeError(f"TikTok {action} failed: {message}")
    return payload


def _exchange_code(
    code: str,
    verifier: str,
    credentials: dict,
) -> dict:
    response = requests.post(
        TOKEN_URL,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Cache-Control": "no-cache",
        },
        data={
            "client_key": credentials["client_key"],
            "client_secret": credentials["client_secret"],
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": credentials["redirect_uri"],
            "code_verifier": verifier,
        },
        timeout=REQUEST_TIMEOUT,
    )
    return _parse_token_response(response, "authorization")


def _refresh_token(credentials: dict, refresh_token: str) -> dict:
    response = requests.post(
        TOKEN_URL,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Cache-Control": "no-cache",
        },
        data={
            "client_key": credentials["client_key"],
            "client_secret": credentials["client_secret"],
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=REQUEST_TIMEOUT,
    )
    return _parse_token_response(response, "token refresh")


def get_access_token() -> str:
    with _TOKEN_LOCK:
        credentials = load_app_credentials()
        if not credentials:
            raise RuntimeError("TikTok app credentials are not configured.")

        tokens = _token_snapshot()
        access = str(tokens.get("access_token") or "")
        refresh = str(tokens.get("refresh_token") or "")
        expires_at = int(tokens.get("access_expires_at") or 0)
        now = int(time.time())

        if access and expires_at > now + TOKEN_REFRESH_SKEW_SECONDS:
            return access
        if not refresh:
            raise RuntimeError("TikTok is not connected. Use CONNECT TIKTOK first.")
        refresh_expires_at = int(tokens.get("refresh_expires_at") or 0)
        if refresh_expires_at and refresh_expires_at <= now:
            raise RuntimeError("TikTok refresh token has expired. Reconnect TikTok.")

        payload = _refresh_token(credentials, refresh)
        _store_token_bundle(payload)
        return str(payload["access_token"])


def disconnect() -> None:
    data = _load_settings()
    for key in (
        "access_token_dpapi",
        "refresh_token_dpapi",
        "access_expires_at",
        "refresh_expires_at",
        "open_id",
        "scope",
        "token_type",
    ):
        data.pop(key, None)
    _save_settings(data)


def _callback_server(redirect_uri: str, expected_state: str):
    parsed = urllib.parse.urlparse(redirect_uri)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port
    callback_path = parsed.path
    result: dict[str, str] = {}
    completed = threading.Event()

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            incoming = urllib.parse.urlparse(self.path)
            if incoming.path != callback_path:
                self.send_response(404)
                self.end_headers()
                return

            values = urllib.parse.parse_qs(incoming.query)
            state = (values.get("state") or [""])[0]
            if state != expected_state:
                result["error"] = "OAuth state did not match. Connection was cancelled for safety."
            elif values.get("error"):
                result["error"] = (values.get("error_description") or values.get("error") or ["TikTok authorization failed."])[0]
            else:
                result["code"] = (values.get("code") or [""])[0]
                result["scopes"] = (values.get("scopes") or [""])[0]
                if not result["code"]:
                    result["error"] = "TikTok callback did not include an authorization code."

            body = (
                "<html><body style='font-family:Segoe UI;background:#06070b;color:#fff;padding:40px'>"
                "<h2>Pulse Social</h2>"
                "<p>TikTok connection received. You can close this tab and return to Pulse Social.</p>"
                "</body></html>"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            completed.set()

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer((host, port), CallbackHandler)
    server.timeout = 0.5
    return server, completed, result


def connect(
    log: Callable[[str], None] | None = None,
    *,
    timeout_seconds: int = 180,
) -> dict:
    credentials = load_app_credentials()
    if not credentials:
        raise RuntimeError("Set TikTok app credentials before connecting.")

    verifier = _generate_code_verifier()
    challenge = _code_challenge(verifier)
    state = secrets.token_urlsafe(32)
    scope = ",".join(DEFAULT_SCOPES)
    redirect_uri = credentials["redirect_uri"]

    params = {
        "client_key": credentials["client_key"],
        "response_type": "code",
        "scope": scope,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    authorize_url = AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)

    try:
        server, completed, result = _callback_server(redirect_uri, state)
    except OSError as exc:
        raise RuntimeError(
            f"Could not start TikTok callback listener on {redirect_uri}: {exc}"
        ) from exc

    if log:
        log("TIKTOK LOGIN | opening TikTok authorization in your browser")
    webbrowser.open(authorize_url)

    deadline = time.time() + timeout_seconds
    try:
        while time.time() < deadline and not completed.is_set():
            server.handle_request()
    finally:
        server.server_close()

    if not completed.is_set():
        raise RuntimeError("TikTok login timed out before the callback was received.")
    if result.get("error"):
        raise RuntimeError(result["error"])

    code = result.get("code") or ""
    if log:
        log("TIKTOK LOGIN | authorization received; exchanging code")
    payload = _exchange_code(code, verifier, credentials)

    granted_scope = str(payload.get("scope") or result.get("scopes") or "")
    granted = {item.strip() for item in granted_scope.split(",") if item.strip()}
    if "video.publish" not in granted:
        raise RuntimeError(
            "TikTok connected, but video.publish was not granted. "
            "Enable/approve Content Posting API Direct Post and reconnect."
        )

    _store_token_bundle(payload)
    if log:
        log("TIKTOK CONNECTED | OAuth complete")
    return payload
