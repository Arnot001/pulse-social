from __future__ import annotations

from platforms.browser_control import (
    CDP_PORT,
    browser_status as dedicated_browser_status,
    choose_browser_name,
    connect_browser,
    installed_browser_names,
    port_open,
    running_browser_names,
)

X_URL = "https://x.com/home"


def _port_open(port: int = CDP_PORT) -> bool:
    return port_open(port)


def preferred_browser() -> str | None:
    """Return the browser Pulse would currently dedicate."""
    return choose_browser_name()


def browser_status() -> str:
    return dedicated_browser_status()


def open_x_browser(
    restart_existing: bool = False,
    browser_name: str | None = None,
) -> tuple[bool, str]:
    return connect_browser(
        browser_name,
        restart_existing=restart_existing,
        start_url=X_URL,
    )


__all__ = [
    "CDP_PORT",
    "X_URL",
    "browser_status",
    "installed_browser_names",
    "open_x_browser",
    "preferred_browser",
    "running_browser_names",
]
