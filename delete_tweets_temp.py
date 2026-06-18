import time
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError

HANDLE = "BROKENfilter___"
MODE = "posts"  # "posts", "reposts", or "likes"
DRY_RUN = True
MAX_ACTIONS = 100
DELAY = 3
REFRESH_EVERY_ACTIONS = 25

BRAVE_EXE = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
PROFILE_DIR = r"C:\Users\lenno\brave_x_bot"
LOG_FILE = r"C:\Users\lenno\deleted_log.txt"


def profile_url():
    if MODE == "likes":
        return f"https://x.com/{HANDLE}/likes"
    return f"https://x.com/{HANDLE}"


def safe_text(locator):
    try:
        return locator.inner_text(timeout=3000)
    except Exception:
        return ""


def close_menu(page):
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass


def log_action(action, text):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    preview = text[:180].replace("\n", " ").strip()

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{timestamp} | {action} | {preview}\n")


def is_repost(text):
    lower = text.lower()
    return (
        "you reposted" in lower
        or " reposted " in lower
        or lower.startswith("reposted")
    )


def delete_own_post(page, article):
    text = safe_text(article)

    if not text:
        return False

    if is_repost(text):
        print("Skipping repost")
        return False

    more = article.locator('[aria-label="More"]').first

    if more.count() == 0:
        return False

    if DRY_RUN:
        print("DRY RUN delete candidate:")
        print(text[:220].replace("\n", " "))
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

    log_action("Deleted post", text)

    print("Deleted post")
    time.sleep(DELAY)
    return True


def unlike_post(page, article):
    text = safe_text(article)
    unlike = article.locator('[data-testid="unlike"]').first

    if unlike.count() == 0:
        return False

    if DRY_RUN:
        print("DRY RUN unlike candidate:")
        print(text[:220].replace("\n", " "))
        return True

    unlike.click(timeout=3000)

    log_action("Unliked post", text)

    print("Unliked post")
    time.sleep(DELAY)
    return True


def undo_repost(page, article):
    text = safe_text(article)

    if not is_repost(text):
        return False

    repost_button = article.locator('[data-testid="unretweet"]').first

    if repost_button.count() == 0:
        print("Repost found, but no undo button detected")
        return False

    if DRY_RUN:
        print("DRY RUN repost candidate:")
        print(text[:220].replace("\n", " "))
        return True

    repost_button.click(timeout=3000)
    time.sleep(0.7)

    undo = page.get_by_text("Undo repost")

    if undo.count() == 0:
        close_menu(page)
        return False

    undo.first.click(timeout=3000)

    log_action("Undid repost", text)

    print("Undid repost")
    time.sleep(DELAY)
    return True


with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        user_data_dir=PROFILE_DIR,
        executable_path=BRAVE_EXE,
        headless=False,
        slow_mo=150,
    )

    page = browser.new_page()
    page.goto(profile_url(), wait_until="domcontentloaded")

    print(f"Mode: {MODE}")
    print(f"Dry run: {DRY_RUN}")
    print(f"Max actions: {MAX_ACTIONS}")
    print("Press ENTER when the page is loaded...")
    input()

    actions = 0

    while actions < MAX_ACTIONS:
        articles = page.locator("article")
        article_count = articles.count()

        if article_count == 0:
            print("No articles found. Scrolling...")
            page.mouse.wheel(0, 1000)
            time.sleep(2)
            continue

        acted_this_round = False

        for i in range(article_count):
            if actions >= MAX_ACTIONS:
                break

            article = articles.nth(i)

            try:
                did_action = False

                if MODE == "posts":
                    did_action = delete_own_post(page, article)

                elif MODE == "likes":
                    did_action = unlike_post(page, article)

                elif MODE == "reposts":
                    did_action = undo_repost(page, article)

                if did_action:
                    actions += 1
                    acted_this_round = True
                    print(f"Actions: {actions}/{MAX_ACTIONS}")
                    
                    if actions > 0 and actions % REFRESH_EVERY_ACTIONS == 0:
                        print("Refreshing page to prevent freeze...")
                        page.reload(wait_until="domcontentloaded")
                        time.sleep(5)
                        print("Refresh complete")
                        
                    if DRY_RUN:
                        input("Dry run paused. Press ENTER to continue...")

            except TimeoutError:
                print("Skipped one: timeout")
                close_menu(page)

            except Exception as e:
                try:
                    page.screenshot(path="error.png")
                    print("Screenshot saved: error.png")
                except Exception:
                    pass

                print("Skipped one:", e)
                close_menu(page)

        page.mouse.wheel(0, 1000)
        time.sleep(2)

        if not acted_this_round:
            print("No matching actions on this screen. Scrolling...")

    print("Done.")
    browser.close()