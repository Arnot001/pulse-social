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
from platforms.browser_control import CDP_PORT, CDP_URL, cdp_responding, restart_pulse_browser
from platforms.x.browser_session import open_x_browser
from platforms.x.profile_intelligence import ALL_TOPIC, TOPIC_LABELS, classify_text, filter_inventory, inventory_counts, ranked_inventory

APP_DIR = os.path.join(os.environ["LOCALAPPDATA"], "Pulse Social")
os.makedirs(APP_DIR, exist_ok=True)
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")
LOG_FILE = os.path.join(APP_DIR, "deleted_log.txt")
POST_LOG_FILE = os.path.join(APP_DIR, "post_log.txt")
REPLY_LOG_FILE = os.path.join(APP_DIR, "reply_log.txt")
REPOST_LOG_FILE = os.path.join(APP_DIR, "repost_log.txt")
LIKE_LOG_FILE = os.path.join(APP_DIR, "like_log.txt")
PROFILE_INTELLIGENCE_FILE = os.path.join(APP_DIR, "profile_intelligence.json")
PROFILE_SCAN_LIMIT_PER_MODE = 400

BG = "#07090f"; PANEL = "#0d111b"; PANEL_2 = "#121827"; BORDER = "#20283a"; TEXT = "#f5f7fb"; MUTED = "#8993a6"; ACCENT = "#ff008c"; SUCCESS = "#35d07f"; DANGER = "#ff4057"
DEFAULTS = {"handle":"", "mode":"posts", "dry_run":True, "run_until_empty":False, "max_actions":10, "delay":3, "refresh_every":25, "topic_filter":ALL_TOPIC, "search_query":""}
log_queue = queue.Queue(); continue_event = threading.Event(); stop_event = threading.Event(); run_state_queue = queue.Queue(); intel_queue = queue.Queue(); inventory_queue = queue.Queue()
selected_target_ids = set()
category_buttons = {}

def ui_log(msg): log_queue.put(msg)
def set_run_state(state, dry_run=None, mode=None, limit_label=None): run_state_queue.put((state, dry_run, mode, limit_label))
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE,"r",encoding="utf-8") as f: return {**DEFAULTS, **json.load(f)}
        except Exception: pass
    return DEFAULTS.copy()
def save_settings(settings):
    with open(SETTINGS_FILE,"w",encoding="utf-8") as f: json.dump(settings,f,indent=2)
def load_profile_intelligence():
    if os.path.exists(PROFILE_INTELLIGENCE_FILE):
        try:
            with open(PROFILE_INTELLIGENCE_FILE,"r",encoding="utf-8") as f:
                payload=json.load(f)
            if isinstance(payload,dict) and isinstance(payload.get("items"),list): return payload
        except Exception: pass
    return {"handle":"","scanned_at":"","items":[]}
def save_profile_intelligence(payload):
    with open(PROFILE_INTELLIGENCE_FILE,"w",encoding="utf-8") as f: json.dump(payload,f,indent=2,ensure_ascii=False)
def topic_key_from_label(label):
    for key,value in TOPIC_LABELS.items():
        if value==label: return key
    return ALL_TOPIC
def intelligence_summary(payload):
    items=payload.get("items") or []
    if not items: return "NOT SCANNED // local topic intelligence ready"
    ranked=ranked_inventory(items)[:3]
    bits=[f"{TOPIC_LABELS.get(key,key).upper()} {count}" for key,count in ranked]
    handle=str(payload.get("handle") or "").lstrip("@")
    return f"@{handle} // {len(items)} SCANNED // " + "  •  ".join(bits)
def topic_mode_counts(items,key):
    selected=items if key==ALL_TOPIC else [item for item in items if item.get("topic")==key]
    posts=sum(1 for item in selected if item.get("mode")=="posts")
    replies=sum(1 for item in selected if item.get("mode")=="replies")
    return len(selected),posts,replies
def safe_text(locator):
    try: return locator.inner_text(timeout=3000)
    except Exception: return ""
def is_repost(text):
    lower=text.lower(); return "you reposted" in lower or " reposted " in lower or lower.startswith("reposted")
def is_reply_article(article):
    text=safe_text(article)
    if "replying to" in text.lower(): return True
    try:
        if article.get_by_text("Replying to",exact=False).count()>0: return True
    except Exception: pass
    return False
def parse_status_href(href):
    if not href: return None
    try:
        path=urlparse(href).path if "://" in href else urlparse("https://x.com"+href).path
        parts=[p for p in path.split("/") if p]
        if len(parts)>=3 and parts[1].lower()=="status" and parts[2].isdigit(): return parts[0].lower(),parts[2]
    except Exception: pass
    return None
def authored_status(article,handle):
    clean=handle.strip().lstrip("@").lower()
    if not clean: return None
    try:
        links=article.locator('a[href*="/status/"]')
        for i in range(links.count()):
            parsed=parse_status_href(links.nth(i).get_attribute("href") or "")
            if parsed and parsed[0]==clean: return parsed
    except Exception: pass
    return None
def article_identity(article,handle=None,require_owned=False):
    if handle:
        owned=authored_status(article,handle)
        if owned: return f"status:{owned[1]}"
        if require_owned: return None
    try:
        links=article.locator('a[href*="/status/"]')
        for i in range(links.count()):
            parsed=parse_status_href(links.nth(i).get_attribute("href") or "")
            if parsed: return f"status:{parsed[1]}"
    except Exception: pass
    text=safe_text(article).strip(); return f"text:{text}" if text else None
def repost_status(article):
    try:
        links=article.locator('a[href*="/status/"]')
        for i in range(links.count()):
            parsed=parse_status_href(links.nth(i).get_attribute("href") or "")
            if parsed: return parsed
    except Exception: pass
    return None
def log_action(action,text,mode=None):
    timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"); preview=text[:180].replace("\n"," ").strip()
    target={"posts":POST_LOG_FILE,"replies":REPLY_LOG_FILE,"reposts":REPOST_LOG_FILE,"likes":LIKE_LOG_FILE}.get(mode,LOG_FILE)
    with open(target,"a",encoding="utf-8") as f: f.write(f"{timestamp} | {action} | {preview}\n")
    if target!=LOG_FILE:
        with open(LOG_FILE,"a",encoding="utf-8") as f: f.write(f"{timestamp} | {action} | {preview}\n")
def close_menu(page):
    try: page.keyboard.press("Escape")
    except Exception: pass
def connect_cdp(playwright,timeout_seconds=30):
    if not cdp_responding():
        ui_log("Starting the dedicated Pulse Browser...")
        ok,message=open_x_browser()
        if not ok: raise RuntimeError(f"Could not start/connect Pulse Browser: {message}")
    try:
        return playwright.chromium.connect_over_cdp(CDP_URL,timeout=12000)
    except Exception as first_error:
        if not cdp_responding():
            raise RuntimeError(f"Pulse Browser stopped responding on port {CDP_PORT}. Last error: {first_error}")
        ui_log("Pulse Browser CDP attach stalled. Restarting only the dedicated Pulse Browser profile...")
        ok,message=restart_pulse_browser(start_url="https://x.com/home")
        if not ok:
            raise RuntimeError(f"Could not safely recover Pulse Browser: {message}. Last attach error: {first_error}")
        deadline=time.time()+timeout_seconds; last_error=first_error
        while time.time()<deadline:
            try:
                return playwright.chromium.connect_over_cdp(CDP_URL,timeout=15000)
            except Exception as e:
                last_error=e
                if time.time()<deadline: time.sleep(1)
        raise RuntimeError(f"Pulse Browser restarted, but Playwright still could not attach. Last error: {last_error}")
def find_x_page(context,target_url):
    target_path=x_path(target_url)
    x_pages=[]
    for page in context.pages:
        try:
            url=page.url.lower()
            if "x.com" in url or "twitter.com" in url:
                if x_path(page.url)==target_path:
                    page.bring_to_front()
                    return page
                x_pages.append(page)
        except Exception: pass
    if x_pages:
        page=x_pages[-1]
        try: page.bring_to_front()
        except Exception: pass
        return page
    page=context.new_page(); page.goto(target_url,wait_until="domcontentloaded"); page.bring_to_front(); return page

def x_path(url):
    try: return urlparse(url).path.rstrip("/").lower()
    except Exception: return ""

def reply_tab_locator(page,handle):
    clean=handle.strip().lstrip("@")
    try:
        exact=page.locator(f'a[role="tab"][href="/{clean}/with_replies"]')
        if exact.count()>0: return exact
    except Exception: pass
    return page.locator('a[role="tab"][href$="/with_replies"]')

def on_verified_replies_timeline(page,handle):
    clean=handle.strip().lstrip("@").lower()
    return bool(clean) and x_path(page.url)==f"/{clean}/with_replies"

def ensure_target_timeline(page,target_url,handle,mode):
    target_path=x_path(target_url)
    try: page.bring_to_front()
    except Exception: pass

    if mode=="replies":
        clean=handle.strip().lstrip("@")
        profile_url=f"https://x.com/{clean}"
        profile_path=x_path(profile_url)

        if x_path(page.url) not in (profile_path,target_path):
            ui_log("Opening your X profile before Replies...")
            page.goto(profile_url,wait_until="domcontentloaded")
            time.sleep(1.0)

        if x_path(page.url)!=target_path:
            tab=reply_tab_locator(page,handle)
            if tab.count()==0:
                ui_log("Replies tab was not ready yet; reloading profile...")
                page.goto(profile_url,wait_until="domcontentloaded")
                time.sleep(1.5)
                tab=reply_tab_locator(page,handle)
            if tab.count()==0:
                raise RuntimeError("Could not find the X Replies tab on your profile.")
            ui_log("Opening X Replies tab...")
            tab.first.click(timeout=5000)

        deadline=time.time()+12
        while time.time()<deadline and x_path(page.url)!=target_path:
            time.sleep(.2)
        if x_path(page.url)!=target_path:
            raise RuntimeError(f"X did not reach the Replies timeline; current route is {x_path(page.url) or '/'}.")

        time.sleep(1.2)
        if x_path(page.url)!=target_path:
            raise RuntimeError(f"X left the Replies timeline before cleanup; current route is {x_path(page.url) or '/'}.")

        tab=reply_tab_locator(page,handle)
        if tab.count()>0:
            selected=tab.first.get_attribute("aria-selected")
            if selected not in (None,"true"):
                raise RuntimeError("X reached /with_replies but the Replies tab is not selected.")
        ui_log(f"Replies timeline verified: {target_path}")
        return

    if x_path(page.url)!=target_path:
        page.goto(target_url,wait_until="domcontentloaded")
    if x_path(page.url)!=target_path:
        raise RuntimeError(f"X did not open the expected {mode} timeline.")

def scan_authored_timeline(page,target_url,handle,mode,seen,items,max_items):
    ensure_target_timeline(page,target_url,handle,mode)
    stale_rounds=0; mode_added=0; empty_threshold=6
    while mode_added<max_items and stale_rounds<empty_threshold and not stop_event.is_set():
        articles=page.locator("article"); count=articles.count(); added=0
        for i in range(count):
            if mode_added>=max_items or stop_event.is_set(): break
            article=articles.nth(i)
            owned=authored_status(article,handle)
            if not owned or owned[1] in seen: continue
            text=safe_text(article).strip()
            if not text or is_repost(text): continue
            result=classify_text(text)
            seen.add(owned[1]); added+=1; mode_added+=1
            items.append({
                "status_id":owned[1],
                # Replies timelines also contain original posts. Classify the article, not its route.
                "mode":"replies" if is_reply_article(article) else "posts",
                "topic":result["topic"],
                "topics":result["topics"],
                "confidence":result["confidence"],
                "text":text[:500],
            })
        if added:
            stale_rounds=0
            ui_log(f"PROFILE SCAN // {mode.upper()} // +{added} // {mode_added} THIS TIMELINE // {len(items)} UNIQUE TOTAL")
        else:
            stale_rounds+=1
            ui_log(f"PROFILE SCAN // {mode.upper()} // loading older items {stale_rounds}/{empty_threshold}")
        if mode_added>=max_items or stop_event.is_set(): break
        try:
            articles=page.locator("article"); count=articles.count()
            if count: articles.nth(count-1).scroll_into_view_if_needed(timeout=3000)
            page.evaluate("window.scrollBy(0, Math.max(850, window.innerHeight * 0.9))")
        except Exception:
            page.mouse.wheel(0,1800)
        time.sleep(1.4)

def profile_scan_worker(handle):
    stop_event.clear()
    clean=handle.strip().lstrip("@")
    profile_url=f"https://x.com/{clean}"
    items=[]; seen=set()
    ui_log("PROFILE INTELLIGENCE // read-only scan starting")
    ui_log("Scanning authored Posts first, then Replies. Exact status IDs are deduplicated before classification.")
    try:
        with sync_playwright() as p:
            browser=connect_cdp(p)
            if not browser.contexts: raise RuntimeError("Pulse Browser attached but no browser context was available.")
            context=browser.contexts[0]
            page=find_x_page(context,profile_url)
            scan_authored_timeline(page,profile_url,clean,"posts",seen,items,PROFILE_SCAN_LIMIT_PER_MODE)
            if not stop_event.is_set():
                replies_url=f"https://x.com/{clean}/with_replies"
                scan_authored_timeline(page,replies_url,clean,"replies",seen,items,PROFILE_SCAN_LIMIT_PER_MODE)
        payload={
            "handle":clean,
            "scanned_at":datetime.now().isoformat(timespec="seconds"),
            "items":items,
        }
        save_profile_intelligence(payload)
        ui_log(f"PROFILE INTELLIGENCE COMPLETE // {len(items)} unique authored statuses scanned")
        for index,(key,count) in enumerate(ranked_inventory(items),start=1):
            ui_log(f"{index}. {TOPIC_LABELS.get(key,key).upper()} // {count}")
        if stop_event.is_set(): ui_log("PROFILE SCAN STOPPED // partial inventory saved")
        intel_queue.put(("done",payload))
    except Exception as e:
        ui_log(f"PROFILE INTELLIGENCE FAILED // {e}")
        intel_queue.put(("error",str(e)))

def delete_own_post(page,article,dry_run,delay,handle,mode):
    text=safe_text(article)
    if not text or is_repost(text): return False
    owned=authored_status(article,handle)
    if not owned: return False
    if mode=="replies" and not on_verified_replies_timeline(page,handle): return False
    more=article.locator('[aria-label="More"]').first
    if more.count()==0: return False
    if dry_run:
        ui_log(f"PREVIEW {'REPLY' if mode=='replies' else 'POST'} candidate [{owned[1]}]:"); ui_log(text[:220].replace("\n"," ")); return True
    more.click(timeout=4000); menu_delete=page.get_by_role("menuitem",name="Delete",exact=True)
    if menu_delete.count()==0: close_menu(page); return False
    menu_delete.first.click(timeout=4000); confirm=page.locator('[data-testid="confirmationSheetConfirm"]')
    if confirm.count()==0:
        dialog=page.get_by_role("dialog")
        if dialog.count(): confirm=dialog.get_by_role("button",name="Delete",exact=True)
    if confirm.count()==0: close_menu(page); return False
    confirm.first.click(timeout=4000); log_action(f"Deleted {mode} status {owned[1]}",text,mode); ui_log(f"Deleted {mode} [{owned[1]}]"); time.sleep(delay); return True
def undo_repost(page,article,dry_run,delay):
    text=safe_text(article); button=article.locator('[data-testid="unretweet"]').first
    if button.count()==0: return False
    status=repost_status(article); status_id=status[1] if status else "unknown"
    if dry_run: ui_log(f"PREVIEW REPOST candidate [{status_id}]:"); ui_log(text[:220].replace("\n"," ")); return True
    button.click(timeout=4000); time.sleep(.4); undo=page.get_by_role("menuitem",name="Undo repost",exact=True)
    if undo.count()==0: undo=page.get_by_text("Undo repost",exact=True)
    if undo.count()==0: close_menu(page); return False
    undo.first.click(timeout=4000); log_action(f"Undid repost status {status_id}",text,"reposts"); ui_log(f"Undid repost [{status_id}]"); time.sleep(delay); return True
def unlike_post(page,article,dry_run,delay):
    text=safe_text(article); unlike=article.locator('[data-testid="unlike"]').first
    if unlike.count()==0: return False
    status=repost_status(article); status_id=status[1] if status else "unknown"
    if dry_run: ui_log(f"PREVIEW LIKE candidate [{status_id}]:"); ui_log(text[:220].replace("\n"," ")); return True
    unlike.click(timeout=3000); log_action(f"Removed like status {status_id}",text,"likes"); ui_log(f"Removed like [{status_id}]"); time.sleep(delay); return True

def cleaner_worker(settings):
    stop_event.clear(); continue_event.clear(); handle=settings["handle"].strip().replace("@",""); mode=settings["mode"]; dry_run=settings["dry_run"]; until_empty=settings.get("run_until_empty",False)
    topic_filter=settings.get("topic_filter",ALL_TOPIC); search_query=str(settings.get("search_query") or "").strip(); target_status_ids=set(settings.get("target_status_ids") or [])
    smart_target=topic_filter!=ALL_TOPIC or bool(search_query) or "target_status_ids" in settings
    max_actions=int(settings["max_actions"]); delay=float(settings["delay"]); refresh_every=int(settings["refresh_every"]); limit_label="UNTIL EMPTY" if until_empty else f"MAX {max_actions}"
    if not handle: ui_log("Enter your X handle first."); set_run_state("idle"); return
    # Exact targeting must fail closed, including an explicitly empty selection.
    if smart_target and (mode not in ("posts","replies") or not target_status_ids):
        ui_log("Smart cleanup stopped: select scanned Posts or Replies IDs before starting."); set_run_state("idle"); return
    if smart_target:
        max_actions=len(target_status_ids); until_empty=False; limit_label=f"MAX {max_actions}"
    set_run_state("attaching",dry_run,mode,limit_label)
    url="https://x.com/i/history/likes" if mode=="likes" else f"https://x.com/{handle}/with_replies" if mode=="replies" else f"https://x.com/{handle}/reposts" if mode=="reposts" else f"https://x.com/{handle}"
    ui_log(f"Connecting to Pulse Browser on port {CDP_PORT}...")
    try:
        with sync_playwright() as p:
            try: browser=connect_cdp(p)
            except Exception as e: ui_log(str(e)); return
            if not browser.contexts: ui_log("Pulse Browser attached but no browser context was available."); return
            context=browser.contexts[0]
            try: page=find_x_page(context,url)
            except Exception as e: ui_log(f"Could not find/open X in Pulse Browser: {e}"); return
            ui_log("Attached to Pulse Browser. Sign in to X there if needed before continuing."); ui_log(f"RUN LOCKED: {'PREVIEW ONLY' if dry_run else 'LIVE ACTIONS'} | {mode} | {limit_label}"); ui_log("Click ARM / CONTINUE once to begin.")
            set_run_state("armed",dry_run,mode,limit_label); continue_event.wait()
            if stop_event.is_set(): ui_log("Stopped before cleanup."); return
            try:
                ensure_target_timeline(page,url,handle,mode)
            except Exception as e: ui_log(f"Could not open target X page: {e}"); return
            set_run_state("running",dry_run,mode,limit_label); ui_log(f"Mode: {mode} | Dry run: {dry_run} | {limit_label}"); ui_log("Cleanup started.")
            if mode=="replies": ui_log("Reply safety: verified /with_replies timeline + exact authored status link required.")
            if mode=="reposts": ui_log("Repost safety: dedicated /reposts page + active repost control required.")
            if mode=="likes": ui_log("Like safety: private History/Likes page + active unlike control required.")
            if smart_target:
                topic_label=TOPIC_LABELS.get(topic_filter,topic_filter)
                search_label=f' // SEARCH "{search_query}"' if search_query else ""
                ui_log(f"SMART TARGET // {topic_label}{search_label} // {len(target_status_ids)} scanned {mode} IDs")
            if until_empty: ui_log("Run-until-empty enabled: Pulse will stop only after repeated passes find no new matching items.")
            actions=0; stale_rounds=0; seen_items=set(); empty_threshold=8
            remaining_target_ids=set(target_status_ids); discovered_status_ids=set(); search_exhausted=False
            target_path=x_path(url)
            while (bool(remaining_target_ids) if smart_target else (until_empty or actions<max_actions)) and not stop_event.is_set():
                if mode=="replies" and x_path(page.url)!=target_path:
                    ui_log(f"Replies route changed to {x_path(page.url) or '/'}. Restoring Replies before scanning...")
                    try:
                        ensure_target_timeline(page,url,handle,mode)
                    except Exception as e:
                        ui_log(f"Replies cleanup stopped safely: {e}")
                        break
                articles=page.locator("article"); count=articles.count()
                if count==0:
                    ui_log("No articles found. Scrolling timeline..."); page.mouse.wheel(0,1800); time.sleep(3); stale_rounds+=1
                    if stale_rounds>=empty_threshold:
                        search_exhausted=True
                        ui_log(f"No new {mode} found after repeated loading attempts."); break
                    if stale_rounds==3: page.reload(wait_until="domcontentloaded"); time.sleep(5)
                    continue
                acted=False; requery_after_mutation=False; timeline_progress=False
                for i in range(count):
                    if (not until_empty and actions>=max_actions) or stop_event.is_set(): break
                    article=articles.nth(i)
                    try:
                        require_owned=mode in ("posts","replies"); identity=article_identity(article,handle=handle if require_owned else None,require_owned=require_owned)
                        if require_owned and not identity: continue
                        # Unrelated authored statuses still prove the exact-ID search is progressing.
                        # Keep discovery separate from attempted actions, including failed attempts.
                        if smart_target and identity not in discovered_status_ids:
                            discovered_status_ids.add(identity); timeline_progress=True; stale_rounds=0
                        if identity and identity in seen_items: continue
                        if require_owned and smart_target:
                            status_id=identity.split(":",1)[1] if identity and ":" in identity else ""
                            # Recheck type so older scan inventories cannot cross Posts/Replies.
                            if status_id not in remaining_target_ids or is_reply_article(article)!=(mode=="replies"):
                                if identity: seen_items.add(identity)
                                continue
                        did=delete_own_post(page,article,dry_run,delay,handle,mode) if require_owned else undo_repost(page,article,dry_run,delay) if mode=="reposts" else unlike_post(page,article,dry_run,delay)
                        if did:
                            if identity: seen_items.add(identity)
                            actions+=1; acted=True; stale_rounds=0; ui_log(f"{'Previewed' if dry_run else 'Actions'}: {actions}{'' if until_empty else '/'+str(max_actions)}")
                            if smart_target:
                                remaining_target_ids.discard(status_id)
                                ui_log(f"SMART TARGET // {len(remaining_target_ids)} OF {len(target_status_ids)} REMAINING")
                            if not dry_run:
                                if require_owned and identity and ":" in identity:
                                    inventory_queue.put((handle,identity.split(":",1)[1]))
                                requery_after_mutation=True
                                if actions%refresh_every==0 and (not smart_target or remaining_target_ids): page.reload(wait_until="domcontentloaded"); time.sleep(4)
                                break
                        elif identity: seen_items.add(identity)
                    except TimeoutError: ui_log("Skipped one: X did not respond in time; it can be retried on a later pass"); close_menu(page)
                    except Exception as e: ui_log(f"Skipped one: {e}"); close_menu(page)
                if (not until_empty and actions>=max_actions) or stop_event.is_set(): break
                if requery_after_mutation: time.sleep(.8); continue
                try:
                    articles=page.locator("article"); count=articles.count()
                    if count: articles.nth(count-1).scroll_into_view_if_needed(timeout=3000); page.evaluate("window.scrollBy(0, Math.max(700, window.innerHeight * 0.8))")
                    else: page.mouse.wheel(0,1800)
                except Exception: page.mouse.wheel(0,1600)
                time.sleep(2)
                if not acted and not (smart_target and timeline_progress):
                    stale_rounds+=1
                    if smart_target:
                        ui_log(f"No new authored statuses. Scrolling... | unique discovered {len(discovered_status_ids)} | empty check {stale_rounds}/{empty_threshold}")
                    else:
                        ui_log(f"No new matching actions. Scrolling... | unique seen {len(seen_items)} | empty check {stale_rounds}/{empty_threshold}")
                    if stale_rounds>=empty_threshold:
                        search_exhausted=True
                        if not smart_target: ui_log(f"{mode.upper()} CLEANUP COMPLETE — no new matching items found after repeated scrolling.")
                        break
            if smart_target:
                if not remaining_target_ids:
                    ui_log(f"SMART TARGET COMPLETE // {len(target_status_ids)} OF {len(target_status_ids)} exact statuses processed")
                elif search_exhausted and not stop_event.is_set():
                    ui_log(f"SMART TARGET SEARCH EXHAUSTED // {len(remaining_target_ids)} of {len(target_status_ids)} selected IDs remain unresolved")
                else:
                    ui_log(f"SMART TARGET STOPPED // {len(remaining_target_ids)} OF {len(target_status_ids)} REMAINING")
            else:
                ui_log(f"Done. {'Previewed' if dry_run else 'Completed'} {actions} unique action(s).")
    finally: set_run_state("idle")

def start_session():
    if worker_active.get(): ui_log("A cleanup run is already active. Stop it before starting another."); return
    try: s={"handle":handle_var.get().strip(),"mode":mode_var.get(),"dry_run":dry_var.get(),"run_until_empty":until_empty_var.get(),"max_actions":int(max_actions_var.get()),"delay":float(delay_var.get()),"refresh_every":int(refresh_var.get()),"topic_filter":topic_key_from_label(topic_var.get()),"search_query":search_var.get().strip()}
    except ValueError: messagebox.showerror("Invalid settings","Max actions, delay and refresh every must be numbers."); return
    if not s["handle"]: messagebox.showerror("Missing handle","Enter your X handle first."); return
    smart_target=s["topic_filter"]!=ALL_TOPIC or bool(s["search_query"]) or bool(selected_target_ids)
    if smart_target:
        if s["mode"] not in ("posts","replies"):
            messagebox.showerror("Smart target","Topic/search targeting currently supports Posts and Replies only."); return
        scanned_handle=str(profile_inventory.get("handle") or "").lstrip("@").casefold()
        if scanned_handle!=s["handle"].lstrip("@").casefold():
            messagebox.showerror("Scan profile first","Run PROFILE INTELLIGENCE for this X handle before targeting a topic or search term."); return
        matches=filter_inventory(
            profile_inventory.get("items",[]),
            mode=s["mode"],
            topic=s["topic_filter"],
            query=s["search_query"],
        )
        allowed_ids=[str(item.get("status_id")) for item in matches if item.get("status_id")]
        target_ids=[status_id for status_id in allowed_ids if status_id in selected_target_ids] if selected_target_ids else allowed_ids
        if not target_ids:
            messagebox.showinfo("No matching items","No scanned items match the current topic/search/selection for this mode."); return
        s["target_status_ids"]=target_ids
        s["max_actions"]=len(set(target_ids)); s["run_until_empty"]=False
        max_actions_var.set(str(s["max_actions"])); until_empty_var.set(False); toggle_until_empty()
    save_settings({key:value for key,value in s.items() if key!="target_status_ids"}); limit_text="UNTIL EMPTY" if s["run_until_empty"] else f"MAX {s['max_actions']}"
    target_bits=[]
    if s["topic_filter"]!=ALL_TOPIC: target_bits.append(TOPIC_LABELS.get(s["topic_filter"],s["topic_filter"]))
    if s["search_query"]: target_bits.append(f'SEARCH "{s["search_query"]}"')
    if selected_target_ids: target_bits.append(f"{len(s.get('target_status_ids',[]))} SELECTED")
    target_text="" if not target_bits else "\n\nSMART TARGET: " + " + ".join(target_bits)
    if not s["dry_run"] and not messagebox.askyesno("LIVE CLEANUP",f"LIVE MODE IS ARMED.\n\n{s['mode'].upper()} will run {limit_text}.{target_text}\n\nThe run mode will be LOCKED until it finishes or you press STOP.\n\nContinue?"): return
    worker_active.set(True); set_controls_locked(True); show_run_mode("attaching",s["dry_run"],s["mode"],limit_text); threading.Thread(target=cleaner_worker,args=(s,),daemon=True).start()

def start_profile_scan():
    if worker_active.get(): ui_log("Another Pulse Social task is already active."); return
    handle=handle_var.get().strip()
    if not handle: messagebox.showerror("Missing handle","Enter your X handle first."); return
    worker_active.set(True); stop_event.clear(); set_controls_locked(True); arm_btn.config(state="disabled"); stop_btn.config(state="normal")
    status_var.set("PROFILE INTELLIGENCE // SCANNING // READ ONLY"); status_label.config(fg=SUCCESS)
    threading.Thread(target=profile_scan_worker,args=(handle,),daemon=True).start()

def clear_selected_targets(quiet=False):
    selected_target_ids.clear()
    if "selection_summary_var" in globals():
        selection_summary_var.set("TARGET // all matches in current filter")
    if not quiet: ui_log("SMART TARGET SELECTION CLEARED")

def select_topic(key):
    topic_var.set(TOPIC_LABELS.get(key,key))
    clear_selected_targets(quiet=True)
    refresh_topic_cards(profile_inventory)
    update_match_summary()

def refresh_topic_cards(payload):
    for widget in topic_cards_frame.winfo_children(): widget.destroy()
    category_buttons.clear()
    items=payload.get("items") or []
    ranked_keys=[key for key,_count in ranked_inventory(items)]
    keys=[ALL_TOPIC]+ranked_keys
    selected=topic_key_from_label(topic_var.get())
    if selected not in keys:
        selected=ALL_TOPIC
        topic_var.set(TOPIC_LABELS[ALL_TOPIC])
    for index,key in enumerate(keys):
        total,posts,replies=topic_mode_counts(items,key)
        label=TOPIC_LABELS.get(key,key)
        text=f"{label.upper()}\n{total} TOTAL  •  P {posts}  •  R {replies}" if items else f"{label.upper()}\nNOT SCANNED"
        chosen=key==selected
        btn=tk.Button(
            topic_cards_frame,text=text,command=lambda value=key: select_topic(value),
            bg="#241323" if chosen else PANEL_2,fg=ACCENT if chosen else TEXT,
            activebackground="#2d1930",activeforeground=TEXT,relief="flat",bd=0,
            highlightthickness=1,highlightbackground=ACCENT if chosen else BORDER,
            padx=10,pady=7,font=("Segoe UI",8,"bold"),justify="left",anchor="w",cursor="hand2"
        )
        btn.grid(row=index//2,column=index%2,sticky="ew",padx=(0,5) if index%2==0 else (5,0),pady=4)
        category_buttons[key]=btn
    topic_cards_frame.columnconfigure(0,weight=1,uniform="topics")
    topic_cards_frame.columnconfigure(1,weight=1,uniform="topics")
    intel_summary_var.set(intelligence_summary(payload))

def current_inventory_matches():
    mode=mode_var.get() if mode_var.get() in ("posts","replies") else None
    return filter_inventory(
        profile_inventory.get("items",[]),
        mode=mode,
        topic=topic_key_from_label(topic_var.get()),
        query=search_var.get().strip(),
    )

def update_match_summary():
    if not profile_inventory.get("items"):
        search_result_var.set("SEARCH // scan the profile to build the local inventory")
        return
    matches=current_inventory_matches()
    mode=mode_var.get() if mode_var.get() in ("posts","replies") else "posts + replies"
    query=search_var.get().strip()
    query_text=f' // "{query}"' if query else ""
    search_result_var.set(f"MATCHES // {len(matches)} // {str(mode).upper()}{query_text}")

def preview_search_matches():
    query=search_var.get().strip()
    if not query:
        messagebox.showinfo("Search profile","Type a word or phrase first."); return
    handle=handle_var.get().strip().lstrip("@")
    scanned_handle=str(profile_inventory.get("handle") or "").lstrip("@")
    if not profile_inventory.get("items") or scanned_handle.casefold()!=handle.casefold():
        messagebox.showinfo("Scan profile first","Run PROFILE INTELLIGENCE for this X handle before searching."); return
    matches=current_inventory_matches()
    scope=mode_var.get().upper() if mode_var.get() in ("posts","replies") else "POSTS + REPLIES"
    search_result_var.set(f'SEARCH "{query}" // {len(matches)} MATCHES // {scope}')
    ui_log(f'PROFILE SEARCH // "{query}" // {len(matches)} match(es) // {scope}')
    for item in matches[:20]:
        preview=str(item.get("text") or "").replace("\n"," ")[:180]
        ui_log(f'[{str(item.get("mode") or "").upper()} {item.get("status_id")}] {preview}')
    if len(matches)>20: ui_log(f"... {len(matches)-20} more match(es) not shown in the activity stream.")

def review_matches():
    handle=handle_var.get().strip().lstrip("@")
    scanned_handle=str(profile_inventory.get("handle") or "").lstrip("@")
    if not profile_inventory.get("items") or scanned_handle.casefold()!=handle.casefold():
        messagebox.showinfo("Scan profile first","Run PROFILE INTELLIGENCE for this X handle before reviewing matches."); return
    if mode_var.get() not in ("posts","replies"):
        messagebox.showinfo("Choose Posts or Replies","Smart review currently targets Posts or Replies."); return
    matches=current_inventory_matches()
    if not matches:
        messagebox.showinfo("No matches","Nothing in the saved scan matches the current filters."); return

    win=tk.Toplevel(root); win.title("Pulse Social — Smart Cleanup Review"); win.geometry("1040x650"); win.minsize(860,520); win.configure(bg=BG); win.transient(root)
    tk.Label(win,text="SMART CLEANUP REVIEW",fg=TEXT,bg=BG,font=("Segoe UI",18,"bold")).pack(anchor="w",padx=22,pady=(18,2))
    filter_text=f"{mode_var.get().upper()}  //  {topic_var.get()}"
    if search_var.get().strip(): filter_text+=f'  //  SEARCH "{search_var.get().strip()}"'
    tk.Label(win,text=f"{filter_text}  //  {len(matches)} EXACT SCANNED STATUS IDs",fg=MUTED,bg=BG,font=("Consolas",9)).pack(anchor="w",padx=22,pady=(0,12))

    tk.Label(win,text="CLICK ROWS TO TOGGLE SELECTION  //  NO CTRL KEY REQUIRED",fg=SUCCESS,bg=BG,font=("Consolas",8,"bold")).pack(anchor="w",padx=22,pady=(0,8))
    body=tk.Frame(win,bg=BG); body.pack(fill="both",expand=True,padx=22,pady=(0,10))
    listbox=tk.Listbox(body,selectmode=tk.MULTIPLE,bg="#080c13",fg=TEXT,selectbackground="#39152b",selectforeground=TEXT,relief="flat",bd=0,font=("Consolas",9),activestyle="none",exportselection=False)
    scroll=tk.Scrollbar(body,command=listbox.yview); listbox.configure(yscrollcommand=scroll.set)
    listbox.pack(side="left",fill="both",expand=True); scroll.pack(side="right",fill="y")
    for item in matches:
        preview=" ".join(str(item.get("text") or "").split())[:145]
        listbox.insert(tk.END,f'{item.get("status_id")}  |  {preview}')

    preview_var=tk.StringVar(value="Select one or more rows. Click a selected row again to remove it.")
    review_selection_var=tk.StringVar(value=f"SELECTED // 0 OF {len(matches)}")
    preview_label=tk.Label(win,textvariable=preview_var,fg="#cbd3df",bg=PANEL,justify="left",anchor="nw",wraplength=970,font=("Segoe UI",9),padx=12,pady=10)
    preview_label.pack(fill="x",padx=22,pady=(0,10))
    def sync_review_selection(_event=None):
        chosen=listbox.curselection()
        review_selection_var.set(f"SELECTED // {len(chosen)} OF {len(matches)}")
        if not chosen:
            preview_var.set("Select one or more rows. Click a selected row again to remove it."); return
        try:
            active=listbox.index(tk.ACTIVE)
        except Exception:
            active=chosen[-1]
        index=active if active in chosen else chosen[-1]
        preview_var.set(str(matches[index].get("text") or ""))
    def select_all_review():
        listbox.selection_set(0,tk.END)
        if matches: listbox.activate(0)
        sync_review_selection()
    def clear_review_selection():
        listbox.selection_clear(0,tk.END)
        sync_review_selection()
    listbox.bind("<<ListboxSelect>>",sync_review_selection)

    footer=tk.Frame(win,bg=BG); footer.pack(fill="x",padx=22,pady=(0,18))
    def target_selected(use_all=False):
        indexes=range(len(matches)) if use_all else listbox.curselection()
        ids={str(matches[index].get("status_id")) for index in indexes if matches[index].get("status_id")}
        if not ids:
            messagebox.showinfo("Nothing selected","Select one or more statuses first.",parent=win); return
        selected_target_ids.clear(); selected_target_ids.update(ids)
        max_actions_var.set(str(len(ids))); until_empty_var.set(False); toggle_until_empty()
        selection_summary_var.set(f"TARGET // {len(ids)} exact scanned {mode_var.get()} status IDs")
        ui_log(f"SMART TARGET // {len(ids)} exact scanned {mode_var.get()} status IDs selected")
        win.destroy()
    button(footer,"SELECT ALL",select_all_review).pack(side="left")
    button(footer,"CLEAR SELECTION",clear_review_selection).pack(side="left",padx=8)
    tk.Label(footer,textvariable=review_selection_var,fg=ACCENT,bg=BG,font=("Consolas",9,"bold")).pack(side="left",padx=(8,0))
    button(footer,"TARGET ALL MATCHES",lambda: target_selected(True),bg="#143342").pack(side="right")
    button(footer,"TARGET SELECTED",lambda: target_selected(False),bg=ACCENT).pack(side="right",padx=8)

def on_filter_changed(*_args):
    clear_selected_targets(quiet=True)
    update_match_summary()

def continue_cleanup():
    if worker_active.get(): continue_event.set()
def stop_cleanup():
    if not worker_active.get(): return
    stop_event.set(); continue_event.set(); ui_log("Stop requested."); status_var.set("STOP REQUESTED // WAITING FOR CURRENT ACTION")
def copy_handle(): root.clipboard_clear(); root.clipboard_append(handle_var.get().strip()); ui_log("Handle copied.")
def copy_log():
    text=log_box.get("1.0",tk.END).strip(); root.clipboard_clear(); root.clipboard_append(text); root.update(); status_var.set("LOG COPIED TO CLIPBOARD")
def clear_log_view(): log_box.delete("1.0",tk.END); status_var.set("LOG VIEW CLEARED")
def toggle_until_empty(): max_actions_entry.config(state="disabled" if until_empty_var.get() else "normal")
def apply_inventory_deletions():
    deleted_ids=set()
    inventory_handle=str(profile_inventory.get("handle") or "").lstrip("@").casefold()
    while not inventory_queue.empty():
        handle,status_id=inventory_queue.get()
        if str(handle or "").lstrip("@").casefold()==inventory_handle:
            deleted_ids.add(str(status_id))
    if not deleted_ids: return 0
    items=profile_inventory.get("items") or []
    removed={str(item.get("status_id")) for item in items if str(item.get("status_id")) in deleted_ids}
    if not removed: return 0
    profile_inventory["items"]=[item for item in items if str(item.get("status_id")) not in removed]
    save_profile_intelligence(profile_inventory)
    selected_target_ids.difference_update(removed)
    if selected_target_ids:
        selection_summary_var.set(f"TARGET // {len(selected_target_ids)} exact scanned {mode_var.get()} status IDs")
    else:
        selection_summary_var.set("TARGET // all matches in current filter")
    refresh_topic_cards(profile_inventory); update_match_summary()
    ui_log(f"PROFILE INTELLIGENCE SYNC // removed {len(removed)} deleted status ID(s)")
    return len(removed)
def poll_logs():
    changed=False
    while not log_queue.empty(): log_box.insert(tk.END,log_queue.get()+"\n"); changed=True
    if changed: log_box.see(tk.END)
    while not intel_queue.empty():
        kind,payload=intel_queue.get()
        worker_active.set(False); set_controls_locked(False); toggle_until_empty(); arm_btn.config(state="disabled"); stop_btn.config(state="disabled")
        if kind=="done":
            profile_inventory.clear(); profile_inventory.update(payload); clear_selected_targets(quiet=True); refresh_topic_cards(profile_inventory); update_match_summary()
            status_var.set(f"PROFILE INTELLIGENCE READY // {len(profile_inventory.get('items',[]))} ITEMS"); status_label.config(fg=SUCCESS)
        else:
            status_var.set("PROFILE INTELLIGENCE FAILED"); status_label.config(fg=DANGER)
    while not run_state_queue.empty():
        state,dry_run,mode,limit_label=run_state_queue.get()
        if state=="idle":
            worker_active.set(False); set_controls_locked(False); toggle_until_empty(); apply_inventory_deletions(); show_run_mode("idle"); arm_btn.config(state="disabled"); stop_btn.config(state="disabled")
        else: show_run_mode(state,dry_run,mode,limit_label); arm_btn.config(state="normal" if state=="armed" else "disabled"); stop_btn.config(state="normal")
    root.after(150,poll_logs)
def button(parent,text,command,bg=PANEL_2,fg=TEXT,width=None): return tk.Button(parent,text=text,command=command,bg=bg,fg=fg,activebackground=ACCENT,activeforeground="white",relief="flat",bd=0,padx=14,pady=8,width=width,font=("Segoe UI",9,"bold"),cursor="hand2")
def enable_entry_editing(widget):
    menu=tk.Menu(widget,tearoff=0,bg=PANEL_2,fg=TEXT,activebackground=ACCENT,activeforeground="white")
    def editable():
        try: return str(widget.cget("state"))!="disabled"
        except Exception: return False
    def selected_text():
        try:
            if widget.selection_present():
                return widget.get()[widget.index(tk.SEL_FIRST):widget.index(tk.SEL_LAST)]
        except Exception: pass
        return ""
    def copy_selection(_event=None):
        text=selected_text()
        if text:
            try:
                widget.clipboard_clear(); widget.clipboard_append(text)
            except Exception: pass
        return "break"
    def cut_selection(_event=None):
        if not editable(): return "break"
        text=selected_text()
        if text:
            try:
                widget.clipboard_clear(); widget.clipboard_append(text)
                widget.delete(tk.SEL_FIRST,tk.SEL_LAST)
            except Exception: pass
        return "break"
    def paste_clipboard(_event=None):
        if not editable(): return "break"
        try:
            text=widget.clipboard_get()
            if widget.selection_present(): widget.delete(tk.SEL_FIRST,tk.SEL_LAST)
            widget.insert(tk.INSERT,text)
        except Exception: pass
        return "break"
    def select_all(_event=None):
        try:
            if editable():
                widget.selection_range(0,tk.END); widget.icursor(tk.END)
        except Exception: pass
        return "break"
    def show_menu(event):
        try:
            widget.focus_set()
            enabled="normal" if editable() else "disabled"
            menu.entryconfig(0,state=enabled)
            menu.entryconfig(2,state=enabled)
            menu.entryconfig(3,state=enabled)
            menu.entryconfig(1,state="normal")
            menu.tk_popup(event.x_root,event.y_root)
        finally:
            try: menu.grab_release()
            except Exception: pass
        return "break"
    menu.add_command(label="Cut",command=cut_selection)
    menu.add_command(label="Copy",command=copy_selection)
    menu.add_command(label="Paste",command=paste_clipboard)
    menu.add_command(label="Select All",command=select_all)
    widget.bind("<Control-v>",paste_clipboard)
    widget.bind("<Control-V>",paste_clipboard)
    widget.bind("<Shift-Insert>",paste_clipboard)
    widget.bind("<Control-c>",copy_selection)
    widget.bind("<Control-C>",copy_selection)
    widget.bind("<Control-x>",cut_selection)
    widget.bind("<Control-X>",cut_selection)
    widget.bind("<Control-a>",select_all)
    widget.bind("<Control-A>",select_all)
    widget.bind("<Button-3>",show_menu)
    widget._pulse_edit_menu=menu
    return widget
def field(parent,var,width=12):
    return enable_entry_editing(tk.Entry(parent,textvariable=var,width=width,bg="#090d15",fg=TEXT,insertbackground=TEXT,relief="flat",highlightthickness=1,highlightbackground=BORDER,highlightcolor=ACCENT,font=("Segoe UI",10)))

settings=load_settings(); profile_inventory=load_profile_intelligence(); root=tk.Tk(); root.title("Pulse Social — X Cleanup"); root.geometry("1180x820"); root.minsize(1040,720); root.configure(bg=BG)
handle_var=tk.StringVar(value=settings["handle"]); mode_var=tk.StringVar(value=settings["mode"]); dry_var=tk.BooleanVar(value=settings["dry_run"]); until_empty_var=tk.BooleanVar(value=settings.get("run_until_empty",False)); max_actions_var=tk.StringVar(value=str(settings["max_actions"])); delay_var=tk.StringVar(value=str(settings["delay"])); refresh_var=tk.StringVar(value=str(settings["refresh_every"])); topic_var=tk.StringVar(value=TOPIC_LABELS.get(settings.get("topic_filter",ALL_TOPIC),TOPIC_LABELS[ALL_TOPIC])); search_var=tk.StringVar(value=settings.get("search_query","")); search_result_var=tk.StringVar(value="SEARCH // scan the profile to build the local inventory"); selection_summary_var=tk.StringVar(value="TARGET // all matches in current filter"); intel_summary_var=tk.StringVar(value=intelligence_summary(profile_inventory)); status_var=tk.StringVar(value="READY // SAFE MODE"); worker_active=tk.BooleanVar(value=False)
header=tk.Frame(root,bg=BG); header.pack(fill="x",padx=26,pady=(18,8)); tk.Label(header,text="PULSE",fg=TEXT,bg=BG,font=("Segoe UI",24,"bold")).pack(side="left"); tk.Label(header,text=" SOCIAL",fg=ACCENT,bg=BG,font=("Segoe UI",24,"bold")).pack(side="left"); tk.Label(header,text="X CLEANUP  //  COMMERCE INTELLIGENCE READY",fg=MUTED,bg=BG,font=("Consolas",9)).pack(side="right",pady=10)

workspace=tk.Frame(root,bg=BG); workspace.pack(fill="x",padx=26,pady=(4,6))
workspace.grid_columnconfigure(0,weight=1,uniform="workspace")
workspace.grid_columnconfigure(1,weight=1,uniform="workspace")
workspace.grid_rowconfigure(0,weight=1)

card=tk.Frame(workspace,bg=PANEL,highlightthickness=1,highlightbackground=BORDER); card.grid(row=0,column=0,sticky="nsew",padx=(0,6))
tk.Label(card,text="CLEANUP CONTROL",fg=TEXT,bg=PANEL,font=("Segoe UI",12,"bold")).grid(row=0,column=0,columnspan=4,sticky="w",padx=18,pady=(14,10))
for label,row in [("X HANDLE",1),("MODE",2),("MAX ACTIONS",3),("DELAY / SEC",4),("REFRESH EVERY",5)]: tk.Label(card,text=label,fg=MUTED,bg=PANEL,font=("Consolas",8,"bold")).grid(row=row,column=0,sticky="w",padx=18,pady=5)
card.columnconfigure(1,weight=1)
handle_entry=field(card,handle_var,24); handle_entry.grid(row=1,column=1,sticky="ew",pady=5); copy_handle_btn=button(card,"COPY",copy_handle); copy_handle_btn.grid(row=1,column=2,padx=(8,16))
mode_menu=tk.OptionMenu(card,mode_var,"posts","replies","reposts","likes"); mode_menu.config(bg=PANEL_2,fg=TEXT,activebackground=ACCENT,relief="flat",width=13,highlightthickness=0); mode_menu["menu"].config(bg=PANEL_2,fg=TEXT); mode_menu.grid(row=2,column=1,sticky="w",pady=5)
max_actions_entry=field(card,max_actions_var); max_actions_entry.grid(row=3,column=1,sticky="w",pady=5); delay_entry=field(card,delay_var); delay_entry.grid(row=4,column=1,sticky="w",pady=5); refresh_entry=field(card,refresh_var); refresh_entry.grid(row=5,column=1,sticky="w",pady=5)
until_empty_check=tk.Checkbutton(card,text="  RUN UNTIL EMPTY",variable=until_empty_var,command=toggle_until_empty,fg=ACCENT,bg=PANEL,activebackground=PANEL,activeforeground=ACCENT,selectcolor=PANEL_2,font=("Segoe UI",9,"bold")); until_empty_check.grid(row=6,column=0,columnspan=3,sticky="w",padx=14,pady=(7,1))
dry_check=tk.Checkbutton(card,text="  DRY RUN / PREVIEW ONLY",variable=dry_var,fg=SUCCESS,bg=PANEL,activebackground=PANEL,activeforeground=SUCCESS,selectcolor=PANEL_2,font=("Segoe UI",9,"bold")); dry_check.grid(row=7,column=0,columnspan=3,sticky="w",padx=14,pady=(1,13))

intel_card=tk.Frame(workspace,bg=PANEL,highlightthickness=1,highlightbackground=BORDER); intel_card.grid(row=0,column=1,sticky="nsew",padx=(6,0))
tk.Label(intel_card,text="PROFILE INTELLIGENCE",fg=TEXT,bg=PANEL,font=("Segoe UI",11,"bold")).grid(row=0,column=0,columnspan=3,sticky="w",padx=16,pady=(14,3))
tk.Label(intel_card,text="LOCAL // HASHTAGS + KEYWORDS + TEXT TOPICS // EXACT STATUS-ID TARGETING",fg=MUTED,bg=PANEL,font=("Consolas",8)).grid(row=1,column=0,columnspan=3,sticky="w",padx=16,pady=(0,8))
scan_btn=button(intel_card,"SCAN PROFILE",start_profile_scan,bg="#143342",fg=TEXT,width=15); scan_btn.grid(row=2,column=0,sticky="w",padx=16,pady=(0,8))
tk.Label(intel_card,textvariable=intel_summary_var,fg=MUTED,bg=PANEL,font=("Consolas",8),anchor="w",justify="left",wraplength=480).grid(row=2,column=1,columnspan=2,sticky="ew",padx=(0,16),pady=(0,8))
tk.Label(intel_card,text="TOPIC CARDS",fg=MUTED,bg=PANEL,font=("Consolas",8,"bold")).grid(row=3,column=0,columnspan=3,sticky="w",padx=16,pady=(1,2))
topic_cards_frame=tk.Frame(intel_card,bg=PANEL); topic_cards_frame.grid(row=4,column=0,columnspan=3,sticky="ew",padx=16,pady=(0,6))
tk.Label(intel_card,text="SEARCH",fg=MUTED,bg=PANEL,font=("Consolas",8,"bold")).grid(row=5,column=0,sticky="w",padx=16,pady=(2,6))
search_entry=field(intel_card,search_var,28); search_entry.grid(row=5,column=1,sticky="ew",padx=(0,8),pady=(2,6))
search_btn=button(intel_card,"FIND MATCHES",preview_search_matches,width=13); search_btn.grid(row=5,column=2,sticky="e",padx=(0,16),pady=(2,6))
search_entry.bind("<Return>",lambda _event: preview_search_matches())
tk.Label(intel_card,textvariable=search_result_var,fg=SUCCESS,bg=PANEL,font=("Consolas",8),anchor="w",justify="left",wraplength=480).grid(row=6,column=0,columnspan=3,sticky="ew",padx=16,pady=(2,4))
review_row=tk.Frame(intel_card,bg=PANEL); review_row.grid(row=7,column=0,columnspan=3,sticky="ew",padx=16,pady=(0,5))
review_btn=button(review_row,"REVIEW MATCHES",review_matches,bg="#143342"); review_btn.pack(side="left")
clear_target_btn=button(review_row,"CLEAR TARGET",lambda: clear_selected_targets(False)); clear_target_btn.pack(side="left",padx=8)
tk.Label(review_row,textvariable=selection_summary_var,fg=ACCENT,bg=PANEL,font=("Consolas",8,"bold")).pack(side="left",padx=(8,0))
intel_card.columnconfigure(1,weight=1)
intel_card.columnconfigure(2,weight=0)

actions=tk.Frame(root,bg=BG); actions.pack(fill="x",padx=26,pady=(4,6)); attach_btn=button(actions,"01  ATTACH PULSE BROWSER",start_session,bg=ACCENT,width=22); attach_btn.pack(side="left",padx=(0,8)); arm_btn=button(actions,"02  ARM / CONTINUE",continue_cleanup,width=18); arm_btn.pack(side="left",padx=8); stop_btn=button(actions,"STOP",stop_cleanup,bg="#421526",fg="#ffb4c8",width=10); stop_btn.pack(side="right")
status=tk.Frame(root,bg=PANEL_2); status.pack(fill="x",padx=26,pady=(2,8)); status_label=tk.Label(status,textvariable=status_var,fg=SUCCESS,bg=PANEL_2,font=("Consolas",9,"bold")); status_label.pack(side="left",padx=14,pady=7); tk.Label(status,text="BROWSER: AUTO-DETECTED • DEDICATED PULSE PROFILE • CDP :9222",fg=MUTED,bg=PANEL_2,font=("Consolas",8)).pack(side="right",padx=14)
log_card=tk.Frame(root,bg=PANEL,highlightthickness=1,highlightbackground=BORDER); log_card.pack(fill="both",expand=True,padx=26,pady=(0,18)); log_head=tk.Frame(log_card,bg=PANEL); log_head.pack(fill="x",padx=14,pady=(10,5)); tk.Label(log_head,text="ACTIVITY STREAM",fg=TEXT,bg=PANEL,font=("Segoe UI",11,"bold")).pack(side="left"); button(log_head,"COPY LOG",copy_log).pack(side="right",padx=(6,0)); button(log_head,"CLEAR VIEW",clear_log_view).pack(side="right")
log_box=tk.Text(log_card,bg="#080c13",fg="#cbd3df",insertbackground=TEXT,relief="flat",bd=0,font=("Consolas",9),padx=12,pady=10,wrap="word"); log_box.pack(fill="both",expand=True,padx=14,pady=(0,8)); tk.Label(log_card,text=f"MASTER LOG  //  {LOG_FILE}",fg=MUTED,bg=PANEL,font=("Consolas",8)).pack(anchor="w",padx=14,pady=(0,9))

locked_controls=[handle_entry,copy_handle_btn,mode_menu,max_actions_entry,delay_entry,refresh_entry,until_empty_check,dry_check,attach_btn,scan_btn,search_entry,search_btn,review_btn,clear_target_btn]
def set_controls_locked(locked):
    state="disabled" if locked else "normal"
    for widget in locked_controls:
        try: widget.config(state=state)
        except Exception: pass
    for widget in category_buttons.values():
        try: widget.config(state=state)
        except Exception: pass
def show_run_mode(state,dry_run=None,mode=None,limit_label=None):
    if state=="idle": status_var.set("READY // SAFE MODE"); status_label.config(fg=SUCCESS); return
    label="PREVIEW // NO CHANGES" if dry_run else "LIVE // REAL ACTIONS"; phase={"attaching":"ATTACHING","armed":"ARMED","running":"RUNNING"}.get(state,state.upper()); status_var.set(f"{phase} // {label} // {str(mode).upper()} // {limit_label}"); status_label.config(fg=SUCCESS if dry_run else DANGER)

mode_var.trace_add("write",on_filter_changed); search_var.trace_add("write",on_filter_changed)
refresh_topic_cards(profile_inventory); update_match_summary(); arm_btn.config(state="disabled"); stop_btn.config(state="disabled"); toggle_until_empty(); poll_logs(); root.mainloop()
