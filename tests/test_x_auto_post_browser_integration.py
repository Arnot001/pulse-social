"""Offline integration against a temporary headless browser, never the user's profile."""
import os
import subprocess
import time

import pytest
from playwright.sync_api import sync_playwright

from platforms import browser_control
from platforms.x import auto_post as posting


@pytest.mark.skipif(os.name != 'nt', reason='Pulse browser process verification uses Windows CIM')
def test_real_cdp_profile_and_tab_survive_driver_reconnects(monkeypatch, tmp_path):
    executable = next((browser_control._installed_exe(spec) for spec in browser_control._browser_specs()
                       if browser_control._installed_exe(spec)), None)
    if executable is None:
        pytest.skip('No supported local Chromium installation')
    profiles = tmp_path / 'Pulse Test Profiles'
    profile = profiles / 'brave'
    profile.mkdir(parents=True)
    monkeypatch.setattr(browser_control, 'BROWSER_PROFILE_ROOT', profiles)
    monkeypatch.setattr(posting, '_POSTING_TARGET_ID', None)
    process = subprocess.Popen([
        str(executable), '--headless=new', '--remote-debugging-port=0',
        f'--user-data-dir={profile}', '--no-first-run', '--no-default-browser-check',
        '--disable-background-networking', 'about:blank',
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    endpoint = None
    try:
        port_file = profile / 'DevToolsActivePort'
        deadline = time.monotonic() + 15
        while not port_file.exists() and time.monotonic() < deadline:
            assert process.poll() is None, 'Temporary browser exited before CDP was ready'
            time.sleep(0.1)
        port, path = port_file.read_text().splitlines()[:2]
        endpoint = f'ws://127.0.0.1:{port}{path}'
        target = None
        for index in range(3):
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(endpoint)
                posting._verify_pulse_profile(browser)
                context = browser.contexts[0]
                page, created = posting._get_or_create_posting_page(context)
                assert created == (index == 0)
                current = posting._posting_target_id(context, page)
                if target is not None:
                    assert current == target
                target = current
                # Entirely local content: no connection to X or real account data.
                page.goto(f'data:text/html,<title>Local composer {index}</title>')
                page.evaluate('(name) => window.name = name', posting.POSTING_PAGE_NAME)
                assert len(context.pages) == 2  # initial blank + one posting tab
                if index == 1:
                    posting._POSTING_TARGET_ID = None  # restore from page marker
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(endpoint)
            context = browser.contexts[0]
            page, created = posting._get_or_create_posting_page(context)
            assert not created
            page.close()
            replacement, created = posting._get_or_create_posting_page(context)
            assert created and posting._posting_target_id(context, replacement) != target
            same, created = posting._get_or_create_posting_page(context)
            assert not created and same == replacement
            assert len(context.pages) == 2
    finally:
        if endpoint and process.poll() is None:
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.connect_over_cdp(endpoint)
                    browser.new_browser_cdp_session().send('Browser.close')
            except Exception:
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()  # Only the temporary test-owned browser process.
            process.wait(timeout=5)
