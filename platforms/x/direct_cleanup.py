"""Conservative direct-ID cleanup on an already attached dedicated Pulse page.

Type evidence comes from X's loaded TweetDetail response, not thread text. The
DOM independently binds the timestamp, author and menu to one unquoted article.
Unknown response/DOM forms return False for the caller's exact-ID timeline fallback.
"""

import json
import re
import time
from urllib.parse import parse_qs, urlparse


VERIFY_SECONDS = 5
X_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "api.x.com", "api.twitter.com"}


def status_mode(payload, handle, status_id):
    """Require consistent ID, user identity and conversation/parent metadata."""
    evidence = set()
    pending = [payload]
    while pending:
        node = pending.pop()
        if isinstance(node, list):
            pending.extend(node)
        elif isinstance(node, dict):
            pending.extend(node.values())
            if node.get("__typename") != "Tweet" or node.get("rest_id") != status_id:
                continue
            legacy = node.get("legacy") or {}
            user = ((node.get("core") or {}).get("user_results") or {}).get("result") or {}
            names = {part.get("screen_name", "").casefold()
                     for part in (user.get("core") or {}, user.get("legacy") or {})
                     if part.get("screen_name")}
            if (legacy.get("id_str") != status_id or names != {handle.casefold()}
                    or not user.get("rest_id") or legacy.get("user_id_str") != user["rest_id"]):
                return None
            parent = legacy.get("in_reply_to_status_id_str")
            conversation = legacy.get("conversation_id_str")
            if not isinstance(conversation, str) or not conversation.isdecimal():
                return None
            if isinstance(parent, str) and parent.isdecimal() and parent != status_id and conversation != status_id:
                evidence.add("replies")
            elif parent is None and conversation == status_id:
                evidence.add("posts")
            else:
                return None
    return next(iter(evidence)) if len(evidence) == 1 else None


# Return the actual menu element, not an nth locator which can retarget after DOM
# changes. Quote containers and nested articles cannot contribute identity/menu.
FOCAL_MENU = r"""({handle, statusId}) => {
    const path = value => {
        try {
            const url = new URL(value, location.origin);
            if (!['x.com', 'www.x.com', 'twitter.com', 'www.twitter.com'].includes(url.hostname)) return '';
            return url.pathname.replace(/\/$/, '').toLowerCase();
        } catch (_) { return ''; }
    };
    if (path(location.href) !== `/${handle}/status/${statusId}`) return null;
    const owned = (node, article) => {
        if (node.closest('article') !== article) return false;
        for (let parent = node; parent && parent !== article; parent = parent.parentElement) {
            if (parent.matches('[data-testid="quoteTweet"], [data-testid="tweetText"]') ||
                (parent.getAttribute('role') === 'link' && parent.tagName !== 'A')) return false;
        }
        return true;
    };
    const matches = [];
    for (const article of document.querySelectorAll('main article[data-testid="tweet"]')) {
        if (!article.getClientRects().length || article.parentElement.closest('article, [data-testid="quoteTweet"], [role="link"]')) continue;
        const names = [...article.querySelectorAll('[data-testid="User-Name"]')].filter(n => owned(n, article));
        const times = [...article.querySelectorAll('a[href]')].filter(a => a.querySelector('time') && owned(a, article));
        const menus = [...article.querySelectorAll('[data-testid="caret"]')].filter(n => owned(n, article));
        if (names.length !== 1 || times.length !== 1 || menus.length !== 1) continue;
        const authors = [...names[0].querySelectorAll('a[href]')].map(a => path(a.href)).filter(p => /^\/[a-z0-9_]+$/.test(p));
        if (!authors.length || authors.some(p => p !== `/${handle}`)) continue;
        if (path(times[0].href) !== `/${handle}/status/${statusId}`) continue;
        const menu = menus[0];
        if (!menu.matches('button, [role="button"]') || !menu.getClientRects().length) continue;
        matches.push(menu);
    }
    return matches.length === 1 ? matches[0] : null;
}"""


def try_direct_target(page, handle, status_id, mode, dry_run, delay, stop_event, ui_log, log_action):
    """Return True only after an exact preview or confirmed delete; False falls back."""
    handle = handle.strip().lstrip("@").lower()
    if (mode not in ("posts", "replies") or not re.fullmatch(r"[a-z0-9_]{1,15}", handle)
            or not isinstance(status_id, str) or not re.fullmatch(r"[0-9]+", status_id)
            or stop_event.is_set()):
        return False
    proof = []
    args = {"handle": handle, "statusId": status_id}
    opened_menu = False
    completed = False
    menu_handle = None

    def capture(response):
        try:
            url = urlparse(response.url)
            if (url.scheme != "https" or url.hostname not in X_HOSTS or "/graphql/" not in url.path
                    or not url.path.endswith("/TweetDetail") or response.status != 200):
                return
            variables = json.loads(parse_qs(url.query).get("variables", ["{}"])[0])
            if variables.get("focalTweetId") != status_id:
                return
            proof.append(status_mode(response.json(), handle, status_id))
        except Exception:
            # Missing or changed schema is never permission to act.
            proof.append(None)

    def still_verified():
        return (not stop_event.is_set() and proof and all(value == mode for value in proof)
                and menu_handle.evaluate(f"(element, args) => element.isConnected && element === ({FOCAL_MENU})(args)", args))

    registered = False
    try:
        page.on("response", capture)
        registered = True
        page.goto(f"https://x.com/{handle}/status/{status_id}", wait_until="domcontentloaded", timeout=12000)
        deadline = time.monotonic() + VERIFY_SECONDS
        while not stop_event.is_set():
            if proof:
                if any(value != mode for value in proof):
                    return False
                candidate = page.evaluate_handle(FOCAL_MENU, args)
                menu_handle = candidate.as_element()
                if menu_handle is not None:
                    break
                candidate.dispose()
            if time.monotonic() >= deadline:
                return False
            page.wait_for_timeout(100)  # Pump Playwright responses; bounded STOP check.
        if menu_handle is None or not still_verified():
            return False
        ui_log(f"DIRECT VERIFIED // exact owned {'reply' if mode == 'replies' else 'post'}")
        if dry_run:
            ui_log(f"DIRECT PREVIEW OK // {status_id}")
            return True
        # Do not reuse a pre-existing menu/dialog belonging to another article.
        if (page.get_by_role("menu").count() or page.get_by_role("dialog").count()
                or page.get_by_role("menuitem", name="Delete", exact=True).count()
                or page.locator('[data-testid="confirmationSheetConfirm"]').count()):
            return False
        if not still_verified():
            return False
        opened_menu = True
        menu_handle.click(timeout=2500)
        delete = page.get_by_role("menuitem", name="Delete", exact=True)
        delete.wait_for(state="visible", timeout=2500)
        if delete.count() != 1 or not still_verified():
            return False
        delete.click(timeout=2500)
        confirm = page.locator('[data-testid="confirmationSheetConfirm"]')
        confirm.wait_for(state="visible", timeout=2500)
        if confirm.count() != 1 or not still_verified():
            return False
        confirm.click(timeout=2500)
        completed = True
        try:
            log_action(f"Deleted {mode} status {status_id}", f"Direct exact status {status_id}", mode)
        except Exception:
            ui_log("Direct delete succeeded; the local action log could not be written.")
        ui_log(f"DIRECT DELETE OK // {status_id}")
        stop_event.wait(delay)
        return True
    except Exception:
        return completed
    finally:
        if registered:
            try:
                page.remove_listener("response", capture)
            except Exception:
                pass
        if opened_menu and not completed:
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
        if menu_handle is not None:
            try:
                menu_handle.dispose()
            except Exception:
                pass
