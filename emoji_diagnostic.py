from __future__ import annotations

import json
import os
import platform
import sys
import time
import traceback
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


def timed(label: str, fn):
    log(f"START {label}")
    started = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - started
    log(f"PASS  {label} · {elapsed:.3f}s")
    return result


def main() -> int:
    log("=" * 64)
    log("PULSE SOCIAL EMOJI DIAGNOSTIC")
    log(f"Python {sys.version.split()[0]} · {platform.platform()}")
    log(f"Executable: {sys.executable}")
    log(f"Repo: {Path.cwd()}")
    log(f"Log: {LOG_PATH}")

    try:
        import tkinter as tk
        log(f"Tkinter imported · Tk {tk.TkVersion} · Tcl {tk.TclVersion}")

        try:
            import PIL
            log(f"Pillow {getattr(PIL, '__version__', 'unknown')}")
        except Exception as exc:
            log(f"Pillow unavailable/error: {exc!r}")

        def import_assets():
            from platforms.common import emoji_assets
            return emoji_assets

        emoji_assets = timed("import embedded emoji asset modules", import_assets)
        asset_count = len(getattr(emoji_assets, "ASSETS", {}))
        encoded_chars = sum(len(value) for value in getattr(emoji_assets, "ASSETS", {}).values())
        log(f"Embedded assets: {asset_count} · base64 chars: {encoded_chars:,}")

        def import_picker():
            from platforms.common import emoji_picker
            return emoji_picker

        picker = timed("import emoji picker module", import_picker)
        log(
            "Catalog sizes: "
            + ", ".join(f"{name}={len(values)}" for name, values in picker.EMOJI_CATALOG.items())
        )

        manifest_path = picker._resource_path(picker.SPRITE_MANIFEST_RELATIVE_PATH)
        sprite_path = picker._resource_path(picker.SPRITE_RELATIVE_PATH)
        log(f"Manifest path: {manifest_path} · exists={manifest_path.exists()}")
        log(
            f"Sprite path: {sprite_path} · exists={sprite_path.exists()} · "
            f"size={sprite_path.stat().st_size:,} bytes" if sprite_path.exists()
            else f"Sprite path: {sprite_path} · exists=False"
        )

        manifest = timed("read sprite manifest", picker._load_sprite_manifest)
        log(f"Manifest entries: {len(manifest)}")

        root = timed("create Tk root", lambda: tk.Tk())
        root.withdraw()

        def render_embedded_sample():
            refs = []
            sample = list(picker.EMOJI_CATALOG["SMILEYS"])[:20]
            for index, emoji in enumerate(sample, start=1):
                data = emoji_assets.asset_base64(emoji)
                if not data:
                    continue
                if index in {1, 5, 10, 20}:
                    log(f"  embedded PhotoImage progress {index}/{len(sample)}")
                refs.append(tk.PhotoImage(data=data))
            root._diag_refs = refs
            root.update_idletasks()
            return len(refs)

        embedded_count = timed("create 20 embedded Tk PhotoImages", render_embedded_sample)
        log(f"Embedded PhotoImages created: {embedded_count}")

        def render_all_smileys():
            refs = []
            smileys = list(picker.EMOJI_CATALOG["SMILEYS"])
            for index, emoji in enumerate(smileys, start=1):
                data = emoji_assets.asset_base64(emoji)
                if data:
                    refs.append(tk.PhotoImage(data=data))
                if index % 25 == 0 or index == len(smileys):
                    log(f"  full smiley PhotoImage progress {index}/{len(smileys)}")
                    root.update_idletasks()
            root._diag_smiley_refs = refs
            return len(refs)

        smiley_count = timed("create all smiley Tk PhotoImages", render_all_smileys)
        log(f"Full smiley PhotoImages created: {smiley_count}")

        sprite_photo = None
        if sprite_path.exists():
            def load_sprite():
                nonlocal sprite_photo
                sprite_photo = tk.PhotoImage(file=str(sprite_path))
                root._diag_sprite = sprite_photo
                root.update_idletasks()
                return (sprite_photo.width(), sprite_photo.height())

            dimensions = timed("decode 6.38 MB sprite into Tk PhotoImage", load_sprite)
            log(f"Sprite dimensions: {dimensions[0]}x{dimensions[1]}")

            def copy_sprite_cells():
                refs = []
                sample = ["😀", "😂", "👋", "🐶", "🍕", "⚽", "✈️", "💡", "❤️", "🏁"]
                for index, emoji in enumerate(sample, start=1):
                    coords = manifest.get(emoji) or manifest.get(emoji.replace("\ufe0f", ""))
                    if coords is None:
                        log(f"  no manifest coords for {emoji}")
                        continue
                    source_x = coords[0] * picker.SPRITE_CELL + 1
                    source_y = coords[1] * picker.SPRITE_CELL + 1
                    photo = tk.PhotoImage(width=picker.SPRITE_SIZE, height=picker.SPRITE_SIZE)
                    photo.tk.call(
                        photo,
                        "copy",
                        sprite_photo,
                        "-from",
                        source_x,
                        source_y,
                        source_x + picker.SPRITE_SIZE,
                        source_y + picker.SPRITE_SIZE,
                        "-to",
                        0,
                        0,
                    )
                    refs.append(photo)
                    log(f"  copied sprite cell {index}/{len(sample)} · {emoji}")
                root._diag_cell_refs = refs
                root.update_idletasks()
                return len(refs)

            copied = timed("copy 10 sprite cells", copy_sprite_cells)
            log(f"Sprite cells copied: {copied}")

        def build_button_grid():
            top = tk.Toplevel(root)
            top.withdraw()
            frame = tk.Frame(top)
            frame.pack()
            refs = []
            buttons = []
            values = list(picker.EMOJI_CATALOG["SMILEYS"])
            for index, emoji in enumerate(values):
                data = emoji_assets.asset_base64(emoji)
                if data:
                    photo = tk.PhotoImage(data=data).subsample(2, 2)
                    refs.append(photo)
                    button = tk.Button(frame, image=photo, width=46, height=44)
                else:
                    button = tk.Button(frame, text=emoji, width=3, height=1)
                button.grid(row=index // 10, column=index % 10)
                buttons.append(button)
                if (index + 1) % 25 == 0 or index + 1 == len(values):
                    log(f"  button-grid progress {index + 1}/{len(values)}")
            top._diag_refs = refs
            top._diag_buttons = buttons
            top.update_idletasks()
            top.destroy()
            return len(buttons)

        button_count = timed("construct full smiley button grid", build_button_grid)
        log(f"Buttons constructed: {button_count}")

        root.destroy()
        log("RESULT: ALL LOW-LEVEL EMOJI TESTS PASSED")
        log("If Social still crashes, the fault is in picker/app integration rather than raw image decoding.")
        return 0

    except BaseException as exc:
        log(f"FAIL: {type(exc).__name__}: {exc}")
        for line in traceback.format_exc().splitlines():
            log(line)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
