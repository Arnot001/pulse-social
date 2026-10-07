"""X posting regression tests. All publishing/browser actions are simulated."""
import json
import threading
from contextlib import nullcontext
from dataclasses import asdict
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from platforms.x import auto_post as posting


@pytest.fixture(autouse=True)
def isolated_queue(monkeypatch, tmp_path):
    monkeypatch.setattr(posting, 'QUEUE_FILE', tmp_path / 'queue.json')
    monkeypatch.setattr(posting, 'HISTORY_FILE', tmp_path / 'history.txt')
    monkeypatch.setattr(posting, '_POSTING_TARGET_ID', None)


class OneSweep:
    def __init__(self):
        self.waits = 0
        self.stopped = False

    def wait(self, seconds):
        self.waits += 1
        return self.waits > 1 or self.stopped

    def is_set(self):
        return self.stopped


def due(text='hello'):
    return posting.add_post(text, datetime.now() - timedelta(minutes=1))


def test_persisted_success_is_available_before_notification(monkeypatch):
    item = due()
    monkeypatch.setattr(posting, 'publish_post', Mock())
    snapshots = []
    posting.run_scheduler(OneSweep(), lambda msg: snapshots.append((msg, posting.load_queue())))
    success = next(items for msg, items in snapshots if msg == 'POSTED successfully.')
    assert success[0].post_id == item.post_id
    assert success[0].status == 'posted' and success[0].posted_at
    assert posting.load_queue() == success
    assert posting.HISTORY_FILE.read_text().count('| POSTED |') == 1


def test_duplicate_records_reload_once_and_never_repost_success(monkeypatch):
    item = due()
    record = asdict(item)
    posting.QUEUE_FILE.write_text(json.dumps([record, dict(record, status='posted'), record]))
    publish = Mock()
    monkeypatch.setattr(posting, 'publish_post', publish)
    posting.run_scheduler(OneSweep(), lambda msg: None)
    assert len(posting.load_queue()) == 1
    assert posting.load_queue()[0].status == 'posted'
    publish.assert_not_called()


def test_fast_additions_have_distinct_ids(monkeypatch):
    monkeypatch.setattr(posting.time, 'time', lambda: 123.0)
    first, second = due('same'), due('same')
    assert first.post_id != second.post_id
    assert len(posting.load_queue()) == 2


def test_changes_during_publish_are_preserved_and_removed_due_post_is_skipped(monkeypatch):
    first, second = due('first'), due('remove me')
    def publish(text, *_args, **_kwargs):
        posting.remove_post(second.post_id)
        posting.add_post('added during publish', datetime.now() + timedelta(days=1))
    mock = Mock(side_effect=publish)
    monkeypatch.setattr(posting, 'publish_post', mock)
    posting.run_scheduler(OneSweep(), lambda msg: None)
    assert [(x.text, x.status) for x in posting.load_queue()] == [
        ('first', 'posted'), ('added during publish', 'queued')]
    assert mock.call_count == 1


def test_stop_between_due_posts_and_future_scheduling_are_preserved(monkeypatch):
    due('first'); due('second')
    posting.add_post('future', datetime.now() + timedelta(days=1))
    event = OneSweep()
    def publish(*args, **kwargs):
        event.stopped = True
    monkeypatch.setattr(posting, 'publish_post', publish)
    posting.run_scheduler(event, lambda msg: None)
    assert [x.status for x in posting.load_queue()] == ['posted', 'queued', 'queued']


def test_two_schedulers_cannot_publish_same_snapshot(monkeypatch):
    due('first'); due('second')
    entered, release = threading.Event(), threading.Event()
    calls, failures = [], []
    def publish(text, *args, **kwargs):
        calls.append(text)
        entered.set()
        assert release.wait(5)
    monkeypatch.setattr(posting, 'publish_post', publish)
    def run():
        try:
            posting.run_scheduler(OneSweep(), lambda msg: None)
        except Exception as exc:
            failures.append(exc)
    a, b = threading.Thread(target=run), threading.Thread(target=run)
    a.start()
    assert entered.wait(5)
    b.start()
    release.set()
    a.join(5); b.join(5)
    assert not a.is_alive() and not b.is_alive() and not failures
    assert calls == ['first', 'second']


def test_history_failure_keeps_success_and_post_failure_keeps_error(monkeypatch, tmp_path):
    due('success')
    monkeypatch.setattr(posting, 'HISTORY_FILE', tmp_path)  # cannot append to a directory
    monkeypatch.setattr(posting, 'publish_post', Mock())
    messages = []
    posting.run_scheduler(OneSweep(), messages.append)
    assert posting.load_queue()[0].status == 'posted'
    assert any(msg.startswith('HISTORY WARNING') for msg in messages)
    due('failure')
    monkeypatch.setattr(posting, 'publish_post', Mock(side_effect=RuntimeError('upload failed')))
    posting.run_scheduler(OneSweep(), messages.append)
    assert [x.status for x in posting.load_queue()] == ['posted', 'error']


class Page:
    def __init__(self, target):
        self.target = target
        self.url = 'about:blank'
        self.name = ''
        self.closed = False
        self.posts = []
        self.editor = Mock()
        self.editor.first = self.editor
        self.button = Mock()
        self.button.first = self.button
        self.button.count.return_value = 1
        self.button.is_disabled.return_value = False
        self.button.click.side_effect = lambda **kwargs: self.posts.append(self.draft)
        self.keyboard = SimpleNamespace(insert_text=self.insert_text)
        self.draft = ''

    def insert_text(self, text):
        self.draft += text

    def is_closed(self):
        return self.closed

    def evaluate(self, script, arg=None):
        if arg is not None:
            self.name = arg
        return self.name

    def goto(self, url, **kwargs):
        if self.url == 'about:blank':
            self.name = ''  # Chromium clears pre-navigation window.name.
        self.url, self.draft = url, ''

    def locator(self, selector):
        return self.editor if 'tweetTextarea' in selector else self.button

    def wait_for_timeout(self, delay):
        pass


class Context:
    def __init__(self):
        self.pages = []
        self.created = 0

    def new_page(self):
        self.created += 1
        page = Page(str(self.created))
        self.pages.append(page)
        return page

    def new_cdp_session(self, page):
        return SimpleNamespace(send=lambda command: {'targetInfo': {'targetId': page.target}}, detach=lambda: None)


@pytest.fixture
def fake_browser(monkeypatch):
    context = Context()
    monkeypatch.setattr(posting, 'sync_playwright', lambda: nullcontext(object()))
    monkeypatch.setattr(posting, '_connect_x_browser', lambda p: (None, context, None, 'Pulse'))
    monkeypatch.setattr(posting, '_dismiss_x_overlays', lambda page: None)
    return context


def test_manual_posts_reuse_one_tab_across_connections_and_navigation(fake_browser):
    posting.publish_post('one')
    page = fake_browser.pages[0]
    assert page.name == posting.POSTING_PAGE_NAME
    page.name = ''  # target ID must survive a lost JS marker too
    posting.publish_post('two')
    assert fake_browser.created == 1 and page.posts == ['one', 'two']
    posting._POSTING_TARGET_ID = None  # reopened module/window can recover the marker
    posting.publish_post('three')
    assert fake_browser.created == 1 and page.posts == ['one', 'two', 'three']


def test_closed_posting_tab_is_recreated_once(fake_browser):
    posting.publish_post('one')
    fake_browser.pages[0].closed = True
    posting.publish_post('two')
    posting.publish_post('three')
    assert fake_browser.created == 2
    assert fake_browser.pages[1].posts == ['two', 'three']


def test_due_batch_reuses_same_tab_sequentially(fake_browser):
    for text in ('one', 'two', 'three'):
        due(text)
    posting.run_scheduler(OneSweep(), lambda msg: None)
    assert fake_browser.created == 1
    assert fake_browser.pages[0].posts == ['one', 'two', 'three']
    assert all(item.status == 'posted' for item in posting.load_queue())


def test_publish_lock_prevents_overlapping_composers(fake_browser, monkeypatch):
    original = posting._get_or_create_posting_page
    entered, release = threading.Event(), threading.Event()
    failures = []
    def acquire(context):
        assert posting.X_ACTION_LOCK.locked()
        entered.set()
        assert release.wait(5)
        return original(context)
    monkeypatch.setattr(posting, '_get_or_create_posting_page', acquire)
    def publish(text):
        try:
            posting.publish_post(text)
        except Exception as exc:
            failures.append(exc)
    a, b = threading.Thread(target=publish, args=('one',)), threading.Thread(target=publish, args=('two',))
    a.start(); assert entered.wait(5)
    b.start(); release.set()
    a.join(5); b.join(5)
    assert not failures and not a.is_alive() and not b.is_alive()
    assert fake_browser.created == 1 and fake_browser.pages[0].posts == ['one', 'two']


def test_connect_only_uses_verified_pulse_endpoint(monkeypatch):
    browser = SimpleNamespace(contexts=[Context()])
    attach = Mock(return_value=browser)
    playwright = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=attach))
    monkeypatch.setattr(posting.browser_control, 'cdp_responding', lambda: True)
    launch = Mock()
    monkeypatch.setattr(posting.browser_control, 'connect_browser', launch)
    verify = Mock()
    monkeypatch.setattr(posting, '_verify_pulse_profile', verify)
    assert posting._connect_x_browser(playwright)[0] is browser
    attach.assert_called_once_with(posting.browser_control.CDP_URL, timeout=3500)
    verify.assert_called_once_with(browser)
    launch.assert_not_called()
    assert browser.contexts[0].created == 0  # no extra Home tab while attaching


@pytest.mark.parametrize('profile_kind', ['pulse', 'normal', 'unknown'])
@pytest.mark.parametrize('quoting', ['whole', 'value'])
def test_cdp_process_must_use_dedicated_profile(monkeypatch, tmp_path, profile_kind, quoting):
    root = tmp_path / 'Pulse Social' / 'BrowserProfiles'
    monkeypatch.setattr(posting.browser_control, 'BROWSER_PROFILE_ROOT', root)
    profile = root / 'brave' if profile_kind == 'pulse' else tmp_path / 'normal' / 'User Data'
    arg = f'"--user-data-dir={profile}"' if quoting == 'whole' else f'--user-data-dir="{profile}"'
    command = f'"C:\\Brave\\brave.exe" {arg} --remote-debugging-port=9222' if profile_kind != 'unknown' else ''
    session = Mock()
    session.send.return_value = {'processInfo': [{'type': 'browser', 'id': 123}]}
    browser = SimpleNamespace(new_browser_cdp_session=lambda: session)
    monkeypatch.setattr(posting.subprocess, 'run', Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(command))))
    if profile_kind == 'pulse':
        posting._verify_pulse_profile(browser)
    else:
        with pytest.raises(RuntimeError, match='dedicated Pulse Browser'):
            posting._verify_pulse_profile(browser)
    session.detach.assert_called_once()


def test_missing_cdp_uses_shared_launcher_and_bundled_pdh(monkeypatch, tmp_path):
    control = posting.browser_control
    executable = tmp_path / 'Pulse Social.exe'
    extension = tmp_path / 'pdh_extension'
    extension.mkdir()
    (extension / 'manifest.json').write_text('{}')
    monkeypatch.setattr(control.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(control.sys, 'executable', str(executable))
    monkeypatch.setattr(control, 'BROWSER_PROFILE_ROOT', tmp_path / 'profiles')
    monkeypatch.setattr(control, 'STATE_FILE', tmp_path / 'browser.json')
    monkeypatch.setattr(control, 'choose_browser_name', lambda preferred=None: 'Brave')
    monkeypatch.setattr(control, '_installed_exe', lambda spec: tmp_path / spec.image)
    responding = iter([False, False, True])
    monkeypatch.setattr(control, 'cdp_responding', lambda: next(responding))
    launch = Mock()
    monkeypatch.setattr(control.subprocess, 'Popen', launch)
    monkeypatch.setattr(posting, '_verify_pulse_profile', lambda browser: None)
    browser = SimpleNamespace(contexts=[Context()])
    playwright = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=Mock(return_value=browser)))
    assert posting._connect_x_browser(playwright)[0] is browser
    args = launch.call_args.args[0]
    assert f'--user-data-dir={tmp_path / "profiles" / "brave"}' in args
    assert f'--load-extension={extension.resolve()}' in args
    assert '--remote-debugging-port=9222' in args
    assert 'https://x.com/home' not in args  # posting creates the sole composer tab


def test_unverified_browser_is_rejected_before_any_tab_is_used(monkeypatch):
    context = Context()
    browser = SimpleNamespace(contexts=[context])
    playwright = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=Mock(return_value=browser)))
    monkeypatch.setattr(posting.browser_control, 'cdp_responding', lambda: True)
    monkeypatch.setattr(posting, '_verify_pulse_profile', Mock(side_effect=RuntimeError('wrong profile')))
    with pytest.raises(RuntimeError, match='wrong profile'):
        posting._connect_x_browser(playwright)
    assert not context.pages


def test_other_pulse_tabs_are_left_alone(fake_browser):
    other = fake_browser.new_page()
    other.url = 'https://x.com/some-profile'
    posting.publish_post('one')
    posting.publish_post('two')
    assert fake_browser.created == 2
    assert other.url == 'https://x.com/some-profile' and not other.posts
