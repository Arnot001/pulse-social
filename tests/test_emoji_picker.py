import gc
import threading
import tkinter as tk

import pytest

import emoji_diagnostic as diagnostic
from platforms.common import emoji_picker as picker
from platforms.common.emoji_picker import apply_skin_tone, filter_emojis


def test_emoji_search_uses_unicode_names_and_aliases():
    assert "😂" in filter_emojis("SMILEYS", "laugh")
    assert "🔥" in filter_emojis("SMILEYS", "fire") or "🔥" in filter_emojis("ANIMALS", "fire")
    assert "⚽" in filter_emojis("ACTIVITY", "football")


def test_skin_tone_only_changes_supported_emoji():
    assert apply_skin_tone("👍", "MEDIUM") == "👍🏽"
    assert apply_skin_tone("❤️", "DARK") == "❤️"
    assert apply_skin_tone("👍", "DEFAULT") == "👍"
    assert apply_skin_tone("✌️", "LIGHT") == "✌🏻"


@pytest.fixture(scope="module")
def tk_root():
    window = tk.Tk()
    window.withdraw()
    yield window
    window.destroy()
    gc.collect()


@pytest.fixture
def root(tk_root, monkeypatch):
    monkeypatch.setattr(picker, "_load_recents", lambda: [])
    yield tk_root
    for callback in tk_root.tk.call("after", "info"):
        tk_root.after_cancel(callback)
    for child in tk_root.winfo_children():
        child.destroy()
    tk_root._pulse_emoji_picker = None
    gc.collect()


def open_picker(root):
    return picker.open_emoji_picker(tk.Entry(root))


def category(window, name):
    return next(w for w in diagnostic.widgets(window) if getattr(w, "_emoji_category", None) == name)


def tiles(window):
    return [w for w in diagnostic.widgets(window) if hasattr(w, "_emoji")]


def test_actual_picker_all_categories_and_skin_tones_use_artwork(root, monkeypatch):
    monkeypatch.setattr(diagnostic, "log", lambda message: None)
    window = open_picker(root)
    assert diagnostic.verify_picker(root, window) == sum(map(len, picker.EMOJI_CATALOG.values())) + 5 * len(picker.EMOJI_CATALOG["PEOPLE"])


def test_delayed_sprite_repaints_active_category_and_keeps_tk_on_main_thread(root, monkeypatch):
    decode_threads, photo_threads = [], []
    release = threading.Event()
    original_open = picker.Image.open
    original_photo = picker.ImageTk.PhotoImage

    def delayed_open(*args, **kwargs):
        decode_threads.append(threading.get_ident())
        assert release.wait(5)
        return original_open(*args, **kwargs)

    def tracked_photo(*args, **kwargs):
        photo_threads.append(threading.get_ident())
        assert kwargs["master"].tk is root.tk
        return original_photo(*args, **kwargs)

    monkeypatch.setattr(picker.Image, "open", delayed_open)
    monkeypatch.setattr(picker.ImageTk, "PhotoImage", tracked_photo)
    try:
        window = open_picker(root)
        category(window, "ANIMALS").invoke()
        category(window, "ACTIVITY").invoke()
        assert window._emoji_diagnostics()["sprite_state"] == "loading"
        assert "pending" in window._emoji_diagnostics()["sources"]
        assert "font" not in window._emoji_diagnostics()["sources"]
        heartbeat = []
        root.after(0, lambda: heartbeat.append(True))
        root.update()
        assert heartbeat == [True]
    finally:
        release.set()
    diagnostic.wait_for_sprite(root, window)
    assert window._emoji_diagnostics()["category"] == "ACTIVITY"
    assert "sprite" in window._emoji_diagnostics()["sources"]
    assert all(t != threading.get_ident() for t in decode_threads)
    assert photo_threads and set(photo_threads) == {threading.get_ident()}


def test_missing_pillow_is_reported_once_and_never_uses_font_for_mapped_art(root, monkeypatch, caplog):
    monkeypatch.setattr(picker, "Image", None)
    window = open_picker(root)
    assert all(w._emoji_source == "embedded" for w in tiles(window))
    category(window, "ANIMALS").invoke()
    category(window, "ACTIVITY").invoke()
    assert window._emoji_diagnostics()["sprite_state"] == "failed"
    assert "Pillow is required" in window._emoji_diagnostics()["sprite_error"]
    assert "font" not in window._emoji_diagnostics()["sources"]
    assert sum("Emoji sprite artwork unavailable" in r.message for r in caplog.records) == 1
    with pytest.raises(RuntimeError, match="Pillow is required"):
        diagnostic.wait_for_sprite(root, window)


def test_failed_photo_creation_does_not_cache_font_fallback(root, monkeypatch, caplog):
    window = open_picker(root)
    diagnostic.wait_for_sprite(root, window)
    original_photo = picker.ImageTk.PhotoImage

    def fail(*args, **kwargs):
        raise tk.TclError("injected photo failure")

    monkeypatch.setattr(picker.ImageTk, "PhotoImage", fail)
    category(window, "ANIMALS").invoke()
    assert "pending" in window._emoji_diagnostics()["sources"]
    assert "font" not in window._emoji_diagnostics()["sources"]
    assert sum("injected photo failure" in r.message for r in caplog.records) == 1
    monkeypatch.setattr(picker.ImageTk, "PhotoImage", original_photo)
    category(window, "ANIMALS").invoke()
    assert set(window._emoji_diagnostics()["sources"]) == {"embedded", "sprite"}


def test_variation_selector_lookup_uses_sprite(root, monkeypatch):
    monkeypatch.setattr(picker, "_load_sprite_manifest", lambda: {"\u26bd": [60, 60]})
    monkeypatch.setattr(picker, "asset_base64", lambda emoji: None)
    monkeypatch.setattr(picker, "filter_emojis", lambda *args: ["\u26bd\ufe0f"])
    window = open_picker(root)
    diagnostic.wait_for_sprite(root, window)
    assert window._emoji_diagnostics()["sources"] == ["sprite"]


def test_diagnostic_fails_instead_of_skipping_missing_pillow(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def missing_pillow(name, *args, **kwargs):
        if name == "PIL":
            raise ImportError("injected missing Pillow")
        return real_import(name, *args, **kwargs)

    messages = []
    monkeypatch.setattr(builtins, "__import__", missing_pillow)
    monkeypatch.setattr(diagnostic, "log", messages.append)
    assert diagnostic.main([]) == 1
    assert any("Pillow is required" in message for message in messages)
    assert not any("CHECKS PASSED" in message for message in messages)
