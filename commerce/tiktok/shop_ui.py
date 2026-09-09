from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from .categories import TikTokCategory, children_of, fetch_categories, roots
from .category_collector import collect_category

BG = "#07090f"
PANEL = "#0d111b"
PANEL_2 = "#121827"
BORDER = "#20283a"
TEXT = "#f5f7fb"
MUTED = "#8993a6"
ACCENT = "#ff008c"
SUCCESS = "#35d07f"
DANGER = "#ff4057"


def open_shop_window(parent: tk.Misc) -> None:
    window = tk.Toplevel(parent)
    window.title("Pulse Social — TikTok Shop")
    window.geometry("760x650")
    window.minsize(700, 600)
    window.configure(bg=BG)

    categories: list[TikTokCategory] = []
    maps: list[dict[str, TikTokCategory]] = [{}, {}, {}]
    main_var = tk.StringVar()
    sub_var = tk.StringVar()
    leaf_var = tk.StringVar()
    status_var = tk.StringVar(value="CATEGORY TAXONOMY NOT LOADED")

    header = tk.Frame(window, bg=BG)
    header.pack(fill="x", padx=26, pady=(22, 12))
    tk.Label(header, text="PULSE", fg=TEXT, bg=BG, font=("Segoe UI", 24, "bold")).pack(side="left")
    tk.Label(header, text=" TIKTOK", fg=ACCENT, bg=BG, font=("Segoe UI", 24, "bold")).pack(side="left")
    tk.Label(header, text="SHOP // COMMERCE INTELLIGENCE", fg=MUTED, bg=BG, font=("Consolas", 9)).pack(side="right", pady=10)

    card = tk.Frame(window, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
    card.pack(fill="x", padx=26, pady=8)
    tk.Label(card, text="TIKTOK SHOP CATEGORY", fg=TEXT, bg=PANEL, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", padx=18, pady=(14, 12))

    def combo(row: int, label: str, variable: tk.StringVar) -> ttk.Combobox:
        tk.Label(card, text=label, fg=MUTED, bg=PANEL, font=("Consolas", 8, "bold")).grid(row=row, column=0, sticky="w", padx=18, pady=8)
        box = ttk.Combobox(card, textvariable=variable, state="readonly", width=42)
        box.grid(row=row, column=1, sticky="w", padx=(0, 18), pady=8)
        return box

    main_box = combo(1, "MAIN CATEGORY", main_var)
    sub_box = combo(2, "SUBCATEGORY", sub_var)
    leaf_box = combo(3, "CATEGORY", leaf_var)

    status = tk.Label(card, textvariable=status_var, fg=SUCCESS, bg=PANEL, font=("Consolas", 8, "bold"))
    status.grid(row=4, column=0, columnspan=3, sticky="w", padx=18, pady=(8, 14))

    actions = tk.Frame(window, bg=BG)
    actions.pack(fill="x", padx=26, pady=8)
    log = tk.Text(window, bg="#080c13", fg="#cbd3df", insertbackground=TEXT, relief="flat", bd=0, font=("Consolas", 9), padx=12, pady=10, wrap="word")
    log.pack(fill="both", expand=True, padx=26, pady=(4, 22))

    def write(message: str) -> None:
        def apply() -> None:
            log.insert(tk.END, message + "\n")
            log.see(tk.END)
        window.after(0, apply)

    def set_values(box: ttk.Combobox, variable: tk.StringVar, items: list[TikTokCategory], index: int) -> None:
        maps[index] = {item.name: item for item in items}
        box["values"] = [item.name for item in items]
        variable.set(items[0].name if items else "")
        box.configure(state="readonly" if items else "disabled")

    def selected_category() -> TikTokCategory | None:
        if leaf_var.get() and leaf_var.get() in maps[2]:
            return maps[2][leaf_var.get()]
        if sub_var.get() and sub_var.get() in maps[1]:
            return maps[1][sub_var.get()]
        if main_var.get() and main_var.get() in maps[0]:
            return maps[0][main_var.get()]
        return None

    def update_leafs(*_args) -> None:
        selected = maps[1].get(sub_var.get())
        set_values(leaf_box, leaf_var, children_of(categories, selected.category_id) if selected else [], 2)
        chosen = selected_category()
        status_var.set(f"READY // {chosen.name} // {chosen.category_id}" if chosen else "SELECT A CATEGORY")

    def update_subs(*_args) -> None:
        selected = maps[0].get(main_var.get())
        set_values(sub_box, sub_var, children_of(categories, selected.category_id) if selected else [], 1)
        update_leafs()

    def taxonomy_loaded(items: list[TikTokCategory]) -> None:
        nonlocal categories
        categories = items
        set_values(main_box, main_var, roots(categories), 0)
        update_subs()
        status_var.set(f"READY // {len(categories)} TIKTOK CATEGORIES LOADED")
        refresh_btn.configure(state="normal")
        collect_btn.configure(state="normal" if selected_category() else "disabled")
        write(f"Loaded {len(categories)} categories from TikTok Shop embedded taxonomy.")

    def refresh_worker() -> None:
        try:
            items = fetch_categories()
            if not items:
                raise RuntimeError("TikTok returned no structured categories.")
            window.after(0, lambda: taxonomy_loaded(items))
        except Exception as exc:
            window.after(0, lambda: status_var.set("CATEGORY LOAD FAILED"))
            window.after(0, lambda: refresh_btn.configure(state="normal"))
            write(f"Category refresh failed: {exc}")

    def refresh() -> None:
        refresh_btn.configure(state="disabled")
        collect_btn.configure(state="disabled")
        status_var.set("LOADING LIVE TIKTOK CATEGORY TAXONOMY...")
        write("Refreshing TikTok Shop categories...")
        threading.Thread(target=refresh_worker, daemon=True).start()

    def collect_worker(category: TikTokCategory) -> None:
        try:
            write(f"Collecting {category.name} // {category.url}")
            results = collect_category(category.url)
            recorded = [item for item in results if item.get("status") == "recorded"]
            changed = [item for item in recorded if item.get("price_change") not in (None, 0) or item.get("sold_change") not in (None, 0)]
            write(f"Recorded {len(recorded)} products // Changed {len(changed)}")
            for item in sorted(recorded, key=lambda row: row.get("deal_score", 0), reverse=True)[:25]:
                price = item.get("price")
                price_text = f"{price:.2f}" if isinstance(price, (int, float)) else "?"
                write(f"{item.get('deal_score', 0):>3}/100 | {item.get('currency', 'GBP')} {price_text} | {item.get('title', '')}")
            window.after(0, lambda: status_var.set(f"COMPLETE // {category.name.upper()} // {len(recorded)} RECORDED"))
        except Exception as exc:
            window.after(0, lambda: status_var.set("COLLECTION FAILED"))
            write(f"Collection failed: {exc}")
        finally:
            window.after(0, lambda: collect_btn.configure(state="normal"))

    def collect() -> None:
        category = selected_category()
        if not category:
            messagebox.showerror("No category", "Select a TikTok Shop category first.", parent=window)
            return
        collect_btn.configure(state="disabled")
        status_var.set(f"COLLECTING // {category.name.upper()}")
        threading.Thread(target=collect_worker, args=(category,), daemon=True).start()

    def styled_button(text: str, command, accent: bool = False) -> tk.Button:
        return tk.Button(actions, text=text, command=command, bg=ACCENT if accent else PANEL_2, fg=TEXT, activebackground=ACCENT, activeforeground="white", relief="flat", bd=0, padx=16, pady=9, font=("Segoe UI", 9, "bold"), cursor="hand2")

    refresh_btn = styled_button("REFRESH CATEGORIES", refresh)
    refresh_btn.pack(side="left", padx=(0, 8))
    collect_btn = styled_button("COLLECT CATEGORY", collect, accent=True)
    collect_btn.pack(side="left", padx=8)
    collect_btn.configure(state="disabled")

    main_box.bind("<<ComboboxSelected>>", update_subs)
    sub_box.bind("<<ComboboxSelected>>", update_leafs)
    leaf_box.bind("<<ComboboxSelected>>", lambda _event: status_var.set(f"READY // {selected_category().name} // {selected_category().category_id}" if selected_category() else "SELECT A CATEGORY"))

    refresh()
