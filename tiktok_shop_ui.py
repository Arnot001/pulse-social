import tkinter as tk

from commerce.tiktok.shop_ui import open_shop_window
from pulse_license_gate import require_licence

if not require_licence():
    raise SystemExit(0)

root = tk.Tk()
root.withdraw()
window = open_shop_window(root)
window.protocol("WM_DELETE_WINDOW", root.destroy)
root.mainloop()
