"""TikTok Shop dashboard for the standalone TikTok platform module."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from commerce.store import CommerceStore
from commerce.tiktok.category_session import MODES, ShopListState, clear_log_widget, collect_category_session, session_summary

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
        self.list_state = ShopListState()
        self.list_mode = tk.StringVar(value=MODES[0])
        self.log_generation = 0
        self.category_url = tk.StringVar()
        self.status = tk.StringVar(value="IDLE // enter a public TikTok Shop category URL")
        self.active_tab = "discovery"
        self.tab_buttons: dict[str, tk.Button] = {}
        self.body = None
        self._configure_tree_style()
        self._build()
        self.show_tab("discovery")

    def _configure_tree_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Pulse.Treeview", background=PANEL_2, fieldbackground=PANEL_2,
                        foreground=TEXT, bordercolor=BORDER, rowheight=27,
                        font=("Segoe UI", 9))
        style.map("Pulse.Treeview", background=[("selected", ACCENT)], foreground=[("selected", "white")])
        style.configure("Pulse.Treeview.Heading", background="#171e2e", foreground=TEXT,
                        relief="flat", font=("Segoe UI", 9, "bold"), padding=(7, 7))
        style.map("Pulse.Treeview.Heading", background=[("active", "#20283a")])

    def _build(self):
        tk.Label(self, text="TIKTOK SHOP INTELLIGENCE", bg=PANEL, fg=TEXT,
                 font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=22, pady=(22, 4))
        tk.Label(self, text="Public category discovery, observed deals and price history",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 10)).pack(anchor="w", padx=22)
        tabs = tk.Frame(self, bg=PANEL); tabs.pack(fill="x", padx=22, pady=(18, 10))
        for key, label in (("discovery", "DISCOVERY"), ("deals", "DEALS"), ("watchlist", "WATCHLIST"), ("history", "PRICE HISTORY")):
            button = tk.Button(tabs, text=label, command=lambda k=key: self.show_tab(k), bg=PANEL_2, fg=TEXT,
                               activebackground=ACCENT, activeforeground="white", relief="flat", bd=0,
                               padx=14, pady=8, font=("Segoe UI", 9, "bold"), cursor="hand2")
            button.pack(side="left", padx=(0, 7)); self.tab_buttons[key] = button
        self.body = tk.Frame(self, bg=PANEL); self.body.pack(fill="both", expand=True, padx=22)
        log_head = tk.Frame(self, bg=PANEL); log_head.pack(fill="x", padx=22, pady=(8, 2))
        tk.Label(log_head, text="ACTIVITY", bg=PANEL, fg=MUTED, font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Button(log_head, text="CLEAR LOG", command=self.clear_log, bg=PANEL_2, fg=TEXT,
                  relief="flat", bd=0, padx=12, pady=5).pack(side="right")
        self.log = tk.Text(self, height=5, bg=BG, fg=TEXT, relief="flat", font=("Consolas", 9), wrap="word")
        self.log.pack(fill="x", padx=22)
        tk.Label(self, textvariable=self.status, bg=PANEL_2, fg=SUCCESS, anchor="w", padx=12, pady=9,
                 font=("Consolas", 9, "bold")).pack(fill="x", padx=22, pady=(10, 20))

    def _clear(self):
        for child in self.body.winfo_children(): child.destroy()

    def show_tab(self, tab):
        self.active_tab = tab
        for key, button in self.tab_buttons.items(): button.configure(bg=ACCENT if key == tab else PANEL_2)
        self._clear()
        {"discovery": self._show_discovery, "deals": self._show_deals,
         "history": self._show_history, "watchlist": self._show_watchlist}[tab]()

    def _show_discovery(self):
        tk.Label(self.body, text="CATEGORY COLLECTOR", bg=PANEL, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(6, 7))
        tk.Label(self.body, text="Paste a public TikTok Shop category URL. One sweep records each product once.",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 9))
        row = tk.Frame(self.body, bg=PANEL); row.pack(fill="x")
        tk.Entry(row, textvariable=self.category_url, bg=PANEL_2, fg=TEXT, insertbackground=TEXT,
                 relief="flat", font=("Segoe UI", 10)).pack(side="left", fill="x", expand=True, ipady=9)
        self.collect_button = tk.Button(row, text="COLLECT CATEGORY", command=self.collect_now, bg=ACCENT, fg="white", activebackground=ACCENT,
                  activeforeground="white", relief="flat", bd=0, padx=18, pady=9,
                  font=("Segoe UI", 9, "bold"), cursor="hand2", state="disabled" if self.list_state.busy else "normal")
        self.collect_button.pack(side="left", padx=(8, 0))
        controls = tk.Frame(self.body, bg=PANEL); controls.pack(fill="x", pady=(8, 0))
        tk.Label(controls, text="ITEM LIST", bg=PANEL, fg=MUTED, font=("Consolas", 9)).pack(side="left", padx=(0, 8))
        ttk.Combobox(controls, textvariable=self.list_mode, values=MODES, state="readonly", width=16).pack(side="left")
        tk.Button(controls, text="CLEAR ITEMS", command=self.clear_items, bg=PANEL_2, fg=TEXT,
                  relief="flat", bd=0, padx=12, pady=6).pack(side="left", padx=8)
        self._results_table(self.body, self.last_results)

    def collect_now(self):
        if self.list_state.busy:
            return
        url = self.category_url.get().strip()
        if not url: self.status.set("NEEDS URL // paste a TikTok Shop category URL first"); return
        if "shop.tiktok.com" not in url.lower(): self.status.set("CHECK URL // expected a public shop.tiktok.com category URL"); return
        generation = self.list_state.begin(url, self.list_mode.get())
        self._refresh_items()
        self.status.set("COLLECTING // PASS 1")
        threading.Thread(target=self._collect_worker, args=(url, generation), daemon=True).start()

    def _collect_worker(self, url, generation):
        def progress(event):
            log_generation = self.log_generation
            self.after(0, lambda: self._progress(event, generation, log_generation))
        try:
            results = collect_category_session(url, self.store, on_progress=progress)
            log_generation = self.log_generation
            self.after(0, lambda: self._collection_done(results, generation, log_generation))
        except Exception:
            self.after(0, self._collection_failed)

    def _refresh_items(self):
        self.last_results = list(self.list_state.items.values())
        if self.active_tab in ("discovery", "deals"):
            self.show_tab(self.active_tab)

    def _write(self, message, generation):
        if generation == self.log_generation:
            self.log.insert(tk.END, message + "\n"); self.log.see(tk.END)

    def _progress(self, event, generation, log_generation):
        self.list_state.merge(event["products"], generation)
        self._refresh_items()
        self.status.set(event["message"])
        self._write(event["message"], log_generation)

    def _collection_done(self, results, generation, log_generation):
        self.list_state.merge(results, generation)
        self.list_state.busy = False
        summary = session_summary(results)
        self.status.set(summary)
        self._write(summary, log_generation)
        self._refresh_items()

    def _collection_failed(self):
        self.list_state.busy = False
        self.status.set("STOPPED // RECORDING ERROR // PARTIAL ITEMS RETAINED")
        self._write(self.status.get(), self.log_generation)
        self._refresh_items()

    def clear_items(self):
        self.list_state.clear_items()
        self._refresh_items()
        self.status.set("ITEMS CLEARED // saved data unchanged")

    def clear_log(self):
        self.log_generation += 1
        clear_log_widget(self.log)

    def _movement_text(self, item):
        bits = []
        if item.get("is_new_low"): bits.append("NEW LOW")
        if item.get("price_change") not in (None, 0): bits.append(f"{item['price_change']:+.2f} ({item.get('price_change_pct', 0):+.1f}%)")
        velocity = item.get("sales_velocity_per_day")
        if velocity is not None and abs(velocity) >= 0.05: bits.append(f"{velocity:+.1f}/day")
        return " | ".join(bits)

    def _results_table(self, parent, results):
        frame = tk.Frame(parent, bg=PANEL); frame.pack(fill="both", expand=True, pady=(16, 0))
        columns = ("score", "price", "movement", "median", "range", "sold", "title")
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=11, style="Pulse.Treeview")
        headings = {"score":"Score", "price":"Price", "movement":"Movement / Velocity", "median":"Median", "range":"Observed Range", "sold":"Sold", "title":"Product"}
        widths = {"score":52, "price":78, "movement":155, "median":75, "range":125, "sold":60, "title":300}
        for col in columns:
            tree.heading(col, text=headings[col]); tree.column(col, width=widths[col], anchor="w", stretch=(col == "title"))
        for item in sorted(results, key=lambda r: r.get("deal_score", 0), reverse=True):
            currency = item.get("currency", "GBP")
            med = item.get("historical_median")
            low, high = item.get("historical_low"), item.get("historical_high")
            median_text = f"{currency} {med:.2f}" if med is not None else "—"
            range_text = f"{low:.2f}–{high:.2f}" if low is not None and high is not None else "—"
            price_text = f"{currency} {item['price']:.2f}" if item.get("price") is not None else "—"
            movement = self._movement_text(item) if item.get("status") == "recorded" else item.get("status", "pending").upper()
            tree.insert("", "end", values=(item.get("deal_score", ""), price_text,
                        movement, median_text, range_text, item.get("sold_count", ""), item.get("title", "")))
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview); tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y"); tree.pack(side="left", fill="both", expand=True)

    def _show_deals(self):
        tk.Label(self.body, text="LATEST SWEEP // DEAL INTELLIGENCE", bg=PANEL, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(6, 0))
        tk.Label(self.body, text="Observed price range, median, new lows and sales velocity — not crossed-out marketing prices.",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(6, 0))
        if not self.last_results:
            tk.Label(self.body, text="Run Discovery first. Intelligence from the latest sweep will rank here.", bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(8, 0))
        self._results_table(self.body, self.last_results)

    def _show_watchlist(self):
        tk.Label(self.body, text="WATCHLIST", bg=PANEL, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(6, 7))
        tk.Label(self.body, text="Persistent product watches and alert rules are the next layer. Intelligence is now ready underneath them.", bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w")

    def _show_history(self):
        tk.Label(self.body, text="OBSERVED PRICE HISTORY", bg=PANEL, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(6, 7))
        row = tk.Frame(self.body, bg=PANEL); row.pack(fill="x")
        product_id = tk.StringVar()
        tk.Entry(row, textvariable=product_id, bg=PANEL_2, fg=TEXT, insertbackground=TEXT, relief="flat",
                 font=("Segoe UI", 10)).pack(side="left", fill="x", expand=True, ipady=8)
        output = tk.Text(self.body, height=12, bg=PANEL_2, fg=TEXT, insertbackground=TEXT, relief="flat", font=("Consolas", 9))
        output.pack(fill="both", expand=True, pady=(10, 0))
        def load_history():
            output.delete("1.0", tk.END); pid = product_id.get().strip()
            rows = self.store.price_history("tiktok_shop", pid) if pid else []
            if not rows: output.insert(tk.END, "No observed history for that product ID yet."); return
            prices = [float(r["effective_price"]) for r in rows if r.get("effective_price") is not None]
            if prices:
                from statistics import median
                output.insert(tk.END, f"OBSERVED LOW    GBP {min(prices):.2f}\nOBSERVED HIGH   GBP {max(prices):.2f}\nOBSERVED MEDIAN GBP {median(prices):.2f}\nOBSERVATIONS    {len(prices)}\n\n")
            for row_data in rows:
                output.insert(tk.END, f"{row_data['observed_at']}  |  GBP {row_data['effective_price']:.2f}  |  sold {row_data.get('sold_count')}\n")
        tk.Button(row, text="LOAD HISTORY", command=load_history, bg=PANEL_2, fg=TEXT, relief="flat", bd=0,
                  padx=14, pady=8, font=("Segoe UI", 9, "bold"), cursor="hand2").pack(side="left", padx=(8, 0))
