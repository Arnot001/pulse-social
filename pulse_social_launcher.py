from __future__ import annotations

import subprocess
import sys
import tkinter as tk
from pathlib import Path

BG = "#07090f"
PANEL = "#0d111b"
PANEL_2 = "#121827"
BORDER = "#20283a"
TEXT = "#f5f7fb"
MUTED = "#8993a6"
ACCENT = "#ff008c"
ROOT = Path(__file__).resolve().parent


def launch(script: str) -> None:
    subprocess.Popen([sys.executable, str(ROOT / script)], cwd=str(ROOT))


root = tk.Tk()
root.title("Pulse Social")
root.geometry("720x420")
root.minsize(680, 390)
root.configure(bg=BG)

header = tk.Frame(root, bg=BG)
header.pack(fill="x", padx=30, pady=(30, 12))
tk.Label(header, text="PULSE", fg=TEXT, bg=BG, font=("Segoe UI", 28, "bold")).pack(side="left")
tk.Label(header, text=" SOCIAL", fg=ACCENT, bg=BG, font=("Segoe UI", 28, "bold")).pack(side="left")
tk.Label(root, text="SOCIAL AUTOMATION  //  COMMERCE INTELLIGENCE", fg=MUTED, bg=BG, font=("Consolas", 9)).pack(anchor="w", padx=32)

nav = tk.Frame(root, bg=BG)
nav.pack(fill="both", expand=True, padx=30, pady=28)


def platform_card(title: str, subtitle: str, feature: str, command) -> tk.Frame:
    card = tk.Frame(nav, bg=PANEL, highlightthickness=1, highlightbackground=BORDER, width=310, height=210)
    card.pack_propagate(False)
    tk.Label(card, text=title, fg=TEXT, bg=PANEL, font=("Segoe UI", 22, "bold")).pack(anchor="w", padx=20, pady=(20, 4))
    tk.Label(card, text=subtitle, fg=MUTED, bg=PANEL, font=("Segoe UI", 9), wraplength=260, justify="left").pack(anchor="w", padx=20)
    tk.Label(card, text=feature, fg=ACCENT, bg=PANEL, font=("Consolas", 9, "bold")).pack(anchor="w", padx=20, pady=(18, 8))
    tk.Button(card, text="OPEN", command=command, bg=ACCENT, fg="white", activebackground=ACCENT, activeforeground="white", relief="flat", bd=0, padx=18, pady=8, font=("Segoe UI", 9, "bold"), cursor="hand2").pack(anchor="w", padx=20)
    return card

x_card = platform_card("X", "Cleanup tools for your own X account.", "CLEANUP  //  AUTO POST SOON", lambda: launch("pulse_social_ui.py"))
x_card.pack(side="left", fill="both", expand=True, padx=(0, 10))
tiktok_card = platform_card("TIKTOK", "Shop intelligence powered by TikTok's live category taxonomy.", "SHOP  //  AUTO POST SOON", lambda: launch("tiktok_shop_ui.py"))
tiktok_card.pack(side="left", fill="both", expand=True, padx=(10, 0))

root.mainloop()
