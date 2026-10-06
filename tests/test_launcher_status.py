import runpy
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import MagicMock

import concurrent.futures
import tkinter
import platforms.browser_control as browser
import platforms.pdh_bridge as bridge


def test_launcher_refreshes_connection_without_overlapping_work_and_cancels_on_close(monkeypatch):
    root = MagicMock()
    variable = MagicMock()
    for name in ("Frame", "Button", "Label", "Canvas"):
        monkeypatch.setattr(tkinter, name, MagicMock())
    monkeypatch.setattr(tkinter, "Tk", lambda: root)
    monkeypatch.setattr(tkinter, "StringVar", lambda **kw: variable)
    monkeypatch.setattr(browser, "running_browser_names", lambda: ["Brave"])
    connected = False
    monkeypatch.setattr(bridge, "bridge_status", lambda: {"pdhConnected": connected})
    monkeypatch.setattr(bridge, "ensure_bridge_server", lambda: True)
    futures = []
    executor = MagicMock()
    def submit(fn):
        future = Future()
        futures.append((future, fn))
        return future
    executor.submit.side_effect = submit
    monkeypatch.setattr(concurrent.futures, "ThreadPoolExecutor", lambda **kw: executor)
    namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / "pulse_social_launcher.py"))
    assert root.after.call_args.args[0] == 2000
    tick = root.after.call_args.args[1]
    tick()
    namespace["refresh_pdh_browser"]()
    assert len(futures) == 1
    connected = True
    futures[0][0].set_result(futures[0][1]())
    tick()
    variable.set.assert_called_with("BRAVE OPEN  //  PDH CONNECTED")
    assert len(futures) == 2
    connected = False
    futures[1][0].set_result(futures[1][1]())
    tick()
    variable.set.assert_called_with("BRAVE OPEN  //  WAITING FOR PDH")
    namespace["close_all"]()
    root.after_cancel.assert_called_once()
    executor.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
    root.destroy.assert_called_once()


def test_ambient_clock_pauses_rendering_when_minimized_and_cancels_on_destroy():
    # Exercise the visual clock without creating a desktop window or starting PDH.
    import ast
    import math
    import time
    from types import SimpleNamespace

    source = Path(__file__).resolve().parents[1] / "pulse_social_launcher.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    definition = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "AmbientWaves")
    namespace = {"math": math, "time": time}
    exec(compile(ast.Module(body=[definition], type_ignores=[]), str(source), "exec"), namespace)
    root = MagicMock()
    root.state.return_value = "iconic"
    root.after.return_value = "animation-timer"
    canvas = MagicMock()
    animation = namespace["AmbientWaves"](root, canvas)
    detail = MagicMock()
    animation.details.append(detail)
    animation.start()
    animation.start()
    root.after.assert_called_once()
    animation._tick()
    detail.assert_not_called()
    canvas.winfo_width.assert_not_called()
    assert root.after.call_args.args[0] == 250

    root.state.return_value = "normal"
    canvas.winfo_width.return_value = 1180
    canvas.winfo_height.return_value = 720
    animation._tick()
    detail.assert_called_once()
    assert root.after.call_args.args[0] == 125
    animation._destroy(SimpleNamespace(widget=canvas))
    root.after_cancel.assert_not_called()
    animation._destroy(SimpleNamespace(widget=root))
    root.after_cancel.assert_called_once_with("animation-timer")
    root.after.reset_mock()
    animation._tick()
    animation.start()
    root.after.assert_not_called()
