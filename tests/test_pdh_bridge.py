import json
import io
from collections import deque

import platforms.pdh_bridge as bridge


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_pdh_request_sends_authenticated_local_command(monkeypatch):
    captured = {}

    monkeypatch.setattr(bridge, "ensure_bridge_server", lambda: True)
    monkeypatch.setattr(bridge, "_token", lambda: "test-token")

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeResponse(
            {
                "successful": True,
                "verified": True,
                "status": "READY",
                "version": "0.11.test",
            }
        )

    monkeypatch.setattr(bridge.urllib.request, "urlopen", fake_urlopen)

    result = bridge.pdh_request("pdh.ping", {}, timeout=4.0)

    assert result["status"] == "READY"
    assert captured["url"].endswith("/command")
    assert captured["headers"]["X-pulse-token"] == "test-token"
    assert captured["body"]["operation"] == "pdh.ping"
    assert captured["body"]["requestId"].startswith("pulse-social-")
    assert captured["body"]["_timeoutSeconds"] == 39.0
    assert captured["timeout"] == 41.0


def test_pdh_connected_uses_bridge_heartbeat(monkeypatch):
    monkeypatch.setattr(
        bridge,
        "bridge_status",
        lambda: {"running": True, "pdhConnected": True},
    )
    assert bridge.pdh_connected() is True


def test_heartbeat_survives_alarm_gap_then_expires(monkeypatch):
    handler = object.__new__(bridge._Handler)
    handler.path = "/status"
    replies = []
    handler._send = lambda code, payload: replies.append(payload)
    monkeypatch.setattr(bridge, "_pdh_last_seen", 100.0)
    monkeypatch.setattr(bridge.time, "time", lambda: 140.0)
    handler.do_GET()
    assert replies[-1]["pdhConnected"] is True
    monkeypatch.setattr(bridge.time, "time", lambda: 180.0)
    handler.do_GET()
    assert replies[-1]["pdhConnected"] is False


def test_expired_queued_command_is_not_executed_on_later_wake(monkeypatch):
    handler = object.__new__(bridge._Handler)
    handler.path = "/command"
    body = json.dumps({"requestId": "expired", "operation": "tiktok.delete_item", "_timeoutSeconds": 1}).encode()
    handler.headers = {"Content-Length": str(len(body)), "X-Pulse-Token": "test"}
    handler.rfile = io.BytesIO(body)
    replies = []
    handler._send = lambda code, payload: replies.append((code, payload))
    monkeypatch.setattr(bridge, "_token", lambda: "test")
    monkeypatch.setattr(bridge, "_commands", deque())
    monkeypatch.setattr(bridge, "_results", {})
    # Advance past the deadline without a wall-clock wait.
    clock = iter([100.0, 102.0])
    monkeypatch.setattr(bridge.time, "time", lambda: next(clock))
    handler.do_POST()
    assert replies[-1][0] == 504
    assert not bridge._commands
