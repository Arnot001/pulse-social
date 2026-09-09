from __future__ import annotations

import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from ..pc_market import fingerprint_pc, market_value
from ..pc_market_sources import collect_market_references
from .categories import children_of, fetch_categories, roots
from .category_collector import collect_category
from .notifications import alert_message, load_settings, save_settings, send_discord, send_telegram
from .product_collector import collect_product
from .watchlist import ProductWatch, load_watchlist, remove_watch, upsert_watch

BG="#07090f"; PANEL="#0d111b"; PANEL_2="#121827"; BORDER="#20283a"; TEXT="#f5f7fb"; MUTED="#8993a6"; ACCENT="#ff008c"; SUCCESS="#35d07f"


def open_shop_window(parent: tk.Misc) -> tk.Toplevel:
    window=tk.Toplevel(parent); window.title("Pulse Social — TikTok Shop"); window.geometry("1080x780"); window.minsize(900,700); window.configure(bg=BG)
    categories=[]; maps=[{}, {}, {}]; results_by_iid={}; stop_watch=threading.Event(); last_checked={}
    main_var=tk.StringVar(); sub_var=tk.StringVar(); leaf_var=tk.StringVar(); status_var=tk.StringVar(value="CATEGORY TAXONOMY NOT LOADED")
    style=ttk.Style(window)
    try: style.theme_use("clam")
    except tk.TclError: pass
    style.configure("Pulse.Treeview",background=PANEL_2,fieldbackground=PANEL_2,foreground=TEXT,rowheight=27,font=("Segoe UI",9)); style.map("Pulse.Treeview",background=[("selected",ACCENT)],foreground=[("selected","white")]); style.configure("Pulse.Treeview.Heading",background="#171e2e",foreground=TEXT,font=("Segoe UI",9,"bold"))
    header=tk.Frame(window,bg=BG); header.pack(fill="x",padx=26,pady=(18,8)); tk.Label(header,text="PULSE",fg=TEXT,bg=BG,font=("Segoe UI",24,"bold")).pack(side="left"); tk.Label(header,text=" TIKTOK",fg=ACCENT,bg=BG,font=("Segoe UI",24,"bold")).pack(side="left"); tk.Label(header,text="SHOP  //  COMMERCE INTELLIGENCE",fg=MUTED,bg=BG,font=("Consolas",9)).pack(side="right",pady=10)
    card=tk.Frame(window,bg=PANEL,highlightthickness=1,highlightbackground=BORDER); card.pack(fill="x",padx=26,pady=8); tk.Label(card,text="TIKTOK SHOP CATEGORY",fg=TEXT,bg=PANEL,font=("Segoe UI",12,"bold")).grid(row=0,column=0,columnspan=4,sticky="w",padx=18,pady=(12,8))
    def combo(row,label,var):
        lab=tk.Label(card,text=label,fg=MUTED,bg=PANEL,font=("Consolas",8,"bold")); lab.grid(row=row,column=0,sticky="w",padx=18,pady=6); box=ttk.Combobox(card,textvariable=var,state="readonly",width=45); box.grid(row=row,column=1,sticky="w",pady=6); return lab,box
    _,main_box=combo(1,"MAIN CATEGORY",main_var); _,sub_box=combo(2,"SUBCATEGORY",sub_var); leaf_label,leaf_box=combo(3,"CATEGORY",leaf_var)
    tk.Label(card,textvariable=status_var,fg=SUCCESS,bg=PANEL,font=("Consolas",8,"bold")).grid(row=4,column=0,columnspan=4,sticky="w",padx=18,pady=(6,12))
    actions=tk.Frame(window,bg=BG); actions.pack(fill="x",padx=26,pady=(4,6))
    def button(parent,text,command,accent=False): return tk.Button(parent,text=text,command=command,bg=ACCENT if accent else PANEL_2,fg=TEXT,activebackground=ACCENT,activeforeground="white",relief="flat",bd=0,padx=13,pady=8,font=("Segoe UI",9,"bold"),cursor="hand2")
    results_frame=tk.Frame(window,bg=PANEL); results_frame.pack(fill="both",expand=True,padx=26,pady=(2,4)); cols=("score","price","market","move","sold","product"); tree=ttk.Treeview(results_frame,columns=cols,show="headings",height=10,style="Pulse.Treeview")
    for col,title,width in (("score","Score",50),("price","TikTok",90),("market","Market Value",150),("move","Movement",145),("sold","Sold",60),("product","Product",500)): tree.heading(col,text=title); tree.column(col,width=width,anchor="w",stretch=(col=="product"))
    scroll=ttk.Scrollbar(results_frame,orient="vertical",command=tree.yview); tree.configure(yscrollcommand=scroll.set); scroll.pack(side="right",fill="y"); tree.pack(side="left",fill="both",expand=True)
    log_head=tk.Frame(window,bg=BG); log_head.pack(fill="x",padx=26,pady=(4,2)); tk.Label(log_head,text="ACTIVITY / WATCH ALERTS",fg=TEXT,bg=BG,font=("Segoe UI",10,"bold")).pack(side="left"); log=tk.Text(window,height=7,bg="#080c13",fg="#cbd3df",insertbackground=TEXT,relief="flat",bd=0,font=("Consolas",9),padx=10,pady=8,wrap="word"); log.pack(fill="x",padx=26,pady=(0,18))
    def write(msg):
        def apply(): log.insert(tk.END,msg+"\n"); log.see(tk.END)
        window.after(0,apply)
    def copy_log(): window.clipboard_clear(); window.clipboard_append(log.get("1.0",tk.END).strip()); status_var.set("LOG COPIED")
    def clear_log(): log.delete("1.0",tk.END); status_var.set("LOG CLEARED")
    def export_log():
        path=filedialog.asksaveasfilename(parent=window,defaultextension=".txt",initialfile=f"pulse-tiktok-{datetime.now():%Y%m%d-%H%M%S}.txt",filetypes=[("Text","*.txt"),("All files","*.*")])
        if path: Path(path).write_text(log.get("1.0",tk.END),encoding="utf-8"); status_var.set("LOG EXPORTED")
    button(log_head,"COPY LOG",copy_log).pack(side="right",padx=(6,0)); button(log_head,"EXPORT LOG",export_log).pack(side="right",padx=(6,0)); button(log_head,"CLEAR",clear_log).pack(side="right")
    def set_values(box,var,items,index): maps[index]={x.name:x for x in items}; box["values"]=[x.name for x in items]; var.set(items[0].name if items else ""); box.configure(state="readonly" if items else "disabled")
    def selected_category():
        for idx,var in ((2,leaf_var),(1,sub_var),(0,main_var)):
            if var.get() in maps[idx]: return maps[idx][var.get()]
        return None
    def update_leafs(*_):
        selected=maps[1].get(sub_var.get()); kids=children_of(categories,selected.category_id) if selected else []; set_values(leaf_box,leaf_var,kids,2)
        if kids: leaf_label.grid(); leaf_box.grid()
        else: leaf_label.grid_remove(); leaf_box.grid_remove()
        chosen=selected_category(); status_var.set(f"READY // {chosen.name} // {chosen.category_id}" if chosen else "SELECT A CATEGORY")
    def update_subs(*_): selected=maps[0].get(main_var.get()); set_values(sub_box,sub_var,children_of(categories,selected.category_id) if selected else [],1); update_leafs()
    def taxonomy_loaded(items):
        nonlocal categories; categories=items; set_values(main_box,main_var,roots(categories),0); update_subs(); status_var.set(f"READY // {len(categories)} TIKTOK CATEGORIES LOADED"); refresh_btn.config(state="normal"); collect_btn.config(state="normal"); write(f"Loaded {len(categories)} categories from TikTok Shop embedded taxonomy.")
    def refresh_worker():
        try:
            items=fetch_categories()
            if not items: raise RuntimeError("TikTok returned no structured categories.")
            window.after(0,lambda:taxonomy_loaded(items))
        except Exception as exc: window.after(0,lambda:status_var.set("CATEGORY LOAD FAILED")); window.after(0,lambda:refresh_btn.config(state="normal")); write(f"Category refresh failed: {exc}")
    def refresh(): refresh_btn.config(state="disabled"); collect_btn.config(state="disabled"); status_var.set("LOADING LIVE TIKTOK CATEGORY TAXONOMY..."); write("Refreshing TikTok Shop categories..."); threading.Thread(target=refresh_worker,daemon=True).start()
    def populate(recorded):
        results_by_iid.clear()
        for iid in tree.get_children(): tree.delete(iid)
        for item in sorted(recorded,key=lambda r:r.get("deal_score",0),reverse=True):
            move=[]
            if item.get("is_new_low"): move.append("NEW LOW")
            if item.get("price_change") not in (None,0): move.append(f"{item['price_change']:+.2f} ({item.get('price_change_pct',0):+.1f}%)")
            market=item.get("market_value") or {}; market_text=""
            if market.get("status")=="OK": market_text=f"{market.get('saving_pct',0):+.0f}% vs market"
            iid=tree.insert("","end",values=(item.get("deal_score",""),f"{item.get('currency','GBP')} {item.get('price',0):.2f}",market_text," | ".join(move),item.get("sold_count",""),item.get("title",""))); results_by_iid[iid]=item
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
                if fp.confidence < 2:
                    write(f"MARKET VALUE | {item.get('product_id')} | insufficient PC specification confidence"); return
                window.after(0,lambda:status_var.set("CHECKING UK PC MARKET...")); refs=collect_market_references(fp); value=market_value(float(item.get("price",0)),fp,refs); item["market_value"]=value
                if value.get("status")!="OK":
                    write(f"MARKET VALUE | {fp.cpu} | {fp.gpu} | no reliable comparable retailer prices found"); window.after(0,lambda:status_var.set("NO RELIABLE MARKET COMPARABLES")); return
                lines=[f"{x.retailer}: GBP {x.price:.2f} | {x.title}" for x in value["comparables"]]
                summary=(f"{value['verdict']} | TikTok GBP {item['price']:.2f} | typical GBP {value['typical_price']:.2f} | "f"range GBP {value['market_low']:.2f}-GBP {value['market_high']:.2f} | saving GBP {value['saving']:.2f} ({value['saving_pct']:+.1f}%) | confidence {value['confidence']}/100")
                write("MARKET VALUE | "+summary); [write("  "+line) for line in lines]; window.after(0,lambda:status_var.set(value["verdict"])); window.after(0,lambda:populate(list(results_by_iid.values())))
            except Exception as exc: write(f"MARKET VALUE ERROR | {exc}"); window.after(0,lambda:status_var.set("MARKET CHECK FAILED"))
        threading.Thread(target=worker,daemon=True).start()
    menu=tk.Menu(window,tearoff=0,bg=PANEL_2,fg=TEXT); menu.add_command(label="Open Product",command=open_selected); menu.add_command(label="Copy Product Link",command=copy_link); menu.add_command(label="Copy Product ID",command=copy_id); menu.add_separator(); menu.add_command(label="Compare UK Market Price",command=compare_market); menu.add_command(label="Add to Watchlist",command=add_watch)
    def popup(event):
        iid=tree.identify_row(event.y)
        if iid: tree.selection_set(iid); menu.tk_popup(event.x_root,event.y_root)
    tree.bind("<Double-1>",open_selected); tree.bind("<Button-3>",popup); tree.bind("<Control-c>",lambda _e:copy_link())
    def collect_worker(category):
        try:
            write(f"Collecting {category.name} // {category.url}"); results=collect_category(category.url); recorded=[x for x in results if x.get("status")=="recorded"]; changed=[x for x in recorded if x.get("price_change") not in (None,0) or x.get("sold_change") not in (None,0)]; window.after(0,lambda:populate(recorded)); window.after(0,lambda:status_var.set(f"COMPLETE // {category.name.upper()} // {len(recorded)} RECORDED // {len(changed)} CHANGED")); write(f"Recorded {len(recorded)} products // Changed {len(changed)}")
        except Exception as exc: window.after(0,lambda:status_var.set("COLLECTION FAILED")); write(f"Collection failed: {exc}")
        finally: window.after(0,lambda:collect_btn.config(state="normal"))
    def collect():
        category=selected_category()
        if not category: messagebox.showerror("No category","Select a TikTok Shop category first.",parent=window); return
        collect_btn.config(state="disabled"); status_var.set(f"COLLECTING // {category.name.upper()}"); threading.Thread(target=collect_worker,args=(category,),daemon=True).start()
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
                    reasons=reasons_for(watch,item); write(f"WATCH CHECK | {watch.product_id} | {item.get('currency','GBP')} {item.get('price',0):.2f}"+(f" | {' + '.join(reasons)}" if reasons else ""))
                    if reasons: send_alerts(watch,item,reasons)
                except Exception as exc: write(f"WATCH ERROR | {watch.product_id} | {exc}")
    threading.Thread(target=watch_loop,daemon=True).start()
    def manage_watchlist():
        dialog=tk.Toplevel(window); dialog.title("TikTok Watchlist"); dialog.geometry("960x420"); dialog.configure(bg=PANEL); mapping={}; cols=("interval","drop","rise","desktop","discord","telegram","product"); wt=ttk.Treeview(dialog,columns=cols,show="headings",style="Pulse.Treeview")
        for col,title,width in (("interval","Every",65),("drop","Drop",55),("rise","Rise",55),("desktop","Desktop",65),("discord","Discord",65),("telegram","Telegram",65),("product","Product",540)): wt.heading(col,text=title); wt.column(col,width=width,anchor="w")
        def reload():
            mapping.clear()
            for iid in wt.get_children(): wt.delete(iid)
            for watch in load_watchlist(): mapping[wt.insert("","end",values=(f"{watch.interval_minutes}m","YES" if watch.any_drop else "—","YES" if watch.any_rise else "—","YES" if watch.desktop else "—","YES" if watch.discord else "—","YES" if watch.telegram else "—",watch.title))]=watch
        def selected_watch(): return mapping.get(wt.selection()[0]) if wt.selection() else None
        def remove():
            watch=selected_watch()
            if watch: remove_watch(watch.product_id); reload()
        def channels():
            watch=selected_watch()
            if not watch: return
            watch.discord=messagebox.askyesno("Discord","Send Discord alerts for this product?",parent=dialog); watch.telegram=messagebox.askyesno("Telegram","Send Telegram alerts for this product?",parent=dialog); upsert_watch(watch); reload()
        def price_alerts():
            watch=selected_watch()
            if not watch: return
            watch.any_drop=messagebox.askyesno("Price drops","Alert when this product price drops?",parent=dialog); watch.any_rise=messagebox.askyesno("Price rises","Alert when this product price rises?",parent=dialog); upsert_watch(watch); reload()
        wt.pack(fill="both",expand=True,padx=14,pady=14); bar=tk.Frame(dialog,bg=PANEL); bar.pack(fill="x",padx=14,pady=(0,14)); button(bar,"REMOVE",remove).pack(side="left"); button(bar,"PRICE ALERTS",price_alerts).pack(side="left",padx=8); button(bar,"SET DISCORD / TELEGRAM",channels,True).pack(side="left",padx=8); reload()
    refresh_btn=button(actions,"REFRESH CATEGORIES",refresh); refresh_btn.pack(side="left",padx=(0,8)); collect_btn=button(actions,"COLLECT CATEGORY",collect,True); collect_btn.pack(side="left",padx=8); collect_btn.config(state="disabled"); button(actions,"WATCHLIST",manage_watchlist).pack(side="left",padx=8); button(actions,"ALERT SETTINGS",notification_settings).pack(side="left",padx=8)
    main_box.bind("<<ComboboxSelected>>",update_subs); sub_box.bind("<<ComboboxSelected>>",update_leafs); leaf_box.bind("<<ComboboxSelected>>",lambda _e:status_var.set(f"READY // {selected_category().name}" if selected_category() else "SELECT A CATEGORY"))
    def close(): stop_watch.set(); window.destroy()
    window.protocol("WM_DELETE_WINDOW",close); refresh(); return window
