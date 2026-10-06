"""Bounded Social orchestration and transient Shop list state; no browser ownership."""
from __future__ import annotations

from urllib.parse import urlsplit

from .category_collector import CategoryCollection, request_category
from ..batch import ingest_products
from ..store import CommerceStore

MAX_PASSES = 5
RECOVERABLE = frozenset({"NAVIGATION", "TIMEOUT", "NO_GROWTH"})
MODES = ("PER CATEGORY", "MIXED LIST")


def category_key(url):
    # The request layer validates URLs; slugs/trailing slashes do not change category identity.
    try:
        return urlsplit(url.strip()).path.rstrip('/').rsplit('/', 1)[-1]
    except ValueError:
        # Let the worker report INVALID_URL instead of throwing in a Tk callback.
        return url.strip()


def collect_category_session(url, store=None, on_progress=None):
    """Union passes, then ingest once per unique ID for this user action."""
    products = {}
    metadata = {}
    clicks = duration = 0

    def emit(message):
        if on_progress:
            on_progress({"message": message, "products": [dict(p) for p in products.values()]})

    for pass_number in range(1, MAX_PASSES + 1):
        emit(f"COLLECTING // PASS {pass_number} // {len(products)} COLLECTED")
        try:
            metadata = request_category(url)
        except ValueError:
            metadata = {"complete": False, "stopReason": "INVALID_URL"}
        except Exception:
            # Keep earlier products and do not automatically repeat an unknown failure.
            metadata = {"complete": False, "stopReason": "COLLECTION_ERROR"}
        for item in metadata.get("products", []):
            pid = item["product_id"]
            previous = products.get(pid, {})
            products[pid] = {**previous, **{k: v for k, v in item.items() if v is not None and v != ""}}
        clicks += metadata.get("clicks", 0)
        duration += metadata.get("durationMs", 0)
        reason = metadata.get("stopReason", "UNVERIFIED")
        complete = metadata.get("complete") is True and reason == "END_OF_LIST"
        if complete:
            emit(f"{len(products)} COLLECTED // PASS {pass_number} // VERIFIED COMPLETE // RECORDING")
            break
        continuing = reason in RECOVERABLE and pass_number < MAX_PASSES
        emit(f"PARTIAL // {len(products)} COLLECTED // PASS {pass_number} // {reason}" + (" // CONTINUING" if continuing else " // STOPPED"))
        if not continuing:
            break

    last_reason = reason
    if not complete and reason in RECOVERABLE and pass_number == MAX_PASSES:
        reason = "MAX_PASSES_REACHED"
    # The current request layer already returns a safe projection of product fields.
    # Later passes can fill missing values without creating repeated history observations.
    results = ingest_products(list(products.values()), store or CommerceStore()) if products else []
    skipped = sum(item.get("status") == "skipped" for item in results)
    incomplete = sum(not p.get("title") or p.get("price") is None for p in products.values())
    result = CategoryCollection(results, {
        **metadata, "products": list(products.values()), "complete": complete,
        "stopReason": reason, "clicks": clicks, "durationMs": duration,
        "dataComplete": incomplete == 0 and metadata.get("dataComplete", False),
        "incompleteProductCount": incomplete, "ingestionComplete": skipped == 0,
        "skippedProductCount": skipped,
    })
    result.passes = pass_number
    result.last_stop_reason = last_reason
    return result


def session_summary(result):
    recorded = sum(item.get("status") == "recorded" for item in result)
    state = "COMPLETE" if result.complete and result.stop_reason == "END_OF_LIST" else "STOPPED // " + result.stop_reason.replace('_', ' ')
    return (f"{state} // {result.product_count} COLLECTED // {recorded} RECORDED // "
            f"{result.skipped_product_count} SKIPPED // {result.passes} PASSES" +
            (f" // LAST: {result.last_stop_reason}" if result.stop_reason == "MAX_PASSES_REACHED" else ""))


class ShopListState:
    """UI-only state. Deliberately has no store, file or watchlist access."""
    def __init__(self):
        self.items = {}
        self.category = None
        self.generation = 0
        self.busy = False

    def begin(self, url, mode):
        if self.busy:
            raise RuntimeError("Collection already running")
        category = category_key(url)
        if mode == MODES[0] and category != self.category:
            self.clear_items()
        self.category = category
        self.busy = True
        return self.generation

    def merge(self, rows, generation):
        if generation != self.generation:
            return
        for row in rows:
            pid = str(row.get("product_id") or "")
            if not pid.isdecimal():
                continue
            previous = self.items.get(pid, {"status": "pending"})
            self.items[pid] = {**previous, **{k: v for k, v in row.items() if v is not None and v != ""}}

    def clear_items(self):
        self.items.clear()
        # Queued progress/final callbacks from an in-flight request cannot undo Clear Items.
        self.generation += 1


def clear_log_widget(widget):
    """Only clear the Text widget; callers invalidate queued log messages separately."""
    widget.delete("1.0", "end")
    widget.edit_reset()
