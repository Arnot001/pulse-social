import os
import json
import time
import queue
import threading
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
PROFILE_DIR = r"C:\Users\lenno\brave_x_bot"

BRAVE_EXE = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"

DEFAULTS = {
    "handle": "",
    "mode": "posts",
    "dry_run": True,
    "max_actions": 10,
    "delay": 3,
    "refresh_every": 25,
}

log_queue = queue.Queue()
continue_event = threading.Event()
stop_event = threading.Event()


def ui_log(msg):
    log_queue.put(msg)


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return {**DEFAULTS, **json.load(f)}
        except Exception:
            pass
    return DEFAULTS.copy()


def save_settings(settings):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


def safe_text(locator):
    try:
        return locator.inner_text(timeout=3000)
    except Exception:
        return ""


def is_repost(text):
    lower = text.lower()
    return (
        "you reposted" in lower
        or " reposted " in lower
        or lower.startswith("reposted")
    )


def log_action(action, text, mode=None):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    preview = text[:180].replace("\n", " ").strip()

    if mode == "posts":
        target_file = POST_LOG_FILE
    elif mode == "replies":
        target_file = REPLY_LOG_FILE
    elif mode == "reposts":
        target_file = REPOST_LOG_FILE
    elif mode == "likes":
        target_file = LIKE_LOG_FILE
    else:
        target_file = LOG_FILE

    with open(target_file, "a", encoding="utf-8") as f:
        f.write(f"{timestamp} | {action} | {preview}\n")

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{timestamp} | {action} | {preview}\n")


def close_menu(page):
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass


def delete_own_post(page, article, dry_run, delay, handle, mode):
    text = safe_text(article)

    if not text:
        return False
    
    author = article.locator('[data-testid="User-Name"]').first

    author_text = safe_text(author)

    if f"@{handle.lower()}" not in author_text.lower():
        return False

    if is_repost(text):
        ui_log("Skipping repost")
        return False

    more = article.locator('[aria-label="More"]').first

    if more.count() == 0:
        return False

    if dry_run:
        ui_log("DRY RUN delete candidate:")
        ui_log(text[:220].replace("\n", " "))
        return True

    more.click(timeout=3000)
    time.sleep(0.7)

    delete_option = page.get_by_text("Delete", exact=True)

    if delete_option.count() == 0:
        close_menu(page)
        return False

    delete_option.first.click(timeout=3000)
    time.sleep(0.7)

    confirm = page.get_by_text("Delete", exact=True)
    confirm.first.click(timeout=3000)

    log_action(f"Deleted {mode}", text, mode)

    ui_log("Deleted post")
    time.sleep(delay)
    return True

def undo_repost(page, article, dry_run, delay):
    text = safe_text(article)

    if not is_repost(text):
        return False

    repost_button = article.locator('[data-testid="unretweet"]').first

    if repost_button.count() == 0:
        return False

    if dry_run:
        ui_log("DRY RUN repost candidate:")
        ui_log(text[:220].replace("\n", " "))
        return True

    repost_button.click(timeout=3000)
    time.sleep(0.7)

    undo = page.get_by_text("Undo repost")

    if undo.count() == 0:
        close_menu(page)
        return False

    undo.first.click(timeout=3000)

    log_action("Undid repost", text, "reposts")

    ui_log("Undid repost")
    time.sleep(delay)

    return True

def unlike_post(page, article, dry_run, delay):
    text = safe_text(article)

    unlike = article.locator('[data-testid="unlike"]').first

    if unlike.count() == 0:
        return False

    if dry_run:
        ui_log("DRY RUN like candidate:")
        ui_log(text[:220].replace("\n", " "))
        return True

    unlike.click(timeout=3000)

    log_action("Removed like", text, "likes")

    ui_log("Removed like")

    time.sleep(delay)

    return True

def cleaner_worker(settings):
    stop_event.clear()
    continue_event.clear()

    handle = settings["handle"].strip().replace("@", "")
    mode = settings["mode"]
    dry_run = settings["dry_run"]
    max_actions = int(settings["max_actions"])
    delay = float(settings["delay"])
    refresh_every = int(settings["refresh_every"])

    if mode == "likes":
        url = f"https://x.com/{handle}/likes"
    elif mode == "replies":
        url = f"https://x.com/{handle}/with_replies"
    else:
        url = f"https://x.com/{handle}"

    ui_log("Launching browser...")
    ui_log("Log into X manually if needed.")
    ui_log("Then click Continue Cleanup in the UI.")

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            executable_path=BRAVE_EXE,
            headless=False,
            slow_mo=150,
        )

        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded")

        continue_event.wait()

        if stop_event.is_set():
            ui_log("Stopped before cleanup.")
            browser.close()
            return

        ui_log(f"Mode: {mode}")
        ui_log(f"Dry run: {dry_run}")
        ui_log(f"Max actions: {max_actions}")
        ui_log("Cleanup started.")

        actions = 0

        while actions < max_actions and not stop_event.is_set():
            articles = page.locator("article")
            article_count = articles.count()

            if article_count == 0:
                ui_log("No articles found. Trying to wake timeline...")

                try:
                    page.keyboard.press("End")
                    time.sleep(2)
                    page.keyboard.press("Home")
                    time.sleep(2)
                    page.mouse.wheel(0, 2500)
                    time.sleep(3)
                except Exception:
                    pass

                if page.locator("article").count() == 0:
                    ui_log("Timeline still blank. Hard reload...")
                    page.goto(url, wait_until="networkidle")
                    time.sleep(8)
                    page.keyboard.press("End")
                    time.sleep(3)
                    page.mouse.wheel(0, 2500)
                    time.sleep(3)

                continue

            acted_this_round = False

            for i in range(article_count):
                if actions >= max_actions or stop_event.is_set():
                    break

                article = articles.nth(i)

                try:
                    did_action = False

                    if mode in ("posts", "replies"):
                        did_action = delete_own_post(page, article, dry_run, delay, handle, mode)

                    elif mode == "reposts":
                        did_action = undo_repost(
                            page,
                            article,
                            dry_run,
                            delay,
                        )

                    elif mode == "likes":
                        did_action = unlike_post(
                            page,
                            article,
                            dry_run,
                            delay,
                        )

                    if did_action:
                        actions += 1
                        acted_this_round = True
                        ui_log(f"Actions: {actions}/{max_actions}")

                        if actions > 0 and actions % refresh_every == 0:
                            ui_log("Refreshing page to prevent freeze...")
                            page.reload(wait_until="domcontentloaded")
                            time.sleep(5)
                            page.mouse.wheel(0, 1200)
                            time.sleep(2)
                            ui_log("Refresh complete")

                        if dry_run:
                            ui_log("Dry run paused. Click Continue Cleanup again.")
                            continue_event.clear()
                            continue_event.wait()

                except TimeoutError:
                    ui_log("Skipped one: timeout")
                    close_menu(page)

                except Exception as e:
                    try:
                        error_path = os.path.join(APP_DIR, "error.png")
                        page.screenshot(path=error_path)
                        ui_log(f"Screenshot saved: {error_path}")
                    except Exception:
                        pass

                    ui_log(f"Skipped one: {e}")
                    close_menu(page)

            page.mouse.wheel(0, 1000)
            time.sleep(2)

            if not acted_this_round:
                ui_log("No matching actions on this screen. Scrolling...")

        ui_log("Done.")
        browser.close()


def start_session():
    try:
        settings = {
            "handle": handle_var.get().strip(),
            "mode": mode_var.get(),
            "dry_run": dry_var.get(),
            "max_actions": int(max_actions_var.get()),
            "delay": float(delay_var.get()),
            "refresh_every": int(refresh_var.get()),
        }
    except ValueError:
        messagebox.showerror("Invalid settings", "Max actions, delay and refresh every must be numbers.")
        return

    save_settings(settings)

    if not settings["dry_run"]:
        confirm = messagebox.askyesno(
            "Live Mode Warning",
            "Dry Run is OFF.\n\nThis will actually change your X account.\n\nContinue?"
        )
        if not confirm:
            return

    threading.Thread(target=cleaner_worker, args=(settings,), daemon=True).start()


def continue_cleanup():
    continue_event.set()


def stop_cleanup():
    stop_event.set()
    continue_event.set()
    ui_log("Stop requested.")


def copy_handle():
    root.clipboard_clear()
    root.clipboard_append(handle_var.get().strip())
    ui_log("Handle copied.")


def poll_logs():
    while not log_queue.empty():
        msg = log_queue.get()
        log_box.insert(tk.END, msg + "\n")
        log_box.see(tk.END)
    root.after(200, poll_logs)


settings = load_settings()

root = tk.Tk()
root.title("Pulse Social")
root.geometry("560x640")
root.configure(bg="#07090f")

handle_var = tk.StringVar(value=settings["handle"])
mode_var = tk.StringVar(value=settings["mode"])
dry_var = tk.BooleanVar(value=settings["dry_run"])
max_actions_var = tk.StringVar(value=str(settings["max_actions"]))
delay_var = tk.StringVar(value=str(settings["delay"]))
refresh_var = tk.StringVar(value=str(settings["refresh_every"]))

tk.Label(
    root,
    text="Pulse Social",
    fg="#ff008c",
    bg="#07090f",
    font=("Segoe UI", 22, "bold"),
).pack(pady=12)

tk.Label(
    root,
    text="Cleanup tool for your own X account",
    fg="#7f8899",
    bg="#07090f",
    font=("Segoe UI", 9),
).pack()

frame = tk.Frame(root, bg="#07090f")
frame.pack(pady=15)

tk.Label(frame, text="X Handle", fg="white", bg="#07090f").grid(row=0, column=0, sticky="w")
tk.Entry(frame, textvariable=handle_var, width=32).grid(row=0, column=1, padx=8)
tk.Button(frame, text="Copy Handle", command=copy_handle).grid(row=0, column=2)

tk.Label(frame, text="Mode", fg="white", bg="#07090f").grid(row=1, column=0, sticky="w", pady=8)
tk.OptionMenu(frame, mode_var, "posts", "replies", "reposts", "likes").grid(row=1, column=1, sticky="w")

tk.Checkbutton(
    frame,
    text="Dry Run / Preview Only",
    variable=dry_var,
    fg="white",
    bg="#07090f",
    selectcolor="#121722",
).grid(row=2, column=1, sticky="w")

tk.Label(frame, text="Max Actions", fg="white", bg="#07090f").grid(row=3, column=0, sticky="w")
tk.Entry(frame, textvariable=max_actions_var, width=10).grid(row=3, column=1, sticky="w", pady=5)

tk.Label(frame, text="Delay", fg="white", bg="#07090f").grid(row=4, column=0, sticky="w")
tk.Entry(frame, textvariable=delay_var, width=10).grid(row=4, column=1, sticky="w", pady=5)

tk.Label(frame, text="Refresh Every", fg="white", bg="#07090f").grid(row=5, column=0, sticky="w")
tk.Entry(frame, textvariable=refresh_var, width=10).grid(row=5, column=1, sticky="w", pady=5)

tk.Button(
    root,
    text="Open Login Browser / Start Session",
    command=start_session,
    bg="#ff008c",
    fg="white",
    font=("Segoe UI", 11, "bold"),
).pack(pady=8)

tk.Button(
    root,
    text="Continue Cleanup",
    command=continue_cleanup,
    bg="#121722",
    fg="white",
    font=("Segoe UI", 10, "bold"),
).pack(pady=4)

tk.Button(
    root,
    text="Stop",
    command=stop_cleanup,
    bg="#33111f",
    fg="white",
    font=("Segoe UI", 10, "bold"),
).pack(pady=4)

tk.Label(
    root,
    text="Pulse Social does not store your X password.",
    fg="#7f8899",
    bg="#07090f",
    font=("Segoe UI", 8),
).pack(pady=8)

log_box = tk.Text(root, height=17, width=66, bg="#0b1018", fg="#f5f7fa")
log_box.pack(padx=12, pady=8)

tk.Label(
    root,
    text=f"Log file: {LOG_FILE}",
    fg="#7f8899",
    bg="#07090f",
    font=("Segoe UI", 8),
).pack()

poll_logs()
root.mainloop()