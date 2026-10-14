"""Keep unrelated UI tests from activating a real saved customer licence."""
import pytest
import pulse_license_gate


@pytest.fixture(autouse=True)
def offline_startup_gate(monkeypatch):
    # Tests of licensing itself patch their transport; feature UI tests only need
    # an admitted session. Never call the live licensing service during pytest.
    monkeypatch.setattr(pulse_license_gate, "require_licence", lambda: True)
