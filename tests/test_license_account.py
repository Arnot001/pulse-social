"""Offline device release tests with isolated saved keys and real Tk controls."""
from unittest.mock import Mock
import tkinter as tk

import pytest

import pulse_license_account as account
import pulse_license_gate as gate
from pulse_licensing import LicensingError, LicensingUnavailable


@pytest.fixture
def release(monkeypatch, tmp_path):
    monkeypatch.setattr(gate, "APP_DIR", tmp_path)
    monkeypatch.setattr(gate, "LICENCE_FILE", tmp_path / "licence.json")
    gate.save_licence_key("TEST-ONLY-KEY")
    api = Mock(return_value={"ok": True, "status": "DEACTIVATED", "transfer_ready": True})
    monkeypatch.setattr(account, "deactivate", api)
    return api


def test_release_calls_server_with_saved_key_before_clearing(release):
    def response(key):
        assert gate.LICENCE_FILE.exists()
        assert key == "TEST-ONLY-KEY"
        return {"ok": True, "status": "DEACTIVATED", "transfer_ready": True}
    release.side_effect = response
    assert account.release_this_device() == account.ReleaseResult(True, account.RELEASED_MESSAGE, True)
    release.assert_called_once_with("TEST-ONLY-KEY")
    assert not gate.LICENCE_FILE.exists()


@pytest.mark.parametrize("code,expected", [
    ("DEVICE_MISMATCH", "another device"), ("LICENCE_NOT_ACTIVE", "already inactive"),
    ("LICENCE_INVALID", "not valid"), ("LICENCE_REVOKED", "revoked"),
    ("LICENCE_DISABLED", "disabled"), ("LICENCE_EXPIRED", "expired"),
    ("DEVICE_ID_UNAVAILABLE", "identify"), ("UNKNOWN", "could not release"),
])
def test_backend_failure_keeps_exact_saved_file(release, code, expected):
    before = gate.LICENCE_FILE.read_bytes()
    release.side_effect = LicensingError(code, "sensitive server detail")
    result = account.release_this_device()
    assert not result.released and not result.local_cleared
    assert expected in result.message
    assert "sensitive" not in result.message
    assert gate.LICENCE_FILE.read_bytes() == before


@pytest.mark.parametrize("error", [LicensingUnavailable("LICENSING_UNAVAILABLE"),
                                  LicensingError("HTTP_503", status=503)])
def test_unavailable_service_keeps_key_for_retry(release, error):
    release.side_effect = error
    result = account.release_this_device()
    assert not result.released and "temporarily unavailable" in result.message
    assert gate.load_saved_licence_key() == "TEST-ONLY-KEY"


@pytest.mark.parametrize("payload", [None, [], {}, {"ok": True},
    {"ok": False, "status": "DEACTIVATED", "transfer_ready": True},
    {"ok": True, "status": "ACTIVE", "transfer_ready": True},
    {"ok": True, "status": "DEACTIVATED", "transfer_ready": False},
    {"ok": True, "status": "DEACTIVATED", "transfer_ready": "true"},
])
def test_unconfirmed_release_never_clears_key(release, payload):
    release.return_value = payload
    result = account.release_this_device()
    assert not result.released
    assert gate.load_saved_licence_key() == "TEST-ONLY-KEY"


def test_missing_key_never_calls_server(release):
    gate.clear_saved_licence_key()
    assert not account.release_this_device().released
    release.assert_not_called()


def test_unexpected_error_does_not_leak_details_or_clear_key(release):
    release.side_effect = RuntimeError("TEST-ONLY-KEY private device identity")
    result = account.release_this_device()
    assert not result.released and "private" not in result.message and "TEST-ONLY-KEY" not in result.message
    assert gate.LICENCE_FILE.exists()


def test_local_clear_failure_still_reports_server_release_for_app_shutdown(release, monkeypatch):
    monkeypatch.setattr(account, "clear_saved_licence_key", Mock(side_effect=PermissionError()))
    result = account.release_this_device()
    assert result.released and not result.local_cleared
    assert "could not remove the saved key" in result.message
    assert gate.LICENCE_FILE.exists()


@pytest.fixture(scope="module")
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def ui(monkeypatch, release, tk_root):
    root = tk.Toplevel(tk_root)
    root.withdraw()
    errors, jobs = [], []
    monkeypatch.setattr(tk_root, "report_callback_exception", lambda *args: errors.append(args))
    class Thread:
        def __init__(self, target, **kwargs): self.target = target
        def start(self): jobs.append(self.target)
    monkeypatch.setattr(account.threading, "Thread", Thread)
    for name in ("askyesno", "showinfo", "showwarning"):
        monkeypatch.setattr(account.messagebox, name, Mock(return_value=True))
    closed = Mock()
    window = account.open_licence_account(root, closed)
    window.withdraw()
    root.update()
    panel = window.winfo_children()[0]
    button = next(w for w in panel.winfo_children() if isinstance(w, tk.Button))
    def finish():
        jobs.pop(0)()
        timer = next(t for t in root.tk.call("after", "info") if "poll" in str(root.tk.call("after", "info", t)))
        command = root.tk.call("after", "info", timer)[0]
        root.tk.call("after", "cancel", timer)
        root.tk.call(command)
    yield root, window, button, jobs, closed, finish
    try: root.destroy()
    except tk.TclError: pass
    assert not errors


def test_confirmation_cancel_does_nothing(ui, release):
    _, _, button, jobs, closed, _ = ui
    account.messagebox.askyesno.return_value = False
    button.invoke()
    assert not jobs
    release.assert_not_called()
    closed.assert_not_called()
    assert gate.LICENCE_FILE.exists()


def test_success_is_async_single_request_and_closes_app(ui, release):
    _, _, button, jobs, closed, finish = ui
    button.invoke()
    button.tk.call(button.cget("command"))
    assert len(jobs) == 1 and button.cget("state") == "disabled"
    release.assert_not_called()
    finish()
    account.messagebox.showinfo.assert_called_once()
    assert account.messagebox.showinfo.call_args.args[1] == account.RELEASED_MESSAGE
    closed.assert_called_once()
    assert not gate.LICENCE_FILE.exists()


def test_failure_keeps_dialog_and_key_and_allows_retry(ui, release):
    _, window, button, jobs, closed, finish = ui
    release.side_effect = LicensingError("DEVICE_MISMATCH")
    button.invoke(); finish()
    assert window.winfo_exists() and button.cget("state") == "normal"
    closed.assert_not_called()
    account.messagebox.showinfo.assert_not_called()
    assert gate.LICENCE_FILE.exists()
    button.invoke()
    assert len(jobs) == 1


def test_close_during_pending_release_waits_for_outcome(ui):
    _, window, button, _, _, _ = ui
    button.invoke()
    window.tk.call(window.protocol("WM_DELETE_WINDOW"))
    assert window.winfo_exists()


def test_reopening_account_reuses_same_dialog(ui):
    root, window, _, jobs, _, _ = ui
    assert account.open_licence_account(root, Mock()) is window
    assert not jobs


def test_shutdown_callback_can_destroy_root_without_tk_error(ui):
    root, _, button, _, closed, finish = ui
    closed.side_effect = root.destroy
    button.invoke(); finish()


def test_local_cleanup_failure_warns_and_closes_app(ui, monkeypatch):
    _, _, button, _, closed, finish = ui
    monkeypatch.setattr(account, "clear_saved_licence_key", Mock(side_effect=PermissionError()))
    button.invoke(); finish()
    account.messagebox.showwarning.assert_called_once()
    closed.assert_called_once()
    assert gate.LICENCE_FILE.exists()
