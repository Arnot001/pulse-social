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
