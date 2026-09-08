import os
import json
import time
import queue
import threading
from datetime import datetime
from urllib.parse import urlparse
import tkinter as tk
from tkinter import messagebox
from playwright.sync_api import sync_playwright, TimeoutError

APP_DIR = os.path.join(os.environ["LOCALAPPDATA"], "Pulse Social")
os.makedirs(APP_DIR, exist_ok=True)
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")
LOG_FILE = os.path.join(APP_DIR, "deleted_log.txt")
POST_LOG_FILE = os.path.join(APP_DIR, "post_log.txt")
REPLY_LOG_FILE = os.path.join(APP_DIR, "reply_log.txt")
REPOST_LOG_FILE = os.path.join(APP_DIR, "repost_log.txt")
LIKE_LOG_FILE = os.path.join(APP_DIR, "like_log.txt")
CDP_PORT = 9222
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"

BG = "#07090f"; PANEL = "#0d111b"; PANEL_2 = "#121827"; BORDER = "#20283a"; TEXT = "#f5f7fb"; MUTED = "#8993a6"; ACCENT = "#ff008c"; SUCCESS = "#35d07f"; DANGER = "#ff4057"
DEFAULTS = {"handle": "", "mode": "posts", "dry_run": True, "max_actions": 10, "delay": 3, "refresh_every": 25}
log_queue = queue.Queue(); continue_event = threading.Event(); stop_event = threading.Event(); run_state_queue = queue.Queue()

def ui_log(msg): log_queue.put(msg)
def set_run_state(state, dry_run=None, mode=None, max_actions=None): run_state_queue.put((state, dry_run, mode, max_actions))
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f: return {**DEFAULTS, **json.load(f)}
        except Exception: pass
    return DEFAULTS.copy()
def save_settings(settings):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f: json.dump(settings, f, indent=2)
def safe_text(locator):
    try: return locator.inner_text(timeout=3000)
    except Exception: return ""
def is_repost(text):
    lower = text.lower(); return "you reposted" in lower or " reposted " in lower or lower.startswith("reposted")

def parse_status_href(href):
    if not href: return None
    try:
        path = urlparse(href).path if "://" in href else urlparse("https://x.com" + href).path
        parts = [part for part in path.split("/") if part]
        if len(parts) >= 3 and parts[1].lower() == "status" and parts[2].isdigit(): return parts[0].lower(), parts[2]
    except Exception: pass
    return None

def authored_status(article, handle):
    clean = handle.strip().lstrip("@").lower()
    if not clean: return None
    try:
        links = article.locator('a[href*="/status/"]')
        for i in range(links.count()):
            parsed = parse_status_href(links.nth(i).get_attribute("href") or "")
            if parsed and parsed[0] == clean: return parsed
    except Exception: pass
    return None

def article_identity(article, handle=None, require_owned=False):
    if handle:
        owned = authored_status(article, handle)
        if owned: return f"status:{owned[1]}"
        if require_owned: return None
    try:
        links = article.locator('a[href*="/status/"]')
        for i in range(links.count()):
            parsed = parse_status_href(links.nth(i).get_attribute("href") or "")
            if parsed: return f"status:{parsed[1]}"
    except Exception: pass
    text = safe_text(article).strip(); return f"text:{text}" if text else None

def log_action(action, text, mode=None):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S"); preview = text[:180].replace("\n", " ").strip()
    target = {"posts": POST_LOG_FILE, "replies": REPLY_LOG_FILE, "reposts": REPOST_LOG_FILE, "likes": LIKE_LOG_FILE}.get(mode, LOG_FILE)
    with open(target, "a", encoding="utf-8") as f: f.write(f"{timestamp} | {action} | {preview}\n")
    if target != LOG_FILE:
        with open(LOG_FILE, "a", encoding="utf-8") as f: f.write(f"{timestamp} | {action} | {preview}\n")
def close_menu(page):
    try: page.keyboard.press("Escape")
    except Exception: pass

def connect_cdp(playwright, timeout_seconds=10):
    deadline = time.time() + timeout_seconds; last_error = None
    while time.time() < deadline:
        try: return playwright.chromium.connect_over_cdp(CDP_URL, timeout=3000)
        except Exception as e: last_error = e; time.sleep(0.5)
    raise RuntimeError(f"Could not attach to Brave on port {CDP_PORT}. Start Brave with --remote-debugging-port={CDP_PORT} first. Last error: {last_error}")

def find_x_page(context, target_url):
    for page in context.pages:
        try:
            if "x.com" in page.url.lower() or "twitter.com" in page.url.lower(): return page
        except Exception: pass
    page = context.new_page(); page.goto(target_url, wait_until="domcontentloaded"); return page

def delete_own_post(page, article, dry_run, delay, handle, mode):
    text = safe_text(article)
    if not text or is_repost(text): return False
    owned = authored_status(article, handle)
    if not owned:
        ui_log("Skipped article: no exact authored status link for your handle")
        return False
    more = article.locator('[aria-label="More"]').first
    if more.count() == 0: return False
    if dry_run:
        ui_log(f"PREVIEW {mode[:-1].upper() if mode.endswith('s') else mode.upper()} candidate [{owned[1]}]:")
        ui_log(text[:220].replace("\n", " "))
        return True
    more.click(timeout=4000)
    menu_delete = page.get_by_role("menuitem", name="Delete", exact=True)
    if menu_delete.count() == 0:
        close_menu(page); ui_log(f"Delete menu item not found for status {owned[1]}"); return False
    menu_delete.first.click(timeout=4000)
    confirm = page.locator('[data-testid="confirmationSheetConfirm"]')
    if confirm.count() == 0:
        dialog = page.get_by_role("dialog")
        if dialog.count(): confirm = dialog.get_by_role("button", name="Delete", exact=True)
    if confirm.count() == 0:
        close_menu(page); ui_log(f"Delete confirmation not found for status {owned[1]}"); return False
    confirm.first.click(timeout=4000)
    log_action(f"Deleted {mode} status {owned[1]}", text, mode); ui_log(f"Deleted {mode} [{owned[1]}]"); time.sleep(delay); return True

def undo_repost(page, article, dry_run, delay):
    text = safe_text(article)
    if not is_repost(text): return False
    button = article.locator('[data-testid="unretweet"]').first
    if button.count() == 0: return False
    if dry_run: ui_log("PREVIEW repost candidate:"); ui_log(text[:220].replace("\n", " ")); return True
    button.click(timeout=3000); time.sleep(0.5); undo = page.get_by_text("Undo repost")
    if undo.count() == 0: close_menu(page); return False
    undo.first.click(timeout=3000); log_action("Undid repost", text, "reposts"); ui_log("Undid repost"); time.sleep(delay); return True
def unlike_post(page, article, dry_run, delay):
    text = safe_text(article); unlike = article.locator('[data-testid="unlike"]').first
    if unlike.count() == 0: return False
    if dry_run: ui_log("PREVIEW like candidate:"); ui_log(text[:220].replace("\n", " ")); return True
    unlike.click(timeout=3000); log_action("Removed like", text, "likes"); ui_log("Removed like"); time.sleep(delay); return True

def cleaner_worker(settings):
    stop_event.clear(); continue_event.clear(); handle = settings["handle"].strip().replace("@", ""); mode = settings["mode"]; dry_run = settings["dry_run"]
    max_actions = int(settings["max_actions"]); delay = float(settings["delay"]); refresh_every = int(settings["refresh_every"])
    if not handle: ui_log("Enter your X handle first."); set_run_state("idle"); return
    set_run_state("attaching", dry_run, mode, max_actions)
    url = f"https://x.com/{handle}/likes" if mode == "likes" else f"https://x.com/{handle}/with_replies" if mode == "replies" else f"https://x.com/{handle}"
    ui_log(f"Attaching to your existing Brave session on port {CDP_PORT}...")
    try:
        with sync_playwright() as p:
            try: browser = connect_cdp(p)
            except Exception as e: ui_log(str(e)); return
            contexts = browser.contexts
            if not contexts: ui_log("Brave attached but no browser context was available."); return
            context = contexts[0]
            try: page = find_x_page(context, url)
            except Exception as e: ui_log(f"Could not find/open X in Brave: {e}"); return
            ui_log("Attached to Brave. Your existing browser login/session is being used.")
            ui_log(f"RUN LOCKED: {'PREVIEW ONLY' if dry_run else 'LIVE ACTIONS'} | {mode} | max {max_actions}")
            ui_log("Click ARM / CONTINUE once to begin.")
            set_run_state("armed", dry_run, mode, max_actions)
            continue_event.wait()
            if stop_event.is_set(): ui_log("Stopped before cleanup."); return
            try:
                if page.url.rstrip("/") != url.rstrip("/"): page.goto(url, wait_until="domcontentloaded")
            except Exception as e: ui_log(f"Could not open target X page: {e}"); return
            set_run_state("running", dry_run, mode, max_actions)
            ui_log(f"Mode: {mode} | Dry run: {dry_run} | Max actions: {max_actions}"); ui_log("Cleanup started.")
            actions = 0; stale_rounds = 0; seen_items = set()
            while actions < max_actions and not stop_event.is_set():
                articles = page.locator("article"); count = articles.count()
                if count == 0:
                    ui_log("No articles found. Scrolling timeline..."); page.mouse.wheel(0, 1800); time.sleep(3); stale_rounds += 1
                    if stale_rounds >= 3: ui_log("Timeline still empty. Reloading..."); page.reload(wait_until="domcontentloaded"); time.sleep(5); stale_rounds = 0
                    continue
                acted = False; requery_after_mutation = False
                for i in range(count):
                    if actions >= max_actions or stop_event.is_set(): break
                    article = articles.nth(i)
                    try:
                        require_owned = mode in ("posts", "replies")
                        identity = article_identity(article, handle=handle if require_owned else None, require_owned=require_owned)
                        if require_owned and not identity: continue
                        if identity and identity in seen_items: continue
                        did = delete_own_post(page, article, dry_run, delay, handle, mode) if require_owned else undo_repost(page, article, dry_run, delay) if mode == "reposts" else unlike_post(page, article, dry_run, delay)
                        if did:
                            if identity: seen_items.add(identity)
                            actions += 1; acted = True; stale_rounds = 0; ui_log(f"{'Previewed' if dry_run else 'Actions'}: {actions}/{max_actions}")
                            if not dry_run:
                                requery_after_mutation = True
                                if actions % refresh_every == 0: page.reload(wait_until="domcontentloaded"); time.sleep(4)
                                break
                        elif identity:
                            seen_items.add(identity)
                    except TimeoutError:
                        ui_log("Skipped one: X did not respond in time; it can be retried on a later pass"); close_menu(page)
                    except Exception as e:
                        ui_log(f"Skipped one: {e}"); close_menu(page)
                if actions >= max_actions or stop_event.is_set(): break
                if requery_after_mutation:
                    time.sleep(0.8); continue
                try:
                    articles = page.locator("article"); count = articles.count()
                    if count:
                        articles.nth(count - 1).scroll_into_view_if_needed(timeout=3000)
                        page.evaluate("window.scrollBy(0, Math.max(700, window.innerHeight * 0.8))")
                    else: page.mouse.wheel(0, 1800)
                except Exception: page.mouse.wheel(0, 1600)
                time.sleep(2)
                if not acted: stale_rounds += 1; ui_log(f"No new matching actions. Scrolling... | unique seen {len(seen_items)}")
                if dry_run and stale_rounds >= 8: ui_log("Preview stopped: no new candidates found after repeated scrolling."); break
            ui_log(f"Done. {'Previewed' if dry_run else 'Completed'} {actions} unique action(s).")
    finally:
        set_run_state("idle")

def start_session():
    if worker_active.get(): ui_log("A cleanup run is already active. Stop it before starting another."); return
    try: s = {"handle": handle_var.get().strip(), "mode": mode_var.get(), "dry_run": dry_var.get(), "max_actions": int(max_actions_var.get()), "delay": float(delay_var.get()), "refresh_every": int(refresh_var.get())}
    except ValueError: messagebox.showerror("Invalid settings", "Max actions, delay and refresh every must be numbers."); return
    if not s["handle"]: messagebox.showerror("Missing handle", "Enter your X handle first."); return
    save_settings(s)
    if not s["dry_run"] and not messagebox.askyesno("LIVE CLEANUP", f"LIVE MODE IS ARMED.\n\nUp to {s['max_actions']} real {s['mode']} actions will run on @{s['handle'].lstrip('@')}.\n\nThe run mode will be LOCKED until it finishes or you press STOP.\n\nContinue?"): return
    worker_active.set(True); set_controls_locked(True); show_run_mode("attaching", s["dry_run"], s["mode"], s["max_actions"])
    threading.Thread(target=cleaner_worker, args=(s,), daemon=True).start()
def continue_cleanup():
    if not worker_active.get(): return
    continue_event.set()
def stop_cleanup():
    if not worker_active.get(): return
    stop_event.set(); continue_event.set(); ui_log("Stop requested."); status_var.set("STOP REQUESTED // WAITING FOR CURRENT ACTION")
def copy_handle(): root.clipboard_clear(); root.clipboard_append(handle_var.get().strip()); ui_log("Handle copied.")
def copy_log():
    text = log_box.get("1.0", tk.END).strip(); root.clipboard_clear(); root.clipboard_append(text); root.update(); status_var.set("LOG COPIED TO CLIPBOARD")
def clear_log_view(): log_box.delete("1.0", tk.END); status_var.set("LOG VIEW CLEARED")
def poll_logs():
    changed = False
    while not log_queue.empty(): log_box.insert(tk.END, log_queue.get() + "\n"); changed = True
    if changed: log_box.see(tk.END)
    while not run_state_queue.empty():
        state, dry_run, mode, max_actions = run_state_queue.get()
        if state == "idle":
            worker_active.set(False); set_controls_locked(False); show_run_mode("idle"); arm_btn.config(state="disabled"); stop_btn.config(state="disabled")
        else:
            show_run_mode(state, dry_run, mode, max_actions)
            arm_btn.config(state="normal" if state == "armed" else "disabled"); stop_btn.config(state="normal")
    root.after(150, poll_logs)
def button(parent, text, command, bg=PANEL_2, fg=TEXT, width=None): return tk.Button(parent, text=text, command=command, bg=bg, fg=fg, activebackground=ACCENT, activeforeground="white", relief="flat", bd=0, padx=14, pady=8, width=width, font=("Segoe UI", 9, "bold"), cursor="hand2")
def field(parent, var, width=12): return tk.Entry(parent, textvariable=var, width=width, bg="#090d15", fg=TEXT, insertbackground=TEXT, relief="flat", highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT, font=("Segoe UI", 10))

settings = load_settings(); root = tk.Tk(); root.title("Pulse Social — X Cleanup"); root.geometry("760x760"); root.minsize(700, 700); root.configure(bg=BG)
handle_var = tk.StringVar(value=settings["handle"]); mode_var = tk.StringVar(value=settings["mode"]); dry_var = tk.BooleanVar(value=settings["dry_run"]); max_actions_var = tk.StringVar(value=str(settings["max_actions"])); delay_var = tk.StringVar(value=str(settings["delay"])); refresh_var = tk.StringVar(value=str(settings["refresh_every"])); status_var = tk.StringVar(value="READY // SAFE MODE"); worker_active = tk.BooleanVar(value=False)
header = tk.Frame(root, bg=BG); header.pack(fill="x", padx=26, pady=(22, 12)); tk.Label(header, text="PULSE", fg=TEXT, bg=BG, font=("Segoe UI", 24, "bold")).pack(side="left"); tk.Label(header, text=" SOCIAL", fg=ACCENT, bg=BG, font=("Segoe UI", 24, "bold")).pack(side="left"); tk.Label(header, text="X CLEANUP  //  COMMERCE INTELLIGENCE READY", fg=MUTED, bg=BG, font=("Consolas", 9)).pack(side="right", pady=10)
card = tk.Frame(root, bg=PANEL, highlightthickness=1, highlightbackground=BORDER); card.pack(fill="x", padx=26, pady=8); tk.Label(card, text="CLEANUP CONTROL", fg=TEXT, bg=PANEL, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, columnspan=4, sticky="w", padx=18, pady=(14, 12))
for label, row in [("X HANDLE",1),("MODE",2),("MAX ACTIONS",3),("DELAY / SEC",4),("REFRESH EVERY",5)]: tk.Label(card, text=label, fg=MUTED, bg=PANEL, font=("Consolas", 8, "bold")).grid(row=row, column=0, sticky="w", padx=18, pady=7)
handle_entry = field(card, handle_var, 28); handle_entry.grid(row=1, column=1, sticky="w", pady=7); copy_handle_btn = button(card, "COPY", copy_handle); copy_handle_btn.grid(row=1, column=2, padx=8)
mode_menu = tk.OptionMenu(card, mode_var, "posts", "replies", "reposts", "likes"); mode_menu.config(bg=PANEL_2, fg=TEXT, activebackground=ACCENT, relief="flat", width=13, highlightthickness=0); mode_menu["menu"].config(bg=PANEL_2, fg=TEXT); mode_menu.grid(row=2, column=1, sticky="w", pady=7)
max_actions_entry = field(card, max_actions_var); max_actions_entry.grid(row=3, column=1, sticky="w", pady=7); delay_entry = field(card, delay_var); delay_entry.grid(row=4, column=1, sticky="w", pady=7); refresh_entry = field(card, refresh_var); refresh_entry.grid(row=5, column=1, sticky="w", pady=7)
dry_check = tk.Checkbutton(card, text="  DRY RUN / PREVIEW ONLY", variable=dry_var, fg=SUCCESS, bg=PANEL, activebackground=PANEL, activeforeground=SUCCESS, selectcolor=PANEL_2, font=("Segoe UI", 9, "bold")); dry_check.grid(row=6, column=0, columnspan=3, sticky="w", padx=14, pady=(8,15))
actions = tk.Frame(root, bg=BG); actions.pack(fill="x", padx=26, pady=8); attach_btn = button(actions, "01  ATTACH BRAVE", start_session, bg=ACCENT, width=18); attach_btn.pack(side="left", padx=(0,8)); arm_btn = button(actions, "02  ARM / CONTINUE", continue_cleanup, width=18); arm_btn.pack(side="left", padx=8); stop_btn = button(actions, "STOP", stop_cleanup, bg="#421526", fg="#ffb4c8", width=10); stop_btn.pack(side="right")
status = tk.Frame(root, bg=PANEL_2); status.pack(fill="x", padx=26, pady=(4,10)); status_label = tk.Label(status, textvariable=status_var, fg=SUCCESS, bg=PANEL_2, font=("Consolas", 9, "bold")); status_label.pack(side="left", padx=14, pady=8); tk.Label(status, text="BROWSER: EXISTING BRAVE CDP :9222  •  SESSION: YOURS", fg=MUTED, bg=PANEL_2, font=("Consolas", 8)).pack(side="right", padx=14)
log_card = tk.Frame(root, bg=PANEL, highlightthickness=1, highlightbackground=BORDER); log_card.pack(fill="both", expand=True, padx=26, pady=(0,22)); log_head = tk.Frame(log_card, bg=PANEL); log_head.pack(fill="x", padx=14, pady=(12,6)); tk.Label(log_head, text="ACTIVITY STREAM", fg=TEXT, bg=PANEL, font=("Segoe UI", 11, "bold")).pack(side="left"); button(log_head, "COPY LOG", copy_log).pack(side="right", padx=(6,0)); button(log_head, "CLEAR VIEW", clear_log_view).pack(side="right")
log_box = tk.Text(log_card, bg="#080c13", fg="#cbd3df", insertbackground=TEXT, relief="flat", bd=0, font=("Consolas", 9), padx=12, pady=10, wrap="word"); log_box.pack(fill="both", expand=True, padx=14, pady=(0,8)); tk.Label(log_card, text=f"MASTER LOG  //  {LOG_FILE}", fg=MUTED, bg=PANEL, font=("Consolas", 8)).pack(anchor="w", padx=14, pady=(0,10))

locked_controls = [handle_entry, copy_handle_btn, mode_menu, max_actions_entry, delay_entry, refresh_entry, dry_check, attach_btn]
def set_controls_locked(locked):
    state = "disabled" if locked else "normal"
    for widget in locked_controls:
        try: widget.config(state=state)
        except Exception: pass

def show_run_mode(state, dry_run=None, mode=None, max_actions=None):
    if state == "idle":
        status_var.set("READY // SAFE MODE"); status_label.config(fg=SUCCESS); return
    label = "PREVIEW // NO CHANGES" if dry_run else "LIVE // REAL ACTIONS"
    phase = {"attaching":"ATTACHING", "armed":"ARMED", "running":"RUNNING"}.get(state, state.upper())
    status_var.set(f"{phase} // {label} // {str(mode).upper()} // MAX {max_actions}")
    status_label.config(fg=SUCCESS if dry_run else DANGER)

arm_btn.config(state="disabled"); stop_btn.config(state="disabled")
poll_logs(); root.mainloop()
