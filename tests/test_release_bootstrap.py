from pathlib import Path
import builtins
import sys
from types import SimpleNamespace

import pytest

import release_bootstrap


def test_child_dispatch_uses_only_known_entrypoint_basenames():
    assert release_bootstrap._child_module(r"C:\anything\x_auto_post_ui.py") == "x_auto_post_ui"
    assert release_bootstrap._child_module("/tmp/tiktok_shop_ui.py") == "tiktok_shop_ui"
    assert release_bootstrap._child_module("unknown.py") is None


def test_release_child_entrypoints_are_declared():
    assert release_bootstrap.CHILD_MODULES == {
        "pulse_social_ui.py": "pulse_social_ui",
        "x_auto_post_ui.py": "x_auto_post_ui",
        "tiktok_shop_ui.py": "tiktok_shop_ui",
        "tiktok_auto_post_ui.py": "tiktok_auto_post_ui",
        "tiktok_cleanup_ui.py": "tiktok_cleanup_ui",
    }


def test_release_build_script_pins_pdh_version():
    script = Path("release/build_beta.ps1").read_text(encoding="utf-8")
    assert "0.11.100" in script
    assert "--onedir" in script
    assert "pdh_extension" in script
    assert "tests/test_pulse_splash.py" in script


@pytest.mark.parametrize("entrypoint,module", release_bootstrap.CHILD_MODULES.items())
@pytest.mark.parametrize("implicit_argv", [False, True])
def test_child_dispatch_bypasses_splash_and_launcher(monkeypatch, entrypoint, module, implicit_argv):
    args = [str(Path("modules") / entrypoint.upper()), "--profile", "beta"]
    monkeypatch.setattr(sys, "argv", ["Pulse Social.exe", *args])
    calls = []
    monkeypatch.setattr(release_bootstrap.runpy, "run_module",
                        lambda name, **kw: calls.append((name, kw, list(sys.argv))))
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        assert name not in {"pulse_splash", "pulse_social_launcher", "tkinter"}
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    release_bootstrap.main(None if implicit_argv else args)
    assert calls == [(module, {"run_name": "__main__"}, args)]


@pytest.mark.parametrize("args", [[], ["unknown.py", "--flag"]])
@pytest.mark.parametrize("failure", [None, "import", "display"])
def test_main_shows_splash_before_launcher_and_fails_open(monkeypatch, args, failure):
    calls = []
    monkeypatch.setattr(sys, "argv", ["Pulse Social.exe", *args])
    original_argv = list(sys.argv)
    original_import = builtins.__import__

    def show():
        calls.append("splash")
        if failure == "display":
            raise RuntimeError("Display unavailable")

    def fake_import(name, *args, **kwargs):
        if name == "pulse_splash":
            calls.append("splash import")
            if failure == "import":
                raise ImportError("Tk unavailable")
            return SimpleNamespace(show_splash=show)
        if name == "pulse_social_launcher":
            calls.append("launcher")
            return SimpleNamespace()
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    release_bootstrap.main(args)
    assert calls == (["splash import", "launcher"] if failure == "import" else
                     ["splash import", "splash", "launcher"])
    assert sys.argv == original_argv


def test_launcher_errors_are_not_swallowed(monkeypatch):
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pulse_splash":
            return SimpleNamespace(show_splash=lambda: None)
        if name == "pulse_social_launcher":
            raise RuntimeError("launcher failure")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="launcher failure"):
        release_bootstrap.main([])
