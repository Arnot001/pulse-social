from __future__ import annotations

import runpy
import sys
from pathlib import Path


CHILD_MODULES = {
    "pulse_social_ui.py": "pulse_social_ui",
    "x_auto_post_ui.py": "x_auto_post_ui",
    "tiktok_shop_ui.py": "tiktok_shop_ui",
    "tiktok_auto_post_ui.py": "tiktok_auto_post_ui",
    "tiktok_cleanup_ui.py": "tiktok_cleanup_ui",
}


def _child_module(argument: str) -> str | None:
    return CHILD_MODULES.get(Path(argument).name.casefold())


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        module = _child_module(args[0])
        if module:
            sys.argv = [args[0], *args[1:]]
            runpy.run_module(module, run_name="__main__")
            return

    # Presentation only: child entrypoints bypass this and a splash failure must
    # never prevent the approved launcher from opening. Keep the static import
    # so PyInstaller discovers the splash and its Tk dependency automatically.
    try:
        from pulse_splash import show_splash

        show_splash()
    except Exception:
        pass

    # The approved launcher remains the single source of truth for the main UI.
    # Importing it starts its Tk event loop exactly as the developer launcher does.
    import pulse_social_launcher  # noqa: F401


if __name__ == "__main__":
    main()
