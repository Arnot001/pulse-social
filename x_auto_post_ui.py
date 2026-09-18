from __future__ import annotations

import tkinter as tk

from platforms.x.auto_post_ui import open_auto_post_window

root = tk.Tk()
root.withdraw()
window = open_auto_post_window(root)
window.protocol("WM_DELETE_WINDOW", root.destroy)
root.mainloop()
