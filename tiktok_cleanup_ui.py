from __future__ import annotations

import tkinter as tk

from platforms.tiktok.cleanup_ui import open_cleanup_window

root = tk.Tk()
root.withdraw()
window = open_cleanup_window(root)
window.protocol("WM_DELETE_WINDOW", root.destroy)
root.mainloop()
