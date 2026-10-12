from platforms.tiktok import browser_session


def test_open_tiktok_browser_launches_pulse_browser_when_cdp_is_missing(monkeypatch):
    calls = []

    monkeypatch.setattr(browser_session, "_port_open", lambda: False)
    monkeypatch.setattr(
        browser_session,
        "connect_browser",
        lambda **kwargs: (calls.append(kwargs) or (False, "launch failed")),
    )

    ok, message = browser_session.open_tiktok_browser()

    assert ok is False
    assert message == "launch failed"
    assert calls == [{"start_url": browser_session.TIKTOK_URL}]


def test_open_tiktok_browser_continues_after_successful_pulse_browser_launch(monkeypatch):
    calls = []

    monkeypatch.setattr(browser_session, "_port_open", lambda: False)
    monkeypatch.setattr(
        browser_session,
        "connect_browser",
        lambda **kwargs: (calls.append(kwargs) or (True, "connected")),
    )

    class FakePage:
        url = "https://www.tiktok.com/"

        def bring_to_front(self):
            return None

    class FakeContext:
        pages = [FakePage()]

    class FakeBrowser:
        contexts = [FakeContext()]

    class FakeChromium:
        def connect_over_cdp(self, *_args, **_kwargs):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeManager:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(browser_session, "sync_playwright", lambda: FakeManager())

    ok, message = browser_session.open_tiktok_browser()

    assert ok is True
    assert message == "CONNECTED // EXISTING TIKTOK TAB"
    assert calls == [{"start_url": browser_session.TIKTOK_URL}]


# These tests use isolated fake browser contexts and never connect to CDP.
def shop_browser(monkeypatch, urls):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from unittest.mock import Mock
    pages = [Mock(url=url) for url in urls]
    context = Mock(pages=pages)
    created = Mock()
    def new_page():
        context.pages.append(created)
        return created
    context.new_page.side_effect = new_page
    created.goto.side_effect = lambda url, **kwargs: setattr(created, "url", url)
    browser = Mock(contexts=[context])
    chromium = Mock()
    chromium.connect_over_cdp.return_value = browser
    monkeypatch.setattr(browser_session, "sync_playwright", lambda: nullcontext(SimpleNamespace(chromium=chromium)))
    monkeypatch.setattr(browser_session, "_port_open", lambda: True)
    connect = Mock(return_value=(True, "ready"))
    monkeypatch.setattr(browser_session, "connect_browser", connect)
    return pages, context, created, browser, connect


def test_shop_focuses_existing_category_without_navigating_or_touching_other_tabs(monkeypatch):
    pages, context, _, browser, connect = shop_browser(monkeypatch, [
        "https://www.tiktok.com/", "https://x.com/home", "https://shop.tiktok.com/gb/c/phones/123"])
    assert browser_session.open_tiktok_browser(shop=True) == (True, "CONNECTED // EXISTING TIKTOK SHOP TAB")
    pages[2].bring_to_front.assert_called_once()
    for page in pages:
        page.goto.assert_not_called()
    pages[0].bring_to_front.assert_not_called()
    pages[1].bring_to_front.assert_not_called()
    context.new_page.assert_not_called()
    connect.assert_not_called()
    browser.close.assert_not_called()


def test_shop_creates_then_reuses_tab_ignoring_lookalike_hosts(monkeypatch):
    pages, context, created, browser, _ = shop_browser(monkeypatch, [
        "https://www.tiktok.com/", "https://shop.tiktok.com.example.org/", "https://example.org/shop.tiktok.com"])
    assert browser_session.open_tiktok_browser(shop=True)[0]
    created.goto.assert_called_once_with(browser_session.TIKTOK_SHOP_URL, wait_until="domcontentloaded", timeout=30000)
    assert browser_session.open_tiktok_browser(shop=True)[0]
    context.new_page.assert_called_once()
    assert created.bring_to_front.call_count == 2
    browser.close.assert_not_called()


def test_shop_starts_shared_adaptive_browser_at_shop_url(monkeypatch):
    _, context, created, _, connect = shop_browser(monkeypatch, [])
    monkeypatch.setattr(browser_session, "_port_open", lambda: False)
    assert browser_session.open_tiktok_browser(shop=True)[0]
    connect.assert_called_once_with(start_url=browser_session.TIKTOK_SHOP_URL)
    context.new_page.assert_called_once()
    created.bring_to_front.assert_called_once()


def test_shop_launch_failure_is_reported_without_attaching(monkeypatch):
    from unittest.mock import Mock
    monkeypatch.setattr(browser_session, "_port_open", lambda: False)
    monkeypatch.setattr(browser_session, "connect_browser", Mock(return_value=(False, "launch failed")))
    playwright = Mock()
    monkeypatch.setattr(browser_session, "sync_playwright", playwright)
    assert browser_session.open_tiktok_browser(shop=True) == (False, "launch failed")
    playwright.assert_not_called()
