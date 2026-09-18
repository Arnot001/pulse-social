from __future__ import annotations

import threading
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox, ttk

from .auto_post import add_post, load_queue, remove_post, run_scheduler

BG="#07090f"; PANEL="#0d111b"; PANEL_2="#121827"; BORDER="#20283a"; TEXT="#f5f7fb"; MUTED="#8993a6"; ACCENT="#ff008c"; SUCCESS="#35d07f"


def open_auto_post_window(parent: tk.Misc) -> tk.Toplevel:
    window=tk.Toplevel(parent); window.title("Pulse Social — X Auto Post"); window.geometry("900x720"); window.minsize(780,650); window.configure(bg=BG)
    stop_event=threading.Event(); worker=[None]; status=tk.StringVar(value="STOPPED")
    style=ttk.Style(window)
    try: style.theme_use("clam")
    except tk.TclError: pass
    style.configure("Pulse.Treeview",background=PANEL_2,fieldbackground=PANEL_2,foreground=TEXT,rowheight=28,font=("Segoe UI",9))
    style.configure("Pulse.Treeview.Heading",background="#171e2e",foreground=TEXT,font=("Segoe UI",9,"bold"))

    def button(parent,text,command,accent=False):
        return tk.Button(parent,text=text,command=command,bg=ACCENT if accent else PANEL_2,fg=TEXT,activebackground=ACCENT,activeforeground="white",relief="flat",bd=0,padx=14,pady=8,font=("Segoe UI",9,"bold"),cursor="hand2")

    header=tk.Frame(window,bg=BG); header.pack(fill="x",padx=26,pady=(20,10))
    tk.Label(header,text="PULSE",fg=TEXT,bg=BG,font=("Segoe UI",24,"bold")).pack(side="left")
    tk.Label(header,text=" X",fg=ACCENT,bg=BG,font=("Segoe UI",24,"bold")).pack(side="left")
    tk.Label(header,text="AUTO POST",fg=MUTED,bg=BG,font=("Consolas",9,"bold")).pack(side="right",pady=10)

    compose=tk.Frame(window,bg=PANEL,highlightthickness=1,highlightbackground=BORDER); compose.pack(fill="x",padx=26,pady=8)
    tk.Label(compose,text="COMPOSE",fg=TEXT,bg=PANEL,font=("Segoe UI",12,"bold")).pack(anchor="w",padx=16,pady=(14,6))
    text=tk.Text(compose,height=6,bg="#080c13",fg=TEXT,insertbackground=TEXT,relief="flat",font=("Segoe UI",10),wrap="word",padx=10,pady=8)
    text.pack(fill="x",padx=16,pady=(0,10))
    controls=tk.Frame(compose,bg=PANEL); controls.pack(fill="x",padx=16,pady=(0,14))
    tk.Label(controls,text="POST IN",fg=MUTED,bg=PANEL,font=("Consolas",8,"bold")).pack(side="left")
    delay=tk.StringVar(value="60"); tk.Entry(controls,textvariable=delay,width=8,bg=PANEL_2,fg=TEXT,insertbackground=TEXT,relief="flat").pack(side="left",padx=(8,4))
    tk.Label(controls,text="minutes",fg=MUTED,bg=PANEL,font=("Segoe UI",9)).pack(side="left")

    cols=("due","status","post"); tree=ttk.Treeview(window,columns=cols,show="headings",style="Pulse.Treeview",height=10)
    for col,title,width in (("due","Due",150),("status","Status",80),("post","Post",590)):
        tree.heading(col,text=title); tree.column(col,width=width,anchor="w",stretch=(col=="post"))
    tree.pack(fill="both",expand=True,padx=26,pady=8)
    mapping={}

    log=tk.Text(window,height=7,bg="#080c13",fg="#cbd3df",insertbackground=TEXT,relief="flat",font=("Consolas",9),wrap="word",padx=10,pady=8)
    log.pack(fill="x",padx=26,pady=(6,18))
    def write(msg):
        window.after(0,lambda:(log.insert(tk.END,msg+"\n"),log.see(tk.END),refresh()))

    def refresh():
        selected=tree.selection(); selected_id=mapping.get(selected[0]).post_id if selected and selected[0] in mapping else None
        mapping.clear()
        for iid in tree.get_children(): tree.delete(iid)
        pick=None
        for item in load_queue():
            try: due=datetime.fromisoformat(item.due_at).strftime("%d/%m/%Y %H:%M")
            except ValueError: due=item.due_at
            iid=tree.insert("","end",values=(due,item.status.upper(),item.text.replace("\n"," "))); mapping[iid]=item
            if item.post_id==selected_id: pick=iid
        if pick: tree.selection_set(pick)

    def queue_post():
        body=text.get("1.0",tk.END).strip()
        try:
            minutes=int(delay.get())
            if minutes < 0: raise ValueError
        except ValueError:
            messagebox.showerror("Invalid delay","Post delay must be 0 or more whole minutes.",parent=window); return
        if not body:
            messagebox.showerror("Empty post","Write the post first.",parent=window); return
        due=datetime.now()+timedelta(minutes=minutes)
        add_post(body,due); text.delete("1.0",tk.END); refresh(); write(f"QUEUED | {due:%H:%M} | {body[:90]}")

    def remove_selected():
        sel=tree.selection()
        if not sel: return
        item=mapping.get(sel[0])
        if item: remove_post(item.post_id); refresh()

    def start():
        if worker[0] and worker[0].is_alive(): return
        stop_event.clear(); worker[0]=threading.Thread(target=run_scheduler,args=(stop_event,write),daemon=True); worker[0].start(); status.set("RUNNING")
    def stop():
        stop_event.set(); status.set("STOPPED")

    bar=tk.Frame(window,bg=BG); bar.pack(fill="x",padx=26,pady=(0,4))
    button(bar,"QUEUE POST",queue_post,True).pack(side="left")
    button(bar,"REMOVE",remove_selected).pack(side="left",padx=8)
    button(bar,"START AUTO POST",start,True).pack(side="right")
    button(bar,"STOP",stop).pack(side="right",padx=8)
    tk.Label(bar,textvariable=status,fg=SUCCESS,bg=BG,font=("Consolas",9,"bold")).pack(side="right",padx=12)

    def close():
        stop_event.set(); window.destroy()
    window.protocol("WM_DELETE_WINDOW",close); refresh(); return window
