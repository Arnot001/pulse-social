from __future__ import annotations

import tkinter as tk

from platforms.tiktok.cleanup_ui import open_cleanup_window
from pulse_license_gate import require_licence

if not require_licence():
    raise SystemExit(0)

root = tk.Tk()
root.withdraw()
window = open_cleanup_window(root)
window.protocol("WM_DELETE_WINDOW", root.destroy)
root.mainloop()
