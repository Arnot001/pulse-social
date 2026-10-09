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
