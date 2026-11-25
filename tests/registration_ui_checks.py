"""Explicit subprocess-only Tk checks; invoked by test_beta_registration.py."""
import gc
import tkinter as tk
from unittest.mock import Mock
import pytest
import pulse_licensing as api
import pulse_license_gate as gate


@pytest.fixture(scope="module")
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()
    gc.collect()


@pytest.fixture
def ui(monkeypatch, tmp_path, tk_root):
    monkeypatch.setattr(gate, "APP_DIR", tmp_path)
    monkeypatch.setattr(gate, "LICENCE_FILE", tmp_path / "licence.json")
    jobs, errors = [], []
    class Thread:
        def __init__(self, target, **kwargs): self.target = target
        def start(self): jobs.append(self.target)
    monkeypatch.setattr(gate.threading, "Thread", Thread)
    monkeypatch.setattr(gate, "activate", Mock(return_value=api.ActivationResult("ACTIVE", "l", "a", False)))
    monkeypatch.setattr(gate, "start_registration", Mock(return_value="a" * 64))
    monkeypatch.setattr(gate, "verify_registration", Mock(return_value="TEST-BETA-KEY"))
    monkeypatch.setattr(gate.messagebox, "askyesno", Mock(return_value=True))
    root = tk.Toplevel(tk_root)
    root.withdraw()
    monkeypatch.setattr(tk_root, "report_callback_exception", lambda *args: errors.append(args))
    done = Mock()
    screen = gate.LicenceScreen(root, done)
    def finish():
        jobs.pop(0)()
        command = root.tk.call("after", "info", screen.timer)[0]
        root.tk.call("after", "cancel", screen.timer)
        root.tk.call(command)
    yield screen, jobs, done, finish
    root.destroy()
    gc.collect()
    assert not errors


def test_signup_and_verify_are_async_single_flight_and_save_only_after_success(ui):
    screen, jobs, done, finish = ui
    screen.email_form("access")
    screen.email.set("owner@example.com")
    screen.send_code(); screen.send_code()
    assert len(jobs) == 1 and screen.busy
    gate.start_registration.assert_not_called()
    finish()
    gate.start_registration.assert_called_once_with("owner@example.com", "access", "")
    assert not gate.LICENCE_FILE.exists()
    screen.code.set("12345678")
    screen.verify(); screen.verify()
    assert len(jobs) == 1
    gate.verify_registration.assert_not_called()
    finish()
    assert gate.load_saved_licence_key() == "TEST-BETA-KEY"
    done.assert_called_once()


def test_bad_code_keeps_verification_screen_and_does_not_save_or_admit(ui):
    screen, _, done, finish = ui
    screen.code_form("a" * 64)
    screen.code.set("12345678")
    gate.verify_registration.side_effect = api.LicensingError("INVALID_CODE")
    screen.verify(); finish()
    assert "incorrect" in screen.status.get()
    assert not gate.LICENCE_FILE.exists()
    assert screen.primary.cget("state") == "normal"
    done.assert_not_called()


def test_manual_activation_remains_available_and_async(ui):
    screen, jobs, done, finish = ui
    screen.manual_form()
    screen.key.set("TEST-MANUAL-KEY")
    screen.primary.invoke()
    assert len(jobs) == 1
    gate.activate.assert_not_called()
    finish()
    gate.activate.assert_called_once_with("TEST-MANUAL-KEY")
    assert gate.load_saved_licence_key() == "TEST-MANUAL-KEY"
    done.assert_called_once()


def test_recovery_requires_explicit_confirmation(ui):
    screen, jobs, _, _ = ui
    screen.email_form("transfer")
    screen.email.set("owner@example.com")
    gate.messagebox.askyesno.return_value = False
    screen.send_code()
    assert not jobs
    gate.start_registration.assert_not_called()


def test_saved_activation_is_async_and_keeps_key_on_unavailable(ui):
    screen, jobs, done, finish = ui
    gate.save_licence_key("EXISTING-KEY")
    before = gate.LICENCE_FILE.read_bytes()
    gate.activate.side_effect = api.LicensingUnavailable("LICENSING_UNAVAILABLE")
    screen.run(lambda: screen.activate_and_save("EXISTING-KEY"), screen.finished, "Checking...")
    assert len(jobs) == 1
    screen.close()
    assert screen.root.winfo_exists()
    finish()
    assert "temporarily unavailable" in screen.status.get()
    assert gate.LICENCE_FILE.read_bytes() == before
    done.assert_not_called()


def test_save_failure_never_grants_access_or_erases_existing_key(ui, monkeypatch):
    screen, _, done, finish = ui
    gate.save_licence_key("EXISTING-KEY")
    monkeypatch.setattr(gate.os, "replace", Mock(side_effect=PermissionError()))
    screen.code_form("a" * 64)
    screen.code.set("12345678")
    screen.verify(); finish()
    assert "could not be saved" in screen.status.get()
    assert gate.load_saved_licence_key() == "EXISTING-KEY"
    done.assert_not_called()


def test_link_flow_sends_existing_key_for_verified_association(ui):
    screen, _, _, finish = ui
    screen.link_key = "TEST-MANUAL-KEY"
    screen.email_form("link")
    screen.email.set("owner@example.com")
    screen.send_code(); finish()
    screen.code.set("12345678")
    screen.verify(); finish()
    gate.start_registration.assert_called_once_with("owner@example.com", "link", "TEST-MANUAL-KEY")
    gate.verify_registration.assert_called_once_with("a" * 64, "12345678", "TEST-MANUAL-KEY")


def test_corrupt_saved_file_falls_back_to_registration(ui):
    gate.LICENCE_FILE.write_text("[]")
    assert gate.load_saved_licence_key() == ""
