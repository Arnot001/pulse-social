"""No live email, credentials, registry or licensing service in these tests."""
import io
import json
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest
import pulse_licensing as api
import pulse_license_gate as gate


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.setattr(api, "windows_device_id", lambda: "test-device-hash")
    transport = Mock(side_effect=AssertionError("No live requests"))
    monkeypatch.setattr(api.urllib.request, "urlopen", transport)
    return transport


def response(transport, data):
    transport.side_effect = None
    transport.return_value = io.BytesIO(json.dumps(data).encode())


def test_start_sends_email_and_receives_only_challenge(transport):
    response(transport, {"ok": True, "challenge_id": "a" * 64})
    assert api.start_registration(" owner@example.com ") == "a" * 64
    request = transport.call_args.args[0]
    assert request.full_url.endswith("/registration/start")
    assert json.loads(request.data) == {"email": "owner@example.com", "intent": "access", "licence_key": "",
                                        "product": "pulse_social", "device_id": "test-device-hash"}


def test_verified_activation_returns_key_without_user_copying(transport):
    response(transport, {"ok": True, "status": "ACTIVE", "licence_key": "TEST-KEY",
                         "licence_id": "test-licence", "activation_id": "test-activation"})
    assert api.verify_registration("a" * 64, " 12345678 ") == "TEST-KEY"
    assert json.loads(transport.call_args.args[0].data)["code"] == "12345678"


@pytest.mark.parametrize("data", [[], None, {"ok": True}, {"ok": True, "status": "ACTIVE"},
    {"ok": True, "status": "PENDING", "licence_key": "TEST-KEY", "licence_id": "a", "activation_id": "b"}])
def test_incomplete_verification_never_grants_access(transport, data):
    response(transport, data)
    with pytest.raises(api.LicensingUnavailable):
        api.verify_registration("a" * 64, "12345678")


def test_arbitrary_server_error_cannot_expose_credentials(transport):
    transport.side_effect = HTTPError(api.API_BASE, 503, "Unavailable", {},
        io.BytesIO(b'{"error":"PRIVATE-CUSTOMER-KEY"}'))
    with pytest.raises(api.LicensingError) as exc:
        api.start_registration("owner@example.com")
    assert str(exc.value) == "HTTP_503"
    assert "PRIVATE" not in gate._friendly_error(exc.value)


def test_registration_ui_contracts_in_isolated_tk_process():
    # Tk owns native process-global state. Keep these lifecycle checks separate
    # from the existing emoji/browser suite's independently managed interpreters.
    import subprocess
    import sys
    from pathlib import Path
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/registration_ui_checks.py", "-q"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
