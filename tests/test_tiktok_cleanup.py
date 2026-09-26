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
