import tkinter as tk

from commerce.tiktok.shop_ui import open_shop_window

root = tk.Tk()
root.withdraw()
window = open_shop_window(root)
root.mainloop()
