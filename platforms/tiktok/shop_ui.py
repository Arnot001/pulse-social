"""TikTok Shop dashboard for the standalone TikTok platform module."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from commerce.store import CommerceStore
from commerce.tiktok.category_collector import collect_category

BG = "#07090f"
PANEL = "#0d111b"
PANEL_2 = "#121827"
BORDER = "#20283a"
TEXT = "#f5f7fb"
MUTED = "#8993a6"
ACCENT = "#ff008c"
SUCCESS = "#35d07f"
DANGER = "#ff4057"


class TikTokShopView(tk.Frame):
    """UI adapter around the existing Commerce/TikTok collector."""

    def __init__(self, master, **kwargs):
        super().__init__(master, bg=PANEL, **kwargs)
        self.store = CommerceStore()
        self.last_results: list[dict] = []
        self.category_url = tk.StringVar()
        self.status = tk.StringVar(value="READY // enter a public TikTok Shop category URL")
        self.active_tab = "discovery"
        self.tab_buttons: dict[str, tk.Button] = {}
        self.body = None
        self._build()
        self.show_tab("discovery")

    def _build(self):
        tk.Label(self, text="TIKTOK SHOP INTELLIGENCE", bg=PANEL, fg=TEXT,
                 font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=22, pady=(22, 4))
        tk.Label(self, text="Public category discovery, observed deals and price history",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 10)).pack(anchor="w", padx=22)

        tabs = tk.Frame(self, bg=PANEL)
        tabs.pack(fill="x", padx=22, pady=(18, 10))
        for key, label in (("discovery", "DISCOVERY"), ("deals", "DEALS"),
                           ("watchlist", "WATCHLIST"), ("history", "PRICE HISTORY")):
            button = tk.Button(tabs, text=label, command=lambda k=key: self.show_tab(k),
                               bg=PANEL_2, fg=TEXT, activebackground=ACCENT,
                               activeforeground="white", relief="flat", bd=0,
                               padx=14, pady=8, font=("Segoe UI", 9, "bold"), cursor="hand2")
            button.pack(side="left", padx=(0, 7))
            self.tab_buttons[key] = button

        self.body = tk.Frame(self, bg=PANEL)
        self.body.pack(fill="both", expand=True, padx=22)
        tk.Label(self, textvariable=self.status, bg=PANEL_2, fg=SUCCESS, anchor="w",
                 padx=12, pady=9, font=("Consolas", 9, "bold")).pack(fill="x", padx=22, pady=(10, 20))

    def _clear(self):
        for child in self.body.winfo_children():
            child.destroy()

    def show_tab(self, tab):
        self.active_tab = tab
        for key, button in self.tab_buttons.items():
            button.configure(bg=ACCENT if key == tab else PANEL_2)
        self._clear()
        if tab == "discovery":
            self._show_discovery()
        elif tab == "deals":
            self._show_deals()
        elif tab == "history":
            self._show_history()
        else:
            self._show_watchlist()

    def _show_discovery(self):
        tk.Label(self.body, text="CATEGORY COLLECTOR", bg=PANEL, fg=TEXT,
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(6, 7))
        tk.Label(self.body, text="Paste a public TikTok Shop category URL. One sweep records each product once.",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 9))
        row = tk.Frame(self.body, bg=PANEL)
        row.pack(fill="x")
        entry = tk.Entry(row, textvariable=self.category_url, bg=PANEL_2, fg=TEXT,
                         insertbackground=TEXT, relief="flat", font=("Segoe UI", 10))
        entry.pack(side="left", fill="x", expand=True, ipady=9)
        tk.Button(row, text="COLLECT NOW", command=self.collect_now, bg=ACCENT, fg="white",
                  activebackground=ACCENT, activeforeground="white", relief="flat", bd=0,
                  padx=18, pady=9, font=("Segoe UI", 9, "bold"), cursor="hand2").pack(side="left", padx=(8, 0))
        self._results_table(self.body, self.last_results)

    def collect_now(self):
        url = self.category_url.get().strip()
        if not url:
            self.status.set("NEEDS URL // paste a TikTok Shop category URL first")
            return
        if "shop.tiktok.com" not in url.lower():
            self.status.set("CHECK URL // expected a public shop.tiktok.com category URL")
            return
        self.status.set("COLLECTING // fetching public category data...")
        threading.Thread(target=self._collect_worker, args=(url,), daemon=True).start()

    def _collect_worker(self, url):
        try:
            results = collect_category(url, self.store)
            self.after(0, lambda: self._collection_done(results))
        except Exception as exc:
            self.after(0, lambda: self.status.set(f"COLLECT FAILED // {exc}"))

    def _collection_done(self, results):
        self.last_results = results
        recorded = [r for r in results if r.get("status") == "recorded"]
        changed = [r for r in recorded if r.get("price_change") not in (None, 0) or r.get("sold_change") not in (None, 0)]
        self.status.set(f"SWEEP COMPLETE // {len(recorded)} recorded // {len(changed)} changed")
        self.show_tab(self.active_tab)

    def _results_table(self, parent, results):
        frame = tk.Frame(parent, bg=PANEL)
        frame.pack(fill="both", expand=True, pady=(16, 0))
        columns = ("score", "price", "change", "sold", "title")
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=11)
        headings = {"score": "Score", "price": "Price", "change": "Movement", "sold": "Sold", "title": "Product"}
        widths = {"score": 60, "price": 90, "change": 150, "sold": 70, "title": 390}
        for col in columns:
            tree.heading(col, text=headings[col])
            tree.column(col, width=widths[col], anchor="w")
        for item in sorted((r for r in results if r.get("status") == "recorded"),
                           key=lambda r: r.get("deal_score", 0), reverse=True):
            change = ""
            if item.get("price_change") not in (None, 0):
                change = f"{item['price_change']:+.2f} ({item.get('price_change_pct', 0):+.1f}%)"
            if item.get("sold_change") not in (None, 0):
                change = (change + "  " if change else "") + f"SOLD {item['sold_change']:+d}"
            tree.insert("", "end", values=(item.get("deal_score", ""),
                        f"{item.get('currency', 'GBP')} {item.get('price', 0):.2f}", change,
                        item.get("sold_count", ""), item.get("title", "")))
        tree.pack(fill="both", expand=True)

    def _show_deals(self):
        tk.Label(self.body, text="LATEST SWEEP // DEAL RANKING", bg=PANEL, fg=TEXT,
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(6, 0))
        if not self.last_results:
            tk.Label(self.body, text="Run Discovery first. Deals from the latest sweep will rank here.",
                     bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(8, 0))
        self._results_table(self.body, self.last_results)

    def _show_watchlist(self):
        tk.Label(self.body, text="WATCHLIST", bg=PANEL, fg=TEXT,
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(6, 7))
        tk.Label(self.body, text="Reserved for persistent product watches and alerts. No fake data, no X dependency.",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w")

    def _show_history(self):
        tk.Label(self.body, text="OBSERVED PRICE HISTORY", bg=PANEL, fg=TEXT,
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(6, 7))
        row = tk.Frame(self.body, bg=PANEL)
        row.pack(fill="x")
        product_id = tk.StringVar()
        tk.Entry(row, textvariable=product_id, bg=PANEL_2, fg=TEXT, insertbackground=TEXT,
                 relief="flat", font=("Segoe UI", 10)).pack(side="left", fill="x", expand=True, ipady=8)
        output = tk.Text(self.body, height=12, bg=PANEL_2, fg=TEXT, insertbackground=TEXT,
                         relief="flat", font=("Consolas", 9))
        output.pack(fill="both", expand=True, pady=(10, 0))

        def load_history():
            output.delete("1.0", tk.END)
            pid = product_id.get().strip()
            rows = self.store.price_history("tiktok_shop", pid) if pid else []
            if not rows:
                output.insert(tk.END, "No observed history for that product ID yet.")
                return
            for row_data in rows:
                output.insert(tk.END, f"{row_data['observed_at']}  |  GBP {row_data['effective_price']:.2f}  |  sold {row_data.get('sold_count')}\n")

        tk.Button(row, text="LOAD HISTORY", command=load_history, bg=PANEL_2, fg=TEXT,
                  relief="flat", bd=0, padx=14, pady=8, font=("Segoe UI", 9, "bold"),
                  cursor="hand2").pack(side="left", padx=(8, 0))
