import os
import json
import time
import queue
import threading
import subprocess
from datetime import datetime
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
CHROME_PROFILE_DIR = os.path.join(APP_DIR, "chrome_profile")
CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CHROME_EXE_X86 = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
CDP_PORT = 9223
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"

BG = "#07090f"; PANEL = "#0d111b"; PANEL_2 = "#121827"; BORDER = "#20283a"; TEXT = "#f5f7fb"; MUTED = "#8993a6"; ACCENT = "#ff008c"; SUCCESS = "#35d07f"
DEFAULTS = {"handle": "", "mode": "posts", "dry_run": True, "max_actions": 10, "delay": 3, "refresh_every": 25}
log_queue = queue.Queue(); continue_event = threading.Event(); stop_event = threading.Event()

def ui_log(msg): log_queue.put(msg)
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
def article_belongs_to_handle(article, handle):
    clean = handle.strip().lstrip("@").lower()
    if not clean: return False
    try:
        if article.locator(f'a[href="/{clean}"], a[href^="/{clean}/"]').count() > 0: return True
    except Exception: pass
    return f"@{clean}" in safe_text(article).lower()
def article_identity(article):
    try:
        links = article.locator('a[href*="/status/"]')
        for i in range(links.count()):
            href = links.nth(i).get_attribute("href") or ""
            if "/status/" in href:
                sid = href.split("/status/", 1)[1].split("/", 1)[0].split("?", 1)[0]
                if sid: return f"status:{sid}"
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

def find_chrome():
    for path in (CHROME_EXE, CHROME_EXE_X86):
        if os.path.exists(path): return path
    return None

def launch_social_chrome(url):
    chrome = find_chrome()
    if not chrome: raise RuntimeError("Google Chrome was not found in Program Files.")
    os.makedirs(CHROME_PROFILE_DIR, exist_ok=True)
    args = [chrome, f"--remote-debugging-port={CDP_PORT}", f"--user-data-dir={CHROME_PROFILE_DIR}", "--no-first-run", "--no-default-browser-check", url]
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ui_log("Chrome opened in the persistent Pulse Social profile.")
    ui_log("Log into X normally in this Chrome window if needed.")
    ui_log("Your X session will remain in this Chrome profile for future runs.")

def connect_cdp(playwright, timeout_seconds=15):
    deadline = time.time() + timeout_seconds; last_error = None
    while time.time() < deadline:
        try: return playwright.chromium.connect_over_cdp(CDP_URL, timeout=3000)
        except Exception as e: last_error = e; time.sleep(0.5)
    raise RuntimeError(f"Could not attach to Pulse Social Chrome on port {CDP_PORT}: {last_error}")

def delete_own_post(page, article, dry_run, delay, handle, mode):
    text = safe_text(article)
    if not text or is_repost(text): return False
    if not article_belongs_to_handle(article, handle): ui_log("Skipped non-owned post"); return False
    more = article.locator('[aria-label="More"]').first
    if more.count() == 0: return False
    if dry_run: ui_log(f"PREVIEW {mode[:-1].upper() if mode.endswith('s') else mode.upper()} candidate:"); ui_log(text[:220].replace("\n", " ")); return True
    more.click(timeout=3000); time.sleep(0.7); delete_option = page.get_by_text("Delete", exact=True)
    if delete_option.count() == 0: close_menu(page); return False
    delete_option.first.click(timeout=3000); time.sleep(0.7); confirm = page.get_by_text("Delete", exact=True)
    if confirm.count() == 0: close_menu(page); return False
    confirm.last.click(timeout=3000); log_action(f"Deleted {mode}", text, mode); ui_log(f"Deleted {mode}"); time.sleep(delay); return True
def undo_repost(page, article, dry_run, delay):
    text = safe_text(article)
    if not is_repost(text): return False
    button = article.locator('[data-testid="unretweet"]').first
    if button.count() == 0: return False
    if dry_run: ui_log("PREVIEW repost candidate:"); ui_log(text[:220].replace("\n", " ")); return True
    button.click(timeout=3000); time.sleep(0.7); undo = page.get_by_text("Undo repost")
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
    if not handle: ui_log("Enter your X handle first."); return
    url = f"https://x.com/{handle}/likes" if mode == "likes" else f"https://x.com/{handle}/with_replies" if mode == "replies" else f"https://x.com/{handle}"
    try: launch_social_chrome(url)
    except Exception as e: ui_log(f"Chrome launch failed: {e}"); return
    ui_log("Waiting for Chrome, then attaching over CDP...")
    with sync_playwright() as p:
        try: browser = connect_cdp(p)
        except Exception as e: ui_log(str(e)); return
        contexts = browser.contexts
        if not contexts: ui_log("Chrome attached but no browser context was available."); return
        context = contexts[0]; pages = context.pages; page = pages[-1] if pages else context.new_page()
        try:
            if "x.com" not in page.url: page.goto(url, wait_until="domcontentloaded")
        except Exception: pass
        ui_log("Attached to Pulse Social Chrome. Log in if required, then click ARM / CONTINUE once.")
        continue_event.wait()
        if stop_event.is_set(): ui_log("Stopped before cleanup."); return
        try:
            if page.url.rstrip("/") != url.rstrip("/"): page.goto(url, wait_until="domcontentloaded")
        except Exception: pass
        ui_log(f"Mode: {mode} | Dry run: {dry_run} | Max actions: {max_actions}"); ui_log("Cleanup started.")
        actions = 0; stale_rounds = 0; seen_items = set()
        while actions < max_actions and not stop_event.is_set():
            articles = page.locator("article"); count = articles.count()
            if count == 0:
                ui_log("No articles found. Scrolling timeline..."); page.mouse.wheel(0, 1800); time.sleep(3); stale_rounds += 1
                if stale_rounds >= 3: ui_log("Timeline still empty. Reloading..."); page.reload(wait_until="domcontentloaded"); time.sleep(5); stale_rounds = 0
                continue
            acted = False
            for i in range(count):
                if actions >= max_actions or stop_event.is_set(): break
                article = articles.nth(i)
                try:
                    identity = article_identity(article)
                    if identity and identity in seen_items: continue
                    if identity: seen_items.add(identity)
                    did = delete_own_post(page, article, dry_run, delay, handle, mode) if mode in ("posts", "replies") else undo_repost(page, article, dry_run, delay) if mode == "reposts" else unlike_post(page, article, dry_run, delay)
                    if did:
                        actions += 1; acted = True; stale_rounds = 0; ui_log(f"{'Previewed' if dry_run else 'Actions'}: {actions}/{max_actions}")
                        if not dry_run and actions % refresh_every == 0: page.reload(wait_until="domcontentloaded"); time.sleep(5)
                except TimeoutError: ui_log("Skipped one: timeout"); close_menu(page)
                except Exception as e: ui_log(f"Skipped one: {e}"); close_menu(page)
            if actions >= max_actions: break
            page.mouse.wheel(0, 1400); time.sleep(2)
            if not acted: stale_rounds += 1; ui_log("No new matching actions on this screen. Scrolling...")
            if dry_run and stale_rounds >= 8: ui_log("Preview stopped: no new candidates found after repeated scrolling."); break
        ui_log(f"Done. {'Previewed' if dry_run else 'Completed'} {actions} unique action(s).")

def start_session():
    try: s = {"handle": handle_var.get().strip(), "mode": mode_var.get(), "dry_run": dry_var.get(), "max_actions": int(max_actions_var.get()), "delay": float(delay_var.get()), "refresh_every": int(refresh_var.get())}
    except ValueError: messagebox.showerror("Invalid settings", "Max actions, delay and refresh every must be numbers."); return
    save_settings(s)
    if not s["dry_run"] and not messagebox.askyesno("LIVE CLEANUP", f"LIVE MODE IS ARMED.\n\nUp to {s['max_actions']} real {s['mode']} actions will run on @{s['handle'].lstrip('@')}.\n\nContinue?"): return
    threading.Thread(target=cleaner_worker, args=(s,), daemon=True).start()
def continue_cleanup(): continue_event.set()
def stop_cleanup(): stop_event.set(); continue_event.set(); ui_log("Stop requested.")
def copy_handle(): root.clipboard_clear(); root.clipboard_append(handle_var.get().strip()); ui_log("Handle copied.")
def copy_log():
    text = log_box.get("1.0", tk.END).strip(); root.clipboard_clear(); root.clipboard_append(text); root.update(); status_var.set("LOG COPIED TO CLIPBOARD")
def clear_log_view(): log_box.delete("1.0", tk.END); status_var.set("LOG VIEW CLEARED")
def poll_logs():
    changed = False
    while not log_queue.empty(): log_box.insert(tk.END, log_queue.get() + "\n"); changed = True
    if changed: log_box.see(tk.END)
    root.after(150, poll_logs)
def button(parent, text, command, bg=PANEL_2, fg=TEXT, width=None): return tk.Button(parent, text=text, command=command, bg=bg, fg=fg, activebackground=ACCENT, activeforeground="white", relief="flat", bd=0, padx=14, pady=8, width=width, font=("Segoe UI", 9, "bold"), cursor="hand2")
def field(parent, var, width=12): return tk.Entry(parent, textvariable=var, width=width, bg="#090d15", fg=TEXT, insertbackground=TEXT, relief="flat", highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT, font=("Segoe UI", 10))

settings = load_settings(); root = tk.Tk(); root.title("Pulse Social — X Cleanup"); root.geometry("760x760"); root.minsize(700, 700); root.configure(bg=BG)
handle_var = tk.StringVar(value=settings["handle"]); mode_var = tk.StringVar(value=settings["mode"]); dry_var = tk.BooleanVar(value=settings["dry_run"]); max_actions_var = tk.StringVar(value=str(settings["max_actions"])); delay_var = tk.StringVar(value=str(settings["delay"])); refresh_var = tk.StringVar(value=str(settings["refresh_every"])); status_var = tk.StringVar(value="READY // SAFE MODE")
header = tk.Frame(root, bg=BG); header.pack(fill="x", padx=26, pady=(22, 12)); tk.Label(header, text="PULSE", fg=TEXT, bg=BG, font=("Segoe UI", 24, "bold")).pack(side="left"); tk.Label(header, text=" SOCIAL", fg=ACCENT, bg=BG, font=("Segoe UI", 24, "bold")).pack(side="left"); tk.Label(header, text="X CLEANUP  //  COMMERCE INTELLIGENCE READY", fg=MUTED, bg=BG, font=("Consolas", 9)).pack(side="right", pady=10)
card = tk.Frame(root, bg=PANEL, highlightthickness=1, highlightbackground=BORDER); card.pack(fill="x", padx=26, pady=8); tk.Label(card, text="CLEANUP CONTROL", fg=TEXT, bg=PANEL, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, columnspan=4, sticky="w", padx=18, pady=(14, 12))
for label, row in [("X HANDLE",1),("MODE",2),("MAX ACTIONS",3),("DELAY / SEC",4),("REFRESH EVERY",5)]: tk.Label(card, text=label, fg=MUTED, bg=PANEL, font=("Consolas", 8, "bold")).grid(row=row, column=0, sticky="w", padx=18, pady=7)
field(card, handle_var, 28).grid(row=1, column=1, sticky="w", pady=7); button(card, "COPY", copy_handle).grid(row=1, column=2, padx=8)
mode_menu = tk.OptionMenu(card, mode_var, "posts", "replies", "reposts", "likes"); mode_menu.config(bg=PANEL_2, fg=TEXT, activebackground=ACCENT, relief="flat", width=13, highlightthickness=0); mode_menu["menu"].config(bg=PANEL_2, fg=TEXT); mode_menu.grid(row=2, column=1, sticky="w", pady=7)
field(card, max_actions_var).grid(row=3, column=1, sticky="w", pady=7); field(card, delay_var).grid(row=4, column=1, sticky="w", pady=7); field(card, refresh_var).grid(row=5, column=1, sticky="w", pady=7)
tk.Checkbutton(card, text="  DRY RUN / PREVIEW ONLY", variable=dry_var, fg=SUCCESS, bg=PANEL, activebackground=PANEL, activeforeground=SUCCESS, selectcolor=PANEL_2, font=("Segoe UI", 9, "bold")).grid(row=6, column=0, columnspan=3, sticky="w", padx=14, pady=(8,15))
actions = tk.Frame(root, bg=BG); actions.pack(fill="x", padx=26, pady=8); button(actions, "01  OPEN CHROME", start_session, bg=ACCENT, width=18).pack(side="left", padx=(0,8)); button(actions, "02  ARM / CONTINUE", continue_cleanup, width=18).pack(side="left", padx=8); button(actions, "STOP", stop_cleanup, bg="#421526", fg="#ffb4c8", width=10).pack(side="right")
status = tk.Frame(root, bg=PANEL_2); status.pack(fill="x", padx=26, pady=(4,10)); tk.Label(status, textvariable=status_var, fg=SUCCESS, bg=PANEL_2, font=("Consolas", 9, "bold")).pack(side="left", padx=14, pady=8); tk.Label(status, text="BROWSER: CHROME CDP  •  SESSION: PERSISTENT", fg=MUTED, bg=PANEL_2, font=("Consolas", 8)).pack(side="right", padx=14)
log_card = tk.Frame(root, bg=PANEL, highlightthickness=1, highlightbackground=BORDER); log_card.pack(fill="both", expand=True, padx=26, pady=(0,22)); log_head = tk.Frame(log_card, bg=PANEL); log_head.pack(fill="x", padx=14, pady=(12,6)); tk.Label(log_head, text="ACTIVITY STREAM", fg=TEXT, bg=PANEL, font=("Segoe UI", 11, "bold")).pack(side="left"); button(log_head, "COPY LOG", copy_log).pack(side="right", padx=(6,0)); button(log_head, "CLEAR VIEW", clear_log_view).pack(side="right")
log_box = tk.Text(log_card, bg="#080c13", fg="#cbd3df", insertbackground=TEXT, relief="flat", bd=0, font=("Consolas", 9), padx=12, pady=10, wrap="word"); log_box.pack(fill="both", expand=True, padx=14, pady=(0,8)); tk.Label(log_card, text=f"MASTER LOG  //  {LOG_FILE}", fg=MUTED, bg=PANEL, font=("Consolas", 8)).pack(anchor="w", padx=14, pady=(0,10))
poll_logs(); root.mainloop()
