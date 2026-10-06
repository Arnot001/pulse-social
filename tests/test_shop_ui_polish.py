"""Real Tk regression checks for the main Shop polish; no live collection."""
import tkinter as tk
from tkinter import ttk

import pytest

from commerce.tiktok import shop_ui
from commerce.tiktok.categories import TikTokCategory
from commerce.tiktok.category_collector import CategoryCollection


def descendants(parent):
    for child in parent.winfo_children():
        yield child
        yield from descendants(child)


@pytest.fixture(scope='module')
def polish_root():
    root=tk.Tk(); root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def shop(monkeypatch,polish_root):
    root=polish_root
    jobs=[]; errors=[]
    root.report_callback_exception=lambda *args: errors.append(args)
    class Thread:
        def __init__(self,target,args=(),**kwargs): self.target=target; self.args=args
        def start(self): jobs.append(self)
    monkeypatch.setattr(shop_ui.threading,'Thread',Thread)
    monkeypatch.setattr(shop_ui,'fetch_categories',lambda:[TikTokCategory('123','Phones','phones',1,'0',True)])
    monkeypatch.setattr(shop_ui,'bridge_status',lambda:{'pdhConnected':True})
    rows=[]
    def collect(url,on_progress):
        on_progress({'products':list(rows),'message':'VERIFIED COMPLETE // RECORDING'})
        result=CategoryCollection(list(rows),{'products':list(rows),'complete':True,'stopReason':'END_OF_LIST'})
        result.passes=1
        return result
    monkeypatch.setattr(shop_ui,'collect_category_session',collect)
    window=shop_ui.open_shop_window(root); window.withdraw()
    def run(name):
        job=next(j for j in jobs if j.target.__name__==name)
        jobs.remove(job); job.target(*job.args); root.update()
    def button(text):
        return next(w for w in descendants(window) if isinstance(w,tk.Button) and w.cget('text')==text)
    run('refresh_worker')
    tree=next(w for w in descendants(window) if isinstance(w,ttk.Treeview))
    class Harness: pass
    h=Harness()
    h.root,h.window,h.rows,h.tree,h.run,h.button,h.jobs=root,window,rows,tree,run,button,jobs
    yield h
    window.tk.call(window.protocol('WM_DELETE_WINDOW'))
    assert not any('poll_pdh' in str(root.tk.call('after','info',t)) for t in root.tk.call('after','info'))
    root.update()
    assert not errors


def item(pid,**values):
    return {'product_id':str(pid),'title':f'Product {pid}','price':10,'currency':'GBP',
            'deal_score':70,'status':'recorded','sold_count':1200,**values}


@pytest.mark.parametrize('fields,text,tone',[
    ({},'—',''),
    ({'price_change':0},'NO CHANGE',''),
    ({'is_new_low':True},'[NEW LOW]','new_low'),
    ({'price_change':-2,'price_change_pct':-20},'↓ -2.00 (-20.0%)','drop'),
    ({'price_change':2,'price_change_pct':None},'↑ +2.00','rise'),
    ({'status':'skipped','is_new_low':True},'SKIPPED','pending'),
])
def test_movement_does_not_invent_history(fields,text,tone):
    assert shop_ui.movement_display(item(1,**fields))==(text,tone)


def test_counts_follow_visible_rows_mode_and_clear(shop):
    label=next(w for w in descendants(shop.window) if isinstance(w,tk.Label) and '0 PRODUCTS' in w.cget('text'))
    assert label.cget('text')=='1 CATEGORIES  //  PER CATEGORY  //  0 PRODUCTS'
    shop.rows.extend([item(1),item(2,price_change=-1,is_new_low=True)])
    shop.button('COLLECT CATEGORY').invoke(); shop.run('collect_worker')
    assert label.cget('text').endswith('2 PRODUCTS')
    box=next(w for w in descendants(shop.window) if isinstance(w,ttk.Combobox) and 'MIXED LIST' in w.cget('values'))
    box.set('MIXED LIST')
    assert 'MIXED LIST' in label.cget('text')
    shop.button('CLEAR ITEMS').invoke()
    assert label.cget('text').endswith('0 PRODUCTS')


def test_table_retains_selection_focus_and_full_product_fields(shop):
    title='A long full product title '+('with details '*15)
    shop.rows.extend([item(1,title=title),item(2,price_change=-1,is_new_low=True)])
    shop.button('COLLECT CATEGORY').invoke(); shop.run('collect_worker')
    shop.tree.selection_set('1'); shop.tree.focus('1')
    shop.button('COLLECT CATEGORY').invoke(); shop.run('collect_worker')
    assert shop.tree.selection()==('1',) and shop.tree.focus()=='1'
    assert shop.tree.item('1','values')[-1]==title
    assert shop.tree.item('1','values')[4]=='1,200'
    assert 'new_low' in shop.tree.item('2','tags')
    assert 'even' in shop.tree.item('1','tags') and 'odd' in shop.tree.item('2','tags')
    assert shop.tree.cget('xscrollcommand')


def test_bridge_status_is_independent_of_taxonomy_and_polling_stops_on_close(shop,monkeypatch):
    label=next(w for w in descendants(shop.window) if isinstance(w,tk.Label) and w.cget('text')=='PDH CHECKING')
    timers=shop.window.tk.call('after','info')
    timer=next(t for t in timers if 'poll_pdh' in str(shop.window.tk.call('after','info',t)))
    command=shop.window.tk.call('after','info',timer)[0]
    shop.run('read_pdh')
    shop.window.tk.call('after','cancel',timer); shop.window.tk.call(command)
    assert label.cget('text')=='PDH CONNECTED'
    monkeypatch.setattr(shop_ui,'bridge_status',lambda:{})
    shop.run('read_pdh')
    timer=next(t for t in shop.window.tk.call('after','info') if 'poll_pdh' in str(shop.window.tk.call('after','info',t)))
    command=shop.window.tk.call('after','info',timer)[0]
    shop.window.tk.call('after','cancel',timer); shop.window.tk.call(command)
    assert label.cget('text')=='PDH DISCONNECTED'


@pytest.mark.parametrize('size', ['900x700','1080x780','1536x864'])
def test_control_deck_fits_supported_window_sizes(shop,size):
    shop.window.geometry(size); shop.window.deiconify(); shop.root.update()
    for text in ['COLLECT CATEGORY','REFRESH CATEGORIES','WATCHLIST','ALERT SETTINGS','CLEAR ITEMS']:
        button=shop.button(text)
        assert button.winfo_ismapped()
        assert button.winfo_rootx()+button.winfo_width() <= shop.window.winfo_rootx()+shop.window.winfo_width()
    log=next(w for w in descendants(shop.window) if isinstance(w,tk.Text))
    assert log.winfo_ismapped() and log.winfo_height()>60
    assert log.winfo_rooty()+log.winfo_height() <= shop.window.winfo_rooty()+shop.window.winfo_height()
    assert shop.tree.winfo_height()>100
    assert shop.button('COLLECT CATEGORY').master.master==shop.button('CLEAR ITEMS').master.master
