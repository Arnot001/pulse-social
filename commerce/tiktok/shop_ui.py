from __future__ import annotations

import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from platforms.pdh_bridge import bridge_status

from ..pc_market import fingerprint_pc, market_value
from ..pc_market_sources import collect_market_references, market_diagnostics
from .categories import children_of, fetch_categories, roots
from .category_session import MODES, ShopListState, clear_log_widget, collect_category_session, session_summary
from .notifications import alert_message, load_settings, save_settings, send_discord, send_telegram
from .product_collector import collect_product
from .watchlist import ProductWatch, load_watchlist, remove_watch, upsert_watch

BG="#07090f"; PANEL="#0d111b"; PANEL_2="#121827"; BORDER="#20283a"; TEXT="#f5f7fb"; MUTED="#8993a6"; ACCENT="#ff008c"; SUCCESS="#35d07f"
TAXONOMY_ATTEMPTS = 3
TAXONOMY_RETRY_SECONDS = 7


def movement_display(item):
    """Present observed fields only; missing history is not an unchanged price."""
    bits=[]; tone=""
    if item.get("status") != "recorded":
        return item.get("status","pending").upper(),"pending"
    change=item.get("price_change")
    if item.get("is_new_low"): bits.append("[NEW LOW]"); tone="new_low"
    if change not in (None,0):
        arrow="↓" if change<0 else "↑"
        pct=item.get("price_change_pct")
        bits.append(f"{arrow} {change:+.2f}"+(f" ({pct:+.1f}%)" if pct is not None else ""))
        tone=tone or ("drop" if change<0 else "rise")
    elif change == 0 and not bits: bits.append("NO CHANGE")
    return "  ".join(bits) or "—",tone


def open_shop_window(parent: tk.Misc) -> tk.Toplevel:
    window=tk.Toplevel(parent); window.title("Pulse Social — TikTok Shop"); window.geometry("1080x780"); window.minsize(900,700); window.configure(bg=BG)
    categories=[]; maps=[{}, {}, {}]; results_by_iid={}; stop_watch=threading.Event(); last_checked={}
    list_state=ShopListState(); list_mode=tk.StringVar(value=MODES[0])
    taxonomy_loading=False
    main_var=tk.StringVar(); sub_var=tk.StringVar(); leaf_var=tk.StringVar(); status_var=tk.StringVar(value="CATEGORY TAXONOMY NOT LOADED")
    style=ttk.Style(window)
    try: style.theme_use("clam")
    except tk.TclError: pass
    # Retain the existing watchlist style; the main table has its own style.
    style.configure("Pulse.Treeview",background=PANEL_2,fieldbackground=PANEL_2,foreground=TEXT,rowheight=27,font=("Segoe UI",9))
    style.map("Pulse.Treeview",background=[("selected",ACCENT)],foreground=[("selected","white")])
    style.configure("Pulse.Treeview.Heading",background="#171e2e",foreground=TEXT,font=("Segoe UI",9,"bold"))
    style.configure("Shop.Treeview", background=PANEL_2, fieldbackground=PANEL_2,
                    foreground=TEXT, bordercolor=BORDER, lightcolor=BORDER,
                    darkcolor=BORDER, borderwidth=0, rowheight=32, font=("Segoe UI",9))
    style.map("Shop.Treeview", background=[("selected","#42243d")],
              foreground=[("selected",TEXT)])
    style.configure("Shop.Treeview.Heading", background="#171e2e", foreground=MUTED,
                    relief="flat", borderwidth=0, padding=(8,8), font=("Segoe UI",9,"bold"))
    style.map("Shop.Treeview.Heading", background=[("active",BORDER)])
    style.configure("Shop.TCombobox", fieldbackground=PANEL_2, background=PANEL_2,
                    foreground=TEXT, arrowcolor=MUTED, bordercolor=BORDER, lightcolor=BORDER,
                    darkcolor=BORDER, padding=5)
    style.map("Shop.TCombobox", fieldbackground=[("readonly",PANEL_2)],
              foreground=[("disabled",MUTED),("readonly",TEXT)],
              selectbackground=[("readonly",PANEL_2)], selectforeground=[("readonly",TEXT)])
    style.configure("Shop.Vertical.TScrollbar", background=BORDER, troughcolor=PANEL,
                    bordercolor=PANEL, arrowcolor=MUTED, lightcolor=PANEL, darkcolor=PANEL)
    header=tk.Frame(window,bg=BG); header.pack(fill="x",padx=26,pady=(16,7))
    tk.Label(header,text="PULSE",fg=TEXT,bg=BG,font=("Segoe UI",23,"bold")).pack(side="left")
    tk.Label(header,text=" TIKTOK",fg=ACCENT,bg=BG,font=("Segoe UI",23,"bold")).pack(side="left")
    tk.Label(header,text="SHOP  //  COMMERCE INTELLIGENCE",fg=MUTED,bg=BG,font=("Consolas",9)).pack(side="right",pady=9)

    # Compact system strip: useful live state, not a second dashboard.
    strip=tk.Frame(window,bg=PANEL,highlightthickness=1,highlightbackground=BORDER)
    strip.pack(fill="x",padx=26,pady=(0,8))
    pdh_label=tk.Label(strip,text="PDH CHECKING",fg=MUTED,bg=PANEL,font=("Consolas",9,"bold"))
    pdh_label.pack(side="left",padx=(12,14),pady=7)
    tk.Frame(strip,bg=BORDER,width=1,height=14).pack(side="left",padx=(0,14))
    counts_label=tk.Label(strip,text="0 CATEGORIES  //  PER CATEGORY  //  0 PRODUCTS",
                          fg=MUTED,bg=PANEL,font=("Consolas",9))
    counts_label.pack(side="left",pady=7)

    # Category deck: selectors sit side-by-side so the controls stay compact.
    card=tk.Frame(window,bg=PANEL,highlightthickness=1,highlightbackground=BORDER)
    card.pack(fill="x",padx=26,pady=(0,8))
    tk.Label(card,text="TIKTOK SHOP CATEGORY",fg=TEXT,bg=PANEL,
             font=("Segoe UI",11,"bold")).pack(anchor="w",padx=14,pady=(10,7))

    selectors=tk.Frame(card,bg=PANEL)
    selectors.pack(fill="x",padx=14)
    for col in range(3): selectors.columnconfigure(col,weight=1,uniform="shop-category")

    def combo(column,label,var):
        slot=tk.Frame(selectors,bg=PANEL)
        slot.grid(row=0,column=column,sticky="ew",padx=(0,10) if column<2 else 0)
        lab=tk.Label(slot,text=label,fg=MUTED,bg=PANEL,font=("Consolas",8,"bold"))
        lab.pack(anchor="w",pady=(0,4))
        box=ttk.Combobox(slot,textvariable=var,state="readonly",style="Shop.TCombobox")
        box.pack(fill="x")
        return slot,lab,box

    _,_,main_box=combo(0,"MAIN CATEGORY",main_var)
    _,_,sub_box=combo(1,"SUBCATEGORY",sub_var)
    leaf_slot,leaf_label,leaf_box=combo(2,"CATEGORY",leaf_var)

    actions=tk.Frame(card,bg=PANEL)
    actions.pack(fill="x",padx=14,pady=(10,0))

    def button(parent,text,command,accent=False):
        return tk.Button(parent,text=text,command=command,bg=ACCENT if accent else PANEL_2,
                         fg=TEXT,activebackground="#cc0876" if accent else BORDER,activeforeground=TEXT,
                         disabledforeground=MUTED,relief="flat",bd=0,padx=11,pady=7,
                         font=("Segoe UI",9,"bold"),cursor="hand2")

    mode_controls=tk.Frame(actions,bg=PANEL)
    mode_controls.pack(side="right")
    tk.Label(mode_controls,text="ITEM LIST",bg=PANEL,fg=MUTED,
             font=("Consolas",8,"bold")).pack(side="left",padx=(0,7))
    ttk.Combobox(mode_controls,textvariable=list_mode,values=MODES,state="readonly",
                 width=15,style="Shop.TCombobox").pack(side="left")

    status_label=tk.Label(card,textvariable=status_var,fg=SUCCESS,bg=PANEL,
                          font=("Consolas",8,"bold"),anchor="w",justify="left")
    status_label.pack(fill="x",padx=14,pady=(8,10))
    card.bind("<Configure>",lambda event:status_label.configure(wraplength=max(200,event.width-30)))
    results_frame=tk.Frame(window,bg=PANEL,highlightthickness=1,highlightbackground=BORDER)
    results_frame.pack(fill="both",expand=True,padx=26,pady=(0,4))
    cols=("score","price","market","move","sold","product")
    tree=ttk.Treeview(results_frame,columns=cols,show="headings",height=10,style="Shop.Treeview")
    for col,title,width,anchor in (("score","Score",58,"center"),("price","TikTok",100,"e"),
                                  ("market","Market Value",125,"e"),("move","Movement",230,"w"),
                                  ("sold","Sold",65,"e"),("product","Product",340,"w")):
        tree.heading(col,text=title,anchor=anchor)
        tree.column(col,width=width,minwidth=width if col!="product" else 160,anchor=anchor,stretch=(col=="product"))
    tree.tag_configure("even",background=PANEL_2)
    tree.tag_configure("odd",background="#161d2d")
    tree.tag_configure("new_low",foreground="#7edbb0")
    tree.tag_configure("drop",foreground="#a0d7c4")
    tree.tag_configure("rise",foreground="#e7bd89")
    tree.tag_configure("pending",foreground=MUTED)
    # The table already fits the window; avoid a bright native horizontal scrollbar.
    # A classic Tk scrollbar is more consistently themeable on Windows than ttk here.
    scroll=tk.Scrollbar(results_frame,orient="vertical",command=tree.yview,
                        bg=BORDER,troughcolor=PANEL,activebackground=ACCENT,
                        relief="flat",bd=0,highlightthickness=0,width=12)
    tree.configure(yscrollcommand=scroll.set)
    results_frame.rowconfigure(0,weight=1); results_frame.columnconfigure(0,weight=1)
    tree.grid(row=0,column=0,sticky="nsew"); scroll.grid(row=0,column=1,sticky="ns")
    def update_counts(*_):
        counts_label.configure(text=f"{len(categories)} CATEGORIES  //  {list_mode.get()}  //  {len(results_by_iid)} PRODUCTS")
    list_mode.trace_add("write",update_counts)
    # Read the existing bridge endpoint in a worker; all Tk updates stay on the UI thread.
    pdh_state={"pending":False,"connected":None}
    pdh_timer=None
    def read_pdh():
        try: pdh_state["connected"]=bool(bridge_status().get("pdhConnected"))
        except Exception: pdh_state["connected"]=False
        finally: pdh_state["pending"]=False
    def poll_pdh():
        nonlocal pdh_timer
        if stop_watch.is_set(): return
        connected=pdh_state["connected"]
        pdh_label.configure(text="PDH CONNECTED" if connected else "PDH CHECKING" if connected is None else "PDH DISCONNECTED",
                            fg="#27d9ed" if connected else MUTED)
        if not pdh_state["pending"]:
            pdh_state["pending"]=True
            threading.Thread(target=read_pdh,daemon=True).start()
        pdh_timer=window.after(2000,poll_pdh)
    log_head=tk.Frame(window,bg=BG); log_head.pack(fill="x",padx=26,pady=(4,2)); tk.Label(log_head,text="ACTIVITY / WATCH ALERTS",fg=TEXT,bg=BG,font=("Segoe UI",10,"bold")).pack(side="left"); log=tk.Text(window,height=7,bg="#080c13",fg="#cbd3df",insertbackground=TEXT,relief="flat",bd=0,font=("Consolas",9),padx=10,pady=8,wrap="word"); log.pack(fill="x",padx=26,pady=(0,18))
    # Reserve the activity controls before letting the table consume remaining height.
    results_frame.pack_forget(); log_head.pack_forget(); log.pack_forget()
    log.configure(height=5)
    log.pack(side="bottom",fill="x",padx=26,pady=(0,18))
    log_head.pack(side="bottom",fill="x",padx=26,pady=(4,2))
    results_frame.pack(fill="both",expand=True,padx=26,pady=(0,4))
    log_generation=[0]
    def write(msg):
        generation=log_generation[0]
        def apply():
            if generation != log_generation[0] or not log.winfo_exists():
                return
            log.insert(tk.END,msg+"\n"); log.see(tk.END)
        window.after(0,apply)
    def copy_log(): window.clipboard_clear(); window.clipboard_append(log.get("1.0",tk.END).strip()); status_var.set("LOG COPIED")
    def clear_log():
        log_generation[0]+=1
        clear_log_widget(log)
    def export_log():
        path=filedialog.asksaveasfilename(parent=window,defaultextension=".txt",initialfile=f"pulse-tiktok-{datetime.now():%Y%m%d-%H%M%S}.txt",filetypes=[("Text","*.txt"),("All files","*.*")])
        if path: Path(path).write_text(log.get("1.0",tk.END),encoding="utf-8"); status_var.set("LOG EXPORTED")
    button(log_head,"COPY LOG",copy_log).pack(side="right",padx=(6,0)); button(log_head,"EXPORT LOG",export_log).pack(side="right",padx=(6,0)); button(log_head,"CLEAR LOG",clear_log).pack(side="right")
    def set_values(box,var,items,index): maps[index]={x.name:x for x in items}; box["values"]=[x.name for x in items]; var.set(items[0].name if items else ""); box.configure(state="readonly" if items else "disabled")
    def selected_category():
        for idx,var in ((2,leaf_var),(1,sub_var),(0,main_var)):
            if var.get() in maps[idx]: return maps[idx][var.get()]
        return None
    def update_leafs(*_):
        selected=maps[1].get(sub_var.get()); kids=children_of(categories,selected.category_id) if selected else []; set_values(leaf_box,leaf_var,kids,2)
        if kids: leaf_slot.grid()
        else: leaf_slot.grid_remove()
        chosen=selected_category()
        if not list_state.busy and not taxonomy_loading: status_var.set(f"READY // {chosen.name} // {chosen.category_id}" if chosen else "SELECT A CATEGORY")
    def update_subs(*_): selected=maps[0].get(main_var.get()); set_values(sub_box,sub_var,children_of(categories,selected.category_id) if selected else [],1); update_leafs()
    def taxonomy_loaded(items):
        nonlocal categories, taxonomy_loading
        if stop_watch.is_set(): return
        categories=items
        update_counts()
        set_values(main_box,main_var,roots(categories),0); update_subs()
        taxonomy_loading=False
        message=f"CATEGORIES READY // {len(categories)} LOADED"
        status_var.set(message); write(message)
        refresh_btn.config(state="normal"); collect_btn.config(state="normal")
    def taxonomy_failed():
        nonlocal taxonomy_loading
        if stop_watch.is_set(): return
        taxonomy_loading=False
        status_var.set("CATEGORY LOAD FAILED"); write("CATEGORY LOAD FAILED")
        refresh_btn.config(state="normal")
        collect_btn.config(state="normal" if selected_category() else "disabled")
    def refresh_worker():
        # Fetch/parser and their existing request timeout remain unchanged. Only
        # publish a usable result or one terminal failure, never transient errors.
        for attempt in range(TAXONOMY_ATTEMPTS):
            if stop_watch.is_set(): return
            try:
                items=fetch_categories()
                usable=bool(items and roots(items))
            except Exception:
                usable=False
            if stop_watch.is_set(): return
            if usable:
                window.after(0,lambda items=items:taxonomy_loaded(items))
                return
            if attempt < TAXONOMY_ATTEMPTS - 1 and stop_watch.wait(TAXONOMY_RETRY_SECONDS): return
        window.after(0,taxonomy_failed)
    def refresh():
        nonlocal taxonomy_loading
        if list_state.busy or taxonomy_loading: return
        taxonomy_loading=True
        refresh_btn.config(state="disabled"); collect_btn.config(state="disabled")
        status_var.set("COLLECTING CATEGORIES...")
        threading.Thread(target=refresh_worker,daemon=True).start()
    def populate(recorded):
        selected=tree.selection(); focused=tree.focus(); position=tree.yview()
        results_by_iid.clear()
        for iid in tree.get_children(): tree.delete(iid)
        for index,item in enumerate(sorted(recorded,key=lambda r:r.get("deal_score") or 0,reverse=True)):
            move,tone=movement_display(item)
            market=item.get("market_value") or {}; market_text="—"
            if market.get("status")=="OK": market_text=f"{market.get('saving_pct',0):+.0f}% vs market"
            price_text=f"{item.get('currency','GBP')} {item['price']:.2f}" if item.get("price") is not None else "—"
            sold=item.get("sold_count")
            sold_text=f"{sold:,}" if isinstance(sold,(int,float)) else sold if sold is not None else "—"
            score=item.get("deal_score")
            score_text=f"{score:g}" if isinstance(score,(int,float)) else score if score is not None else "—"
            iid=tree.insert("","end",iid=str(item["product_id"]),
                            values=(score_text,price_text,market_text,move,sold_text,item.get("title","")),
                            tags=("odd" if index%2 else "even",tone))
            results_by_iid[iid]=item
        retained=[iid for iid in selected if iid in results_by_iid]
        if retained: tree.selection_set(retained)
        if focused in results_by_iid: tree.focus(focused)
        if position: tree.yview_moveto(position[0])
        update_counts()
    def clear_items():
        list_state.clear_items()
        populate([])
        status_var.set("ITEMS CLEARED // saved data unchanged")
    button(mode_controls,"CLEAR ITEMS",clear_items).pack(side="left",padx=(8,0))
    def selected_result():
        sel=tree.selection(); return results_by_iid.get(sel[0]) if sel else None
    def open_selected(*_):
        item=selected_result()
        if item and item.get("url"): webbrowser.open(item["url"])
    def copy_link():
        item=selected_result()
        if item and item.get("url"): window.clipboard_clear(); window.clipboard_append(item["url"]); status_var.set("PRODUCT LINK COPIED")
    def copy_id():
        item=selected_result()
        if item: window.clipboard_clear(); window.clipboard_append(str(item.get("product_id",""))); status_var.set("PRODUCT ID COPIED")
    def add_watch():
        item=selected_result()
        if not item: return
        interval=simpledialog.askinteger("Watch interval","Check every how many minutes?",parent=window,initialvalue=15,minvalue=1,maxvalue=1440)
        if interval is None: return
        upsert_watch(ProductWatch(product_id=str(item.get("product_id","")),title=item.get("title",""),url=item.get("url",""),interval_minutes=interval)); status_var.set(f"WATCHING // every {interval} min"); write(f"WATCH ADDED | {item.get('product_id')} | every {interval} min | price drops + rises | {item.get('url')}")
    def compare_market():
        item=selected_result()
        if not item: return
        def worker():
            try:
                fp=fingerprint_pc(item.get("title", ""), item.get("specs") or {})
                if fp.confidence < 2: write(f"MARKET VALUE | {item.get('product_id')} | insufficient PC specification confidence"); return
                window.after(0,lambda:status_var.set("CHECKING UK PC MARKET...")); refs=collect_market_references(fp); value=market_value(float(item.get("price",0)),fp,refs); item["market_value"]=value
                if value.get("status")!="OK":
                    write(f"MARKET VALUE | {fp.cpu} | {fp.gpu} | no reliable comparable retailer prices found")
                    for diag in market_diagnostics(): write("  SOURCE | "+diag)
                    window.after(0,lambda:status_var.set("NO RELIABLE MARKET COMPARABLES")); return
                lines=[f"{x.retailer}: GBP {x.price:.2f} | {x.title}" for x in value["comparables"]]
                summary=(f"{value['verdict']} | TikTok GBP {item['price']:.2f} | typical GBP {value['typical_price']:.2f} | range GBP {value['market_low']:.2f}-GBP {value['market_high']:.2f} | saving GBP {value['saving']:.2f} ({value['saving_pct']:+.1f}%) | confidence {value['confidence']}/100")
                write("MARKET VALUE | "+summary); [write("  "+line) for line in lines]; window.after(0,lambda:status_var.set(value["verdict"])); window.after(0,lambda:populate(list(results_by_iid.values())))
            except Exception as exc: write(f"MARKET VALUE ERROR | {exc}"); window.after(0,lambda:status_var.set("MARKET CHECK FAILED"))
        threading.Thread(target=worker,daemon=True).start()
    menu=tk.Menu(window,tearoff=0,bg=PANEL_2,fg=TEXT); menu.add_command(label="Open Product",command=open_selected); menu.add_command(label="Copy Product Link",command=copy_link); menu.add_command(label="Copy Product ID",command=copy_id); menu.add_separator(); menu.add_command(label="Compare UK Market Price",command=compare_market); menu.add_command(label="Add to Watchlist",command=add_watch)
    def popup(event):
        iid=tree.identify_row(event.y)
        if iid: tree.selection_set(iid); menu.tk_popup(event.x_root,event.y_root)
    tree.bind("<Double-1>",open_selected); tree.bind("<Button-3>",popup); tree.bind("<Control-c>",lambda _e:copy_link())
    def collection_progress(event,generation,category_name):
        list_state.merge(event["products"],generation)
        populate(list(list_state.items.values()))
        status_var.set(f"{category_name.upper()} // {event['message']}")
    def collection_finished():
        list_state.busy=False
        collect_btn.config(state="normal"); refresh_btn.config(state="normal")
    def collect_worker(category,generation):
        def progress(event):
            write(f"{category.name.upper()} // {event['message']}")
            window.after(0,lambda:collection_progress(event,generation,category.name))
        try:
            results=collect_category_session(category.url,on_progress=progress)
            summary=session_summary(results)
            def done():
                list_state.merge(results,generation)
                populate(list(list_state.items.values()))
                status_var.set(summary)
            window.after(0,done)
            write(summary)
        except Exception:
            window.after(0,lambda:status_var.set("STOPPED // RECORDING ERROR // PARTIAL ITEMS RETAINED"))
            write("STOPPED // RECORDING ERROR // PARTIAL ITEMS RETAINED")
        finally: window.after(0,collection_finished)
    def collect():
        if list_state.busy or taxonomy_loading: return
        category=selected_category()
        if not category: messagebox.showerror("No category","Select a TikTok Shop category first.",parent=window); return
        generation=list_state.begin(category.url,list_mode.get())
        populate(list(list_state.items.values()))
        collect_btn.config(state="disabled"); refresh_btn.config(state="disabled")
        status_var.set(f"COLLECTING // {category.name.upper()} // PASS 1")
        threading.Thread(target=collect_worker,args=(category,generation),daemon=True).start()
    def notification_settings():
        current=load_settings(); dialog=tk.Toplevel(window); dialog.title("TikTok Shop Alerts"); dialog.geometry("650x300"); dialog.configure(bg=PANEL); dialog.transient(window); dialog.grab_set(); vars={k:tk.StringVar(value=current.get(k,"")) for k in current}
        for row,(key,label) in enumerate((("discord_webhook","DISCORD WEBHOOK"),("telegram_bot_token","TELEGRAM BOT TOKEN"),("telegram_chat_id","TELEGRAM CHAT ID"))): tk.Label(dialog,text=label,bg=PANEL,fg=MUTED,font=("Consolas",8,"bold")).grid(row=row,column=0,sticky="w",padx=18,pady=12); tk.Entry(dialog,textvariable=vars[key],width=55,bg=PANEL_2,fg=TEXT,insertbackground=TEXT,show="*" if key!="telegram_chat_id" else "").grid(row=row,column=1,padx=12,pady=12)
        def save(): save_settings({k:v.get().strip() for k,v in vars.items()}); dialog.destroy(); status_var.set("ALERT SETTINGS SAVED")
        button(dialog,"SAVE ALERT SETTINGS",save,True).grid(row=4,column=1,sticky="e",padx=12,pady=18)
    def reasons_for(watch,item):
        reasons=[]; change=item.get("price_change"); pct=item.get("price_change_pct")
        if watch.any_drop and change is not None and change < -0.005: reasons.append("PRICE DROP")
        if watch.any_rise and change is not None and change > 0.005: reasons.append("PRICE RISE")
        if watch.new_low and item.get("is_new_low"): reasons.append("NEW OBSERVED LOW")
        if watch.target_price is not None and item.get("price") is not None and item["price"]<=watch.target_price: reasons.append(f"TARGET PRICE {watch.target_price:.2f}")
        if watch.drop_pct is not None and pct is not None and pct<=-abs(watch.drop_pct): reasons.append(f"DROP {abs(watch.drop_pct):.1f}%+")
        return reasons
    def send_alerts(watch,item,reasons):
        msg=alert_message(item," + ".join(reasons)); write("ALERT | "+msg.replace("\n"," | ")); settings=load_settings()
        if watch.desktop: window.after(0,lambda:messagebox.showinfo("Pulse TikTok Shop Alert",msg,parent=window))
        if watch.discord and settings.get("discord_webhook"):
            try: send_discord(settings["discord_webhook"],msg)
            except Exception as exc: write(f"Discord alert failed: {exc}")
        if watch.telegram and settings.get("telegram_bot_token") and settings.get("telegram_chat_id"):
            try: send_telegram(settings["telegram_bot_token"],settings["telegram_chat_id"],msg)
            except Exception as exc: write(f"Telegram alert failed: {exc}")
    def watch_loop():
        while not stop_watch.wait(30):
            now=time.time()
            for watch in load_watchlist():
                if now-last_checked.get(watch.product_id,0)<max(60,watch.interval_minutes*60): continue
                last_checked[watch.product_id]=now
                try:
                    item=collect_product(watch.url)
                    if item.get("status")!="recorded": write(f"WATCH SKIP | {watch.product_id} | {item.get('error','not recorded')}"); continue
                    source_note=" | CATEGORY FALLBACK" if item.get("watch_price_source")=="stored_category_observation" else ""
                    reasons=reasons_for(watch,item); write(f"WATCH CHECK | {watch.product_id} | {item.get('currency','GBP')} {item.get('price',0):.2f}{source_note}"+(f" | {' + '.join(reasons)}" if reasons else ""))
                    if reasons: send_alerts(watch,item,reasons)
                except Exception as exc: write(f"WATCH ERROR | {watch.product_id} | {exc}")
    threading.Thread(target=watch_loop,daemon=True).start()
    def manage_watchlist():
        dialog=tk.Toplevel(window); dialog.title("TikTok Watchlist"); dialog.geometry("960x420"); dialog.configure(bg=PANEL); dialog.transient(window); mapping={}; cols=("interval","drop","rise","desktop","discord","telegram","product"); wt=ttk.Treeview(dialog,columns=cols,show="headings",style="Pulse.Treeview",selectmode="browse")
        for col,title,width in (("interval","Every",65),("drop","Drop",55),("rise","Rise",55),("desktop","Desktop",65),("discord","Discord",65),("telegram","Telegram",65),("product","Product",540)): wt.heading(col,text=title); wt.column(col,width=width,anchor="w")
        def reload(select_product_id=None):
            mapping.clear()
            for iid in wt.get_children(): wt.delete(iid)
            select_iid=None
            for watch in load_watchlist():
                iid=wt.insert("","end",values=(f"{watch.interval_minutes}m","YES" if watch.any_drop else "—","YES" if watch.any_rise else "—","YES" if watch.desktop else "—","YES" if watch.discord else "—","YES" if watch.telegram else "—",watch.title)); mapping[iid]=watch
                if select_product_id and watch.product_id==select_product_id: select_iid=iid
            children=wt.get_children()
            if select_iid is None and children: select_iid=children[0]
            if select_iid: wt.selection_set(select_iid); wt.focus(select_iid); wt.see(select_iid)
        def selected_watch(): return mapping.get(wt.selection()[0]) if wt.selection() else None
        def require_watch():
            watch=selected_watch()
            if watch is None: messagebox.showinfo("Select a product","Select a watchlist product first.",parent=dialog)
            return watch
        def remove():
            watch=require_watch()
            if watch: remove_watch(watch.product_id); reload()
        def channels():
            watch=require_watch()
            if not watch: return
            product_id=watch.product_id
            watch.discord=messagebox.askyesno("Discord",f"Send Discord alerts for:\n\n{watch.title}?",parent=dialog)
            watch.telegram=messagebox.askyesno("Telegram",f"Send Telegram alerts for:\n\n{watch.title}?",parent=dialog)
            upsert_watch(watch); reload(product_id)
        def price_alerts():
            watch=require_watch()
            if not watch: return
            product_id=watch.product_id
            watch.any_drop=messagebox.askyesno("Price drops",f"Alert when this product price drops?\n\n{watch.title}",parent=dialog); watch.any_rise=messagebox.askyesno("Price rises",f"Alert when this product price rises?\n\n{watch.title}",parent=dialog); upsert_watch(watch); reload(product_id)
        wt.pack(fill="both",expand=True,padx=14,pady=14); bar=tk.Frame(dialog,bg=PANEL); bar.pack(fill="x",padx=14,pady=(0,14)); button(bar,"REMOVE",remove).pack(side="left"); button(bar,"PRICE ALERTS",price_alerts).pack(side="left",padx=8); button(bar,"SET DISCORD / TELEGRAM",channels,True).pack(side="left",padx=8); reload()
    collect_btn=button(actions,"COLLECT CATEGORY",collect,True); collect_btn.pack(side="left",padx=(0,8)); collect_btn.config(state="disabled")
    refresh_btn=button(actions,"REFRESH CATEGORIES",refresh); refresh_btn.pack(side="left",padx=(0,8))
    button(actions,"WATCHLIST",manage_watchlist).pack(side="left",padx=(0,8))
    button(actions,"ALERT SETTINGS",notification_settings).pack(side="left")
    main_box.bind("<<ComboboxSelected>>",update_subs); sub_box.bind("<<ComboboxSelected>>",update_leafs); leaf_box.bind("<<ComboboxSelected>>",lambda _e:None if list_state.busy or taxonomy_loading else status_var.set(f"READY // {selected_category().name}" if selected_category() else "SELECT A CATEGORY"))
    def close():
        stop_watch.set()
        if pdh_timer is not None: window.after_cancel(pdh_timer)
        window.destroy()
    window.protocol("WM_DELETE_WINDOW",close); refresh(); poll_pdh(); return window
