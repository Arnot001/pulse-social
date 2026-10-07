"""Exercise the real animation scheduler with a deterministic, headless Tk host."""
import importlib
from unittest.mock import Mock

import pytest

import pulse_splash


@pytest.fixture
def display(monkeypatch):
    root = Mock()
    canvas = Mock()
    root.winfo_screenwidth.return_value = 1920
    root.winfo_screenheight.return_value = 1080
    clock = [0.0]
    timers = {}
    sequence = [0]
    running = [True]

    def after(delay, callback):
        sequence[0] += 1
        token = str(sequence[0])
        timers[token] = (clock[0] + delay / 1000, callback)
        return token

    def mainloop():
        while timers and running[0]:
            token = min(timers, key=lambda key: timers[key][0])
            clock[0], callback = timers.pop(token)
            callback()
            assert clock[0] <= 1.8, "splash failed to meet its deadline"

    root.after.side_effect = after
    root.after_cancel.side_effect = lambda token: timers.pop(token, None)
    root.mainloop.side_effect = mainloop
    root.quit.side_effect = lambda: running.__setitem__(0, False)
    monkeypatch.setattr(pulse_splash.tk, "Tk", lambda: root)
    monkeypatch.setattr(pulse_splash.tk, "Canvas", lambda *a, **kw: canvas)
    monkeypatch.setattr(pulse_splash.time, "monotonic", lambda: clock[0])
    return root, canvas, clock, timers


def test_import_does_not_create_a_window(monkeypatch):
    constructor = Mock(side_effect=AssertionError("window created during import"))
    monkeypatch.setattr(pulse_splash.tk, "Tk", constructor)
    importlib.reload(pulse_splash)
    constructor.assert_not_called()


def test_splash_is_centered_borderless_animated_and_bounded(display):
    root, canvas, clock, timers = display
    pulse_splash.show_splash()
    root.overrideredirect.assert_called_once_with(True)
    root.geometry.assert_called_once_with("600x340+660+370")
    assert root.method_calls.index(next(c for c in root.method_calls if c[0] == "withdraw")) < \
        root.method_calls.index(next(c for c in root.method_calls if c[0] == "deiconify"))
    assert 1.3 <= clock[0] <= 1.8
    assert canvas.coords.call_count > 100
    assert root.attributes.call_count > 10
    assert not timers
    root.destroy.assert_called_once()
    texts = [call.kwargs["text"] for call in canvas.create_text.call_args_list]
    assert "PULSE" in texts
    assert "S O C I A L" in texts
    assert texts[-1] == "OPENING LAUNCHER"
    assert not any("READY" in text or "%" in text for text in texts)


@pytest.mark.parametrize("operation", ["configure", "mainloop"])
def test_setup_or_event_loop_failure_destroys_root(display, operation):
    root, _, _, timers = display
    getattr(root, operation).side_effect = RuntimeError("display failure")
    with pytest.raises(RuntimeError, match="display failure"):
        pulse_splash.show_splash()
    root.destroy.assert_called_once()
    assert not timers


@pytest.mark.parametrize("delayed", [False, True])
def test_animation_callback_failure_returns_without_leaking_timers(display, delayed):
    root, canvas, _, timers = display
    if delayed:
        pump = root.mainloop.side_effect

        def fail_during_loop():
            canvas.coords.side_effect = RuntimeError("drawing failed")
            pump()

        root.mainloop.side_effect = fail_during_loop
    else:
        canvas.coords.side_effect = RuntimeError("drawing failed")
    pulse_splash.show_splash()
    root.destroy.assert_called_once()
    if not delayed:
        root.mainloop.assert_not_called()
    assert not timers


def test_unsupported_opacity_still_completes(display):
    root, _, clock, timers = display
    root.attributes.side_effect = pulse_splash.tk.TclError("alpha unsupported")
    pulse_splash.show_splash()
    assert 1.3 <= clock[0] <= 1.8
    root.attributes.assert_called_once()
    root.destroy.assert_called_once()
    assert not timers


def test_escape_closes_early_and_cancels_callbacks(display):
    root, _, clock, timers = display

    def escape():
        event, callback = root.bind.call_args.args
        assert event == "<Escape>"
        callback(None)

    root.mainloop.side_effect = escape
    pulse_splash.show_splash()
    assert clock[0] < 1.3
    assert not timers
    root.destroy.assert_called_once()


def test_late_frame_finishes_instead_of_replaying_animation(display):
    root, _, clock, timers = display

    def delayed_loop():
        clock[0] = 2.0
        token = min(timers, key=lambda key: timers[key][0])
        _, frame = timers.pop(token)
        frame()

    root.mainloop.side_effect = delayed_loop
    pulse_splash.show_splash()
    root.destroy.assert_called_once()
    assert not timers
