"""Smart cleanup safety checks using fake timelines; never connect to X."""

import ast
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_x_cleanup_attach import cleanup


def articles(*items):
    return SimpleNamespace(count=lambda: len(items), nth=lambda index: items[index])


def article(status_id, *, reply=False, owner="example", text="Manchester United"):
    result = Mock()
    result.inner_text.return_value = ("Replying to @someone\n" if reply else "") + text
    result.get_by_text.return_value.count.return_value = int(reply)
    link = Mock()
    link.get_attribute.return_value = f"/{owner}/status/{status_id}"
    result.locator.return_value = articles(link)
    return result


@pytest.fixture
def worker(cleanup, monkeypatch):
    page = Mock(url="https://x.com/example/with_replies")
    page.goto.side_effect = lambda url, **_kwargs: setattr(page, "url", url)
    # Existing timeline assertions now exercise the unchanged exact-ID fallback.
    monkeypatch.setitem(cleanup, "try_direct_target", Mock(return_value=False))
    page.locator.return_value = articles()
    monkeypatch.setitem(cleanup, "sync_playwright", Mock(return_value=nullcontext(object())))
    monkeypatch.setitem(cleanup, "connect_cdp", Mock(return_value=SimpleNamespace(contexts=[object()])))
    monkeypatch.setitem(cleanup, "find_x_page", lambda *args: page)
    monkeypatch.setitem(cleanup, "ensure_target_timeline", Mock())
    monkeypatch.setattr(cleanup["time"], "sleep", lambda _seconds: None)
    monkeypatch.setattr(cleanup["continue_event"], "wait", Mock())
    for name in ("delete_own_post", "undo_repost", "unlike_post"):
        monkeypatch.setitem(cleanup, name, Mock(return_value=True))
    return cleanup, page


@pytest.mark.parametrize("targets", [[], None])
@pytest.mark.parametrize("dry_run", [True, False])
def test_explicit_empty_ids_stop_before_browser_attach(worker, targets, dry_run):
    ns, _ = worker
    ns["cleaner_worker"](dict(ns["DEFAULTS"], handle="example", dry_run=dry_run,
                              target_status_ids=targets))
    ns["connect_cdp"].assert_not_called()
    ns["delete_own_post"].assert_not_called()
    assert ns["run_state_queue"].get_nowait()[0] == "idle"


@pytest.mark.parametrize("mode", ["reposts", "likes"])
@pytest.mark.parametrize("target", [{"topic_filter": "mufc"}, {"search_query": "United"},
                                    {"target_status_ids": ["1"]}])
def test_smart_filters_never_reach_repost_or_like_actions(worker, mode, target):
    ns, page = worker
    page.locator.return_value = articles(article("1"))
    ns["cleaner_worker"](dict(ns["DEFAULTS"], handle="example", mode=mode, dry_run=False,
                              max_actions=1, **target))
    ns["connect_cdp"].assert_not_called()
    ns["undo_repost"].assert_not_called()
    ns["unlike_post"].assert_not_called()


@pytest.mark.parametrize("mode", ["posts", "replies"])
@pytest.mark.parametrize("dry_run", [True, False])
def test_only_selected_owned_ids_of_correct_type_reach_delete(worker, mode, dry_run):
    ns, page = worker
    selected = article("1", reply=mode == "replies")
    other_type = article("2", reply=mode != "replies")
    unselected = article("3", reply=mode == "replies")
    foreign = article("4", reply=mode == "replies", owner="someone_else")
    page.locator.return_value = articles(other_type, unselected, foreign, selected)
    ns["cleaner_worker"](dict(ns["DEFAULTS"], handle="example", mode=mode, dry_run=dry_run,
                              target_status_ids=["1", "2", "4"], max_actions=10))
    ns["delete_own_post"].assert_called_once_with(page, selected, dry_run, 3.0, "example", mode)
    ns["undo_repost"].assert_not_called()
    ns["unlike_post"].assert_not_called()


@pytest.mark.parametrize("mode", ["posts", "replies"])
def test_live_owned_delete_queues_profile_inventory_sync(worker, mode):
    ns, page = worker
    selected = article("1", reply=mode == "replies")
    page.locator.return_value = articles(selected)
    ns["cleaner_worker"](dict(ns["DEFAULTS"], handle="example", mode=mode,
                              dry_run=False, max_actions=1))
    assert ns["inventory_queue"].get_nowait() == ("example", "1")
    assert ns["inventory_queue"].empty()


@pytest.mark.parametrize("mode", ["posts", "replies"])
def test_dry_run_never_queues_profile_inventory_sync(worker, mode):
    ns, page = worker
    selected = article("1", reply=mode == "replies")
    page.locator.return_value = articles(selected)
    ns["cleaner_worker"](dict(ns["DEFAULTS"], handle="example", mode=mode,
                              dry_run=True, max_actions=1))
    assert ns["inventory_queue"].empty()


def test_missing_selected_id_does_not_expand_to_other_matching_text(worker):
    ns, page = worker
    page.locator.return_value = articles(article("2"))
    ns["cleaner_worker"](dict(ns["DEFAULTS"], handle="example", target_status_ids=["1"],
                              topic_filter="mufc", search_query="United", dry_run=False))
    ns["delete_own_post"].assert_not_called()


@pytest.mark.parametrize("mode,action", [("posts", "delete_own_post"),
                                         ("reposts", "undo_repost"), ("likes", "unlike_post")])
def test_unfiltered_cleanup_still_uses_existing_action_path(worker, mode, action):
    ns, page = worker
    page.locator.return_value = articles(article("1"))
    ns["cleaner_worker"](dict(ns["DEFAULTS"], handle="example", mode=mode, max_actions=1))
    assert ns[action].call_count == 1


def test_scan_classifies_mixed_timelines_and_deduplicates_status_ids(worker):
    ns, page = worker
    seen, inventory = set(), []
    # A reply can appear in a profile thread; with_replies also contains originals.
    page.locator.return_value = articles(article("1"), article("2", reply=True))
    ns["scan_authored_timeline"](page, "https://x.com/example", "example", "posts", seen, inventory, 2)
    page.locator.return_value = articles(article("1"), article("2", reply=True), article("3"),
                                         article("4", reply=True), article("5", owner="other"),
                                         article("6", text="You reposted Manchester United"))
    ns["scan_authored_timeline"](page, page.url, "example", "replies", seen, inventory, 10)
    assert {item["status_id"]: item["mode"] for item in inventory} == {
        "1": "posts", "2": "replies", "3": "posts", "4": "replies"}
    assert len(inventory) == 4
    ns["save_profile_intelligence"]({"handle": "example", "items": inventory})
    assert ns["load_profile_intelligence"]()["items"] == inventory


@pytest.fixture(scope="module")
def tk_root():
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def ui(cleanup, monkeypatch, tk_root):
    # Exercise actual Tk controls, with isolated settings and no event loop/thread.
    source = Path(__file__).resolve().parents[1] / "pulse_social_ui.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    boundary = next(i for i, node in enumerate(tree.body)
                    if isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "settings" for t in node.targets))
    tail = [node for node in tree.body[boundary:]
            if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                    and ((isinstance(node.value.func, ast.Name) and node.value.func.id == "poll_logs")
                         or (isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "mainloop")))]
    monkeypatch.setattr(cleanup["tk"], "Tk", lambda: tk_root)
    monkeypatch.setattr(cleanup["threading"], "Thread", Mock())
    for method in ("showinfo", "showerror", "askyesno"):
        monkeypatch.setattr(cleanup["messagebox"], method, Mock(return_value=True))
    exec(compile(ast.Module(body=tail, type_ignores=[]), str(source), "exec"), cleanup)
    cleanup["handle_var"].set("example")
    cleanup["profile_inventory"].update(handle="example", items=[
        {"status_id": "1", "mode": "posts", "topic": "mufc", "text": "United"},
        {"status_id": "2", "mode": "replies", "topic": "mufc", "text": "United"},
        {"status_id": "3", "mode": "posts", "topic": "politics", "text": "United"},
        {"status_id": "4", "mode": "posts", "topic": "mufc", "text": "Different"},
    ])
    cleanup["refresh_topic_cards"](cleanup["profile_inventory"])
    try:
        yield cleanup
    finally:
        for callback in tk_root.tk.call("after", "info"):
            tk_root.after_cancel(callback)
        for child in tk_root.winfo_children():
            child.destroy()


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def test_all_x_input_fields_support_paste_and_context_editing(ui):
    entries=[w for w in descendants(ui["root"]) if isinstance(w,ui["tk"].Entry)]
    assert len(entries) >= 5
    for entry in entries:
        for sequence in ("<Control-v>","<Shift-Insert>","<Control-c>","<Control-x>","<Control-a>","<Button-3>"):
            assert entry.bind(sequence)
        menu=getattr(entry,"_pulse_edit_menu")
        assert [menu.entrycget(i,"label") for i in range(4)] == ["Cut","Copy","Paste","Select All"]

    target=entries[0]
    target.delete(0,ui["tk"].END)
    ui["root"].clipboard_clear(); ui["root"].clipboard_append("pulse paste check")
    target.icursor(0)
    target._pulse_edit_menu.invoke(2)
    assert target.get() == "pulse paste check"


@pytest.mark.parametrize("all_matches", [False, True])
@pytest.mark.parametrize("mode,expected", [("posts", ["1"]), ("replies", ["2"])])
def test_review_passes_exact_filtered_ids_to_worker(ui, all_matches, mode, expected):
    ui["mode_var"].set(mode)
    ui["select_topic"]("mufc")
    ui["search_var"].set("United")
    ui["review_matches"]()
    widgets = list(descendants(ui["root"]))
    listing = next(w for w in widgets if isinstance(w, ui["tk"].Listbox))
    assert listing.size() == 1
    listing.selection_set(0)
    label = "TARGET ALL MATCHES" if all_matches else "TARGET SELECTED"
    next(w for w in widgets if isinstance(w, ui["tk"].Button) and w.cget("text") == label).invoke()
    ui["start_session"]()
    settings = ui["threading"].Thread.call_args.kwargs["args"][0]
    assert settings["target_status_ids"] == expected
    assert settings["mode"] == mode
    assert "target_status_ids" not in ui["load_settings"]()


def test_review_click_toggle_multiselect_targets_only_chosen_ids(ui):
    ui["mode_var"].set("posts")
    ui["select_topic"]("all")
    ui["search_var"].set("")
    ui["review_matches"]()
    widgets = list(descendants(ui["root"]))
    listing = next(w for w in widgets if isinstance(w, ui["tk"].Listbox))
    assert listing.cget("selectmode") == "multiple"
    assert listing.size() == 3

    listing.selection_set(0)
    listing.selection_set(2)

    next(w for w in widgets if isinstance(w, ui["tk"].Button)
         and w.cget("text") == "TARGET SELECTED").invoke()
    assert ui["selected_target_ids"] == {"1", "4"}

    ui["start_session"]()
    settings = ui["threading"].Thread.call_args.kwargs["args"][0]
    assert settings["target_status_ids"] == ["1", "4"]


def test_review_can_remove_one_item_from_multiple_selection(ui):
    ui["mode_var"].set("posts")
    ui["select_topic"]("all")
    ui["search_var"].set("")
    ui["review_matches"]()
    widgets = list(descendants(ui["root"]))
    listing = next(w for w in widgets if isinstance(w, ui["tk"].Listbox))
    listing.selection_set(0)
    listing.selection_set(1)
    listing.selection_set(2)
    listing.selection_clear(1)

    next(w for w in widgets if isinstance(w, ui["tk"].Button)
         and w.cget("text") == "TARGET SELECTED").invoke()
    assert ui["selected_target_ids"] == {"1", "4"}


def test_review_selection_controls_update_live_count(ui):
    ui["mode_var"].set("posts")
    ui["select_topic"]("all")
    ui["search_var"].set("")
    ui["review_matches"]()
    widgets = list(descendants(ui["root"]))
    listing = next(w for w in widgets if isinstance(w, ui["tk"].Listbox))
    selection_label = next(
        w for w in widgets
        if isinstance(w, ui["tk"].Label) and w.cget("textvariable")
        and str(w.getvar(w.cget("textvariable"))).startswith("SELECTED //")
    )
    select_all = next(w for w in widgets if isinstance(w, ui["tk"].Button)
                      and w.cget("text") == "SELECT ALL")
    clear_selection = next(w for w in widgets if isinstance(w, ui["tk"].Button)
                           and w.cget("text") == "CLEAR SELECTION")

    assert selection_label.getvar(selection_label.cget("textvariable")) == "SELECTED // 0 OF 3"
    select_all.invoke()
    assert listing.curselection() == (0, 1, 2)
    assert selection_label.getvar(selection_label.cget("textvariable")) == "SELECTED // 3 OF 3"
    clear_selection.invoke()
    assert listing.curselection() == ()
    assert selection_label.getvar(selection_label.cget("textvariable")) == "SELECTED // 0 OF 3"


def test_review_empty_selection_fails_closed(ui):
    ui["mode_var"].set("posts")
    ui["select_topic"]("all")
    ui["search_var"].set("")
    ui["messagebox"].showinfo.reset_mock()
    ui["review_matches"]()
    widgets = list(descendants(ui["root"]))
    next(w for w in widgets if isinstance(w, ui["tk"].Button)
         and w.cget("text") == "TARGET SELECTED").invoke()
    ui["messagebox"].showinfo.assert_called_once()
    assert not ui["selected_target_ids"]


def test_inventory_sync_removes_only_confirmed_deleted_ids_and_persists(ui):
    ui["mode_var"].set("posts")
    ui["search_var"].set("United")
    ui["selected_target_ids"].update({"1", "4"})
    ui["selection_summary_var"].set("TARGET // 2 exact scanned posts status IDs")
    ui["inventory_queue"].put(("example", "1"))
    ui["inventory_queue"].put(("example", "4"))
    ui["inventory_queue"].put(("different_handle", "3"))

    assert ui["apply_inventory_deletions"]() == 2
    assert {item["status_id"] for item in ui["profile_inventory"]["items"]} == {"2", "3"}
    assert not ui["selected_target_ids"]
    assert ui["selection_summary_var"].get() == "TARGET // all matches in current filter"
    assert ui["search_result_var"].get() == 'MATCHES // 1 // POSTS // "United"'
    assert {item["status_id"] for item in ui["load_profile_intelligence"]()["items"]} == {"2", "3"}


def test_inventory_sync_ignores_unknown_or_already_missing_ids(ui):
    before=list(ui["profile_inventory"]["items"])
    ui["inventory_queue"].put(("different_handle", "1"))
    ui["inventory_queue"].put(("example", "999"))

    assert ui["apply_inventory_deletions"]() == 0
    assert ui["profile_inventory"]["items"] == before


def test_nonmatching_selected_ids_never_fall_back_to_all_matches(ui):
    ui["selected_target_ids"].add("2")  # Reply ID with Posts selected.
    ui["start_session"]()
    ui["threading"].Thread.assert_not_called()
    ui["messagebox"].showinfo.assert_called_once()


@pytest.mark.parametrize("mode", ["reposts", "likes"])
@pytest.mark.parametrize("filter_kind", ["topic", "search", "selection"])
def test_ui_blocks_smart_targeting_for_reposts_and_likes(ui, mode, filter_kind):
    ui["mode_var"].set(mode)
    if filter_kind == "topic":
        ui["select_topic"]("mufc")
    elif filter_kind == "search":
        ui["search_var"].set("United")
    else:
        ui["selected_target_ids"].add("1")
    ui["start_session"]()
    ui["threading"].Thread.assert_not_called()
    ui["messagebox"].showerror.assert_called_once()


@pytest.mark.parametrize("task", ["scan", "live"])
def test_topic_cards_lock_through_scan_or_live_cleanup_until_completion(ui, task):
    ui["select_topic"]("mufc")
    if task == "scan":
        ui["start_profile_scan"]()
    else:
        ui["dry_var"].set(False)
        ui["start_session"]()
    assert ui["worker_active"].get()
    assert all(w.cget("state") == "disabled" for w in ui["category_buttons"].values())
    ui["category_buttons"]["all"].invoke()
    assert ui["topic_key_from_label"](ui["topic_var"].get()) == "mufc"
    if task == "scan":
        ui["intel_queue"].put(("done", dict(ui["profile_inventory"])))
    else:
        for state in ("armed", "running"):
            ui["set_run_state"](state, False, "posts", "MAX 10")
            ui["poll_logs"]()
            assert all(w.cget("state") == "disabled" for w in ui["category_buttons"].values())
        ui["set_run_state"]("idle")
    ui["poll_logs"]()
    assert not ui["worker_active"].get()
    assert all(w.cget("state") == "normal" for w in ui["category_buttons"].values())


def queued_logs(ns):
    lines = []
    while not ns["log_queue"].empty():
        lines.append(ns["log_queue"].get_nowait())
    return lines


def scrolling_timeline(page, batches):
    """Advance only on scrolling, leaving live-delete requeries on the same batch."""
    state = {"index": 0}
    page.locator.side_effect = lambda _selector: articles(*batches[state["index"]])
    def advance(*_args):
        state["index"] = min(state["index"] + 1, len(batches) - 1)
    page.evaluate.side_effect = advance
    page.mouse.wheel.side_effect = advance
    return state


@pytest.mark.parametrize("all_matches", [False, True])
@pytest.mark.parametrize("previous_max", [1, 99])
def test_four_locked_ids_set_visible_and_effective_limit(ui, all_matches, previous_max):
    ui["profile_inventory"]["items"] = [
        {"status_id": str(i), "mode": "posts", "topic": "mufc", "text": "United"}
        for i in range(1, 6 if not all_matches else 5)
    ]
    ui["max_actions_var"].set(str(previous_max))
    ui["until_empty_var"].set(True)
    ui["review_matches"]()
    widgets = list(descendants(ui["root"]))
    listing = next(w for w in widgets if isinstance(w, ui["tk"].Listbox))
    if not all_matches:
        listing.selection_set(0, 3)
    label = "TARGET ALL MATCHES" if all_matches else "TARGET SELECTED"
    next(w for w in widgets if isinstance(w, ui["tk"].Button) and w.cget("text") == label).invoke()
    assert ui["selected_target_ids"] == {"1", "2", "3", "4"}
    assert ui["max_actions_var"].get() == "4"
    assert not ui["until_empty_var"].get()
    # Editing an old limit after review must not override the locked IDs.
    ui["max_actions_var"].set(str(previous_max))
    ui["until_empty_var"].set(True)
    ui["start_session"]()
    settings = ui["threading"].Thread.call_args.kwargs["args"][0]
    assert settings["max_actions"] == 4
    assert not settings["run_until_empty"]
    assert ui["max_actions_var"].get() == "4"
    assert "MAX 4" in ui["status_var"].get()


@pytest.mark.parametrize("mode", ["posts", "replies"])
@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize("previous_max", [1, 99])
def test_exact_search_crosses_unrelated_batches_and_resets_stale_progress(worker, mode, dry_run, previous_max):
    ns, page = worker
    targets = [article(str(i), reply=mode == "replies") for i in range(1, 5)]
    # Seven stale passes, fresh authored content, then seven more stale passes:
    # discovery must reset the counter, even when none of that content is selected.
    first_unrelated = article("100")
    second_unrelated = article("101")
    batches = [[targets[0]], *[[first_unrelated]] * 8, *[[second_unrelated]] * 8]
    batches += [[article(str(i))] for i in range(102, 115)]
    batches += [[target] for target in targets[1:]]
    state = scrolling_timeline(page, batches)
    payload = {"handle": "example", "items": [{"status_id": str(i)} for i in range(1, 5)]}
    ns["save_profile_intelligence"](payload)
    before = Path(ns["PROFILE_INTELLIGENCE_FILE"]).read_bytes()
    ns["cleaner_worker"](dict(ns["DEFAULTS"], handle="example", mode=mode, dry_run=dry_run,
                              target_status_ids=["1", "2", "3", "4", "4"],
                              max_actions=previous_max, run_until_empty=True))
    assert [call.args[1] for call in ns["delete_own_post"].call_args_list] == targets
    assert state["index"] == len(batches) - 1
    # All targets complete: do not keep scrolling the final repeated batch.
    assert page.evaluate.call_count == len(batches) - 1
    logs = queued_logs(ns)
    assert "SMART TARGET // 3 OF 4 REMAINING" in logs
    assert "SMART TARGET COMPLETE // 4 OF 4 exact statuses processed" in logs
    assert not any("SEARCH EXHAUSTED" in line for line in logs)
    assert any("RUN LOCKED:" in line and "MAX 4" in line for line in logs)
    assert Path(ns["PROFILE_INTELLIGENCE_FILE"]).read_bytes() == before
    events = []
    while not ns["inventory_queue"].empty():
        events.append(ns["inventory_queue"].get_nowait())
    assert events == ([] if dry_run else [("example", str(i)) for i in range(1, 5)])
    expected_url = "https://x.com/example/with_replies" if mode == "replies" else "https://x.com/example"
    page.goto.assert_called_once_with(expected_url, wait_until="domcontentloaded", timeout=12000)


@pytest.mark.parametrize("empty_timeline", [False, True])
def test_true_exhaustion_reports_unresolved_ids_without_claiming_complete(worker, empty_timeline):
    ns, page = worker
    scrolling_timeline(page, [[article("1")], [] if empty_timeline else [article("100")]])
    ns["cleaner_worker"](dict(ns["DEFAULTS"], handle="example", target_status_ids=["1", "2", "3", "4"]))
    assert ns["delete_own_post"].call_count == 1
    logs = queued_logs(ns)
    assert "SMART TARGET SEARCH EXHAUSTED // 3 of 4 selected IDs remain unresolved" in logs
    assert not any("COMPLETE" in line for line in logs)
    assert page.locator.call_count < 50


def test_repeated_target_errors_do_not_count_as_new_timeline_progress(worker):
    ns, page = worker
    page.locator.return_value = articles(article("1"))
    ns["delete_own_post"].side_effect = RuntimeError("temporarily unavailable")
    ns["cleaner_worker"](dict(ns["DEFAULTS"], handle="example", target_status_ids=["1"]))
    assert ns["delete_own_post"].call_count <= 9
    assert ns["inventory_queue"].empty()
    assert "SMART TARGET SEARCH EXHAUSTED // 1 of 1 selected IDs remain unresolved" in queued_logs(ns)


@pytest.mark.parametrize("mode", ["posts", "replies"])
def test_stop_aborts_exact_search_before_later_selected_items(worker, mode):
    ns, page = worker
    scrolling_timeline(page, [[article("100")], [article("1", reply=mode == "replies")]])
    page.evaluate.side_effect = lambda *_args: ns["stop_event"].set()
    ns["cleaner_worker"](dict(ns["DEFAULTS"], handle="example", mode=mode, target_status_ids=["1"]))
    ns["delete_own_post"].assert_not_called()
    assert ns["inventory_queue"].empty()
    logs = queued_logs(ns)
    assert "SMART TARGET STOPPED // 1 OF 1 REMAINING" in logs
    assert not any("EXHAUSTED" in line or "COMPLETE" in line for line in logs)


@pytest.mark.parametrize("dry_run", [True, False])
def test_replies_deletion_rejects_unverified_status_route(cleanup, dry_run):
    candidate = article("1", reply=True)
    page = Mock(url="https://x.com/example/status/1")
    assert not cleanup["delete_own_post"](page, candidate, dry_run, 0, "example", "replies")
    page.get_by_role.assert_not_called()
    page.locator.assert_not_called()
    candidate.locator.assert_called_once_with('a[href*="/status/"]')


def test_exact_reply_search_stops_when_replies_route_cannot_be_restored(worker):
    ns, page = worker
    page.locator.return_value = articles(article("100"))
    page.evaluate.side_effect = lambda *_args: setattr(page, "url", "https://x.com/example/status/2")
    ns["ensure_target_timeline"].side_effect = [None, RuntimeError("Replies route unavailable")]
    ns["cleaner_worker"](dict(ns["DEFAULTS"], handle="example", mode="replies", target_status_ids=["1"]))
    ns["delete_own_post"].assert_not_called()
    assert ns["ensure_target_timeline"].call_count == 2
    assert all(call.args[1] == "https://x.com/example/with_replies"
               for call in ns["ensure_target_timeline"].call_args_list)
    logs = queued_logs(ns)
    assert any("Replies cleanup stopped safely" in line for line in logs)
    assert not any("COMPLETE" in line or "EXHAUSTED" in line for line in logs)


# Direct-mode tests use a fresh headless browser with every request fulfilled
# locally. No account, personal profile, CDP session or real X endpoint is used.
@pytest.fixture(scope="module")
def direct_browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        # Use an installed Edge binary if this machine lacks Playwright Chromium.
        # launch() always creates a temporary isolated profile.
        executable = playwright.chromium.executable_path
        options = {"executable_path": executable} if Path(executable).exists() else {"channel": "msedge"}
        browser = playwright.chromium.launch(headless=True, **options)
        yield browser
        browser.close()


def tweet_record(status_id="1", owner="example", reply=False):
    legacy = {"id_str": status_id, "user_id_str": "42",
              "conversation_id_str": "90" if reply else status_id}
    if reply:
        legacy["in_reply_to_status_id_str"] = "90"
    return {"__typename": "Tweet", "rest_id": status_id, "legacy": legacy,
            "core": {"user_results": {"result": {"rest_id": "42", "core": {"screen_name": owner}}}}}


def status_html(status_id="1", owner="example", extra="", menu=True):
    caret = f'<button data-testid="caret" data-status="{status_id}">More</button>' if menu else ''
    return (f'<article data-testid="tweet"><div data-testid="User-Name"><a href="/{owner}">@{owner}</a></div>'
            f'<a href="/{owner}/status/{status_id}"><time>Today</time></a>'
            f'<div data-testid="tweetText">Test content</div>{extra}{caret}</article>')


@pytest.fixture
def direct_page(direct_browser, monkeypatch):
    import json
    from platforms.x import direct_cleanup
    monkeypatch.setattr(direct_cleanup, "VERIFY_SECONDS", 1.5)
    context = direct_browser.new_context()
    page = context.new_page()
    def serve(html, payload, *, response_id="1", after_menu=""):
        script = '''
        window.clicked = []; window.deleted = [];
        document.addEventListener('click', event => {
            const caret = event.target.closest('[data-testid="caret"]');
            if (!caret) return;
            const article = caret.closest('article');
            window.clicked.push(caret.dataset.status);
            const menu = document.createElement('div'); menu.setAttribute('role', 'menu');
            const item = document.createElement('button'); item.setAttribute('role', 'menuitem'); item.textContent = 'Delete';
            menu.append(item); document.body.append(menu);
            item.onclick = () => {
                menu.remove();
                const dialog = document.createElement('div'); dialog.setAttribute('role', 'dialog');
                const confirm = document.createElement('button'); confirm.dataset.testid = 'confirmationSheetConfirm'; confirm.textContent = 'Delete';
                dialog.append(confirm); document.body.append(dialog);
                confirm.onclick = () => { window.deleted.push(caret.dataset.status); article.remove(); dialog.remove(); };
            };
            AFTER_MENU
        });
        fetch('/i/api/graphql/test/TweetDetail?variables=' + encodeURIComponent(JSON.stringify({focalTweetId: RESPONSE_ID})));
        '''.replace('AFTER_MENU', after_menu).replace('RESPONSE_ID', json.dumps(response_id))
        body = '<main>' + html + '</main><script>' + script + '</script>'
        def route(request):
            if '/graphql/' in request.request.url:
                request.fulfill(status=200, content_type='application/json', body=json.dumps(payload))
            else:
                request.fulfill(status=200, content_type='text/html', body=body)
        page.route('**/*', route)
    yield page, serve
    context.close()


@pytest.mark.parametrize("mode", ["posts", "replies"])
@pytest.mark.parametrize("dry_run", [True, False])
def test_direct_navigation_verifies_and_acts_only_on_focal_article(direct_page, mode, dry_run):
    import threading
    from platforms.x.direct_cleanup import try_direct_target
    page, serve = direct_page
    # Parent, recommended post, foreign reply and an owned quoted post are decoys.
    quote = '<div role="link" data-testid="quoteTweet">' + status_html("5") + '</div>'
    serve(status_html("90") + status_html(extra=quote) + status_html("8", "stranger") + status_html("9"),
          {"items": [tweet_record("90"), tweet_record(reply=mode == "replies"), tweet_record("8", "stranger", True)]})
    log, action_log = Mock(), Mock()
    assert try_direct_target(page, "@Example", "1", mode, dry_run, 0, threading.Event(), log, action_log)
    assert page.url == "https://x.com/example/status/1"
    assert page.evaluate('window.clicked') == ([] if dry_run else ["1"])
    assert page.evaluate('window.deleted') == ([] if dry_run else ["1"])
    assert action_log.call_count == int(not dry_run)
    assert page.locator('a[href="/example/status/90"]').count() == 1
    assert page.locator('a[href="/stranger/status/8"]').count() == 1


@pytest.mark.parametrize("problem", ["wrong_id", "wrong_author", "post_is_reply", "reply_is_post",
                                     "missing_type", "wrong_user_id", "other_response", "no_record"])
def test_direct_rejects_inconsistent_or_missing_status_metadata(direct_page, problem):
    import threading
    from platforms.x.direct_cleanup import try_direct_target
    page, serve = direct_page
    record = tweet_record()
    mode, response_id = "posts", "1"
    if problem == "wrong_id": record = tweet_record("2")
    if problem == "wrong_author": record = tweet_record(owner="stranger")
    if problem == "post_is_reply": record = tweet_record(reply=True)
    if problem == "reply_is_post": mode = "replies"
    if problem == "missing_type": record["legacy"].pop("conversation_id_str")
    if problem == "wrong_user_id": record["legacy"]["user_id_str"] = "99"
    if problem == "other_response": response_id = "2"
    if problem == "no_record": record = {}
    serve(status_html(), record, response_id=response_id)
    log, diagnostics = Mock(), Mock()
    assert not try_direct_target(page, "example", "1", mode, False, 0, threading.Event(), diagnostics, log)
    reasons = {
        "wrong_id": "focal status not found in TweetDetail", "wrong_author": "author mismatch",
        "post_is_reply": "expected post, got reply", "reply_is_post": "expected reply, got post",
        "missing_type": "post/reply type unavailable", "wrong_user_id": "author mismatch",
        "other_response": "status ID mismatch (TweetDetail request)",
        "no_record": "focal status not found in TweetDetail",
    }
    diagnostics.assert_called_once_with("DIRECT VERIFY FAILED // " + reasons[problem])
    assert page.evaluate('window.clicked') == []
    assert page.evaluate('window.deleted') == []
    log.assert_not_called()


@pytest.mark.parametrize("problem", ["wrong_id", "wrong_author", "quoted_target", "nested_target",
                                     "duplicate_target", "parent_only", "no_menu", "quote_menu_only"])
def test_direct_rejects_thread_and_quote_identity_confusion(direct_page, problem):
    import threading
    from platforms.x.direct_cleanup import try_direct_target
    page, serve = direct_page
    if problem in ("wrong_id", "parent_only"): html = status_html("90")
    elif problem == "wrong_author": html = status_html(owner="stranger")
    elif problem == "quoted_target":
        html = status_html("90", extra='<div role="link">' + status_html() + '</div>')
    elif problem == "nested_target": html = status_html("90", extra=status_html())
    elif problem == "duplicate_target": html = status_html() + status_html()
    elif problem == "no_menu": html = status_html(menu=False)
    else: html = status_html(menu=False, extra='<div role="link">' + status_html("90") + '</div>')
    serve(html, tweet_record())
    diagnostics = Mock()
    assert not try_direct_target(page, "example", "1", "posts", False, 0, threading.Event(), diagnostics, Mock())
    reason = {"wrong_author": "author mismatch (focal article)", "duplicate_target": "focal article ambiguous",
              "no_menu": "focal menu not safely bound", "quote_menu_only": "focal menu not safely bound"}
    diagnostics.assert_called_once_with("DIRECT VERIFY FAILED // " + reason.get(problem, "focal status not found"))
    assert page.evaluate('window.clicked') == []
    assert page.evaluate('window.deleted') == []


@pytest.mark.parametrize("change", ["identity", "replace_button", "stop"])
def test_direct_rechecks_pinned_focal_identity_and_stop_before_delete(direct_page, change):
    import threading
    from platforms.x.direct_cleanup import try_direct_target
    page, serve = direct_page
    stop = threading.Event()
    scripts = {"identity": "article.querySelector('a:has(time)').href = '/example/status/2';",
               "replace_button": "caret.replaceWith(caret.cloneNode(true));",
               "stop": "console.log('stop-requested');"}
    page.on('console', lambda msg: stop.set() if msg.text == 'stop-requested' else None)
    serve(status_html(), tweet_record(), after_menu=scripts[change])
    assert not try_direct_target(page, "example", "1", "posts", False, 0, stop, Mock(), Mock())
    assert page.evaluate('window.deleted') == []


@pytest.mark.parametrize("mode", ["posts", "replies"])
def test_one_direct_fallback_does_not_block_other_targets_or_repeat_completed_ids(worker, mode):
    ns, page = worker
    ns["try_direct_target"].side_effect = [False, True, True]
    missing = article("1", reply=mode == "replies")
    already_done = article("2", reply=mode == "replies")
    page.locator.return_value = articles(already_done, missing)
    ns["cleaner_worker"](dict(ns["DEFAULTS"], handle="example", mode=mode, dry_run=False,
                              target_status_ids=["1", "2", "3"], max_actions=1))
    assert [call.args[2] for call in ns["try_direct_target"].call_args_list] == ["1", "2", "3"]
    ns["delete_own_post"].assert_called_once_with(page, missing, False, 3.0, "example", mode)
    expected_url = "https://x.com/example/with_replies" if mode == "replies" else "https://x.com/example"
    ns["ensure_target_timeline"].assert_called_once_with(page, expected_url, "example", mode)
    assert [ns["inventory_queue"].get_nowait() for _ in range(3)] == [("example", "2"), ("example", "3"), ("example", "1")]
    assert ns["inventory_queue"].empty()


@pytest.mark.parametrize("dry_run", [True, False])
def test_all_direct_targets_finish_without_timeline_navigation_and_sync_only_live(worker, dry_run):
    ns, page = worker
    ns["try_direct_target"].return_value = True
    ns["cleaner_worker"](dict(ns["DEFAULTS"], handle="example", dry_run=dry_run, target_status_ids=["1", "2"]))
    assert ns["try_direct_target"].call_count == 2
    ns["ensure_target_timeline"].assert_not_called()
    ns["delete_own_post"].assert_not_called()
    page.locator.assert_not_called()
    assert ns["inventory_queue"].qsize() == (0 if dry_run else 2)
    assert "SMART DIRECT COMPLETE // 2/2 processed" in queued_logs(ns)


def test_stop_prevents_next_direct_target_and_fallback(worker):
    ns, page = worker
    def stop_after_first(*_args):
        ns["stop_event"].set()
        return True
    ns["try_direct_target"].side_effect = stop_after_first
    ns["cleaner_worker"](dict(ns["DEFAULTS"], handle="example", dry_run=False, target_status_ids=["1", "2"]))
    assert ns["try_direct_target"].call_count == 1
    ns["ensure_target_timeline"].assert_not_called()
    assert ns["inventory_queue"].get_nowait() == ("example", "1")
    assert "SMART TARGET STOPPED // 1 OF 2 REMAINING" in queued_logs(ns)


@pytest.mark.parametrize("mode", ["posts", "replies", "reposts", "likes"])
def test_normal_cleanup_never_enters_direct_mode(worker, mode):
    ns, page = worker
    page.locator.return_value = articles(article("1", reply=mode == "replies"))
    ns["cleaner_worker"](dict(ns["DEFAULTS"], handle="example", mode=mode, max_actions=1))
    ns["try_direct_target"].assert_not_called()


@pytest.mark.parametrize("mode", ["reposts", "likes"])
def test_reposts_and_likes_reject_direct_targets_before_navigation(worker, mode):
    ns, page = worker
    ns["cleaner_worker"](dict(ns["DEFAULTS"], handle="example", mode=mode, target_status_ids=["1"]))
    ns["try_direct_target"].assert_not_called()
    ns["connect_cdp"].assert_not_called()
    page.goto.assert_not_called()


@pytest.mark.parametrize("stale_control", [
    '<div role="menu"><button role="menuitem">Delete</button></div>',
    '<button role="menuitem">Delete</button>',
    '<button data-testid="confirmationSheetConfirm">Delete</button>',
])
def test_direct_never_reuses_another_articles_open_delete_controls(direct_page, stale_control):
    import threading
    from platforms.x.direct_cleanup import try_direct_target
    page, serve = direct_page
    serve(status_html() + stale_control, tweet_record())
    assert not try_direct_target(page, "example", "1", "posts", False, 0, threading.Event(), Mock(), Mock())
    assert page.evaluate('window.clicked') == []
    assert page.evaluate('window.deleted') == []


@pytest.mark.parametrize("mode", ["posts", "replies"])
@pytest.mark.parametrize("dry_run", [True, False])
def test_real_direct_worker_preserves_inventory_in_preview_and_queues_only_live(direct_page, worker, monkeypatch, mode, dry_run):
    from platforms.x.direct_cleanup import try_direct_target
    ns, _ = worker
    page, serve = direct_page
    serve(status_html(), tweet_record(reply=mode == "replies"))
    monkeypatch.setitem(ns, "try_direct_target", try_direct_target)
    monkeypatch.setitem(ns, "find_x_page", lambda *_args: page)
    payload = {"handle": "example", "items": [{"status_id": "1", "mode": mode}]}
    ns["save_profile_intelligence"](payload)
    before = Path(ns["PROFILE_INTELLIGENCE_FILE"]).read_bytes()
    ns["cleaner_worker"](dict(ns["DEFAULTS"], handle="example", mode=mode, dry_run=dry_run,
                              target_status_ids=["1"], delay=0))
    ns["ensure_target_timeline"].assert_not_called()
    assert page.evaluate('window.deleted') == ([] if dry_run else ["1"])
    assert ns["inventory_queue"].qsize() == int(not dry_run)
    if not dry_run:
        assert ns["inventory_queue"].get_nowait() == ("example", "1")
    assert Path(ns["PROFILE_INTELLIGENCE_FILE"]).read_bytes() == before
    assert "SMART DIRECT COMPLETE // 1/1 processed" in queued_logs(ns)


def test_direct_load_failure_fails_closed_and_releases_response_listener():
    import threading
    from platforms.x.direct_cleanup import try_direct_target
    page = Mock()
    page.goto.side_effect = RuntimeError("navigation failed")
    assert not try_direct_target(page, "example", "1", "replies", False, 0, threading.Event(), Mock(), Mock())
    page.evaluate_handle.assert_not_called()
    page.remove_listener.assert_called_once_with("response", page.on.call_args.args[1])


def test_stop_before_direct_navigation_performs_no_browser_action():
    import threading
    from platforms.x.direct_cleanup import try_direct_target
    stop = threading.Event()
    stop.set()
    page = Mock()
    assert not try_direct_target(page, "example", "1", "posts", False, 0, stop, Mock(), Mock())
    assert page.mock_calls == []


def test_conflicting_reply_metadata_cannot_authorize_a_direct_action():
    from platforms.x.direct_cleanup import status_mode
    assert status_mode({"items": [tweet_record(), tweet_record(reply=True)]}, "example", "1") is None


@pytest.mark.parametrize("problem,reason", [
    ("missing_id", "status ID unavailable (legacy.id_str)"),
    ("id_mismatch", "status ID mismatch"),
    ("missing_author", "author unavailable"),
    ("conflicting_type", "post/reply type conflicting"),
    ("invalid_parent", "post/reply type unavailable"),
    ("invalid_schema", "TweetDetail data unavailable"),
])
@pytest.mark.parametrize("dry_run", [True, False])
def test_direct_metadata_diagnostics_preserve_fail_closed(direct_page, problem, reason, dry_run):
    import threading
    from platforms.x.direct_cleanup import try_direct_target
    page, serve = direct_page
    record = tweet_record()
    if problem == "missing_id": record["legacy"].pop("id_str")
    if problem == "id_mismatch": record["legacy"]["id_str"] = "2"
    if problem == "missing_author": record.pop("core")
    if problem == "conflicting_type": record = [record, tweet_record(reply=True)]
    if problem == "invalid_parent": record["legacy"]["in_reply_to_status_id_str"] = "unknown"
    if problem == "invalid_schema": record["legacy"] = "changed schema"
    serve(status_html(), record)
    diagnostics, action = Mock(), Mock()
    assert not try_direct_target(page, "example", "1", "posts", dry_run, 0, threading.Event(), diagnostics, action)
    diagnostics.assert_called_once_with("DIRECT VERIFY FAILED // " + reason)
    assert page.evaluate('window.clicked') == []
    assert page.evaluate('window.deleted') == []
    action.assert_not_called()


@pytest.mark.parametrize("problem,reason", [
    ("missing", "TweetDetail response unavailable"),
    ("http", "TweetDetail HTTP 429"),
    ("json", "TweetDetail data unavailable"),
    ("load", "direct page load failed"),
])
def test_direct_response_and_load_failure_reasons(monkeypatch, problem, reason):
    import threading
    from platforms.x import direct_cleanup
    monkeypatch.setattr(direct_cleanup, "VERIFY_SECONDS", 0)
    page = Mock()
    def navigate(*_args, **_kwargs):
        if problem == "load": raise RuntimeError("private exception details")
        if problem == "missing": return
        response = Mock(url='https://x.com/i/api/graphql/test/TweetDetail?variables=%7B%22focalTweetId%22%3A%221%22%7D',
                        status=429 if problem == "http" else 200)
        response.json.side_effect = ValueError("private response body")
        page.on.call_args.args[1](response)
    page.goto.side_effect = navigate
    diagnostics = Mock()
    assert not direct_cleanup.try_direct_target(page, "example", "1", "posts", False, 0, threading.Event(), diagnostics, Mock())
    diagnostics.assert_called_once_with("DIRECT VERIFY FAILED // " + reason)
    page.evaluate_handle.assert_not_called()
    page.get_by_role.assert_not_called()


@pytest.mark.parametrize("mode", ["posts", "replies"])
def test_fallback_resets_and_verifies_route_before_crawler(worker, mode):
    ns, page = worker
    expected = "https://x.com/example" + ("/with_replies" if mode == "replies" else "")
    order = []
    def direct(*_args):
        page.url = "https://x.com/example/status/1"
        return False
    ns["try_direct_target"].side_effect = direct
    def goto(url, **_kwargs):
        assert url == expected
        order.append("navigate")
        page.url = url
    page.goto.side_effect = goto
    def verify(*_args):
        assert page.url == expected
        order.append("verify")
    ns["ensure_target_timeline"].side_effect = verify
    selected = article("1", reply=mode == "replies")
    def crawl(_selector):
        assert order[:2] == ["navigate", "verify"]
        assert page.url == expected
        order.append("crawl")
        return articles(selected)
    page.locator.side_effect = crawl
    ns["cleaner_worker"](dict(ns["DEFAULTS"], handle="example", mode=mode, target_status_ids=["1"]))
    assert order == ["navigate", "verify", "crawl"]
    ns["delete_own_post"].assert_called_once_with(page, selected, True, 3.0, "example", mode)
    assert f"SMART TARGET FALLBACK // {mode.upper()} route verified" in queued_logs(ns)


@pytest.mark.parametrize("mode", ["posts", "replies"])
@pytest.mark.parametrize("problem", ["load", "status_route", "other_handle", "other_mode", "foreign_host", "tab_unverified", "late_redirect"])
def test_failed_fallback_route_reset_never_starts_crawler(worker, mode, problem):
    ns, page = worker
    expected = "https://x.com/example" + ("/with_replies" if mode == "replies" else "")
    def goto(_url, **_kwargs):
        if problem == "load": raise RuntimeError("navigation failed")
        page.url = {"status_route": "https://x.com/example/status/1", "other_handle": expected.replace("example", "other"),
                    "other_mode": "https://x.com/example" if mode == "replies" else "https://x.com/example/with_replies",
                    "foreign_host": expected.replace("x.com", "example.org")}.get(problem, expected)
    page.goto.side_effect = goto
    if problem == "tab_unverified": ns["ensure_target_timeline"].side_effect = RuntimeError("Replies tab not selected")
    if problem == "late_redirect": ns["ensure_target_timeline"].side_effect = lambda *_args: setattr(page, "url", "https://x.com/home")
    ns["cleaner_worker"](dict(ns["DEFAULTS"], handle="example", mode=mode, dry_run=False, target_status_ids=["1"]))
    page.locator.assert_not_called()
    page.mouse.wheel.assert_not_called()
    ns["delete_own_post"].assert_not_called()
    assert ns["inventory_queue"].empty()
    assert "SMART TARGET STOPPED // 1 OF 1 REMAINING" in queued_logs(ns)


@pytest.mark.parametrize("stage", ["navigation", "verification"])
def test_stop_during_fallback_reset_prevents_crawler(worker, stage):
    ns, page = worker
    if stage == "navigation": page.goto.side_effect = lambda *_args, **_kwargs: ns["stop_event"].set()
    else: ns["ensure_target_timeline"].side_effect = lambda *_args: ns["stop_event"].set()
    ns["cleaner_worker"](dict(ns["DEFAULTS"], handle="example", target_status_ids=["1"]))
    page.locator.assert_not_called()
    ns["delete_own_post"].assert_not_called()
    assert "SMART TARGET STOPPED // 1 OF 1 REMAINING" in queued_logs(ns)
