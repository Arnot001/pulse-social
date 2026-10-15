from __future__ import annotations

from pathlib import Path
import inspect

import pytest

from platforms.tiktok import browser_post


class FakePage:
    def __init__(self):
        self.waits = []

    def wait_for_timeout(self, milliseconds):
        self.waits.append(milliseconds)


def test_open_sound_picker_waits_until_search_becomes_available(monkeypatch):
    page = FakePage()
    checks = iter([None, None, object()])

    monkeypatch.setattr(
        browser_post,
        "_music_search_input",
        lambda _page: next(checks),
    )
    monkeypatch.setattr(
        browser_post,
        "_click_first_visible",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(browser_post, "_visible_error", lambda _page: None)

    browser_post._open_sound_picker(page, timeout_seconds=5)

    assert page.waits


def test_open_sound_picker_surfaces_upload_error(monkeypatch):
    page = FakePage()

    monkeypatch.setattr(browser_post, "_music_search_input", lambda _page: None)
    monkeypatch.setattr(
        browser_post,
        "_click_first_visible",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        browser_post,
        "_visible_error",
        lambda _page: "Video processing failed",
    )

    with pytest.raises(RuntimeError, match="Video processing failed"):
        browser_post._open_sound_picker(page, timeout_seconds=5)



def test_open_sound_picker_dismisses_known_onboarding_overlays(monkeypatch):
    page = FakePage()
    checks = iter([None, object()])
    dismissed = []

    monkeypatch.setattr(
        browser_post,
        "_music_search_input",
        lambda _page: next(checks),
    )
    monkeypatch.setattr(
        browser_post,
        "_dismiss_sound_picker_overlays",
        lambda _page: dismissed.append(True) or True,
        raising=False,
    )
    monkeypatch.setattr(
        browser_post,
        "_click_first_visible",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(browser_post, "_visible_error", lambda _page: None)

    browser_post._open_sound_picker(page, timeout_seconds=5)

    assert dismissed



def test_open_sound_picker_uses_safe_exact_trigger_not_generic_click(monkeypatch):
    page = FakePage()
    checks = iter([None, object()])
    safe_trigger_calls = []

    monkeypatch.setattr(
        browser_post,
        "_music_search_input",
        lambda _page: next(checks),
    )
    monkeypatch.setattr(
        browser_post,
        "_dismiss_sound_picker_overlays",
        lambda _page: False,
    )
    monkeypatch.setattr(
        browser_post,
        "_click_sound_picker_trigger",
        lambda _page: safe_trigger_calls.append(True) or False,
        raising=False,
    )
    monkeypatch.setattr(
        browser_post,
        "_click_first_visible",
        lambda *_args, **_kwargs: pytest.fail(
            "Sound picker must not use the generic partial-match click helper"
        ),
    )
    monkeypatch.setattr(browser_post, "_visible_error", lambda _page: None)

    browser_post._open_sound_picker(page, timeout_seconds=5)

    assert safe_trigger_calls == [True]


def test_sound_media_can_be_prepared_before_music_search():
    assert callable(
        getattr(browser_post, "prepare_tiktok_sound_media", None)
    ), "TikTok media must have a dedicated preparation step before ADD MUSIC"


def test_sound_results_wait_for_full_list_to_settle(monkeypatch):
    page = FakePage()

    first_25 = [f"sound {index}" for index in range(25)]
    full_40 = [f"sound {index}" for index in range(40)]
    batches = [
        first_25,
        full_40,
        full_40,
        full_40,
    ]
    requested_limits = []

    def fake_results(_page, limit=25):
        requested_limits.append(limit)
        if batches:
            return batches.pop(0)
        return full_40

    monkeypatch.setattr(
        browser_post,
        "_sound_result_texts",
        fake_results,
    )

    results = browser_post._wait_for_settled_sound_results(
        page,
        max_polls=8,
        stable_polls=2,
        limit=100,
    )

    assert len(results) == 40
    assert max(requested_limits) == 100
    assert page.waits


def test_prepared_sound_page_is_bound_to_exact_cdp_target(monkeypatch):
    class FakePreparedPage:
        def __init__(self, target_id):
            self.target_id = target_id

        def is_closed(self):
            return False

    class FakeContext:
        def __init__(self, pages):
            self.pages = pages

    first = FakePreparedPage("target-a")
    prepared = FakePreparedPage("target-b")
    context = FakeContext([first, prepared])

    monkeypatch.setattr(
        browser_post,
        "_PREPARED_SOUND_TARGET_ID",
        "target-b",
        raising=False,
    )
    monkeypatch.setattr(
        browser_post,
        "_PREPARED_SOUND_MEDIA_KEY",
        "media-key",
        raising=False,
    )
    monkeypatch.setattr(
        browser_post,
        "_page_target_id",
        lambda page: page.target_id,
        raising=False,
    )

    result = browser_post._prepared_sound_page(
        context,
        "media-key",
    )

    assert result is prepared
    assert browser_post._prepared_sound_page(
        context,
        "different-media",
    ) is None


def test_missing_prepared_sound_session_refuses_reupload(monkeypatch):
    monkeypatch.setattr(
        browser_post,
        "_prepared_sound_page",
        lambda *_args, **_kwargs: None,
        raising=False,
    )

    with pytest.raises(RuntimeError, match="PREPARED MEDIA SESSION LOST"):
        browser_post._require_prepared_sound_page(
            object(),
            "media-key",
        )


def test_sound_preview_reuses_prepared_tab_without_reupload():
    source = inspect.getsource(browser_post.preview_tiktok_sound)

    assert "_require_prepared_sound_page" in source
    assert "_sound_preview_page" not in source
    assert "set_input_files" not in source
    assert "page.goto" not in source


def test_publish_reuses_prepared_tab_without_reupload():
    source = inspect.getsource(browser_post.publish_browser_post)

    assert "_require_prepared_sound_page" in source
    assert "_posting_page" not in source
    assert "set_input_files" not in source
    assert "page.goto" not in source


def test_activity_log_has_readable_minimum_height():
    source = Path(r"platforms\tiktok\auto_post_ui.py").read_text(encoding="utf-8")

    assert "height=5" in source
    assert 'activity.pack(fill="both"' in source
