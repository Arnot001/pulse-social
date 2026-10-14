from __future__ import annotations

import tkinter as tk

from platforms.tiktok.auto_post_ui import open_auto_post_window
from pulse_license_gate import require_licence

if not require_licence():
    raise SystemExit(0)

root = tk.Tk()
root.withdraw()
window = open_auto_post_window(root)
window.protocol("WM_DELETE_WINDOW", root.destroy)
root.mainloop()
