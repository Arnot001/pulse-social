import threading

import platforms.tiktok.cleanup as cleanup
from platforms.tiktok.cleanup import TikTokItem, select_targets


def _item(item_id: str, item_type: int, post_time: int, can_delete: bool = True):
    return TikTokItem(
        item_id=item_id,
        desc=item_id,
        item_type=item_type,
        post_time=post_time,
        play_count=0,
        like_count=0,
        comment_count=0,
        share_count=0,
        favorite_count=0,
        visibility=1,
        status=102,
        in_review=False,
        can_delete=can_delete,
    )


def test_select_targets_filters_videos_and_keeps_newest_first():
    items = [
        _item("old-video", 1, 10),
        _item("photo", 2, 30),
        _item("new-video", 1, 20),
    ]
    assert [item.item_id for item in select_targets(items, "videos")] == [
        "new-video",
        "old-video",
    ]


def test_select_targets_honours_count_limit():
    items = [_item(str(index), 1, index) for index in range(1, 6)]
    assert [item.item_id for item in select_targets(items, "videos", 2)] == ["5", "4"]


def test_select_targets_everything_excludes_undeletable_and_failed_ids():
    items = [
        _item("video", 1, 3),
        _item("photo", 2, 2),
        _item("blocked", 1, 4, can_delete=False),
    ]
    selected = select_targets(items, "everything", excluded_ids={"video"})
    assert [item.item_id for item in selected] == ["photo"]


def test_verified_pdh_result_short_circuits_local_browser_fallback(monkeypatch):
    item = _item("741234", 1, 10)
    logs = []
    recorded = []

    monkeypatch.setattr(
        cleanup,
        "_request_pdh_delete",
        lambda page, target: {
            "successful": True,
            "verified": True,
            "mutated": True,
            "status": "DELETE_VERIFIED",
        },
    )
    monkeypatch.setattr(cleanup, "_log_deleted", lambda target: recorded.append(target.item_id))
    monkeypatch.setattr(
        cleanup,
        "_find_item_row",
        lambda page, target: (_ for _ in ()).throw(AssertionError("local fallback should not run")),
    )

    assert cleanup.delete_studio_item(object(), item, logs.append) is True
    assert recorded == ["741234"]
    assert any("PDH DELETED" in line for line in logs)


def test_unverified_pdh_mutation_blocks_second_delete_attempt(monkeypatch):
    item = _item("741235", 1, 10)
    logs = []

    monkeypatch.setattr(
        cleanup,
        "_request_pdh_delete",
        lambda page, target: {
            "successful": False,
            "verified": False,
            "mutated": True,
            "status": "DELETE_SENT_UNVERIFIED",
        },
    )
    monkeypatch.setattr(
        cleanup,
        "_find_item_row",
        lambda page, target: (_ for _ in ()).throw(AssertionError("local fallback should be blocked")),
    )

    assert cleanup.delete_studio_item(object(), item, logs.append) is False
    assert any("PDH HOLD" in line for line in logs)



def test_pdh_inventory_is_normalized_newest_first(monkeypatch):
    monkeypatch.setattr(
        cleanup,
        "pdh_request",
        lambda operation, payload, timeout=20.0: {
            "successful": True,
            "status": "INVENTORY_READY",
            "hasMore": False,
            "items": [
                {"item_id": "300", "item_type": 1, "desc": "newest", "order": 0, "can_delete": True},
                {"item_id": "200", "item_type": 2, "desc": "older", "order": 1, "can_delete": True},
            ],
        },
    )

    items, has_more = cleanup._load_pdh_items()

    assert has_more is False
    assert [item.item_id for item in items] == ["300", "200"]
    assert [item.kind for item in items] == ["video", "photo"]


def test_run_cleanup_uses_pdh_without_starting_cdp(monkeypatch):
    logs = []
    stop_event = threading.Event()

    monkeypatch.setattr(
        cleanup,
        "_pdh_ping",
        lambda: {"successful": True, "status": "READY", "version": "0.11.test"},
    )
    monkeypatch.setattr(
        cleanup,
        "_run_cleanup_via_pdh",
        lambda options, **kwargs: 4,
    )
    monkeypatch.setattr(
        cleanup,
        "sync_playwright",
        lambda: (_ for _ in ()).throw(AssertionError("CDP fallback must not start")),
    )

    result = cleanup.run_cleanup(
        cleanup.CleanupOptions(mode="videos", max_actions=4, dry_run=True),
        log=logs.append,
        stop_event=stop_event,
    )

    assert result == 4
    assert any("PDH CONNECTED" in line for line in logs)
