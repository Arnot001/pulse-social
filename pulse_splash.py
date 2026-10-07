"""Short, optional release introduction; never imports or checks app services."""
from __future__ import annotations

import math
import time
import tkinter as tk


DURATION_MS = 1600
FRAME_MS = 25
WIDTH, HEIGHT = 600, 340
BG = "#070910"
CYAN = "#27def5"
PINK = "#ff48ad"


def _blend(colour: str, amount: float) -> str:
    amount = max(0.0, min(1.0, amount))
    return "#" + "".join(
        f"{round(int(BG[i:i + 2], 16) * (1 - amount) + int(colour[i:i + 2], 16) * amount):02x}"
        for i in (1, 3, 5)
    )


class _Splash:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.frame_id = None
        self.deadline_id = None
        self.stopped = False
        self.alpha_supported = True

    def run(self) -> None:
        root = self.root
        # Lay out while hidden to avoid a flash of the default decorated window.
        root.withdraw()
        root.overrideredirect(True)
        root.configure(bg=BG)
        root.title("Pulse Social")
        x = max(0, (root.winfo_screenwidth() - WIDTH) // 2)
        y = max(0, (root.winfo_screenheight() - HEIGHT) // 2)
        root.geometry(f"{WIDTH}x{HEIGHT}+{x}+{y}")
        self._opacity(0.0)
        self.canvas = tk.Canvas(root, bg=BG, bd=0, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_rectangle(1, 1, WIDTH - 1, HEIGHT - 1, outline="#1b2638")
        self.waves = [
            [self.canvas.create_line(0, 0, 1, 1, smooth=True, splinesteps=12,
                                     width=width, fill=BG)
             for width in (42, 22, 2)]
            for _ in (CYAN, PINK)
        ]
        self.eyebrow = self.canvas.create_text(
            300, 78, text="P U L S E   / /   S O C I A L", fill=BG,
            font=("Segoe UI", 9))
        self.brand = self.canvas.create_text(
            300, 141, text="PULSE", fill=BG, font=("Segoe UI", 40, "bold"))
        self.social = self.canvas.create_text(
            300, 190, text="S O C I A L", fill=BG, font=("Segoe UI", 16))
        self.canvas.create_line(120, 241, 480, 241, fill="#1b2638")
        # A passing accent, not a progress bar or a claim about readiness.
        self.sweep = [self.canvas.create_line(120, 241, 121, 241, fill=BG, width=w)
                      for w in (8, 2)]
        self.status = self.canvas.create_text(
            300, 281, text="OPENING LAUNCHER", fill=BG, font=("Segoe UI", 9))
        root.bind("<Escape>", lambda _event: self.close())
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.update_idletasks()
        self.started = time.monotonic()
        # A separate deadline bounds the splash even if animation stops early.
        self.deadline_id = root.after(DURATION_MS, self.close)
        root.deiconify()
        self._tick()
        if not self.stopped:
            root.mainloop()

    def _opacity(self, value: float) -> None:
        if self.alpha_supported:
            try:
                self.root.attributes("-alpha", value)
            except tk.TclError:
                self.alpha_supported = False

    def _tick(self) -> None:
        self.frame_id = None
        if self.stopped:
            return
        try:
            elapsed = time.monotonic() - self.started
            if elapsed >= DURATION_MS / 1000:
                self.close()
                return
            fade = min(1.0, elapsed / .20, (DURATION_MS / 1000 - elapsed) / .20)
            self._opacity(max(0.0, fade))
            for item, colour, delay in (
                (self.eyebrow, "#93a0b4", 0), (self.brand, "#f8f9fc", .05),
                (self.social, CYAN, .18), (self.status, "#93a0b4", .30),
            ):
                self.canvas.itemconfigure(item, fill=_blend(colour, (elapsed - delay) / .30))
            for band, (items, colour) in enumerate(zip(self.waves, (CYAN, PINK))):
                points = []
                for step in range(41):
                    x = -40 + (WIDTH + 80) * step / 40
                    y = 170 + band * 30 + math.sin(x / 115 + elapsed * .6 + band * 2) * 38
                    points.extend((x, y))
                for item, strength in zip(items, (.025, .045, .16)):
                    self.canvas.coords(item, *points)
                    self.canvas.itemconfigure(item, fill=_blend(colour, strength * min(1, elapsed / .5)))
            position = min(1.0, elapsed / 1.3)
            centre = 120 + 360 * position
            for item, strength in zip(self.sweep, (.09, .85)):
                self.canvas.coords(item, max(120, centre - 32), 241, min(480, centre + 32), 241)
                self.canvas.itemconfigure(item, fill=_blend(
                    CYAN if position < .5 else PINK, strength * math.sin(position * math.pi)))
            self.frame_id = self.root.after(FRAME_MS, self._tick)
        except Exception:
            # Tk otherwise reports callback errors and keeps its event loop alive.
            self.close()

    def close(self) -> None:
        if self.stopped:
            return
        self.stopped = True
        for timer in (self.frame_id, self.deadline_id):
            if timer is not None:
                try:
                    self.root.after_cancel(timer)
                except tk.TclError:
                    pass
        self.frame_id = self.deadline_id = None
        self.root.quit()


def show_splash() -> None:
    """Return only after the splash's independent Tk root has been destroyed."""
    root = tk.Tk()
    splash = _Splash(root)
    try:
        splash.run()
    finally:
        try:
            splash.close()
        finally:
            try:
                root.destroy()
            except tk.TclError:
                pass
