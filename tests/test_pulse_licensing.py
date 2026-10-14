"""Offline licensing contract tests: no real registry, account or network access."""

import hashlib
import io
import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest

import pulse_licensing as licensing


@pytest.fixture(autouse=True)
def isolated_client(monkeypatch):
    monkeypatch.setattr(licensing, "windows_device_id", Mock(return_value="hashed-test-device"))
    transport = Mock(side_effect=AssertionError("Unexpected network access"))
    monkeypatch.setattr(licensing.urllib.request, "urlopen", transport)
    return transport


def reply(transport, payload):
    transport.side_effect = None
    transport.return_value = io.BytesIO(json.dumps(payload).encode("utf-8"))


@pytest.mark.parametrize("reused", [False, True])
def test_activate_sends_explicit_user_agent_and_only_hashed_device(isolated_client, reused):
    reply(isolated_client, {"ok": True, "status": "ACTIVE", "licence_id": "test-licence",
                            "activation_id": "test-activation", "reused": reused})
    result = licensing.activate("  TEST-KEY  ")
    assert result == licensing.ActivationResult("ACTIVE", "test-licence", "test-activation", reused)
    request = isolated_client.call_args.args[0]
    assert request.full_url == licensing.API_BASE + "/activate"
    assert request.get_method() == "POST"
    assert request.get_header("User-agent") == "Pulse-Social/1.0 Windows"
    assert request.get_header("Content-type") == "application/json"
    assert request.get_header("Accept") == "application/json"
    assert json.loads(request.data) == {"licence_key": "TEST-KEY", "product": "pulse_social",
                                        "device_id": "hashed-test-device"}
    assert isolated_client.call_args.kwargs == {"timeout": 10}
    licensing.windows_device_id.assert_called_once_with()


def test_deactivate_uses_same_transport_and_returns_transfer_readiness(isolated_client):
    payload = {"ok": True, "status": "DEACTIVATED", "transfer_ready": True}
    reply(isolated_client, payload)
    assert licensing.deactivate("TEST-KEY") == payload
    request = isolated_client.call_args.args[0]
    assert request.full_url == licensing.API_BASE + "/deactivate"
    assert request.get_header("User-agent") == "Pulse-Social/1.0 Windows"
    assert json.loads(request.data)["device_id"] == "hashed-test-device"


def test_explicit_test_device_does_not_read_windows_identity(isolated_client):
    reply(isolated_client, {"ok": True, "status": "DEACTIVATED", "transfer_ready": True})
    licensing.deactivate("TEST-KEY", device_id="fake-second-device")
    assert json.loads(isolated_client.call_args.args[0].data)["device_id"] == "fake-second-device"
    licensing.windows_device_id.assert_not_called()


@pytest.mark.parametrize("key", [None, "", "   "])
def test_missing_key_stops_before_device_lookup_or_network(isolated_client, key):
    with pytest.raises(licensing.LicensingError) as raised:
        licensing.activate(key)
    assert raised.value.code == "LICENCE_KEY_REQUIRED"
    licensing.windows_device_id.assert_not_called()
    isolated_client.assert_not_called()


def test_active_elsewhere_retains_server_code_and_http_status(isolated_client):
    isolated_client.side_effect = HTTPError(licensing.API_BASE, 409, "Conflict", {},
                                           io.BytesIO(b'{"ok":false,"error":"LICENCE_ALREADY_ACTIVE"}'))
    with pytest.raises(licensing.LicensingError) as raised:
        licensing.activate("TEST-KEY", device_id="fake-second-device")
    assert raised.value.code == "LICENCE_ALREADY_ACTIVE"
    assert raised.value.status == 409
    assert not isinstance(raised.value, licensing.LicensingUnavailable)


def test_non_json_cloudflare_error_keeps_http_code_without_leaking_body(isolated_client):
    isolated_client.side_effect = HTTPError(licensing.API_BASE, 403, "Forbidden", {},
                                           io.BytesIO(b"error code: 1010; private response details"))
    with pytest.raises(licensing.LicensingError) as raised:
        licensing.activate("TEST-KEY")
    assert raised.value.code == "HTTP_403"
    assert raised.value.status == 403
    assert str(raised.value) == "HTTP_403"


@pytest.mark.parametrize("error", [URLError("unreachable"), TimeoutError("timeout"), OSError("offline")])
def test_transport_errors_are_unavailable_without_retry_or_activation(isolated_client, error):
    isolated_client.side_effect = error
    with pytest.raises(licensing.LicensingUnavailable) as raised:
        licensing.activate("TEST-KEY")
    assert raised.value.code == "LICENSING_UNAVAILABLE"
    isolated_client.assert_called_once()


def test_invalid_json_is_service_unavailable(isolated_client):
    isolated_client.side_effect = None
    isolated_client.return_value = io.BytesIO(b"not json")
    with pytest.raises(licensing.LicensingUnavailable) as raised:
        licensing.activate("TEST-KEY")
    assert raised.value.code == "INVALID_SERVER_RESPONSE"


@pytest.mark.parametrize("payload,code", [({"ok": False, "error": "LICENCE_NOT_FOUND"}, "LICENCE_NOT_FOUND"),
                                          ({"ok": False}, "LICENSING_ERROR")])
def test_unsuccessful_json_never_returns_active(isolated_client, payload, code):
    reply(isolated_client, payload)
    with pytest.raises(licensing.LicensingError) as raised:
        licensing.activate("TEST-KEY")
    assert raised.value.code == code


# Keep the real function available despite the autouse transport/device isolation.
real_windows_device_id = licensing.windows_device_id


@pytest.mark.parametrize("guid", ["  ABCD-1234  ", "abcd-1234"])
def test_windows_identity_is_normalized_and_domain_separated(monkeypatch, guid):
    key = object()
    registry = SimpleNamespace(HKEY_LOCAL_MACHINE=object(), OpenKey=Mock(return_value=nullcontext(key)),
                               QueryValueEx=Mock(return_value=(guid, 1)))
    monkeypatch.setattr(licensing, "winreg", registry)
    result = real_windows_device_id()
    assert result == hashlib.sha256(b"pulse-device-v1:abcd-1234").hexdigest()
    assert len(result) == 64
    registry.OpenKey.assert_called_once_with(registry.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography")
    registry.QueryValueEx.assert_called_once_with(key, "MachineGuid")


@pytest.mark.parametrize("problem", ["no_registry", "read_error", "empty"])
def test_missing_windows_identity_fails_closed(monkeypatch, problem):
    registry = SimpleNamespace(HKEY_LOCAL_MACHINE=object(), OpenKey=Mock(return_value=nullcontext(object())),
                               QueryValueEx=Mock(return_value=("   ", 1)))
    if problem == "read_error":
        registry.OpenKey.side_effect = OSError("registry unavailable")
    monkeypatch.setattr(licensing, "winreg", None if problem == "no_registry" else registry)
    with pytest.raises(licensing.LicensingError) as raised:
        real_windows_device_id()
    assert raised.value.code == "DEVICE_ID_UNAVAILABLE"


def test_device_failure_cannot_send_request_or_fall_back_to_fake_identity(isolated_client):
    licensing.windows_device_id.side_effect = licensing.LicensingError("DEVICE_ID_UNAVAILABLE")
    with pytest.raises(licensing.LicensingError) as raised:
        licensing.activate("TEST-KEY")
    assert raised.value.code == "DEVICE_ID_UNAVAILABLE"
    isolated_client.assert_not_called()
