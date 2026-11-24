import gettext
import os
import re
from pathlib import Path
from typing import Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkPixbuf", "2.0")

from gi.repository import GLib, Gio, Gtk, Adw, GdkPixbuf
from threading import Event, Thread

from config import AppConfig

from models.filter import FilterDef
from gmic.cli import GmicCLI
from imagemagick.cli import ImageMagickCLI
from imagemagick.filters import get_builtin_filters as get_im_filters
from nodes import (
    NodeGraph, InputNode, VideoInputNode, TimeNode, RawInputNode, OutputNode, Node,
    HistogramNode, WaveformMonitorNode, VectorscopeNode, FrequencyDomainNode,
)
from widgets.node_editor import NodeCanvas
from widgets.filter_browser import FilterBrowser, set_pending_drag_text
from processing.graph_executor import GraphExecutor
from processing.runner import ProcessResult
from video.ffmpeg import FfmpegCLI
from video.renderer import (
    AnimationSettings, render_frames, mux_animation,
    FORMAT_MP4, FORMAT_GIF, FORMAT_PNG_SEQUENCE,
)

try:
    _ = gettext.gettext
except Exception:
    _ = lambda s: s

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _find_ui_file(name: str) -> str:
    paths = [
        Path(__file__).parent.parent / "build" / "resources" / name,
        Path(__file__).parent / "resources" / name,
        Path("/app/share/patchwork") / name,
    ]
    for p in paths:
        if p.exists():
            return str(p)
    return ""


def _generate_id() -> str:
    import uuid
    return uuid.uuid4().hex[:8]


class PatchworkWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self._gmic = GmicCLI()
        self._imagemagick = ImageMagickCLI()
        self._ffmpeg = FfmpegCLI()
        self._graph = NodeGraph()
        self._executor = GraphExecutor(self._gmic, self._imagemagick)
        self._executor.set_ffmpeg(self._ffmpeg)
        self._filter_def_map: dict[str, FilterDef] = {}

        self._config = AppConfig()
        self._canvas: Optional[NodeCanvas] = None
        self._filter_browser: Optional[FilterBrowser] = None
        self._result_pixbuf: Optional[GdkPixbuf.Pixbuf] = None
        self._result_pixbufs: dict[str, GdkPixbuf.Pixbuf] = {}
        self._minimap_switch: Optional[Adw.SwitchRow] = None
        self._auto_save_id: Optional[int] = None
        self._pending_graph: Optional["NodeGraph"] = None
        self._missing_images: list["InputNode"] = []
        self._modified: bool = False
        self._project_path: Optional[str] = None
        self._close_dialog: Optional[Adw.AlertDialog] = None
        self._pending_confirm_action = None
        self._autosave_dialog: Optional[Adw.AlertDialog] = None
        self._pending_autosave: Optional["NodeGraph"] = None
        self._render_active: bool = False
        self._render_cancel_event: Optional[Event] = None



        self._setup_ui()
        self._connect_signals()
        self._load_filters()

    def _setup_ui(self):
        ui_path = _find_ui_file("window.ui")
        if not ui_path:
            return

        builder = Gtk.Builder.new_from_file(ui_path)

        root = builder.get_object("window_root")
        if root:
            try:
                w = root.get_property("default-width")
                h = root.get_property("default-height")
                self.set_default_size(w, h)
            except Exception:
                self.set_default_size(1100, 750)
            self.set_title(root.get_title() or _("Node Editor"))
        self._base_title = self.get_title() or _("Node Editor")

        self._open_button = builder.get_object("open_button")
        self._render_button = builder.get_object("render_button")
        self._export_button = builder.get_object("export_button")
        self._menu_button = builder.get_object("menu_button")
        self._status_label = builder.get_object("status_label")
        self._status_spinner = builder.get_object("status_spinner")
        self._progress_revealer = builder.get_object("progress_revealer")
        self._progress_bar = builder.get_object("progress_bar")
        self._search_entry = builder.get_object("search_entry")
        self._search_revealer = builder.get_object("search_revealer")
        self._search_toggle = builder.get_object("search_toggle")
        self._output_text = builder.get_object("output_text")
        self._output_box = builder.get_object("output_box")
        self._output_paned = builder.get_object("output_paned")
        self._content_title = builder.get_object("content_title")
        self._content_base_title = (
            self._content_title.get_title() if self._content_title else self._base_title
        )

        if self._output_paned:
            self._output_paned.set_position(100000)
        if self._output_box:
            self._output_box.set_visible(False)

        filter_list = builder.get_object("filter_list")
        if filter_list:
            self._filter_browser = FilterBrowser(filter_list, [])
            self._filter_browser.connect("filter-selected", self._on_filter_selected)
            w = filter_list.get_parent()
            while w is not None:
                w.add_css_class("sidebar-bg")
                if isinstance(w, Adw.NavigationPage):
                    break
                w = w.get_parent()

        canvas_container = builder.get_object("canvas_container")
        if canvas_container:
            self._canvas = NodeCanvas(self._graph)
            canvas_container.append(self._canvas)
            self._canvas._minimap.connect("notify::visible", self._on_minimap_visibility_changed)
            self._canvas._grid_visible = self._config.grid_visible
            self._canvas._snap_to_grid = self._config.snap_to_grid
            self._canvas._extended_zoom = self._config.extended_zoom
            self._canvas._minimap.set_visible(self._config.minimap_visible)
            self._canvas.queue_gl_render()

        bp = builder.get_object("bp")
        if bp:
            self.add_breakpoint(bp)

        self._toast_overlay = Adw.ToastOverlay()
        self._split_view = builder.get_object("split_view")
        split_view = self._split_view
        if split_view:
            self._toast_overlay.set_child(split_view)
            self.set_content(self._toast_overlay)

        show_filters_button = builder.get_object("show_filters_button")
        back_to_canvas_button = builder.get_object("back_to_canvas_button")

        def _update_nav_buttons(*_args):
            if not split_view:
                return
            collapsed = split_view.get_collapsed()
            show_content = split_view.get_show_content()
            if show_filters_button:
                show_filters_button.set_visible(collapsed and show_content)
            if back_to_canvas_button:
                back_to_canvas_button.set_visible(collapsed and not show_content)

        if show_filters_button:
            show_filters_button.connect("clicked", lambda b: split_view.set_show_content(False))
        if back_to_canvas_button:
            back_to_canvas_button.connect("clicked", lambda b: split_view.set_show_content(True))

        if split_view:
            split_view.connect("notify::collapsed", _update_nav_buttons)
            split_view.connect("notify::show-content", _update_nav_buttons)
            _update_nav_buttons()

        self._setup_menu()

    def _connect_signals(self):
        if self._open_button:
            self._open_button.connect("clicked", self._on_open_clicked)
        if self._render_button:
            self._render_button.connect("clicked", self._on_render_clicked)
        if self._export_button:
            self._export_button.connect("clicked", self._on_export_clicked)
        if self._canvas:
            self._canvas.connect("node-selected", self._on_node_selected)
            self._canvas.connect("graph-changed", self._on_graph_changed)
            self._canvas.connect("input-node-open", self._on_input_node_open)
        if self._search_entry:
            self._search_entry.connect("search-changed", self._on_search_changed)
        if self._search_toggle:
            self._search_toggle.connect("toggled", self._on_search_toggle)
        self.connect("close-request", self._on_close_request)

    # ─── Menu / Preferences ─────────────────────────────────────────────────

    def _setup_menu(self):
        menu = Gio.Menu()
        menu.append(_("Undo"), "win.undo")
        menu.append(_("Redo"), "win.redo")
        menu.append(_("New Project"), "win.new-project")
        menu.append(_("Open Project"), "win.open-project")
        menu.append(_("Save Project"), "win.save-project")
        menu.append(_("Preferences"), "win.preferences")
        if self._menu_button:
            self._menu_button.set_menu_model(menu)

        for name, handler, accel in [
            ("undo", self._do_undo, "<primary>z"),
            ("redo", self._do_redo, ["<primary><shift>z", "<primary>y"]),
            ("new-project", self._on_new_project, "<primary>n"),
            ("open-project", self._on_open_project, "<primary>o"),
            ("save-project", self._on_save_project, "<primary>s"),
            ("preferences", self._on_preferences, "<primary>comma"),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)
            app = self.get_application()
            if app:
                accels = accel if isinstance(accel, list) else [accel]
                app.set_accels_for_action(f"win.{name}", accels)

    def _do_undo(self, action, param):
        if self._canvas:
            self._canvas.undo()

    def _do_redo(self, action, param):
        if self._canvas:
            self._canvas.redo()



    def _on_preferences(self, action, param):
        dialog = Adw.PreferencesDialog()

        page = Adw.PreferencesPage()
        proc_group = Adw.PreferencesGroup(
            title=_("Processing"),
            description=_("Configure processing limits"),
        )
        timeout_row = Adw.SpinRow(
            title=_("Timeout"),
            subtitle=_("Maximum seconds before rendering is aborted"),
            adjustment=Gtk.Adjustment(
                lower=10, upper=600, step_increment=10, page_increment=30,
            ),
            value=self._config.processing_timeout,
        )
        timeout_row.connect("notify::value", self._on_timeout_changed)
        proc_group.add(timeout_row)
        page.add(proc_group)

        display_group = Adw.PreferencesGroup(title=_("Display"))
        grid_visible_row = Adw.SwitchRow(
            title=_("Disable Grid"),
            subtitle=_("Hide the background grid"),
        )
        if self._canvas:
            grid_visible_row.set_active(not self._canvas._grid_visible)
            grid_visible_row.connect("notify::active", self._on_grid_visible_changed)
        display_group.add(grid_visible_row)
        snap_row = Adw.SwitchRow(
            title=_("Snap to Grid"),
            subtitle=_("Snap nodes to grid positions when moving"),
        )
        if self._canvas:
            snap_row.set_active(self._canvas._snap_to_grid)
            snap_row.connect("notify::active", self._on_snap_to_grid_changed)
        display_group.add(snap_row)
        zoom_row = Adw.SwitchRow(
            title=_("Extended Zoom Range"),
            subtitle=_("Allows zooming from 25% to 1000%, may cause visual artifacts"),
        )
        if self._canvas:
            zoom_row.set_active(self._canvas._extended_zoom)
            zoom_row.connect("notify::active", self._on_extended_zoom_changed)
        display_group.add(zoom_row)
        minimap_row = Adw.SwitchRow(
            title=_("Show Minimap"),
            subtitle=_("Display the minimap overlay in the node editor"),
        )
        if self._canvas:
            minimap_row.set_active(self._canvas._minimap.get_visible())
            minimap_row.connect("notify::active", self._on_minimap_switch_changed)
        display_group.add(minimap_row)
        self._minimap_switch = minimap_row
        page.add(display_group)

        general_group = Adw.PreferencesGroup(
            title=_("General"),
            description=_("Application-wide preferences"),
        )
        auto_save_row = Adw.SpinRow(
            title=_("Auto-save Interval"),
            subtitle=_("Automatically save project every N minutes (0 = off)"),
            adjustment=Gtk.Adjustment(
                lower=0, upper=60, step_increment=1, page_increment=5,
            ),
            value=self._config.auto_save_interval,
        )
        auto_save_row.connect("notify::value", self._on_auto_save_changed)
        general_group.add(auto_save_row)
        page.add(general_group)

        dialog.add(page)
        dialog.present(self)

    def _on_extended_zoom_changed(self, row, pspec):
        if self._canvas:
            self._canvas.set_extended_zoom(row.get_active())
        self._config.extended_zoom = row.get_active()

    def _on_grid_visible_changed(self, row, pspec):
        if self._canvas:
            self._canvas.set_grid_visible(not row.get_active())
        self._config.grid_visible = self._canvas._grid_visible if self._canvas else True

    def _on_minimap_switch_changed(self, row, pspec):
        if self._canvas:
            self._canvas.set_minimap_visible(row.get_active())
        self._config.minimap_visible = row.get_active()

    def _on_minimap_visibility_changed(self, minimap, pspec):
        if self._minimap_switch:
            self._minimap_switch.set_active(minimap.get_visible())

    def _on_timeout_changed(self, row, pspec):
        self._config.processing_timeout = int(row.get_value())

    def _clear_animation_result(self):
        if getattr(self, "_canvas", None):
            self._canvas.clear_node_animations()
        anim = getattr(self, "_result_animation", None)
        if anim:
            anim.cleanup()
            self._result_animation = None
        self._result_pixbufs = {}

    def _on_snap_to_grid_changed(self, row, pspec):
        enabled = row.get_active()
        self._config.snap_to_grid = enabled
        if self._canvas:
            self._canvas.set_snap_to_grid(enabled)

    def _on_auto_save_changed(self, row, pspec):
        interval = int(row.get_value())
        self._config.auto_save_interval = interval
        self._setup_auto_save()

    def _setup_auto_save(self):
        if self._auto_save_id is not None:
            GLib.source_remove(self._auto_save_id)
            self._auto_save_id = None
        interval = self._config.auto_save_interval
        if interval > 0 and self._graph.nodes:
            self._auto_save_id = GLib.timeout_add_seconds(
                interval * 60, self._do_auto_save
            )

    def _autosave_path(self) -> Path:
        return Path.home() / ".cache" / "patchwork" / "autosave.patch"

    def _delete_autosave(self):
        try:
            self._autosave_path().unlink()
        except OSError:
            pass

    def _do_auto_save(self) -> bool:
        if self._modified and self._graph.nodes:
            auto_path = self._autosave_path()
            try:
                auto_path.parent.mkdir(parents=True, exist_ok=True)
                self._save_patchwork_to_path(str(auto_path), self._graph)
            except OSError:
                pass
        if self._config.auto_save_interval > 0:
            self._auto_save_id = GLib.timeout_add_seconds(
                self._config.auto_save_interval * 60, self._do_auto_save
            )
        else:
            self._auto_save_id = None
        return False

    def _maybe_offer_autosave(self):
        """Offer to restore a project left behind by an abnormal exit."""
        if self._autosave_dialog is not None or self._close_dialog is not None:
            return
        path = self._autosave_path()
        if not path.is_file():
            return
        try:
            data, pack_dir = self._load_patchwork_from_path(str(path))
            if not isinstance(data, dict) or data.get("version") != 1:
                self._delete_autosave()
                return
            graph = NodeGraph.from_dict(data, self._filter_def_map)
        except Exception:
            self._delete_autosave()
            return
        if not graph.nodes:
            self._delete_autosave()
            return
        self._rebind_packed_images(graph, pack_dir)

        dialog = Adw.AlertDialog(
            heading=_("Restore Autosaved Project?"),
            body=_("Patchwork found a project that was not saved when the "
                   "application last closed. Restore it?"),
        )
        dialog.add_response("discard", _("Discard"))
        dialog.add_response("restore", _("Restore"))
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_response_appearance("restore", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("restore")
        dialog.set_close_response("discard")
        self._autosave_dialog = dialog
        self._pending_autosave = graph
        dialog.connect("response", self._on_autosave_response)
        dialog.present(self)

    def _on_autosave_response(self, dialog, response: str):
        if self._autosave_dialog is None:
            return  # already resolved
        graph = self._pending_autosave
        self._autosave_dialog = None
        self._pending_autosave = None
        if response == "restore" and graph is not None:
            self._apply_loaded_graph(graph)
            self._project_path = None
            self._mark_modified(True)
            self._set_status(_("Restored autosaved project"))
        self._delete_autosave()

    # ─── Filter browser ──────────────────────────────────────────────────────

    def _on_filter_selected(self, browser, payload):
        if not payload or not self._canvas:
            return
        if isinstance(payload, FilterDef):
            text = f"filter:{payload.engine}:{payload.name}"
        else:
            text = payload
        if self._canvas._drop_target:
            alloc = self._canvas.get_allocation()
            x, y = alloc.width / 2, alloc.height / 2
            set_pending_drag_text(text)
            self._canvas._on_drop(self._canvas._drop_target, text, x, y)
        if getattr(self, '_split_view', None) and self._split_view.get_collapsed():
            self._split_view.set_show_content(True)

    def _on_search_changed(self, entry):
        if self._filter_browser:
            self._filter_browser.set_filter(entry.get_text())

    def _on_search_toggle(self, button):
        if self._search_revealer:
            self._search_revealer.set_reveal_child(button.get_active())

    # ─── Node graph management ────────────────────────────────────────────────

    def _on_node_selected(self, canvas, node: Optional[Node]):
        if node:
            self._set_status(f"{node.label} ({node.node_type})")
        else:
            self._set_status("")

    def _on_graph_changed(self, canvas):
        self._mark_modified()
        self._update_render_button()
        self._setup_auto_save()
        self._clear_animation_result()

    # ─── Unsaved changes ─────────────────────────────────────────────────────

    def _mark_modified(self, modified: bool = True):
        self._modified = modified
        self._update_window_title()

    def _update_window_title(self):
        base = getattr(self, "_base_title", None) or _("Patchwork")
        content_base = getattr(self, "_content_base_title", None) or base
        self.set_title(f"{base} •" if self._modified else base)
        content_title = getattr(self, "_content_title", None)
        if content_title:
            content_title.set_title(
                f"{content_base} •" if self._modified else content_base)

    def _project_file_filter(self) -> Gtk.FileFilter:
        file_filter = Gtk.FileFilter()
        file_filter.set_name(_("Patchwork Projects"))
        file_filter.add_suffix("patch")
        return file_filter

    def _confirm_unsaved(self, on_proceed):
        """Run ``on_proceed`` once the user resolved unsaved changes.

        No changes: proceed at once.  Otherwise the shared Save/Discard/Cancel
        dialog decides: Cancel aborts, Discard proceeds, Save writes the
        project first (a cancelled save dialog aborts as well).
        """
        if not self._modified:
            on_proceed()
            return
        if self._close_dialog is not None or self._autosave_dialog is not None:
            return  # a prompt is already open; ignore the second request
        dialog = Adw.AlertDialog(
            heading=_("Save Changes?"),
            body=_("This project has unsaved changes. Save them before continuing?"),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("discard", _("Discard"))
        dialog.add_response("save", _("Save"))
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")
        self._close_dialog = dialog
        self._pending_confirm_action = on_proceed
        dialog.connect("response", self._on_unsaved_response)
        dialog.present(self)

    def _on_unsaved_response(self, dialog, response: str):
        if self._close_dialog is None:
            return  # already resolved (closing the dialog also reports 'cancel')
        on_proceed = self._pending_confirm_action
        self._close_dialog = None
        self._pending_confirm_action = None
        if on_proceed is None:
            return
        if response == "discard":
            on_proceed()
        elif response == "save":
            self._save_before_action(on_proceed)

    def _save_before_action(self, on_proceed):
        """Save the project first, then continue; a cancelled dialog aborts."""
        if self._project_path:
            if self._save_to_path(self._project_path):
                on_proceed()
            return

        def saved(path: str):
            if self._save_to_path(path):
                on_proceed()

        self._show_save_dialog(saved)

    def _show_save_dialog(self, on_done):
        """Ask for a destination path, then call ``on_done(path)``."""
        dialog = Gtk.FileDialog(
            title=_("Save Project"),
            default_filter=self._project_file_filter(),
            modal=True,
        )

        def response(dlg, result):
            try:
                file = dlg.save_finish(result)
            except GLib.Error as e:
                if e.domain != "gtk-dialog-error-quark":
                    self._show_error(str(e))
                return
            except Exception as e:
                self._show_error(str(e))
                return
            if not file:
                return
            path = file.get_path()
            if not path.endswith(".patch"):
                path += ".patch"
            on_done(path)

        dialog.save(self, None, response)

    def _save_to_path(self, path: str) -> bool:
        try:
            self._save_patchwork_to_path(path, self._graph)
        except Exception as e:
            self._show_error(str(e))
            return False
        self._project_path = path
        self._mark_modified(False)
        self._delete_autosave()
        self._set_status(_("Project saved"))
        return True

    def _on_close_request(self, *_args) -> bool:
        """Ask before closing a project with unsaved changes."""
        if not self._modified:
            self._delete_autosave()
            return False
        self._confirm_unsaved(self._finish_close)
        return True

    def _finish_close(self):
        self._modified = False
        self._delete_autosave()
        # The Save/Discard dialog may still be on screen; closing the window
        # while it is presented is ignored, so close once it is gone.
        GLib.idle_add(self._close_window)

    def _close_window(self) -> bool:
        self.close()
        return False

    # ─── New project ─────────────────────────────────────────────────────────

    def _on_new_project(self, action=None, param=None):
        self._confirm_unsaved(self._new_project)

    def _new_project(self):
        if self._canvas:
            self._canvas.clear_all()
            self._canvas.reset_history()
        self._pending_graph = None
        self._missing_images = []
        self._project_path = None
        self._mark_modified(False)
        self._set_status(_("New project"))

    def _update_render_button(self):
        order = self._graph.topological_sort()
        has_output = any(isinstance(n, OutputNode) for n in self._graph.nodes.values())
        can_render = len(order) > 0 and has_output
        if self._render_button:
            if self._render_active:
                self._render_button.set_sensitive(True)
                self._render_button.set_icon_name("media-playback-pause-symbolic")
                self._render_button.set_tooltip_text(_("Abort rendering"))
            else:
                self._render_button.set_sensitive(can_render)
                self._render_button.set_icon_name("media-playback-start-symbolic")
                self._render_button.set_tooltip_text(_("Render the node graph"))

    # ─── Open image ───────────────────────────────────────────────────────────

    def _on_open_clicked(self, button):
        file_filter = Gtk.FileFilter()
        file_filter.set_name(_("Images"))
        for ext in [
            "image/png", "image/jpeg", "image/tiff", "image/bmp",
            "image/webp", "image/gif", "image/x-portable-pixmap",
        ]:
            file_filter.add_mime_type(ext)

        dialog = Gtk.FileDialog(
            title=_("Open Image"),
            default_filter=file_filter,
            modal=True,
        )
        dialog.open(self, None, self._on_open_response)

    def _on_open_response(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if file:
                path = file.get_path()
                try:
                    GdkPixbuf.Pixbuf.new_from_file(path)
                except Exception as e:
                    self._show_error(str(e))
                    return

                if self._export_button:
                    self._export_button.set_sensitive(False)

                self._mark_modified()
                self._set_status(f"{Path(path).name} loaded")

                found = None
                for n in self._graph.nodes.values():
                    if isinstance(n, InputNode) and n.file_path is None:
                        found = n
                        break
                if found:
                    found.file_path = path
                    if self._canvas:
                        widget = self._canvas.get_node_widget(found.id)
                        if widget:
                            widget.queue_draw()
                        self._canvas.update_node_display(found.id)
                else:
                    nid = _generate_id()
                    node = InputNode(nid, 0, 0)
                    node.file_path = path
                    self._canvas.add_node(node)
                    self._canvas.update_node_display(nid)

                    existing_out = None
                    for n in self._graph.nodes.values():
                        if isinstance(n, OutputNode):
                            existing_out = n
                            break

                    if existing_out is None:
                        out_id = _generate_id()
                        out = OutputNode(out_id, 0, 0)
                        self._canvas.add_node(out)
                        out_id_to_use = out_id

                        def center_pair():
                            alloc = self._canvas.get_allocation()
                            if alloc.width <= 1 or node.width <= 0 or out.width <= 0:
                                return True
                            cx, cy = self._canvas._screen_to_graph(
                                alloc.width / 2, alloc.height / 2
                            )
                            dd = 80
                            node.x = cx - dd / 2 - node.width
                            node.y = cy - node.height / 2
                            out.x = cx + dd / 2
                            out.y = cy - out.height / 2
                            self._canvas._update_all_positions()
                            self._canvas.queue_gl_render()
                            return False
                        GLib.idle_add(center_pair)
                    else:
                        out_id_to_use = existing_out.id

                        def center_single():
                            alloc = self._canvas.get_allocation()
                            if alloc.width <= 1 or node.width <= 0:
                                return True
                            cx, cy = self._canvas._screen_to_graph(
                                alloc.width / 2, alloc.height / 2
                            )
                            node.x = cx - node.width / 2
                            node.y = cy - node.height / 2
                            self._canvas._update_all_positions()
                            self._canvas.queue_gl_render()
                            return False
                        GLib.idle_add(center_single)

                    if self._canvas:
                        edge = self._graph.add_edge(nid, "image", out_id_to_use, "image")
                        if edge:
                            self._canvas._update_all_port_colors()
                            self._canvas.queue_gl_render()

                self._update_render_button()
        except GLib.Error as e:
            if e.domain != "gtk-dialog-error-quark":
                self._show_error(str(e))

    def _on_input_node_open(self, canvas, node_id: str):
        node = self._graph.get_node(node_id)
        if not node or not isinstance(node, (InputNode, VideoInputNode, RawInputNode)):
            return
        is_raw = isinstance(node, RawInputNode)
        if is_raw:
            dialog = Gtk.FileDialog(
                title=_("Select Raw File"),
                modal=True,
            )
        elif isinstance(node, VideoInputNode):
            file_filter = Gtk.FileFilter()
            file_filter.set_name(_("Videos"))
            for mime in ["video/mp4", "video/webm", "video/ogg", "video/quicktime",
                         "video/x-matroska", "video/mpeg", "video/avi"]:
                file_filter.add_mime_type(mime)
            dialog = Gtk.FileDialog(
                title=_("Select Video for Input"),
                default_filter=file_filter,
                modal=True,
            )
        else:
            file_filter = Gtk.FileFilter()
            file_filter.set_name(_("Images"))
            for ext in [
                "image/png", "image/jpeg", "image/tiff", "image/bmp",
                "image/webp", "image/gif", "image/x-portable-pixmap",
            ]:
                file_filter.add_mime_type(ext)
            dialog = Gtk.FileDialog(
                title=_("Select Image for Input"),
                default_filter=file_filter,
                modal=True,
            )
        dialog.open(self, None, lambda d, r: self._on_input_node_response(node, d, r))

    def _on_input_node_response(self, node, dialog, result):
        try:
            file = dialog.open_finish(result)
            if file:
                path = file.get_path()
                if isinstance(node, InputNode):
                    try:
                        GdkPixbuf.Pixbuf.new_from_file(path)
                    except Exception as e:
                        self._show_error(str(e))
                        return
                    if self._export_button:
                        self._export_button.set_sensitive(False)
                node.file_path = path
                if self._canvas:
                    self._canvas.update_node_display(node.id)
                    self._canvas.queue_gl_render()
                self._mark_modified()
                self._set_status(f"{Path(path).name} loaded")
        except GLib.Error as e:
            if e.domain != "gtk-dialog-error-quark":
                self._show_error(str(e))

    # ─── Project save / load ─────────────────────────────────────────────────

    @staticmethod
    def _save_patchwork_to_path(path: str, graph):
        import json, zipfile, io
        data = graph.to_dict()
        input_nodes = [n for n in graph.nodes.values()
                       if isinstance(n, InputNode) and n.file_path]
        if input_nodes:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("graph.json", json.dumps(data, indent=2))
                for n in input_nodes:
                    p = Path(n.file_path)
                    if p.exists():
                        zf.write(str(p), f"images/{n.id}{p.suffix}")
            with open(path, "wb") as f:
                f.write(buf.getvalue())
        else:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)

    @staticmethod
    def _load_patchwork_from_path(path: str) -> tuple:
        import json, zipfile
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path, "r") as zf:
                data = json.loads(zf.read("graph.json"))
                stem = Path(path).stem
                cache_dir = Path.home() / ".cache" / "patchwork" / "packed" / stem
                cache_dir.mkdir(parents=True, exist_ok=True)
                for name in zf.namelist():
                    if name.startswith("images/") and not name.endswith("/"):
                        (cache_dir / Path(name).name).write_bytes(zf.read(name))
                return data, cache_dir
        else:
            with open(path, "r") as f:
                data = json.load(f)
            return data, None

    def _on_open_project(self, action, param):
        self._confirm_unsaved(self._show_open_dialog)

    def _show_open_dialog(self):
        dialog = Gtk.FileDialog(
            title=_("Open Project"),
            default_filter=self._project_file_filter(),
            modal=True,
        )
        dialog.open(self, None, self._on_open_project_response)

    def _rebind_packed_images(self, graph, pack_dir):
        """Point input nodes at the images unpacked from a project archive."""
        if not pack_dir:
            return
        for n in graph.nodes.values():
            if isinstance(n, InputNode) and n.file_path:
                cached = pack_dir / f"{n.id}{Path(n.file_path).suffix}"
                if cached.exists():
                    n.file_path = str(cached)

    def _on_open_project_response(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if not file:
                return
            self._project_path = file.get_path()
            data, pack_dir = self._load_patchwork_from_path(file.get_path())
            if not isinstance(data, dict) or data.get("version") != 1:
                self._show_error(_("Invalid project file"))
                return
            graph = NodeGraph.from_dict(data, self._filter_def_map)

            self._rebind_packed_images(graph, pack_dir)

            missing = [
                n for n in graph.nodes.values()
                if isinstance(n, InputNode) and n.file_path and not os.path.exists(n.file_path)
            ]

            if missing:
                self._pending_graph = graph
                self._missing_images = missing
                self._prompt_next_missing_image()
            else:
                self._apply_loaded_graph(graph)

        except GLib.Error as e:
            if e.domain != "gtk-dialog-error-quark":
                self._show_error(str(e))
        except Exception as e:
            self._show_error(str(e))

    def _apply_loaded_graph(self, graph):
        if self._canvas:
            self._canvas.clear_all()
            for n in graph.nodes.values():
                self._canvas.add_node(n)
            for e in graph.edges:
                self._canvas._graph._edges.append(e)
            self._canvas._update_all_port_colors()
            self._canvas._fit_content()
            self._canvas.queue_gl_render()
            self._canvas.emit("graph-changed")
            self._canvas.reset_history()
        self._mark_modified(False)
        self._set_status(_("Project loaded"))
        self._update_render_button()

    def _prompt_next_missing_image(self):
        if not self._missing_images:
            self._apply_loaded_graph(self._pending_graph)
            self._pending_graph = None
            return
        node = self._missing_images[0]
        file_filter = Gtk.FileFilter()
        file_filter.set_name(_("Images"))
        for ext in [
            "image/png", "image/jpeg", "image/tiff", "image/bmp",
            "image/webp", "image/gif", "image/x-portable-pixmap",
        ]:
            file_filter.add_mime_type(ext)
        dialog = Gtk.FileDialog(
            title=_("Locate image for '{0}'").format(Path(node.file_path).name),
            default_filter=file_filter,
            modal=True,
        )
        dialog.open(self, None, self._on_locate_image_response)

    def _on_locate_image_response(self, dlg, result):
        try:
            file = dlg.open_finish(result)
            if file:
                node = self._missing_images[0]
                node.file_path = file.get_path()
                self._missing_images.pop(0)
            else:
                self._missing_images.pop(0)
        except GLib.Error:
            if self._missing_images:
                self._missing_images.pop(0)
        self._prompt_next_missing_image()

    def _on_save_project(self, action, param):
        self._show_save_dialog(self._save_to_path)

    # ─── Render ───────────────────────────────────────────────────────────────

    def _is_animation_graph(self) -> bool:
        return any(
            isinstance(n, (TimeNode, VideoInputNode))
            for n in self._graph.nodes.values()
        )

    def _animation_settings(self) -> AnimationSettings:
        fps = 12
        frame_count = 24
        for n in self._graph.nodes.values():
            if isinstance(n, TimeNode):
                fps = int(n.fps) if n.fps else fps
                frame_count = int(n.length) if n.length else frame_count
                break
        else:
            for n in self._graph.nodes.values():
                if isinstance(n, VideoInputNode) and n.file_path:
                    info = self._ffmpeg.probe(n.file_path)
                    if info:
                        if info.get("fps"):
                            fps = max(1, int(round(info["fps"])))
                        if info.get("frame_count"):
                            frame_count = info["frame_count"]
                    break
        frame_count = max(1, frame_count)
        fps = max(1, fps)
        return AnimationSettings(
            frame_count=frame_count,
            fps=fps,
            out_format=FORMAT_MP4,
            out_path="",
        )

    def _on_render_clicked(self, button):
        if self._render_active:
            self._abort_render()
            return

        self._clear_animation_result()
        self._render_active = True
        self._render_cancel_event = Event()
        if self._render_button:
            self._render_button.set_sensitive(True)
            self._render_button.set_icon_name("media-playback-pause-symbolic")
            self._render_button.set_tooltip_text(_("Abort rendering"))
        self._set_status(_("Rendering graph..."))
        self._status_spinner.set_spinning(True)
        self._progress_revealer.set_reveal_child(True)
        self._progress_bar.pulse()

        graph = self._graph
        timeout = self._config.processing_timeout
        cancel_event = self._render_cancel_event

        if self._is_animation_graph():
            settings = self._animation_settings()

            def work():
                def progress(msg):
                    GLib.idle_add(self._set_status, msg)
                try:
                    result = render_frames(
                        graph, self._executor, settings,
                        progress_callback=progress, timeout=timeout,
                        cancel_event=cancel_event,
                    )
                except Exception as e:
                    result = ProcessResult(error=str(e))
                GLib.idle_add(self._finish_animation_render, result, settings)
        else:
            fmt = "png"

            def work():
                def progress(msg):
                    GLib.idle_add(self._set_status, msg)
                try:
                    result = self._executor.execute(graph, fmt, progress, timeout=timeout,
                                                    cancel_event=cancel_event)
                except Exception as e:
                    result = ProcessResult(error=str(e))
                GLib.idle_add(self._finish_render, result)

        Thread(target=work, daemon=True).start()

    def _abort_render(self):
        self._render_active = False
        if self._render_cancel_event is not None:
            self._render_cancel_event.set()
        self._render_cancel_event = None
        self._set_status(_("Aborting render..."))
        self._update_render_button()

    def _finish_animation_render(self, result: ProcessResult, settings: AnimationSettings):
        self._progress_revealer.set_reveal_child(False)
        self._status_spinner.set_spinning(False)
        self._render_active = False
        self._render_cancel_event = None
        self._update_render_button()
        if self._canvas:
            self._canvas._update_all_port_colors()
            for n in list(self._graph.nodes.values()):
                if isinstance(n, TimeNode):
                    self._canvas.update_node_display(n.id)

        if result.cancelled:
            settings.cleanup()
            self._set_status(_("Rendering cancelled"))
            return

        if not result.success:
            settings.cleanup()
            self._set_status(_("Animation render failed"))
            details = ""
            if result.stdout:
                details += result.stdout + "\n"
            if result.stderr:
                details += result.stderr
            if not details:
                details = result.error or ""
            if details:
                self._show_output(details.strip())
            return

        self._result_animation = settings
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(settings.frames[-1])
        except Exception:
            pixbuf = None
        self._result_pixbuf = pixbuf
        self._result_pixbufs = {}
        fps = int(settings.fps) or 1
        if self._canvas:
            for n in self._graph.nodes.values():
                if isinstance(n, OutputNode):
                    self._canvas.set_node_animation(n.id, settings.frames, fps)
                    self._result_pixbufs[n.id] = pixbuf
        if self._export_button:
            self._export_button.set_sensitive(True)

        self._set_status(_("Animation rendered ({} frames). Use Export to save.").format(len(settings.frames)))
        toast = Adw.Toast(title=_("Animation rendered"), timeout=2)
        if self._toast_overlay:
            self._toast_overlay.add_toast(toast)

    def _finish_render(self, result: ProcessResult):
        self._progress_revealer.set_reveal_child(False)
        self._status_spinner.set_spinning(False)
        self._render_active = False
        self._render_cancel_event = None
        self._update_render_button()
        if self._canvas:
            self._canvas._update_all_port_colors()

        if result.cancelled:
            self._set_status(_("Rendering cancelled"))
            return

        if not result.success:
            self._set_status(_("Render failed"))
            details = ""
            if result.stdout:
                details += result.stdout + "\n"
            if result.stderr:
                details += result.stderr
            if not details:
                details = result.error or ""
            if details:
                self._show_output(details.strip())
            return

        try:
            self._result_pixbufs = {}
            first_path = result.output_path
            pixbuf = None

            if result.output_paths:
                for node_id, path in result.output_paths.items():
                    try:
                        p = GdkPixbuf.Pixbuf.new_from_file(path)
                        self._result_pixbufs[node_id] = p
                        if self._canvas:
                            self._canvas.set_output_thumbnail(node_id, p)
                        if pixbuf is None:
                            pixbuf = p
                            first_path = path
                    except Exception:
                        continue
                if pixbuf is None:
                    raise Exception("No valid output images")
            else:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(first_path)
                for n in self._graph.nodes.values():
                    if isinstance(n, OutputNode) and self._canvas:
                        self._canvas.set_output_thumbnail(n.id, pixbuf)
                        self._result_pixbufs[n.id] = pixbuf
                        break

            self._result_pixbuf = pixbuf
            if self._export_button:
                self._export_button.set_sensitive(True)

            # Update analysis node displays (no output port — must be done separately)
            if self._canvas and self._graph:
                for n in list(self._graph.nodes.values()):
                    if isinstance(n, (HistogramNode, WaveformMonitorNode, VectorscopeNode, FrequencyDomainNode, TimeNode)):
                        self._canvas.update_node_display(n.id)

            self._set_status(_("Render complete"))
            toast = Adw.Toast(title=_("Render complete"), timeout=2)
            if self._toast_overlay:
                self._toast_overlay.add_toast(toast)
        except Exception as e:
            self._show_error(str(e))

    # ─── Animation export ────────────────────────────────────────────────────

    _IMG_EXT = {
        "png": "png", "jpeg": "jpg", "webp": "webp", "tiff": "tif", "bmp": "bmp",
    }
    _IMG_MIME = {
        "png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp",
        "tiff": "image/tiff", "bmp": "image/bmp",
    }
    _EXT_TO_FORMAT = {
        ".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp",
        ".tif": "tiff", ".tiff": "tiff", ".bmp": "bmp",
    }

    def _on_animation_export(self, result: AnimationSettings):
        file_filter = Gtk.FileFilter()
        file_filter.set_name(_("Animation"))
        file_filter.add_suffix("mp4")
        file_filter.add_suffix("gif")
        chooser = Gtk.FileDialog(
            title=_("Export Animation"),
            default_filter=file_filter,
            modal=True,
            initial_name=_("animation.mp4"),
        )
        chooser.save(self, None, lambda d, r: self._on_animation_export_dest(result, d, r))

    def _on_animation_export_dest(self, anim, dialog, result):
        try:
            file = dialog.save_finish(result)
            if not file:
                return
            out_path = file.get_path() or ""
        except GLib.Error:
            return

        anim.out_path = out_path
        ext = (os.path.splitext(out_path)[1] or "").lower()
        if ext == ".gif":
            anim.out_format = FORMAT_GIF
        elif ext == ".mp4":
            anim.out_format = FORMAT_MP4
        else:
            anim.out_format = FORMAT_PNG_SEQUENCE
        if self._export_button:
            self._export_button.set_sensitive(False)
        self._set_status(_("Exporting animation..."))
        self._status_spinner.set_spinning(True)
        self._progress_revealer.set_reveal_child(True)
        self._progress_bar.pulse()

        def work():
            def progress(msg):
                GLib.idle_add(self._set_status, msg)
            res = mux_animation(self._ffmpeg, anim, progress_callback=progress)
            GLib.idle_add(self._finish_animation_export, res, anim)

        Thread(target=work, daemon=True).start()

    def _finish_animation_export(self, result: ProcessResult, anim: AnimationSettings):
        self._progress_revealer.set_reveal_child(False)
        self._status_spinner.set_spinning(False)
        if self._export_button:
            self._export_button.set_sensitive(True)

        if not result.success:
            self._set_status(_("Animation export failed"))
            details = ""
            if result.stdout:
                details += result.stdout + "\n"
            if result.stderr:
                details += result.stderr
            if not details:
                details = result.error or ""
            if details:
                self._show_output(details.strip())
            return

        self._set_status(_("Animation saved to {}").format(result.output_path))
        toast = Adw.Toast(title=_("Animation exported"), timeout=3)
        if self._toast_overlay:
            self._toast_overlay.add_toast(toast)

    # ─── Export ───────────────────────────────────────────────────────────────

    def _on_export_clicked(self, button):
        anim = getattr(self, "_result_animation", None)
        if anim and anim.frames:
            self._on_animation_export(anim)
            return
        if not self._result_pixbuf:
            return

        file_filter = Gtk.FileFilter()
        file_filter.set_name(_("Images"))
        for fmt in ("png", "jpeg", "webp", "tiff", "bmp"):
            file_filter.add_mime_type(self._IMG_MIME[fmt])

        dialog = Gtk.FileDialog(
            title=_("Export Result"),
            default_filter=file_filter,
            modal=True,
            initial_name=_("output.png"),
        )
        dialog.save(self, None, self._on_export_response)

    def _on_export_response(self, dialog, result):
        try:
            file = dialog.save_finish(result)
            if not file:
                return
            path = file.get_path()
            fmt = self._format_from_path(path)
            if fmt is None:
                fmt = "png"
            ext = "." + self._IMG_EXT[fmt]

            if len(self._result_pixbufs) > 1:
                base = os.path.splitext(path)[0]
                saved = []
                for i, (node_id, pixbuf) in enumerate(self._result_pixbufs.items()):
                    fname = f"{base}{ext}" if i == 0 else f"{base}_{i+1}{ext}"
                    pixbuf.savev(fname, fmt)
                    saved.append(fname)
                self._set_status(_("Saved {} files").format(len(saved)))
            else:
                if self._result_pixbuf:
                    self._result_pixbuf.savev(path, fmt)
                    self._set_status(_("Saved to {}").format(path))
        except GLib.Error as e:
            if e.domain != "gtk-dialog-error-quark":
                self._show_error(str(e))

    def _format_from_path(self, path: str) -> Optional[str]:
        ext = (os.path.splitext(path)[1] or "").lower()
        return self._EXT_TO_FORMAT.get(ext)

    # ─── Filter loading ───────────────────────────────────────────────────────

    def _load_filters(self):
        self._set_status(_("Loading filters..."))

        def load():
            gmic_f = []
            try:
                gf = self._gmic.list_filters()
                if gf:
                    gmic_f = gf
            except Exception:
                pass
            im_f = get_im_filters() if self._imagemagick.available else []
            return gmic_f, im_f

        def done(result):
            gmic_f, im_f = result
            self._finish_loading_filters(gmic_f + im_f)

        def work():
            result = load()
            GLib.idle_add(done, result)

        Thread(target=work, daemon=True).start()

    def _finish_loading_filters(self, all_f):
        """Populate browsers and offer the autosaved project, if any."""
        self._filter_def_map = {f"{f.engine}:{f.name}": f for f in all_f}
        if self._filter_browser:
            self._filter_browser.set_filters(all_f)
        if self._canvas:
            self._canvas.set_filter_defs(all_f)
        total = len(all_f)
        self._set_status(_("{} filters loaded").format(total) if total else _("No filters available"))
        self._maybe_offer_autosave()

    # ─── Utilities ────────────────────────────────────────────────────────────

    def _set_status(self, text: str):
        if self._status_label:
            self._status_label.set_text(text)

    def _show_error(self, message: str):
        self._set_status(f"Error: {message}")
        toast = Adw.Toast(title=message, timeout=3)
        if self._toast_overlay:
            self._toast_overlay.add_toast(toast)
        if self._output_box:
            self._output_box.set_visible(True)
        if self._output_paned:
            alloc = self._output_paned.get_allocation()
            if alloc and alloc.height > 100:
                self._output_paned.set_position(max(100, alloc.height - 250))

    def _show_output(self, text: str):
        cleaned = _strip_ansi(text)
        if self._output_text:
            buf = self._output_text.get_buffer()
            buf.set_text(cleaned)
            buf.move_mark_by_name("insert", buf.get_start_iter())
        if self._output_box:
            self._output_box.set_visible(True)
        if self._output_paned:
            alloc = self._output_paned.get_allocation()
            if alloc and alloc.height > 100:
                self._output_paned.set_position(max(100, alloc.height - 250))
