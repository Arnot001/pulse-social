from pathlib import Path

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
