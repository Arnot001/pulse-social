"""Real Windows Tk tests: rows must be visible, not merely in the widget model."""
import re
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import ttk
from types import SimpleNamespace

import pytest

from platforms.x import auto_post as posting
from platforms.x import auto_post_ui as ui


def descendants(parent):
    for child in parent.winfo_children():
        yield child
        yield from descendants(child)


@pytest.fixture(scope='module')
def root():
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def screen(monkeypatch, tmp_path, root):
    monkeypatch.setattr(posting, 'QUEUE_FILE', tmp_path / 'queue.json')
    monkeypatch.setattr(posting, 'HISTORY_FILE', tmp_path / 'history.txt')
    monkeypatch.setattr(ui, 'browser_status', lambda: 'PULSE BROWSER // CONNECTED')
    errors, windows = [], []
    root.report_callback_exception = lambda *args: errors.append(args)
    def open_window():
        window = ui.open_auto_post_window(root)
        windows.append(window)
        window.attributes("-topmost", True)
        window.lift()
        root.update()
        widgets = list(descendants(window))
        tree = next(w for w in widgets if isinstance(w, ttk.Treeview))
        texts = [w for w in widgets if isinstance(w, tk.Text)]
        entries = [w for w in widgets if isinstance(w, tk.Entry)]
        def button(label):
            return next(w for w in widgets if isinstance(w, tk.Button) and w.cget('text').strip() == label)
        def poll():
            timer = next(t for t in window.tk.call('after', 'info')
                         if 'poll_updates' in str(window.tk.call('after', 'info', t)))
            command = window.tk.call('after', 'info', timer)[0]
            window.tk.call('after', 'cancel', timer)
            window.tk.call(command)
            root.update()
        return SimpleNamespace(window=window, tree=tree, text=texts[0], log=texts[1],
                               entries=entries, button=button, poll=poll)
    yield SimpleNamespace(open=open_window, root=root)
    for window in windows:
        if window.winfo_exists():
            window.tk.call(window.protocol('WM_DELETE_WINDOW'))
    root.update()
    assert not errors


def test_queued_rows_are_rendered_and_unobscured(screen):
    item = posting.add_post('Visible queued post', datetime.now() + timedelta(minutes=5))
    view = screen.open()
    assert view.tree.get_children() == (item.post_id,)
    assert view.tree.item(item.post_id, 'values')[1:] == ('QUEUED', 'Visible queued post')
    box = view.tree.bbox(item.post_id)
    assert box and box[3] > 0 and view.tree.winfo_ismapped()
    x, y = view.tree.winfo_rootx() + box[0] + 20, view.tree.winfo_rooty() + box[1] + 10
    assert view.window.winfo_containing(x, y) == view.tree
    lx, ly = view.log.winfo_rootx() + 10, view.log.winfo_rooty() + 10
    assert view.window.winfo_containing(lx, ly) == view.log


def test_success_moves_to_activity_once_and_reloads_after_reopen(screen):
    item = posting.add_post('Successful post', datetime.now())
    view = screen.open()
    item.status, item.posted_at = 'posted', '2026-10-07T14:00:00'
    posting.save_queue([item, item])
    view.poll(); view.poll()
    assert view.tree.get_children() == ()
    assert view.log.get('1.0', 'end').count('| POSTED | Successful post') == 1
    view.window.tk.call(view.window.protocol('WM_DELETE_WINDOW'))
    reopened = screen.open()
    assert reopened.tree.get_children() == ()
    assert reopened.log.get('1.0', 'end').count('| POSTED | Successful post') == 1


def test_reload_legacy_success_queue_and_no_duplicate_rows(screen):
    queued = posting.add_post('still waiting', datetime.now() + timedelta(days=1))
    posted = posting.QueuedPost('legacy', 'older success', '2026-10-06T10:00:00', 'posted')
    posting.save_queue([queued, queued, posted, posted])
    view = screen.open()
    assert view.tree.get_children() == (queued.post_id,)
    assert view.log.get('1.0', 'end').count('| POSTED | older success') == 1
    view.poll()
    assert view.tree.get_children() == (queued.post_id,)


def test_queue_and_remove_actions_update_visible_rows(screen):
    view = screen.open()
    view.text.insert('1.0', 'New queued post')
    view.button('QUEUE POST').invoke()
    view.poll()
    item, = posting.load_queue()
    assert view.tree.get_children() == (item.post_id,)
    view.tree.selection_set(item.post_id)
    view.button('REMOVE').invoke()
    assert not posting.load_queue() and not view.tree.get_children()


@pytest.mark.parametrize('index', [0, 1, 2, 3])
def test_all_editable_widgets_support_keyboard_and_mouse_clipboard(screen, index):
    view = screen.open()
    widget = [view.text, *view.entries, view.log][index]
    is_text = isinstance(widget, tk.Text)
    start, end = ('1.0', 'end-1c') if is_text else (0, tk.END)
    widget.delete(start, tk.END)
    widget.insert(start, 'clipboard sample')
    # Invoke the widget's registered key binding, independent of OS focus stealing.
    def key(letter):
        script = widget.bind(f'<Control-{letter}>')
        assert script
        widget.tk.call(re.search(r'\[([^ ]+)', script).group(1), '')
        screen.root.update()
    key('a'); key('c')
    assert widget.clipboard_get() == 'clipboard sample'
    key('x')
    assert widget.get(start, end) == '' if is_text else widget.get() == ''
    key('v')
    assert (widget.get(start, end) if is_text else widget.get()) == 'clipboard sample'
    menu = next(w for w in widget.winfo_children() if isinstance(w, tk.Menu))
    assert widget.bind('<Button-3>')
    menu.invoke(3); menu.invoke(0); menu.invoke(2)
    assert (widget.get(start, end) if is_text else widget.get()) == 'clipboard sample'


def test_emoji_button_uses_local_colour_image_and_preserves_picker(screen, monkeypatch):
    calls = []
    monkeypatch.setattr(ui, 'open_emoji_picker', lambda target, **kwargs: calls.append((target, kwargs)))
    view = screen.open()
    button = view.button('EMOJI')
    photo = button._emoji_photo
    assert button.cget('image') and button.cget('compound') == 'left'
    colours = {photo.get(x, y) for x in range(photo.width()) for y in range(photo.height())
               if not photo.transparency_get(x, y)}
    assert any(r > g > b for r, g, b in colours)
    button.invoke()
    assert calls[0][0] is view.text and calls[0][1]['accent'] == ui.ACCENT
