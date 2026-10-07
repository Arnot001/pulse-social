"""Exercise the cleanup entrypoint without creating Tk windows or real browsers."""

import ast
import json
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from platforms import browser_control


@pytest.fixture
def cleanup(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(browser_control, "STATE_FILE", tmp_path / "browser_control.json")
    monkeypatch.setattr(browser_control, "BROWSER_PROFILE_ROOT", tmp_path / "profiles")
    monkeypatch.setattr(browser_control, "cdp_responding", lambda: False)
    monkeypatch.setattr(browser_control, "running_browser_names", lambda: ["Brave"])
    monkeypatch.setattr(browser_control, "installed_browser_names", lambda: ["Brave"])
    monkeypatch.setattr(browser_control, "_installed_exe", lambda spec: tmp_path / spec.image)
    monkeypatch.setattr(browser_control.subprocess, "Popen", Mock())
    monkeypatch.setattr(browser_control, "_kill_browser", Mock(side_effect=AssertionError("Must not kill normal browsers")))

    # The legacy entrypoint creates Tk at module scope. Execute the complete
    # pre-UI module, including real imports and worker functions, without Tk.
    source = Path(__file__).resolve().parents[1] / "pulse_social_ui.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    boundary = next(i for i, node in enumerate(tree.body)
                    if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "settings"
                            for target in node.targets))
    namespace = {"__name__": "x_cleanup_under_test"}
    exec(compile(ast.Module(body=tree.body[:boundary], type_ignores=[]), str(source), "exec"), namespace)
    return namespace


def fake_playwright():
    browser = SimpleNamespace(contexts=[SimpleNamespace(pages=[])])
    attach = Mock(return_value=browser)
    return SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=attach)), browser


def test_existing_cdp_is_reused_without_launching(cleanup, monkeypatch):
    monkeypatch.setitem(cleanup, "cdp_responding", lambda: True)
    launch = Mock(side_effect=AssertionError("Existing CDP must be reused"))
    monkeypatch.setitem(cleanup, "open_x_browser", launch)
    playwright, browser = fake_playwright()

    assert cleanup["connect_cdp"](playwright) is browser

    playwright.chromium.connect_over_cdp.assert_called_once_with(
        "http://127.0.0.1:9222", timeout=3000)
    launch.assert_not_called()
    browser_control.subprocess.Popen.assert_not_called()


def test_no_cdp_launches_dedicated_profile_with_bundled_pdh_then_attaches(cleanup, monkeypatch, tmp_path):
    # Model an installed beta with bundled PDH and a normal Brave window open.
    executable = tmp_path / "release" / "Pulse Social.exe"
    extension = executable.parent / "pdh_extension"
    extension.mkdir(parents=True)
    (extension / "manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    responding = iter([False, True])
    monkeypatch.setattr(browser_control, "cdp_responding", lambda: next(responding))
    events = []
    browser_control.subprocess.Popen.side_effect = lambda *a, **kw: events.append("launch")
    playwright, browser = fake_playwright()
    playwright.chromium.connect_over_cdp.side_effect = lambda *a, **kw: events.append("attach") or browser

    assert cleanup["connect_cdp"](playwright) is browser

    assert events == ["launch", "attach"]
    browser_control.subprocess.Popen.assert_called_once()
    args = browser_control.subprocess.Popen.call_args.args[0]
    profile = tmp_path / "profiles" / "brave"
    assert args[0] == str(tmp_path / "brave.exe")
    assert f"--user-data-dir={profile}" in args
    assert "--remote-debugging-port=9222" in args
    assert "--restore-last-session" in args
    assert f"--load-extension={extension.resolve()}" in args
    assert args[-1] == "https://x.com/home"
    assert profile.is_dir()
    assert json.loads(browser_control.STATE_FILE.read_text())["profile"] == str(profile)
    browser_control._kill_browser.assert_not_called()
    playwright.chromium.connect_over_cdp.assert_called_once_with(
        "http://127.0.0.1:9222", timeout=3000)


@pytest.mark.parametrize("failure", ["spawn", "timeout"])
def test_true_launch_failure_stops_before_attach(cleanup, monkeypatch, failure):
    playwright, _ = fake_playwright()
    if failure == "spawn":
        browser_control.subprocess.Popen.side_effect = OSError("launch denied")
        detail = "Could not start Brave: launch denied"
    else:
        clock = iter([0, 16])
        monkeypatch.setattr(browser_control.time, "time", lambda: next(clock))
        detail = "did not become ready"

    with pytest.raises(RuntimeError, match=detail) as error:
        cleanup["connect_cdp"](playwright)

    assert "Start Brave with" not in str(error.value)
    playwright.chromium.connect_over_cdp.assert_not_called()
    browser_control.subprocess.Popen.assert_called_once()


def test_attach_retries_existing_cdp_without_launching_another_browser(cleanup, monkeypatch):
    monkeypatch.setitem(cleanup, "cdp_responding", lambda: True)
    monkeypatch.setattr(cleanup["time"], "sleep", lambda seconds: None)
    playwright, browser = fake_playwright()
    playwright.chromium.connect_over_cdp.side_effect = [RuntimeError("not ready"), browser]

    assert cleanup["connect_cdp"](playwright) is browser

    assert playwright.chromium.connect_over_cdp.call_count == 2
    browser_control.subprocess.Popen.assert_not_called()


def test_attach_failure_retains_last_error(cleanup, monkeypatch):
    monkeypatch.setitem(cleanup, "cdp_responding", lambda: True)
    clock = iter([0, 0, 11])
    monkeypatch.setattr(cleanup["time"], "time", lambda: next(clock))
    monkeypatch.setattr(cleanup["time"], "sleep", lambda seconds: None)
    playwright, _ = fake_playwright()
    playwright.chromium.connect_over_cdp.side_effect = RuntimeError("CDP disconnected")

    with pytest.raises(RuntimeError, match="CDP disconnected") as error:
        cleanup["connect_cdp"](playwright)

    assert "Start Brave with" not in str(error.value)
    browser_control.subprocess.Popen.assert_not_called()


@pytest.mark.parametrize("launch_ok", [False, True])
def test_worker_reports_failure_or_waits_for_arm_after_attach(cleanup, monkeypatch, launch_ok):
    monkeypatch.setitem(cleanup, "open_x_browser", lambda: (launch_ok, "launch failed"))
    playwright, _ = fake_playwright()
    monkeypatch.setitem(cleanup, "sync_playwright", lambda: nullcontext(playwright))
    page = Mock()
    monkeypatch.setitem(cleanup, "find_x_page", lambda *args: page)
    # Stop at the ARM gate: attaching alone must never perform cleanup.
    wait = Mock(side_effect=lambda: cleanup["stop_event"].set())
    monkeypatch.setattr(cleanup["continue_event"], "wait", wait)

    cleanup["cleaner_worker"](dict(cleanup["DEFAULTS"], handle="example"))

    states = []
    while not cleanup["run_state_queue"].empty():
        states.append(cleanup["run_state_queue"].get()[0])
    logs = []
    while not cleanup["log_queue"].empty():
        logs.append(cleanup["log_queue"].get())
    assert states == (["attaching", "armed", "idle"] if launch_ok else ["attaching", "idle"])
    assert wait.call_count == int(launch_ok)
    assert playwright.chromium.connect_over_cdp.call_count == int(launch_ok)
    page.locator.assert_not_called()
    page.goto.assert_not_called()
    if not launch_ok:
        assert any("launch failed" in line for line in logs)
