import io
import json
from collections import deque

import pytest

from commerce.store import CommerceStore
from commerce.tiktok import category_collector as collector
from platforms import pdh_bridge as bridge

URL = "https://shop.tiktok.com/gb/c/phones-electronics/123"


def products(count=25):
    return [{"product_id": str(i + 1), "title": f"Phone {i + 1}", "price": 12.50} for i in range(count)]


def reply(count=25, complete=True, reason="END_OF_LIST"):
    return {"products": products(count), "complete": complete, "stopReason": reason, "clicks": 2, "durationMs": 3500}


def test_browser_owned_collection_ingests_all_unique_products(tmp_path, monkeypatch):
    response = reply()
    response["products"].append(response["products"][0])
    calls = []
    monkeypatch.setattr(collector, "pdh_request", lambda *a, **kw: calls.append((a, kw)) or response)
    monkeypatch.setattr(collector, "fetch_category_page", lambda *a: pytest.fail("HTTP fallback forbidden"))
    store = CommerceStore(tmp_path / "commerce.db")
    result = collector.collect_category(URL, store)
    assert len(result) == result.product_count == 25
    assert result.complete is True
    assert result.clicks == 2
    assert all(item["status"] == "recorded" for item in result)
    assert len(store.price_history("tiktok_shop", "1")) == 1
    assert calls == [(("tiktok.shop_category", {"url": URL}), {"timeout": 50.0})]
    assert collector.category_summary(result).startswith("COMPLETE // 25 COLLECTED // 25 RECORDED")


@pytest.mark.parametrize("reason", ["TIMEOUT", "CLICK_LIMIT", "NO_GROWTH", "BUTTON_DISABLED", "NAVIGATION", "CHALLENGE", "BUTTON_AMBIGUOUS"])
def test_partial_keeps_products_and_reports_counts(tmp_path, monkeypatch, reason):
    monkeypatch.setattr(collector, "pdh_request", lambda *a, **kw: reply(10, False, reason))
    result = collector.collect_category(URL, CommerceStore(tmp_path / "commerce.db"))
    assert len(result) == result.product_count == 10
    assert result.complete is False
    assert result.stop_reason == reason
    assert collector.category_summary(result).startswith("PARTIAL // 10 COLLECTED // 10 RECORDED")


@pytest.mark.parametrize("response, reason", [(None, "BRIDGE_NO_RESPONSE"), ({"status": "INVALID_REQUEST"}, "INVALID_PDH_RESULT")])
def test_no_response_never_fetches_or_opens_database(monkeypatch, response, reason):
    monkeypatch.setattr(collector, "pdh_request", lambda *a, **kw: response)
    monkeypatch.setattr(collector, "fetch_category_page", lambda *a: pytest.fail("no HTTP fallback"))
    monkeypatch.setattr(collector, "CommerceStore", lambda: pytest.fail("no DB for empty results"))
    result = collector.collect_category(URL)
    assert not result.complete
    assert not result
    assert result.stop_reason == reason


def test_only_allowlisted_fields_reach_persistence(tmp_path, monkeypatch):
    response = reply(1)
    response["products"][0].update({"url": "https://example.invalid/?signature=synthetic", "csrf": "synthetic", "raw": {"session": "synthetic"}})
    monkeypatch.setattr(collector, "pdh_request", lambda *a, **kw: response)
    result = collector.collect_category(URL, CommerceStore(tmp_path / "commerce.db"))
    assert "synthetic" not in json.dumps(result)
    assert result[0]["url"] == "https://shop.tiktok.com/gb/pdp/1"


@pytest.mark.parametrize("bad", [None, {"product_id": "bad"}, {"product_id": "2", "title": "Missing price"}, {"product_id": "2", "title": "NaN", "price": float("nan")}])
def test_dropped_or_incomplete_product_reports_data_quality_without_overriding_end_of_list(monkeypatch, bad):
    response = reply(1)
    response["products"].append(bad)
    monkeypatch.setattr(collector, "pdh_request", lambda *a, **kw: response)
    result = collector.request_category(URL)
    assert result["complete"] is True
    assert result["stopReason"] == "END_OF_LIST"
    assert result["dataComplete"] is False
    assert result["products"][0]["product_id"] == "1"


def test_ingestion_skip_does_not_rewrite_verified_pagination_completion(monkeypatch):
    monkeypatch.setattr(collector, "pdh_request", lambda *a, **kw: reply(2))
    monkeypatch.setattr(
        collector,
        "ingest_products",
        lambda products, store: [
            {"status": "recorded"},
            {"status": "skipped"},
        ],
    )

    result = collector.collect_category(URL, object())

    assert result.complete is True
    assert result.stop_reason == "END_OF_LIST"
    assert result.ingestion_complete is False
    assert result.skipped_product_count == 1


def test_duplicate_with_missing_details_does_not_erase_observed_values(monkeypatch):
    response = reply(1)
    response["products"].append({"product_id": "1"})
    monkeypatch.setattr(collector, "pdh_request", lambda *a, **kw: response)
    assert collector.request_category(URL)["products"][0]["price"] == 12.5


def test_read_only_cli_collects_once_prints_metadata_and_never_ingests(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(collector, "pdh_request", lambda *a, **kw: calls.append((a, kw)) or reply())
    monkeypatch.setattr(collector, "ingest_products", lambda *a: pytest.fail("read-only must not ingest"))
    monkeypatch.setattr("sys.argv", ["category_collector", "--read-only"])
    collector.main()
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "complete": True,
        "stopReason": "END_OF_LIST",
        "dataComplete": True,
        "incompleteProductCount": 0,
        "rejectedProductCount": 0,
        "productCount": 25,
        "clicks": 2,
        "durationMs": 3500,
        "browserStage": "",
        "browserError": "",
    }
    assert len(calls) == 1
    assert calls[0][0][1] == {}


@pytest.mark.parametrize("url", [URL + "?signature=synthetic", URL + "#fragment", "http://shop.tiktok.com/gb/c/phones/123", "https://example.invalid/gb/c/phones/123"])
def test_rejects_nonplain_category_url_before_bridge(monkeypatch, url):
    monkeypatch.setattr(collector, "pdh_request", lambda *a, **kw: pytest.fail("must reject before sending"))
    with pytest.raises(ValueError):
        collector.request_category(url)


@pytest.mark.parametrize("operation, expected", [("tiktok.shop_category", 85.0), ("tiktok.inventory", 60.0), ("tiktok.delete_item", 60.0), ("pdh.ping", 60.0)])
def test_client_timeout_allows_shop_work_and_wake_without_changing_other_operations(monkeypatch, operation, expected):
    monkeypatch.setattr(bridge, "ensure_bridge_server", lambda: True)
    monkeypatch.setattr(bridge, "_token", lambda: "test")
    captured = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return b'{"complete":false,"products":[]}'

    def send(request, timeout):
        captured.update(body=json.loads(request.data), timeout=timeout)
        return Response()

    monkeypatch.setattr(bridge.urllib.request, "urlopen", send)
    bridge.pdh_request(operation, {}, timeout=50.0)
    assert captured["body"]["_timeoutSeconds"] == expected
    assert captured["timeout"] == expected + 2


@pytest.mark.parametrize("operation, expected", [("tiktok.shop_category", 90.0), ("tiktok.inventory", 60.0)])
def test_server_timeout_cap_is_shop_specific(monkeypatch, operation, expected):
    now = [100.0]
    waits = []

    class Lock:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def notify_all(self): pass
        def wait(self, timeout):
            waits.append(timeout)
            now[0] += timeout

    monkeypatch.setattr(bridge, "_lock", Lock())
    monkeypatch.setattr(bridge, "_commands", deque())
    monkeypatch.setattr(bridge, "_results", {})
    monkeypatch.setattr(bridge, "_token", lambda: "test")
    monkeypatch.setattr(bridge.time, "time", lambda: now[0])
    handler = object.__new__(bridge._Handler)
    handler.path = "/command"
    body = json.dumps({"requestId": "test", "operation": operation, "_timeoutSeconds": 999}).encode()
    handler.headers = {"Content-Length": str(len(body)), "X-Pulse-Token": "test"}
    handler.rfile = io.BytesIO(body)
    replies = []
    handler._send = lambda code, payload: replies.append((code, payload))
    handler.do_POST()
    assert waits == [expected]
    assert replies[-1][0] == 504
    assert not bridge._commands


def test_shop_partial_result_claim_is_accepted_once(monkeypatch):
    monkeypatch.setattr(bridge, "_claims", {"shop-test": "test-claim"})
    monkeypatch.setattr(bridge, "_results", {})
    handler = object.__new__(bridge._Handler)
    handler.path = "/pdh/result"
    result = reply(10, False, "NO_GROWTH")
    body = json.dumps({"requestId": "shop-test", "claim": "test-claim", "result": result}).encode()
    handler.headers = {"Content-Length": str(len(body))}
    replies = []
    handler._send = lambda code, payload: replies.append((code, payload))
    handler.rfile = io.BytesIO(body)
    handler.do_POST()
    assert replies[-1][0] == 200
    assert bridge._results["shop-test"] == result
    assert "shop-test" not in bridge._claims
    handler.rfile = io.BytesIO(body)
    handler.do_POST()
    assert replies[-1][0] == 403
