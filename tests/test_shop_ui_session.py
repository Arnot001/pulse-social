"""Exercise the real Tk controls with withdrawn windows and synthetic collection only."""
import tkinter as tk
from tkinter import ttk

import pytest

from commerce.store import CommerceStore
from commerce.tiktok import category_session as session
from commerce.tiktok import shop_ui as commerce_ui
from commerce.tiktok.categories import TikTokCategory
from platforms.tiktok import shop_ui as platform_ui

URL = 'https://shop.tiktok.com/gb/c/phones/123'
OTHER = 'https://shop.tiktok.com/gb/c/parts/456'


def product(pid, price=10):
    return {'product_id': str(pid), 'title': f'Product {pid}', 'price': price, 'currency': 'GBP',
            'url': f'https://shop.tiktok.com/gb/pdp/{pid}'}


def widgets(parent):
    for child in parent.winfo_children():
        yield child
        yield from widgets(child)


@pytest.fixture(scope='module')
def tk_root():
    root = tk.Tk(); root.withdraw()
    yield root
    root.destroy()


@pytest.fixture(params=['commerce', 'platform'])
def ui(request, monkeypatch, tmp_path, tk_root):
    root = tk_root
    callback_errors = []
    monkeypatch.setattr(root, 'report_callback_exception', lambda *args: callback_errors.append(args))
    jobs = []
    class Thread:
        def __init__(self, target, args=(), **kwargs): self.target, self.args = target, args
        def start(self): jobs.append(self)
    monkeypatch.setattr(commerce_ui.threading, 'Thread', Thread)
    monkeypatch.setattr(platform_ui.threading, 'Thread', Thread)
    store = CommerceStore(tmp_path / 'commerce.db')
    monkeypatch.setattr(session, 'CommerceStore', lambda: store)
    monkeypatch.setattr(platform_ui, 'CommerceStore', lambda: store)
    responses = []
    monkeypatch.setattr(session, 'request_category', lambda url: responses.pop(0))
    categories = [
        TikTokCategory('123', 'Phones', 'phones', 1, '0', True),
        TikTokCategory('456', 'Parts', 'parts', 1, '0', True)]
    monkeypatch.setattr(commerce_ui, 'fetch_categories', lambda: categories)
    monkeypatch.setattr(platform_ui, 'fetch_categories', lambda: categories)
    if request.param == 'commerce':
        window = commerce_ui.open_shop_window(root); window.withdraw()
        job = next(j for j in jobs if j.target.__name__ == 'refresh_worker')
        jobs.remove(job); job.target(); root.update()
    else:
        window = platform_ui.TikTokShopView(root)
        job = next(j for j in jobs if j.target.__name__ == '_taxonomy_worker')
        jobs.remove(job); job.target(); root.update()

    def button(text):
        return next(w for w in widgets(window) if isinstance(w, tk.Button) and w.cget('text') == text)

    def select(url):
        box = next(w for w in widgets(window) if isinstance(w, ttk.Combobox) and 'Phones' in w.cget('values'))
        box.set('Phones' if url == URL else 'Parts'); box.event_generate('<<ComboboxSelected>>'); root.update()

    def mode(value):
        box = next(w for w in widgets(window) if isinstance(w, ttk.Combobox) and 'MIXED LIST' in w.cget('values'))
        box.set(value)

    def run_job():
        job = next(j for j in jobs if j.target.__name__ in ('collect_worker', '_collect_worker'))
        jobs.remove(job); job.target(*job.args)

    def collect(url, products, reason='END_OF_LIST'):
        select(url)
        responses.append({'products': products, 'complete': reason == 'END_OF_LIST', 'stopReason': reason, 'dataComplete': True})
        button('COLLECT CATEGORY').invoke(); run_job(); root.update()

    def rows():
        tree = next(w for w in widgets(window) if isinstance(w, ttk.Treeview))
        return [tree.item(i, 'values') for i in tree.get_children()]

    class Harness: pass
    h = Harness()
    h.root, h.window, h.store, h.responses = root, window, store, responses
    h.button, h.select, h.mode, h.run_job, h.collect, h.rows = button, select, mode, run_job, collect, rows
    h.log = next(w for w in widgets(window) if isinstance(w, tk.Text))
    yield h
    if request.param == 'commerce':
        close_command = window.protocol('WM_DELETE_WINDOW')
        window.tk.call(close_command)
    else:
        window.destroy()
    assert not callback_errors


def test_both_screens_default_per_category_and_clear_before_new_request(ui):
    ui.collect(URL, [product(1)])
    assert len(ui.rows()) == 1
    ui.select(OTHER)
    ui.button('COLLECT CATEGORY').invoke()
    assert ui.rows() == []  # Immediate, before the worker has run.
    assert len(ui.store.latest_products()) == 1


def test_both_screens_mixed_mode_updates_duplicates_and_preserves_other_items(ui):
    ui.collect(URL, [product(1)])
    ui.mode('MIXED LIST')
    ui.collect(OTHER, [product(1, 8), product(2)])
    assert len(ui.rows()) == 2
    assert any('GBP 8.00' in row for row in ui.rows())
    assert len(ui.store.price_history('tiktok_shop', '1')) == 2  # Separate deliberate requests.


def test_both_screens_same_category_retry_preserves_preview_and_records_once(ui):
    ui.responses.extend([
        {'products': [product(1)], 'complete': False, 'stopReason': 'TIMEOUT'},
        {'products': [product(1, 8), product(2)], 'complete': True, 'stopReason': 'END_OF_LIST'},
    ])
    ui.button('COLLECT CATEGORY').invoke(); ui.run_job(); ui.root.update()
    assert len(ui.rows()) == 2
    assert len(ui.store.price_history('tiktok_shop', '1')) == 1
    log = ui.log.get('1.0', 'end')
    assert 'CONTINUING' in log and 'PASS 2' in log and 'COMPLETE // 2 COLLECTED // 2 RECORDED' in log


def test_both_clear_controls_are_independent_and_preserve_history(ui):
    ui.collect(URL, [product(1)])
    before = ui.store.path.read_bytes()
    ui.button('CLEAR LOG').invoke()
    assert ui.log.get('1.0', 'end').strip() == ''
    assert len(ui.rows()) == 1
    ui.log.insert('end', 'keep this message')
    ui.button('CLEAR ITEMS').invoke()
    assert ui.rows() == []
    assert ui.log.get('1.0', 'end').strip() == 'keep this message'
    assert ui.store.path.read_bytes() == before


def test_clear_during_request_prevents_queued_callbacks_restoring_items_or_logs(ui):
    ui.responses.append({'products': [product(1)], 'complete': True, 'stopReason': 'END_OF_LIST'})
    ui.button('COLLECT CATEGORY').invoke()
    ui.run_job()  # Callbacks queued but not yet applied by Tk.
    ui.button('CLEAR ITEMS').invoke(); ui.button('CLEAR LOG').invoke()
    ui.root.update()
    assert ui.rows() == []
    assert ui.log.get('1.0', 'end').strip() == ''
    assert len(ui.store.latest_products()) == 1


def test_hard_failure_keeps_partial_items_and_shows_stopped(ui):
    ui.collect(URL, [product(1, None)], 'CHALLENGE')
    assert len(ui.rows()) == 1
    assert 'STOPPED // CHALLENGE' in ui.log.get('1.0', 'end')
    assert len(ui.store.latest_products()) == 0


@pytest.fixture
def taxonomy_ui(monkeypatch, tk_root):
    root = tk_root
    jobs, outcomes, waits, calls, states, errors, events = [], [], [], [], [], [], []
    monkeypatch.setattr(root, 'report_callback_exception', lambda *args: errors.append(args))
    class Thread:
        def __init__(self, target, args=(), **kwargs): self.target, self.args = target, args
        def start(self): jobs.append(self)
    class Event:
        stopped = False
        def __init__(self): events.append(self)
        def is_set(self): return self.stopped
        def set(self): self.stopped = True
        def wait(self, seconds):
            waits.append(seconds)
            root.update()  # Process queued UI callbacks between simulated background attempts.
            assert status() == 'COLLECTING CATEGORIES...'
            assert 'FAILED' not in log.get('1.0', 'end')
            return self.stopped
    monkeypatch.setattr(commerce_ui.threading, 'Thread', Thread)
    monkeypatch.setattr(commerce_ui.threading, 'Event', Event)
    def fetch():
        calls.append(status())
        assert status() == 'COLLECTING CATEGORIES...'
        value = outcomes.pop(0)
        if isinstance(value, Exception): raise value
        return value
    monkeypatch.setattr(commerce_ui, 'fetch_categories', fetch)
    window = commerce_ui.open_shop_window(root); window.withdraw()
    label = next(w for w in widgets(window) if isinstance(w, tk.Label) and w.cget('textvariable'))
    variable = label.cget('textvariable')
    def status(): return str(root.globalgetvar(variable))
    command = root.register(lambda *args: states.append(status()))
    root.tk.call('trace', 'add', 'variable', variable, 'write', command)
    log = next(w for w in widgets(window) if isinstance(w, tk.Text))
    def button(text):
        return next(w for w in widgets(window) if isinstance(w, tk.Button) and w.cget('text') == text)
    def run():
        job = next(j for j in jobs if j.target.__name__ == 'refresh_worker')
        jobs.remove(job); job.target(); root.update()
    class Harness: pass
    h = Harness()
    h.window, h.root, h.log, h.status, h.button, h.run = window, root, log, status, button, run
    h.outcomes, h.waits, h.calls, h.states, h.jobs = outcomes, waits, calls, states, jobs
    h.cancel = events[0]
    yield h
    root.tk.call('trace', 'remove', 'variable', variable, 'write', command)
    root.deletecommand(command)
    window.tk.call(window.protocol('WM_DELETE_WINDOW'))
    assert not errors


def taxonomy(count=240):
    return [TikTokCategory(str(i + 1), f'Category {i + 1}', f'category-{i + 1}', 1, '0', True) for i in range(count)]


@pytest.mark.parametrize('transient', [[], OSError('temporary transport failure')])
def test_taxonomy_transient_attempts_stay_pending_and_log_only_success(taxonomy_ui, transient):
    ui = taxonomy_ui
    assert not ui.calls  # Startup queues background work; it does not fetch inside the Tk callback.
    assert ui.status() == 'COLLECTING CATEGORIES...'
    ui.outcomes.extend([transient, [], taxonomy()])
    ui.run()
    assert ui.calls == ['COLLECTING CATEGORIES...'] * 3
    assert ui.waits == [7, 7]
    assert ui.status() == 'CATEGORIES READY // 240 LOADED'
    assert ui.states == ['CATEGORIES READY // 240 LOADED']
    assert ui.log.get('1.0', 'end').strip().splitlines() == ['CATEGORIES READY // 240 LOADED']
    assert ui.button('COLLECT CATEGORY').cget('state') == 'normal'
    assert ui.button('REFRESH CATEGORIES').cget('state') == 'normal'


@pytest.mark.parametrize('cached', [False, True])
def test_taxonomy_exhaustion_reports_once_and_preserves_previous_list(taxonomy_ui, cached):
    ui = taxonomy_ui
    if cached:
        ui.outcomes.append(taxonomy(3)); ui.run()
        boxes = [w for w in widgets(ui.window) if isinstance(w, ttk.Combobox) and 'Category 1' in w.cget('values')]
        box = boxes[0]; box.set('Category 2'); box.event_generate('<<ComboboxSelected>>'); ui.root.update()
        before = (box.cget('values'), box.get())
        ui.button('CLEAR LOG').invoke()
        ui.button('REFRESH CATEGORIES').invoke()
        # Category selection while pending must not change the pending status.
        box.event_generate('<<ComboboxSelected>>'); ui.root.update()
        assert (box.cget('values'), box.get()) == before
    ui.states.clear()
    ui.outcomes.extend([[], OSError('temporary'), []])
    ui.run()
    assert ui.status() == 'CATEGORY LOAD FAILED'
    assert ui.states == ['CATEGORY LOAD FAILED']
    assert ui.log.get('1.0', 'end').strip().splitlines() == ['CATEGORY LOAD FAILED']
    assert ui.button('REFRESH CATEGORIES').cget('state') == 'normal'
    assert ui.button('COLLECT CATEGORY').cget('state') == ('normal' if cached else 'disabled')
    assert not ui.outcomes and ui.waits == [7, 7]
    if cached:
        assert (box.cget('values'), box.get()) == before
        ui.button('COLLECT CATEGORY').invoke()
        job = next(j for j in ui.jobs if j.target.__name__ == 'collect_worker')
        assert job.args[0].category_id == '2'


def test_taxonomy_refresh_cannot_start_overlapping_jobs(taxonomy_ui):
    ui = taxonomy_ui
    button = ui.button('REFRESH CATEGORIES')
    # Exercise the callback directly too: the flag protects against accidental reentry.
    ui.window.tk.call(button.cget('command'))
    assert len([job for job in ui.jobs if job.target.__name__ == 'refresh_worker']) == 1
    ui.outcomes.append(taxonomy(1)); ui.run()
    assert len(ui.calls) == 1 and not ui.waits


def test_taxonomy_close_signal_cancels_queued_success(taxonomy_ui):
    ui = taxonomy_ui
    ui.outcomes.append(taxonomy(1))
    job = next(j for j in ui.jobs if j.target.__name__ == 'refresh_worker')
    job.target()
    # Signal closure after the background result is queued, before Tk applies it.
    ui.cancel.set()
    ui.root.update()
    assert not ui.states
    assert ui.log.get('1.0', 'end').strip() == ''
