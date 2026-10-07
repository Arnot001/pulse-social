from __future__ import annotations

import argparse
import gc
import os
import platform
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

LOG_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Pulse Social"
LOG_PATH = LOG_DIR / "emoji_diagnostic.log"


def log(message: str) -> None:
    line = f"{time.strftime('%H:%M:%S')}  {message}"
    print(line, flush=True)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def widgets(parent):
    for child in parent.winfo_children():
        yield child
        yield from widgets(child)


def wait_for_sprite(root, window, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        status = window._emoji_diagnostics()
        if status["sprite_error"]:
            raise RuntimeError(status["sprite_error"])
        if status["sprite_state"] == "ready" and "pending" not in status["sources"]:
            return
        time.sleep(0.01)
    raise TimeoutError("The real picker did not finish loading its sprite within 10 seconds.")


def verify_picker(root, window):
    """Exercise the real picker and read pixels back from its Tk button images."""
    from PIL import Image, ImageTk
    from platforms.common import emoji_picker as picker

    wait_for_sprite(root, window)
    categories = {w._emoji_category: w for w in widgets(window) if hasattr(w, "_emoji_category")}
    tones = {w._emoji_tone: w for w in widgets(window) if hasattr(w, "_emoji_tone")}
    manifest = picker._load_sprite_manifest()
    with Image.open(picker._resource_path(picker.SPRITE_RELATIVE_PATH)) as source:
        sheet = source.convert("RGBA")
    total = 0

    def check(category, tone="DEFAULT"):
        nonlocal total
        categories[category].invoke()
        tones[tone].invoke()
        root.update()
        gc.collect()
        buttons = [w for w in widgets(window) if hasattr(w, "_emoji")]
        expected_values = picker.filter_emojis(category, tone=tone)
        if [w._emoji for w in buttons] != expected_values:
            raise AssertionError(f"{category}: the picker did not render the requested category.")
        counts = Counter()
        for button in buttons:
            emoji = button._emoji
            source = button._emoji_source
            counts[source] += 1
            if source not in {"embedded", "sprite"} or not button.cget("image"):
                raise AssertionError(f"{category}: {ascii(emoji)} is using {source}, not artwork.")
            # PhotoImage references must survive GC; compare pixels from the actual
            # Tk image, not merely the Pillow tile or diagnostic source label.
            photo = button._emoji_photo
            if str(photo) != str(button.cget("image")):
                raise AssertionError("Button image reference does not match its Tk image.")
            if source == "sprite":
                coords = manifest.get(emoji) or manifest.get(emoji.replace("\ufe0f", ""))
                x, y = (value * 34 + 1 for value in coords)
                expected = sheet.crop((x, y, x + 32, y + 32)).resize((28, 28), Image.Resampling.LANCZOS)
                actual = ImageTk.getimage(photo)
                # Tk can discard RGB data on fully transparent pixels.
                background = Image.new("RGBA", (28, 28), picker.PANEL)
                if (Image.alpha_composite(background, actual).tobytes()
                        != Image.alpha_composite(background, expected).tobytes()):
                    raise AssertionError(f"Wrong sprite pixels: {ascii(emoji)}")
            total += 1
        log(f"PASS {category}/{tone}: {len(buttons)} real Tk buttons, {dict(counts)}")

    for category in picker.EMOJI_CATALOG:
        check(category)
    for tone in picker.TONE_MODIFIERS:
        if tone != "DEFAULT":
            check("PEOPLE", tone)
    categories["ANIMALS"].invoke()
    root.update()
    log(f"PASS actual picker: {total} button images verified, including all skin tones")
    return total


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Verify the actual offline Tk emoji picker.")
    parser.add_argument("--show-picker", action="store_true", help="Leave the real picker open for visual inspection.")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    root = None
    log("PULSE SOCIAL EMOJI DIAGNOSTIC")
    log(f"Python {sys.version.split()[0]} | {platform.platform()}")
    log(f"Executable: {sys.executable}")
    try:
        import tkinter as tk
        try:
            import PIL
            from PIL import ImageTk
        except ImportError as exc:
            raise RuntimeError("Pillow is required. Install the project requirements with this Python and restart Social.") from exc
        log(f"Pillow {PIL.__version__} | Tk {tk.TkVersion}")
        from platforms.common import emoji_picker as picker
        log(f"Sprite: {picker._resource_path(picker.SPRITE_RELATIVE_PATH)}")
        log(f"Manifest entries: {len(picker._load_sprite_manifest())}")
        root = tk.Tk()
        root.title("Emoji diagnostic - no posting")
        root.geometry("420x100")
        if not args.show_picker:
            root.withdraw()
        target = tk.Text(root, height=2)
        target.pack(fill="both", expand=True)
        window = picker.open_emoji_picker(target)
        verify_picker(root, window)
        log("RESULT: ACTUAL TK PICKER ARTWORK CHECKS PASSED")
        if args.show_picker:
            log("Picker left open on ANIMALS for visual inspection; close the diagnostic to finish.")
            window.protocol("WM_DELETE_WINDOW", root.destroy)
            window.lift()
            root.mainloop()
            root = None
        return 0
    except Exception as exc:
        log(f"FAIL: {type(exc).__name__}: {exc}")
        for line in traceback.format_exc().splitlines():
            log(line)
        return 1
    finally:
        if root is not None:
            root.destroy()


if __name__ == "__main__":
    raise SystemExit(main())
