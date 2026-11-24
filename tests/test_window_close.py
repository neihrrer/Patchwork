"""Unsaved-changes prompt when closing the main window.

Needs a display and the compiled UI file; skips in a headless container.
Metadata-only test: it exercises the window handlers, not the real widgets.
"""

import os
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


def _display_available() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _ensure_ui_file() -> bool:
    target = ROOT / "build" / "resources" / "window.ui"
    if target.exists():
        return True
    compiled = ROOT / "build" / "src" / "window.ui"
    if compiled.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(compiled, target)
        return True
    return False


pytestmark = pytest.mark.skipif(
    not (_display_available() and _ensure_ui_file()),
    reason="needs a display and a compiled window.ui",
)


def _pump(rounds: int = 20):
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import GLib

    context = GLib.MainContext.default()
    # Bounded: an animation elsewhere can keep the context permanently
    # pending, so never loop "while pending()".
    for _ in range(rounds):
        context.iteration(False)


@pytest.fixture
def window(monkeypatch):
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")

    from window import PatchworkWindow

    monkeypatch.setattr(PatchworkWindow, "_load_filters", lambda self: None)
    win = PatchworkWindow()
    win.present()
    _pump()
    yield win
    win.destroy()


def _respond(window, response: str):
    """Simulate the user picking a dialog response (dialog closes first)."""
    dialog = window._close_dialog
    dialog.close()
    _pump()
    window._on_close_response(dialog, response)
    _pump()


class TestCloseConfirmation:
    def test_clean_window_closes_without_prompt(self, window):
        assert window._modified is False
        assert window._on_close_request() is False

    def test_dirty_window_prompts(self, window):
        window._mark_modified()
        assert window._on_close_request() is True
        dialog = window._close_dialog
        assert dialog is not None

    def test_cancel_keeps_window_open(self, window):
        window._mark_modified()
        window._on_close_request()
        _respond(window, "cancel")
        assert window.get_visible()
        assert window._modified is True

    def test_discard_closes_window(self, window):
        window._mark_modified()
        window._on_close_request()
        _respond(window, "discard")
        assert window._modified is False
        assert not window.get_visible()

    def test_save_with_known_path_writes_project(self, window, tmp_path):
        target = tmp_path / "project.patch"
        window._project_path = str(target)
        window._mark_modified()
        window._on_close_request()
        _respond(window, "save")
        assert target.exists()
        assert window._modified is False
        assert not window.get_visible()

    def test_marking_modified_updates_title(self, window):
        window._mark_modified()
        assert window.get_title().endswith("\u2022")
        window._mark_modified(False)
        assert not window.get_title().endswith("\u2022")
