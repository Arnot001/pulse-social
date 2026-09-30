import json

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
    assert captured["body"]["_timeoutSeconds"] == 4.0


def test_pdh_connected_uses_bridge_heartbeat(monkeypatch):
    monkeypatch.setattr(
        bridge,
        "bridge_status",
        lambda: {"running": True, "pdhConnected": True},
    )
    assert bridge.pdh_connected() is True
