"""Unsaved-changes guard, New Project and autosave recovery.

Display-gated like test_window_close.py (the compiled UI is required); the
tests drive the window handlers, not real widget interaction.
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
    for _ in range(rounds):
        context.iteration(False)


@pytest.fixture
def window(monkeypatch, tmp_path):
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    gi.require_version("GdkPixbuf", "2.0")

    from window import PatchworkWindow

    monkeypatch.setattr(PatchworkWindow, "_load_filters", lambda self: None)
    autosave = tmp_path / "autosave.patch"
    monkeypatch.setattr(PatchworkWindow, "_autosave_path", lambda self: autosave)
    win = PatchworkWindow()
    win.present()
    _pump()
    yield win
    win.destroy()


def _respond(window, response: str):
    """Simulate the user picking a response on the unsaved-changes dialog."""
    dialog = window._close_dialog
    window._on_unsaved_response(dialog, response)
    dialog.close()
    _pump()


def _respond_autosave(window, response: str):
    dialog = window._autosave_dialog
    window._on_autosave_response(dialog, response)
    dialog.close()
    _pump()


def _add_node(window):
    from nodes import InputNode
    window._canvas.add_node(InputNode("in"))


class TestUnsavedGuard:
    def test_clean_action_proceeds_without_prompt(self, window):
        calls = []
        window._confirm_unsaved(lambda: calls.append("go"))
        assert calls == ["go"]
        assert window._close_dialog is None

    def test_modified_action_prompts(self, window):
        calls = []
        window._mark_modified()
        window._confirm_unsaved(lambda: calls.append("go"))
        assert window._close_dialog is not None
        assert calls == []

    def test_cancel_does_nothing(self, window):
        calls = []
        window._mark_modified()
        window._confirm_unsaved(lambda: calls.append("go"))
        _respond(window, "cancel")
        assert calls == []
        assert window._modified is True

    def test_discard_proceeds(self, window):
        calls = []
        window._mark_modified()
        window._confirm_unsaved(lambda: calls.append("go"))
        _respond(window, "discard")
        assert calls == ["go"]

    def test_save_writes_then_proceeds(self, window, tmp_path):
        target = tmp_path / "project.patch"
        window._project_path = str(target)
        calls = []
        window._mark_modified()
        window._confirm_unsaved(lambda: calls.append("go"))
        _respond(window, "save")
        assert target.exists()
        assert calls == ["go"]
        assert window._modified is False

    def test_cancelled_save_dialog_aborts_the_action(self, window, monkeypatch):
        window._project_path = None
        calls = []
        window._mark_modified()
        monkeypatch.setattr(window, "_show_save_dialog", lambda on_done: None)
        window._confirm_unsaved(lambda: calls.append("go"))
        _respond(window, "save")
        assert calls == []
        assert window._modified is True

    def test_second_prompt_is_ignored(self, window):
        first, second = [], []
        window._mark_modified()
        window._confirm_unsaved(lambda: first.append(1))
        dialog = window._close_dialog
        window._confirm_unsaved(lambda: second.append(1))
        assert window._close_dialog is dialog
        _respond(window, "discard")
        assert first == [1]
        assert second == []


class TestOpenProjectGuard:
    def test_open_with_unsaved_changes_prompts(self, window, monkeypatch):
        opened = []
        monkeypatch.setattr(window, "_show_open_dialog", lambda: opened.append(1))
        window._mark_modified()
        window._on_open_project(None, None)
        assert window._close_dialog is not None
        assert opened == []

    def test_cancel_keeps_graph_and_modified_state(self, window, monkeypatch):
        opened = []
        monkeypatch.setattr(window, "_show_open_dialog", lambda: opened.append(1))
        _add_node(window)
        window._mark_modified()
        window._on_open_project(None, None)
        _respond(window, "cancel")
        assert opened == []
        assert "in" in window._graph.nodes
        assert window._modified is True

    def test_discard_opens(self, window, monkeypatch):
        opened = []
        monkeypatch.setattr(window, "_show_open_dialog", lambda: opened.append(1))
        window._mark_modified()
        window._on_open_project(None, None)
        _respond(window, "discard")
        assert opened == [1]

    def test_save_writes_project_then_opens(self, window, monkeypatch, tmp_path):
        opened = []
        monkeypatch.setattr(window, "_show_open_dialog", lambda: opened.append(1))
        target = tmp_path / "project.patch"
        window._project_path = str(target)
        window._mark_modified()
        window._on_open_project(None, None)
        _respond(window, "save")
        assert target.exists()
        assert opened == [1]

    def test_clean_open_does_not_prompt(self, window, monkeypatch):
        opened = []
        monkeypatch.setattr(window, "_show_open_dialog", lambda: opened.append(1))
        window._on_open_project(None, None)
        assert window._close_dialog is None
        assert opened == [1]


class TestNewProject:
    def test_clears_canvas_and_resets_state(self, window):
        _add_node(window)
        window._project_path = "/tmp/old.patch"
        window._mark_modified()
        window._new_project()
        assert window._graph.nodes == {}
        assert window._canvas._node_widgets == {}
        assert window._project_path is None
        assert window._modified is False
        assert window._status_label.get_text() == "New project"

    def test_action_prompts_then_clears(self, window):
        _add_node(window)
        window._mark_modified()
        window._on_new_project(None, None)
        assert window._close_dialog is not None
        _respond(window, "discard")
        assert window._graph.nodes == {}
        assert window._modified is False

    def test_action_without_changes_is_immediate(self, window):
        window._on_new_project(None, None)
        assert window._close_dialog is None
        assert window._modified is False


class TestAutosaveRecovery:
    @staticmethod
    def _write(window, path, with_node=True):
        from nodes import InputNode, NodeGraph
        graph = NodeGraph()
        if with_node:
            graph.add_node(InputNode("in"))
        window._save_patchwork_to_path(str(path), graph)

    def test_valid_autosave_offers_restore(self, window, tmp_path):
        path = window._autosave_path()
        self._write(window, path)
        window._maybe_offer_autosave()
        assert window._autosave_dialog is not None
        _respond_autosave(window, "discard")
        assert not path.exists()

    def test_discard_keeps_current_graph(self, window):
        path = window._autosave_path()
        self._write(window, path)
        window._maybe_offer_autosave()
        _respond_autosave(window, "discard")
        assert window._graph.nodes == {}
        assert not path.exists()

    def test_restore_applies_graph_and_marks_modified(self, window):
        path = window._autosave_path()
        self._write(window, path)
        window._maybe_offer_autosave()
        _respond_autosave(window, "restore")
        assert "in" in window._graph.nodes
        assert window._project_path is None
        assert window._modified is True
        assert "Restored" in window._status_label.get_text()
        assert not path.exists()

    def test_broken_file_is_removed_without_prompt(self, window):
        path = window._autosave_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not a project")
        window._maybe_offer_autosave()
        assert window._autosave_dialog is None
        assert not path.exists()

    def test_empty_project_is_removed_without_prompt(self, window):
        path = window._autosave_path()
        self._write(window, path, with_node=False)
        window._maybe_offer_autosave()
        assert window._autosave_dialog is None
        assert not path.exists()

    def test_explicit_save_deletes_autosave(self, window, tmp_path):
        path = window._autosave_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stale")
        target = tmp_path / "project.patch"
        assert window._save_to_path(str(target))
        assert not path.exists()

    def test_clean_close_deletes_autosave(self, window):
        path = window._autosave_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stale")
        window._mark_modified(False)
        assert window._on_close_request() is False
        assert not path.exists()

    def test_filters_loading_offers_autosave(self, window):
        path = window._autosave_path()
        self._write(window, path)
        window._finish_loading_filters([])
        assert window._autosave_dialog is not None
        _respond_autosave(window, "discard")
