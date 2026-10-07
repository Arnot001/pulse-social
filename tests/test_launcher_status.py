import runpy
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import concurrent.futures
import pytest
import tkinter
import platforms.browser_control as browser
import platforms.pdh_bridge as bridge


def test_launcher_refreshes_connection_without_overlapping_work_and_cancels_on_close(monkeypatch):
    root = MagicMock()
    variable = MagicMock()
    for name in ("Frame", "Button", "Label", "Canvas"):
        monkeypatch.setattr(tkinter, name, MagicMock())
    monkeypatch.setattr(tkinter, "Tk", lambda: root)
    monkeypatch.setattr(tkinter, "StringVar", lambda **kw: variable)
    monkeypatch.setattr(browser, "running_browser_names", lambda: ["Brave"])
    connected = False
    monkeypatch.setattr(bridge, "bridge_status", lambda: {"pdhConnected": connected})
    monkeypatch.setattr(bridge, "ensure_bridge_server", lambda: True)
    futures = []
    executor = MagicMock()
    def submit(fn):
        future = Future()
        futures.append((future, fn))
        return future
    executor.submit.side_effect = submit
    monkeypatch.setattr(concurrent.futures, "ThreadPoolExecutor", lambda **kw: executor)
    namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / "pulse_social_launcher.py"))
    assert root.after.call_args.args[0] == 2000
    tick = root.after.call_args.args[1]
    tick()
    namespace["refresh_pdh_browser"]()
    assert len(futures) == 1
    connected = True
    futures[0][0].set_result(futures[0][1]())
    tick()
    variable.set.assert_called_with("BRAVE OPEN // PDH CONNECTED")
    assert len(futures) == 2
    connected = False
    futures[1][0].set_result(futures[1][1]())
    tick()
    variable.set.assert_called_with("BRAVE OPEN // WAITING FOR PDH")
    namespace["close_all"]()
    root.after_cancel.assert_called_once()
    executor.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
    root.destroy.assert_called_once()


def test_ambient_clock_pauses_rendering_when_minimized_and_cancels_on_destroy():
    # Exercise the visual clock without creating a desktop window or starting PDH.
    import ast
    import math
    import time
    from types import SimpleNamespace

    source = Path(__file__).resolve().parents[1] / "pulse_social_launcher.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    definition = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "AmbientWaves")
    namespace = {"math": math, "time": time}
    exec(compile(ast.Module(body=[definition], type_ignores=[]), str(source), "exec"), namespace)
    root = MagicMock()
    root.state.return_value = "iconic"
    root.after.return_value = "animation-timer"
    canvas = MagicMock()
    animation = namespace["AmbientWaves"](root, canvas)
    detail = MagicMock()
    animation.details.append(detail)
    animation.start()
    animation.start()
    root.after.assert_called_once()
    animation._tick()
    detail.assert_not_called()
    canvas.winfo_width.assert_not_called()
    assert root.after.call_args.args[0] == 250

    root.state.return_value = "normal"
    canvas.winfo_width.return_value = 1180
    canvas.winfo_height.return_value = 720
    animation._tick()
    detail.assert_called_once()
    assert root.after.call_args.args[0] == 125
    animation._destroy(SimpleNamespace(widget=canvas))
    root.after_cancel.assert_not_called()
    animation._destroy(SimpleNamespace(widget=root))
    root.after_cancel.assert_called_once_with("animation-timer")
    root.after.reset_mock()
    animation._tick()
    animation.start()
    root.after.assert_not_called()


@pytest.fixture
def launcher(monkeypatch):
    root = MagicMock()
    variable = MagicMock()
    buttons = {}
    for name in ("Frame", "Label", "Canvas"):
        monkeypatch.setattr(tkinter, name, MagicMock(side_effect=lambda *a, **kw: MagicMock()))

    def make_button(parent, **kwargs):
        widget = MagicMock()
        buttons[kwargs["text"]] = SimpleNamespace(
            widget=widget, parent=parent, command=kwargs["command"], options=kwargs,
        )
        return widget

    monkeypatch.setattr(tkinter, "Button", make_button)
    monkeypatch.setattr(tkinter, "Tk", lambda: root)
    monkeypatch.setattr(tkinter, "StringVar", lambda **kw: variable)
    monkeypatch.setattr(browser, "running_browser_names", lambda: ["Chrome"])
    connection = {"pdhConnected": False}
    monkeypatch.setattr(bridge, "bridge_status", lambda: connection)
    monkeypatch.setattr(bridge, "ensure_bridge_server", lambda: True)
    error = MagicMock()
    monkeypatch.setattr(tkinter.messagebox, "showerror", error)
    jobs = []
    executor = MagicMock()

    def submit(fn):
        future = Future()
        jobs.append((future, fn))
        return future

    executor.submit.side_effect = submit
    monkeypatch.setattr(concurrent.futures, "ThreadPoolExecutor", lambda **kw: executor)
    namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / "pulse_social_launcher.py"))

    def complete(index):
        future, fn = jobs[index]
        try:
            future.set_result(fn())
        except Exception as exc:
            future.set_exception(exc)

    return SimpleNamespace(
        root=root, variable=variable, buttons=buttons, connection=connection,
        error=error, jobs=jobs, executor=executor, namespace=namespace,
        tick=namespace["poll_pdh_browser_status"], complete=complete,
    )


@pytest.mark.parametrize("already_open", [False, True])
def test_main_page_launches_or_reuses_pulse_profile_with_bundled_pdh(
    monkeypatch, tmp_path, launcher, already_open,
):
    spec = browser.BrowserSpec("Chrome", "chrome.exe", (tmp_path / "chrome.exe",))
    profiles = tmp_path / "BrowserProfiles"
    extension = tmp_path / "pdh_extension"
    extension.mkdir()
    (extension / "manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(browser.sys, "frozen", True, raising=False)
    monkeypatch.setattr(browser.sys, "executable", str(tmp_path / "Pulse Social.exe"))
    monkeypatch.setattr(browser, "BROWSER_PROFILE_ROOT", profiles)
    monkeypatch.setattr(browser, "_browser_specs", lambda: (spec,))
    monkeypatch.setattr(browser, "_installed_exe", lambda value: spec.paths[0])
    monkeypatch.setattr(browser, "_save_state", MagicMock())
    ready = already_open
    monkeypatch.setattr(browser, "cdp_responding", lambda: ready)
    kill = MagicMock(side_effect=AssertionError("Everyday browser must remain untouched"))
    monkeypatch.setattr(browser, "_kill_browser", kill)

    def start(*args, **kwargs):
        nonlocal ready
        ready = True

    process = MagicMock(side_effect=start)
    monkeypatch.setattr(browser.subprocess, "Popen", process)
    open_button = launcher.buttons["OPEN PULSE BROWSER"]
    refresh = launcher.buttons["↻  PDH / REFRESH"]
    assert open_button.parent is launcher.namespace["browser_outer"]
    assert refresh.parent is open_button.parent
    open_button.command()
    open_button.command()
    refresh.command()
    assert len(launcher.jobs) == 2  # One existing status check and one launch.
    assert launcher.jobs[1][1] is browser.connect_browser
    process.assert_not_called()  # No browser work on the Tk thread.
    open_button.widget.configure.assert_called_with(state="disabled")
    launcher.complete(0)
    launcher.tick()
    launcher.variable.set.assert_called_with("OPENING PULSE BROWSER...")
    assert len(launcher.jobs) == 2

    launcher.complete(1)
    launcher.tick()
    open_button.widget.configure.assert_called_with(state="normal")
    assert len(launcher.jobs) == 3  # Fresh status requested after launch/reuse.
    kill.assert_not_called()
    assert process.call_count == (0 if already_open else 1)
    if not already_open:
        args = process.call_args.args[0]
        assert f"--user-data-dir={profiles / 'chrome'}" in args
        assert "--remote-debugging-port=9222" in args
        assert f"--load-extension={extension.resolve()}" in args
        assert "--restore-last-session" in args

    launcher.complete(2)
    launcher.tick()
    launcher.variable.set.assert_called_with("CHROME OPEN // WAITING FOR PDH")
    launcher.connection["pdhConnected"] = True
    launcher.complete(3)
    launcher.tick()
    launcher.variable.set.assert_called_with("CHROME OPEN // PDH CONNECTED")

    # A later click reuses the endpoint without spawning a second browser.
    open_button.command()
    launcher.complete(4)
    launcher.complete(5)
    launcher.tick()
    assert process.call_count == (0 if already_open else 1)
    launcher.error.assert_not_called()


@pytest.mark.parametrize("unexpected", [False, True])
def test_browser_failure_is_reported_on_tk_thread_and_allows_retry(launcher, unexpected):
    open_button = launcher.buttons["OPEN PULSE BROWSER"]
    open_button.command()
    launcher.complete(0)
    if unexpected:
        launcher.jobs[1][0].set_exception(RuntimeError("Could not start Chrome"))
    else:
        launcher.jobs[1][0].set_result((False, "Could not start Chrome"))
    launcher.error.assert_not_called()
    launcher.tick()
    launcher.error.assert_called_once_with(
        "Pulse Browser", "Could not start Chrome", parent=launcher.root,
    )
    open_button.widget.configure.assert_called_with(state="normal")
    launcher.variable.set.assert_called_with("PULSE BROWSER COULD NOT OPEN")
    assert len(launcher.jobs) == 3
    open_button.command()
    assert len(launcher.jobs) == 4
    open_button.widget.configure.assert_called_with(state="disabled")


def test_status_refresh_recovers_after_failure_without_launching_browser(launcher):
    launcher.jobs[0][0].set_exception(RuntimeError("Status unavailable"))
    launcher.tick()
    launcher.variable.set.assert_called_with("PDH STATUS UNAVAILABLE")
    launcher.buttons["↻  PDH / REFRESH"].command()
    launcher.buttons["↻  PDH / REFRESH"].command()
    assert len(launcher.jobs) == 2
    launcher.connection["pdhConnected"] = True
    launcher.complete(1)
    launcher.tick()
    launcher.variable.set.assert_called_with("CHROME OPEN // PDH CONNECTED")
    assert all(fn is not browser.connect_browser for _, fn in launcher.jobs)


def test_close_cancels_poll_and_queued_browser_work(launcher):
    launcher.buttons["OPEN PULSE BROWSER"].command()
    launcher.namespace["close_all"]()
    launcher.root.after_cancel.assert_called_once()
    launcher.executor.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
    launcher.root.destroy.assert_called_once()
    launcher.error.assert_not_called()
