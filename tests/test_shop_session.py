import pytest

from commerce.store import CommerceStore
from commerce.tiktok import category_session as session
from commerce.tiktok.watchlist import ProductWatch, load_watchlist, save_watchlist

URL = 'https://shop.tiktok.com/gb/c/phones/123'
OTHER = 'https://shop.tiktok.com/gb/c/parts/456'


def product(pid=1, price=10):
    return {'product_id': str(pid), 'title': f'Product {pid}', 'price': price, 'currency': 'GBP',
            'url': f'https://shop.tiktok.com/gb/pdp/{pid}'}


def reply(reason, products=(), complete=None):
    return {'products': list(products), 'stopReason': reason,
            'complete': reason == 'END_OF_LIST' if complete is None else complete,
            'dataComplete': True, 'clicks': 1, 'durationMs': 100}


def run(monkeypatch, tmp_path, replies):
    calls, events = [], []
    pending = iter(replies)
    def request(url):
        calls.append(url)
        result = next(pending)
        if isinstance(result, Exception): raise result
        return result
    monkeypatch.setattr(session, 'request_category', request)
    store = CommerceStore(tmp_path / 'commerce.db')
    result = session.collect_category_session(URL, store, events.append)
    return result, calls, events, store


@pytest.mark.parametrize('reason', ['NAVIGATION', 'TIMEOUT', 'NO_GROWTH'])
def test_recoverable_passes_resume_same_category_and_ingest_union_once(monkeypatch, tmp_path, reason):
    result, calls, events, store = run(monkeypatch, tmp_path, [
        reply(reason, [product(1), product(2)]), reply('END_OF_LIST', [product(2, 9), product(3)])])
    assert calls == [URL, URL]
    assert result.complete and result.product_count == 3 and result.passes == 2
    assert result[1]['price'] == 9
    assert any('CONTINUING' in event['message'] for event in events)
    assert events[2]['products'] == [product(1), product(2)]
    for pid in ('1', '2', '3'):
        assert len(store.price_history('tiktok_shop', pid)) == 1


@pytest.mark.parametrize('reason', ['CHALLENGE', 'LOGIN_REQUIRED', 'PAGE_BLOCKED', 'PAGE_ERROR',
    'BUTTON_AMBIGUOUS', 'BUTTON_SCOPE_CHANGED', 'CATEGORY_CHANGED', 'TAB_AMBIGUOUS',
    'INVALID_CATEGORY_URL', 'INVALID_REQUEST', 'BRIDGE_NO_RESPONSE', 'BROWSER_ERROR',
    'CLICK_LIMIT', 'UNVERIFIED'])
def test_hard_errors_never_retry_and_keep_partial_products(monkeypatch, tmp_path, reason):
    result, calls, _, store = run(monkeypatch, tmp_path, [reply(reason, [product()])])
    assert len(calls) == 1
    assert not result.complete and result.stop_reason == reason
    assert result.product_count == 1 and len(store.price_history('tiktok_shop', '1')) == 1
    assert session.session_summary(result).startswith('STOPPED')


def test_max_five_passes_preserves_products_and_last_error(monkeypatch, tmp_path):
    result, calls, events, store = run(monkeypatch, tmp_path, [reply('TIMEOUT', [product(i)]) for i in range(1, 6)])
    assert len(calls) == result.passes == 5
    assert result.stop_reason == 'MAX_PASSES_REACHED' and not result.complete
    assert result.last_stop_reason == 'TIMEOUT' and result.product_count == 5
    assert 'CONTINUING' not in events[-1]['message']
    assert 'MAX PASSES REACHED' in session.session_summary(result)
    assert len(store.latest_products()) == 5


def test_navigation_without_products_can_recover(monkeypatch, tmp_path):
    result, calls, _, _ = run(monkeypatch, tmp_path, [reply('NAVIGATION'), reply('END_OF_LIST', [product()])])
    assert result.complete and len(calls) == 2


def test_unverified_end_never_shows_complete_or_retries(monkeypatch, tmp_path):
    result, calls, _, _ = run(monkeypatch, tmp_path, [reply('END_OF_LIST', [product()], False)])
    assert len(calls) == 1 and not result.complete
    assert not session.session_summary(result).startswith('COMPLETE')


@pytest.mark.parametrize('error, reason', [(ValueError('invalid'), 'INVALID_URL'), (RuntimeError('unexpected'), 'COLLECTION_ERROR')])
def test_later_exception_preserves_prior_products(monkeypatch, tmp_path, error, reason):
    result, calls, _, store = run(monkeypatch, tmp_path, [reply('TIMEOUT', [product()]), error])
    assert result.stop_reason == reason and len(calls) == 2
    assert len(store.latest_products()) == 1


def test_missing_later_fields_do_not_erase_price_or_title(monkeypatch, tmp_path):
    result, _, _, _ = run(monkeypatch, tmp_path, [reply('NO_GROWTH', [product()]),
        reply('END_OF_LIST', [{'product_id': '1', 'price': None, 'title': ''}])])
    assert result[0]['price'] == 10 and result[0]['title'] == 'Product 1'


def test_separate_user_actions_keep_legitimate_history(monkeypatch, tmp_path):
    monkeypatch.setattr(session, 'request_category', lambda url: reply('END_OF_LIST', [product()]))
    store = CommerceStore(tmp_path / 'commerce.db')
    session.collect_category_session(URL, store)
    session.collect_category_session(URL, store)
    assert len(store.price_history('tiktok_shop', '1')) == 2


def test_per_category_only_clears_when_starting_different_category():
    state = session.ShopListState()
    token = state.begin(URL, 'PER CATEGORY')
    state.merge([product()], token)
    state.merge([product(2)], token)  # Next pass in same action.
    assert len(state.items) == 2
    state.busy = False
    token = state.begin(URL + '/', 'PER CATEGORY')
    assert len(state.items) == 2
    state.busy = False
    state.begin(OTHER, 'PER CATEGORY')
    assert state.items == {}


def test_mixed_list_updates_by_id_across_categories():
    state = session.ShopListState()
    token = state.begin(URL, 'MIXED LIST')
    state.merge([product()], token)
    state.busy = False
    token = state.begin(OTHER, 'MIXED LIST')
    state.merge([product(1, 8), product(2)], token)
    assert len(state.items) == 2 and state.items['1']['price'] == 8


def test_clear_items_invalidates_queued_progress_and_completion():
    state = session.ShopListState()
    token = state.begin(URL, 'PER CATEGORY')
    state.merge([product()], token)
    state.clear_items()
    state.merge([product(), product(2)], token)
    assert state.items == {} and state.busy
    with pytest.raises(RuntimeError): state.begin(OTHER, 'MIXED LIST')


def test_malformed_url_stops_before_bridge_without_breaking_ui_state(monkeypatch):
    from commerce.tiktok import category_collector
    monkeypatch.setattr(category_collector, 'pdh_request', lambda *a, **kw: pytest.fail('invalid URL must not reach bridge'))
    monkeypatch.setattr(session, 'CommerceStore', lambda: pytest.fail('empty invalid request must not open store'))
    url = 'https://[shop.tiktok.com'
    state = session.ShopListState()
    state.begin(url, 'PER CATEGORY')
    result = session.collect_category_session(url)
    assert result.stop_reason == 'INVALID_URL' and result.passes == 1
    assert not result.complete and not result


def test_clear_actions_cannot_delete_persistent_data(tmp_path):
    store = CommerceStore(tmp_path / 'commerce.db')
    session.ingest_products([product()], store)
    watch_file = tmp_path / 'watchlist.json'
    save_watchlist([ProductWatch('1', 'Product 1', product()['url'])], watch_file)
    alerts = tmp_path / 'alerts.json'; alerts.write_text('{"existing":true}')
    before = {p: p.read_bytes() for p in (store.path, watch_file, alerts)}
    state = session.ShopListState()
    state.merge([product()], 0)
    class Log:
        text = 'activity'
        def delete(self, *args): self.text = ''
        def edit_reset(self): pass
    log = Log()
    session.clear_log_widget(log)
    assert state.items and log.text == ''
    log.text = 'new activity'
    state.clear_items()
    assert log.text == 'new activity' and not state.items
    assert before == {p: p.read_bytes() for p in before}
    assert len(load_watchlist(watch_file)) == 1
