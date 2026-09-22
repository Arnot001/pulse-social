from __future__ import annotations

import os
from typing import Any

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
REQUEST_TIMEOUT = 45

CLIENT_KEY = os.environ.get("TIKTOK_CLIENT_KEY", "").strip()
CLIENT_SECRET = os.environ.get("TIKTOK_CLIENT_SECRET", "").strip()
REDIRECT_URI = os.environ.get(
    "TIKTOK_REDIRECT_URI",
    "http://127.0.0.1:3455/callback/",
).strip()
SCOPES = tuple(
    scope.strip()
    for scope in os.environ.get(
        "TIKTOK_SCOPES",
        "user.info.basic,video.publish",
    ).split(",")
    if scope.strip()
)

app = FastAPI(
    title="Pulse Social TikTok OAuth",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)


class ExchangeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=2048)
    code_verifier: str = Field(min_length=43, max_length=128)
    redirect_uri: str = Field(min_length=1, max_length=512)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=4096)


def _require_configuration() -> None:
    if not CLIENT_KEY or not CLIENT_SECRET:
        raise HTTPException(
            status_code=503,
            detail="TikTok OAuth service is not configured.",
        )


def _token_request(data: dict[str, str], action: str) -> dict[str, Any]:
    _require_configuration()
    try:
        response = requests.post(
            TOKEN_URL,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Cache-Control": "no-cache",
            },
            data=data,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail=f"TikTok {action} request failed.",
        ) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"TikTok {action} returned invalid JSON.",
        ) from exc

    if response.status_code >= 400 or payload.get("error"):
        message = payload.get("error_description") or payload.get("error") or "TikTok OAuth error"
        raise HTTPException(
            status_code=400 if response.status_code < 500 else 502,
            detail=str(message),
        )

    return payload


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok" if CLIENT_KEY and CLIENT_SECRET else "not_configured"}


@app.get("/v1/tiktok/config")
def tiktok_config() -> dict[str, Any]:
    _require_configuration()
    return {
        "client_key": CLIENT_KEY,
        "redirect_uri": REDIRECT_URI,
        "scopes": list(SCOPES),
    }


@app.post("/v1/tiktok/oauth/exchange")
def exchange_code(request: ExchangeRequest) -> dict[str, Any]:
    _require_configuration()
    if request.redirect_uri != REDIRECT_URI:
        raise HTTPException(
            status_code=400,
            detail="Redirect URI does not match the configured Pulse Social callback.",
        )

    return _token_request(
        {
            "client_key": CLIENT_KEY,
            "client_secret": CLIENT_SECRET,
            "code": request.code,
            "grant_type": "authorization_code",
            "redirect_uri": request.redirect_uri,
            "code_verifier": request.code_verifier,
        },
        "authorization",
    )


@app.post("/v1/tiktok/oauth/refresh")
def refresh_token(request: RefreshRequest) -> dict[str, Any]:
    return _token_request(
        {
            "client_key": CLIENT_KEY,
            "client_secret": CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": request.refresh_token,
        },
        "token refresh",
    )
