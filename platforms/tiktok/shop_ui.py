"""TikTok Shop dashboard for the standalone TikTok platform module."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from commerce.store import CommerceStore
from commerce.tiktok.categories import children_of, fetch_categories, roots
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
CYAN = "#29def4"
SUBTLE = "#65758b"
TABLE_BG = "#0b111b"
TAXONOMY_ATTEMPTS = 3
TAXONOMY_RETRY_SECONDS = 7


class TikTokShopView(tk.Frame):
    """UI adapter around the existing Commerce/TikTok collector."""

    def __init__(self, master, **kwargs):
        super().__init__(master, bg=PANEL, **kwargs)
        self.store = CommerceStore()
        self.last_results: list[dict] = []
        self.list_state = ShopListState()
        self.list_mode = tk.StringVar(value=MODES[0])
        self.log_generation = 0
        self.status = tk.StringVar(value="CATEGORY TAXONOMY NOT LOADED")
        self.active_tab = "discovery"
        self.tab_buttons: dict[str, tk.Button] = {}
        self.body = None
        self.categories = []
        self.category_maps = [{}, {}, {}]
        self.main_var = tk.StringVar()
        self.sub_var = tk.StringVar()
        self.leaf_var = tk.StringVar()
        self.taxonomy_loading = False
        self.main_box = None
        self.sub_box = None
        self.leaf_box = None
        self.leaf_slot = None
        self.collect_button = None
        self.refresh_categories_button = None
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
        style.configure(
            "Shop.TCombobox",
            fieldbackground="#111a28",
            background="#111a28",
            foreground=TEXT,
            arrowcolor=CYAN,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            padding=7,
        )
        style.map(
            "Shop.TCombobox",
            fieldbackground=[("readonly", PANEL_2)],
            foreground=[("disabled", MUTED), ("readonly", TEXT)],
            selectbackground=[("readonly", PANEL_2)],
            selectforeground=[("readonly", TEXT)],
        )
        style.configure(
            "Shop.Vertical.TScrollbar",
            background=BORDER,
            troughcolor=PANEL,
            bordercolor=PANEL,
            arrowcolor=MUTED,
            lightcolor=PANEL,
            darkcolor=PANEL,
        )

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
        tk.Label(
            self.body,
            text="CATEGORY COLLECTOR",
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w", pady=(6, 7))
        tk.Label(
            self.body,
            text="Choose a TikTok Shop category. Pulse loads the live taxonomy instead of making you paste URLs.",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(0, 9))

        selectors = tk.Frame(self.body, bg=PANEL)
        selectors.pack(fill="x")
        for col in range(3):
            selectors.columnconfigure(col, weight=1, uniform="shop-category")

        def combo(column, label, variable):
            slot = tk.Frame(selectors, bg=PANEL)
            slot.grid(row=0, column=column, sticky="ew", padx=(0, 10) if column < 2 else 0)
            tk.Label(
                slot,
                text=label,
                bg=PANEL,
                fg=MUTED,
                font=("Segoe UI", 8, "bold"),
            ).pack(anchor="w", pady=(0, 5))
            box = ttk.Combobox(
                slot,
                textvariable=variable,
                state="readonly",
                style="Shop.TCombobox",
            )
            box.pack(fill="x")
            return slot, box

        _, self.main_box = combo(0, "MAIN CATEGORY", self.main_var)
        _, self.sub_box = combo(1, "SUBCATEGORY", self.sub_var)
        self.leaf_slot, self.leaf_box = combo(2, "CATEGORY", self.leaf_var)

        self.main_box.bind("<<ComboboxSelected>>", self._update_subcategories)
        self.sub_box.bind("<<ComboboxSelected>>", self._update_leaf_categories)
        self.leaf_box.bind("<<ComboboxSelected>>", self._category_selected)

        controls = tk.Frame(self.body, bg=PANEL)
        controls.pack(fill="x", pady=(10, 0))
        self.collect_button = tk.Button(
            controls,
            text="COLLECT CATEGORY",
            command=self.collect_now,
            bg=ACCENT,
            fg="white",
            activebackground=ACCENT,
            activeforeground="white",
            relief="flat",
            bd=0,
            padx=16,
            pady=8,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )
        self.collect_button.pack(side="left")

        self.refresh_categories_button = tk.Button(
            controls,
            text="REFRESH CATEGORIES",
            command=self._refresh_taxonomy,
            bg=PANEL_2,
            fg=TEXT,
            activebackground="#20283a",
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            padx=12,
            pady=8,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )
        self.refresh_categories_button.pack(side="left", padx=(8, 0))

        tk.Label(
            controls,
            text="ITEM LIST",
            bg=PANEL,
            fg=MUTED,
            font=("Consolas", 9),
        ).pack(side="left", padx=(18, 8))
        ttk.Combobox(
            controls,
            textvariable=self.list_mode,
            values=MODES,
            state="readonly",
            width=16,
            style="Shop.TCombobox",
        ).pack(side="left")
        tk.Button(
            controls,
            text="CLEAR ITEMS",
            command=self.clear_items,
            bg=PANEL_2,
            fg=TEXT,
            relief="flat",
            bd=0,
            padx=12,
            pady=6,
        ).pack(side="left", padx=8)

        self._populate_taxonomy_controls()
        self._results_table(self.body, self.last_results)

        if not self.categories and not self.taxonomy_loading:
            self._refresh_taxonomy()

    def _set_category_values(self, box, variable, items, index):
        self.category_maps[index] = {item.name: item for item in items}
        box["values"] = [item.name for item in items]
        variable.set(items[0].name if items else "")
        box.configure(state="readonly" if items else "disabled")

    def _selected_category(self):
        for index, variable in ((2, self.leaf_var), (1, self.sub_var), (0, self.main_var)):
            selected = self.category_maps[index].get(variable.get())
            if selected is not None:
                return selected
        return None

    def _populate_taxonomy_controls(self):
        if not (self.main_box and self.main_box.winfo_exists()):
            return
        if not self.categories:
            for box, variable, index in (
                (self.main_box, self.main_var, 0),
                (self.sub_box, self.sub_var, 1),
                (self.leaf_box, self.leaf_var, 2),
            ):
                self._set_category_values(box, variable, [], index)
            if self.leaf_slot and self.leaf_slot.winfo_exists():
                self.leaf_slot.grid_remove()
            if self.collect_button and self.collect_button.winfo_exists():
                self.collect_button.configure(state="disabled")
            return
        self._set_category_values(self.main_box, self.main_var, roots(self.categories), 0)
        self._update_subcategories()

    def _update_subcategories(self, *_):
        if not (self.sub_box and self.sub_box.winfo_exists()):
            return
        selected = self.category_maps[0].get(self.main_var.get())
        children = children_of(self.categories, selected.category_id) if selected else []
        self._set_category_values(self.sub_box, self.sub_var, children, 1)
        self._update_leaf_categories()

    def _update_leaf_categories(self, *_):
        if not (self.leaf_box and self.leaf_box.winfo_exists()):
            return
        selected = self.category_maps[1].get(self.sub_var.get())
        children = children_of(self.categories, selected.category_id) if selected else []
        self._set_category_values(self.leaf_box, self.leaf_var, children, 2)
        if self.leaf_slot and self.leaf_slot.winfo_exists():
            if children:
                self.leaf_slot.grid()
            else:
                self.leaf_slot.grid_remove()
        self._category_selected()

    def _category_selected(self, *_):
        selected = self._selected_category()
        if self.collect_button and self.collect_button.winfo_exists():
            self.collect_button.configure(
                state="disabled" if self.taxonomy_loading or self.list_state.busy or selected is None else "normal"
            )
        if selected is not None and not self.taxonomy_loading and not self.list_state.busy:
            self.status.set(f"READY // {selected.name} // {selected.category_id}")

    def _refresh_taxonomy(self):
        if self.taxonomy_loading or self.list_state.busy:
            return
        self.taxonomy_loading = True
        self.status.set("COLLECTING CATEGORIES...")
        if self.collect_button and self.collect_button.winfo_exists():
            self.collect_button.configure(state="disabled")
        if self.refresh_categories_button and self.refresh_categories_button.winfo_exists():
            self.refresh_categories_button.configure(state="disabled")
        threading.Thread(target=self._taxonomy_worker, daemon=True).start()

    def _taxonomy_worker(self):
        for attempt in range(TAXONOMY_ATTEMPTS):
            try:
                items = fetch_categories()
                usable = bool(items and roots(items))
            except Exception:
                items = []
                usable = False
            if usable:
                self.after(0, lambda data=items: self._taxonomy_loaded(data))
                return
            if attempt < TAXONOMY_ATTEMPTS - 1:
                threading.Event().wait(TAXONOMY_RETRY_SECONDS)
        self.after(0, self._taxonomy_failed)

    def _taxonomy_loaded(self, items):
        self.categories = items
        self.taxonomy_loading = False
        self.status.set(f"CATEGORIES READY // {len(items)} LOADED")
        self._write(self.status.get(), self.log_generation)
        if self.active_tab == "discovery":
            self.show_tab("discovery")

    def _taxonomy_failed(self):
        self.taxonomy_loading = False
        self.status.set("CATEGORY LOAD FAILED // try REFRESH CATEGORIES")
        self._write(self.status.get(), self.log_generation)
        if self.active_tab == "discovery":
            self.show_tab("discovery")

    def collect_now(self):
        if self.list_state.busy or self.taxonomy_loading:
            return
        category = self._selected_category()
        if category is None:
            self.status.set("SELECT A CATEGORY")
            return
        generation = self.list_state.begin(category.url, self.list_mode.get())
        self._refresh_items()
        self.status.set(f"COLLECTING // {category.name.upper()} // PASS 1")
        threading.Thread(
            target=self._collect_worker,
            args=(category.url, generation, category.name),
            daemon=True,
        ).start()

    def _collect_worker(self, url, generation, category_name):
        def progress(event):
            log_generation = self.log_generation
            self.after(
                0,
                lambda: self._progress(
                    {**event, "message": f"{category_name.upper()} // {event['message']}"},
                    generation,
                    log_generation,
                ),
            )
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
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview, style="Shop.Vertical.TScrollbar"); tree.configure(yscrollcommand=scroll.set)
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
