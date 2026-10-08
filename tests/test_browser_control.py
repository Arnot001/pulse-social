from pathlib import Path

import platforms.browser_control as browser_control


def _chrome_spec() -> browser_control.BrowserSpec:
    return browser_control.BrowserSpec(
        name="Chrome",
        image="chrome.exe",
        paths=(Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),),
    )


def test_launch_args_use_dedicated_non_default_profile(monkeypatch, tmp_path):
    spec = _chrome_spec()
    monkeypatch.setattr(browser_control, "BROWSER_PROFILE_ROOT", tmp_path / "profiles")

    args = browser_control._launch_args(
        spec,
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        "https://www.tiktok.com/",
    )

    assert "--remote-debugging-port=9222" in args
    assert f"--user-data-dir={tmp_path / 'profiles' / 'chrome'}" in args
    assert "--restore-last-session" in args
    assert "--no-first-run" in args
    assert "--no-default-browser-check" in args
    assert args[-1] == "https://www.tiktok.com/"


def test_connect_browser_does_not_kill_everyday_browser(monkeypatch, tmp_path):
    spec = _chrome_spec()
    fake_exe = tmp_path / "chrome.exe"
    fake_exe.write_text("", encoding="utf-8")

    responding = iter([False, True])
    launched = []

    monkeypatch.setattr(browser_control, "BROWSER_PROFILE_ROOT", tmp_path / "profiles")
    monkeypatch.setattr(browser_control, "choose_browser_name", lambda preferred=None: "Chrome")
    monkeypatch.setattr(browser_control, "browser_spec", lambda name: spec)
    monkeypatch.setattr(browser_control, "_installed_exe", lambda value: fake_exe)
    monkeypatch.setattr(browser_control, "cdp_responding", lambda: next(responding))
    monkeypatch.setattr(browser_control, "_save_state", lambda name: None)
    monkeypatch.setattr(browser_control.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        browser_control.subprocess,
        "Popen",
        lambda args, creationflags=0: launched.append(args),
    )
    monkeypatch.setattr(
        browser_control,
        "_kill_browser",
        lambda value: (_ for _ in ()).throw(
            AssertionError("Pulse must not kill the user's everyday browser")
        ),
    )

    ok, message = browser_control.connect_browser("Chrome")

    assert ok is True
    assert "CONNECTED" in message
    assert launched
    assert any(arg.startswith("--user-data-dir=") for arg in launched[0])



def test_open_browser_wins_over_saved_browser(monkeypatch):
    monkeypatch.setattr(browser_control, "running_browser_names", lambda: ["Brave"])
    monkeypatch.setattr(browser_control, "dedicated_browser_name", lambda: "Chrome")
    monkeypatch.setattr(browser_control, "installed_browser_names", lambda: ["Brave", "Chrome"])

    assert browser_control.choose_browser_name() == "Brave"


def test_dedicated_browser_name_only_returns_saved_choice(monkeypatch):
    monkeypatch.setattr(browser_control, "_load_state", lambda: {})
    monkeypatch.setattr(browser_control, "running_browser_names", lambda: ["Brave"])

    assert browser_control.dedicated_browser_name() is None


def test_status_shows_current_open_browser_before_stale_saved_choice(monkeypatch):
    monkeypatch.setattr(browser_control, "cdp_responding", lambda: False)
    monkeypatch.setattr(browser_control, "running_browser_names", lambda: ["Brave"])
    monkeypatch.setattr(browser_control, "dedicated_browser_name", lambda: "Chrome")
    monkeypatch.setattr(browser_control, "installed_browser_names", lambda: ["Brave", "Chrome"])

    assert browser_control.browser_status() == "BRAVE OPEN // READY TO ATTACH"



def test_pulse_browser_pid_lookup_matches_only_dedicated_profile(monkeypatch, tmp_path):
    spec = _chrome_spec()
    monkeypatch.setattr(browser_control, "BROWSER_PROFILE_ROOT", tmp_path / "profiles")
    captured = {}

    class Result:
        returncode = 0
        stdout = "4321\n"
        stderr = ""

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["env"] = kwargs.get("env", {})
        return Result()

    monkeypatch.setattr(browser_control.subprocess, "run", fake_run)

    assert browser_control._pulse_browser_pids(spec) == [4321]
    assert captured["env"]["PULSE_PROFILE_MATCH"] == str(tmp_path / "profiles" / "chrome")
    assert captured["env"]["PULSE_BROWSER_IMAGE"] == "chrome.exe"
    assert captured["args"][0].lower() == "powershell"


def test_stop_pulse_browser_kills_profile_pid_not_browser_image(monkeypatch):
    spec = _chrome_spec()
    calls = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(browser_control, "browser_spec", lambda name: spec)
    monkeypatch.setattr(browser_control, "_pulse_browser_pids", lambda value: [4321])
    monkeypatch.setattr(browser_control, "cdp_responding", lambda: False)
    monkeypatch.setattr(
        browser_control.subprocess,
        "run",
        lambda args, **kwargs: calls.append(args) or Result(),
    )

    ok, message = browser_control.stop_pulse_browser("Chrome")

    assert ok is True
    assert "stopped" in message.lower()
    assert calls == [["taskkill", "/PID", "4321", "/T", "/F"]]
