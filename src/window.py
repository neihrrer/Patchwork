import gettext
import os
import re
from pathlib import Path
from typing import Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")

from gi.repository import GLib, Gio, Gtk, Gdk, Adw, GdkPixbuf
from threading import Thread

from models.app_state import VALID_OUTPUT_FORMATS
from models.filter import FilterDef
from gmic.cli import GmicCLI
from imagemagick.cli import ImageMagickCLI
from imagemagick.filters import get_builtin_filters as get_im_filters
from nodes import (
    NodeGraph, InputNode, OutputNode, Node,
)
from widgets.node_editor import NodeCanvas
from widgets.filter_browser import FilterBrowser
from processing.graph_executor import GraphExecutor
from processing.runner import ProcessResult

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
        Path("/app/share/ring") / name,
    ]
    for p in paths:
        if p.exists():
            return str(p)
    return ""


def _generate_id() -> str:
    import uuid
    return uuid.uuid4().hex[:8]


class RingWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self._gmic = GmicCLI()
        self._imagemagick = ImageMagickCLI()
        self._graph = NodeGraph()
        self._executor = GraphExecutor(self._gmic, self._imagemagick)
        self._all_filter_defs: list[FilterDef] = []
        self._filter_def_map: dict[str, FilterDef] = {}

        self._canvas: Optional[NodeCanvas] = None
        self._filter_browser: Optional[FilterBrowser] = None
        self._current_pixbuf: Optional[GdkPixbuf.Pixbuf] = None
        self._result_pixbuf: Optional[GdkPixbuf.Pixbuf] = None
        self._result_pixbufs: dict[str, GdkPixbuf.Pixbuf] = {}
        self._output_format: str = "png"
        self._minimap_switch: Optional[Adw.SwitchRow] = None

        self._light_header_css = Gtk.CssProvider()
        self._light_header_css.load_from_data(b"""
            .node-header.input { background: #4CAF50; }
            .node-header.output { background: #EF5350; }
            .node-header.filter { background: #2196F3; }
            .node-header.blend { background: #FF9800; }
            .node-header.mask { background: #26A69A; }
            .node-header.opacity { background: #AB47BC; }
            .node-header.color { background: #00BCD4; }
            .node-header.coloring { background: #29B6F6; }
            .node-header.constant { background: #FFC107; }
            .node-header.add { background: #66BB6A; }
            .node-header.subtract { background: #E91E63; }
            .node-header.multiply { background: #1E88E5; }
            .node-header.divide { background: #F44336; }
        """)

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

        self._builder = builder
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
        self._output_scrolled = builder.get_object("output_scrolled")

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

        bp = builder.get_object("bp")
        if bp:
            self.add_breakpoint(bp)

        self._toast_overlay = Adw.ToastOverlay()
        split_view = builder.get_object("split_view")
        if split_view:
            self._toast_overlay.set_child(split_view)
            self.set_content(self._toast_overlay)

        self._setup_menu()
        self._setup_node_header_theme()

    def _setup_node_header_theme(self):
        style_mgr = Adw.StyleManager.get_default()
        self._update_node_header_theme(style_mgr)
        style_mgr.connect("notify::dark", self._update_node_header_theme)

    def _update_node_header_theme(self, manager, pspec=None):
        display = Gdk.Display.get_default()
        if not display:
            return
        if manager.get_dark():
            Gtk.StyleContext.remove_provider_for_display(display, self._light_header_css)
        else:
            Gtk.StyleContext.add_provider_for_display(
                display, self._light_header_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

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

    # ─── Menu / Preferences ─────────────────────────────────────────────────

    def _setup_menu(self):
        menu = Gio.Menu()
        menu.append(_("Open Project"), "win.open-project")
        menu.append(_("Save Project"), "win.save-project")
        menu.append(_("Preferences"), "win.preferences")
        if self._menu_button:
            self._menu_button.set_menu_model(menu)

        for name, handler, accel in [
            ("open-project", self._on_open_project, "<primary>o"),
            ("save-project", self._on_save_project, "<primary>s"),
            ("preferences", self._on_preferences, "<primary>comma"),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)
            app = self.get_application()
            if app:
                app.set_accels_for_action(f"win.{name}", [accel])



    def _on_preferences(self, action, param):
        dialog = Adw.PreferencesDialog()

        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title=_("Output"),
            description=_("Default image format for rendered results"),
        )
        formats = Gtk.StringList.new(VALID_OUTPUT_FORMATS)
        row = Adw.ComboRow(
            title=_("Output Format"),
            model=formats,
        )
        row.set_selected(VALID_OUTPUT_FORMATS.index(self._output_format))
        row.connect("notify::selected", self._on_output_format_changed)
        group.add(row)
        page.add(group)

        display_group = Adw.PreferencesGroup(title=_("Display"))
        grid_visible_row = Adw.SwitchRow(
            title=_("Disable Grid"),
            subtitle=_("Hide the background grid"),
        )
        if self._canvas:
            grid_visible_row.set_active(not self._canvas._grid_visible)
            grid_visible_row.connect("notify::active", self._on_grid_visible_changed)
        display_group.add(grid_visible_row)
        zoom_row = Adw.SwitchRow(
            title=_("Extended Zoom Range"),
            subtitle=_("Allows zooming from 25% to 1000% at the cost of performance"),
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

        dialog.add(page)
        dialog.present(self)

    def _on_extended_zoom_changed(self, row, pspec):
        if self._canvas:
            self._canvas.set_extended_zoom(row.get_active())

    def _on_grid_visible_changed(self, row, pspec):
        if self._canvas:
            self._canvas.set_grid_visible(not row.get_active())

    def _on_minimap_switch_changed(self, row, pspec):
        if self._canvas:
            self._canvas.set_minimap_visible(row.get_active())

    def _on_minimap_visibility_changed(self, minimap, pspec):
        if self._minimap_switch:
            self._minimap_switch.set_active(minimap.get_visible())

    def _on_output_format_changed(self, row, pspec):
        self._output_format = VALID_OUTPUT_FORMATS[row.get_selected()]

    # ─── Filter browser ──────────────────────────────────────────────────────

    def _on_filter_selected(self, browser, filter_def: Optional[FilterDef]):
        if not filter_def or not self._canvas:
            return
        if self._canvas._drop_target:
            alloc = self._canvas.get_allocation()
            x, y = alloc.width / 2, alloc.height / 2
            self._canvas._on_drop(self._canvas._drop_target, f"filter:{filter_def.engine}:{filter_def.name}", x, y)

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
        self._update_render_button()

    def _update_render_button(self):
        order = self._graph.topological_sort()
        has_output = any(isinstance(n, OutputNode) for n in self._graph.nodes.values())
        can_render = len(order) > 0 and has_output
        if self._render_button:
            self._render_button.set_sensitive(can_render)

    # ─── Open image ───────────────────────────────────────────────────────────

    _open_dialog_result_path: Optional[str] = None

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
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
                except Exception as e:
                    self._show_error(str(e))
                    return

                self._current_pixbuf = pixbuf

                if self._export_button:
                    self._export_button.set_sensitive(False)

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
                    self._open_dialog_result_path = path
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
        if not node or not isinstance(node, InputNode):
            return
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

    def _on_input_node_response(self, node: InputNode, dialog, result):
        try:
            file = dialog.open_finish(result)
            if file:
                path = file.get_path()
                try:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
                except Exception as e:
                    self._show_error(str(e))
                    return
                self._current_pixbuf = pixbuf
                if self._export_button:
                    self._export_button.set_sensitive(False)
                node.file_path = path
                if self._canvas:
                    self._canvas.update_node_display(node.id)
                    self._canvas.queue_gl_render()
                self._set_status(f"{Path(path).name} loaded")
        except GLib.Error as e:
            if e.domain != "gtk-dialog-error-quark":
                self._show_error(str(e))

    # ─── Project save / load ─────────────────────────────────────────────────

    def _on_open_project(self, action, param):
        file_filter = Gtk.FileFilter()
        file_filter.set_name(_("Ring Projects"))
        file_filter.add_suffix("ring")

        dialog = Gtk.FileDialog(
            title=_("Open Project"),
            default_filter=file_filter,
            modal=True,
        )
        dialog.open(self, None, self._on_open_project_response)

    def _on_open_project_response(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if not file:
                return
            import json
            data = json.loads(file.get_path() and open(file.get_path(), "r").read() or "{}")
            if not isinstance(data, dict) or data.get("version") != 1:
                self._show_error(_("Invalid project file"))
                return
            graph = NodeGraph.from_dict(data, self._filter_def_map)
            if self._canvas:
                self._canvas.clear_all()
                for n in graph.nodes.values():
                    self._canvas.add_node(n)
                for e in graph.edges:
                    self._canvas._graph._edges.append(e)
                    if hasattr(self._canvas, "_update_all_port_colors"):
                        self._canvas._update_all_port_colors()
                self._canvas._fit_content()
                self._canvas.queue_gl_render()
                self._canvas.emit("graph-changed")
            self._set_status(_("Project loaded"))
            self._update_render_button()
        except GLib.Error as e:
            if e.domain != "gtk-dialog-error-quark":
                self._show_error(str(e))
        except Exception as e:
            self._show_error(str(e))

    def _on_save_project(self, action, param):
        file_filter = Gtk.FileFilter()
        file_filter.set_name(_("Ring Projects"))
        file_filter.add_suffix("ring")

        dialog = Gtk.FileDialog(
            title=_("Save Project"),
            default_filter=file_filter,
            modal=True,
        )
        dialog.save(self, None, self._on_save_project_response)

    def _on_save_project_response(self, dialog, result):
        try:
            file = dialog.save_finish(result)
            if not file:
                return
            import json
            data = self._graph.to_dict()
            path = file.get_path()
            if not path.endswith(".ring"):
                path += ".ring"
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            self._set_status(_("Project saved"))
        except GLib.Error as e:
            if e.domain != "gtk-dialog-error-quark":
                self._show_error(str(e))
        except Exception as e:
            self._show_error(str(e))

    # ─── Render ───────────────────────────────────────────────────────────────

    def _on_render_clicked(self, button):
        if self._render_button:
            self._render_button.set_sensitive(False)
        self._set_status(_("Rendering graph..."))
        self._status_spinner.set_spinning(True)
        self._progress_revealer.set_reveal_child(True)
        self._progress_bar.pulse()

        graph = self._graph
        fmt = self._output_format

        def work():
            def progress(msg):
                GLib.idle_add(self._set_status, msg)
            result = self._executor.execute(graph, fmt, progress)
            GLib.idle_add(self._finish_render, result)

        Thread(target=work, daemon=True).start()

    def _finish_render(self, result: ProcessResult):
        self._progress_revealer.set_reveal_child(False)
        self._status_spinner.set_spinning(False)
        self._update_render_button()

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
            self._set_status(_("Render complete"))
            toast = Adw.Toast(title=_("Render complete"), timeout=2)
            if self._toast_overlay:
                self._toast_overlay.add_toast(toast)
        except Exception as e:
            self._show_error(str(e))

    # ─── Export ───────────────────────────────────────────────────────────────

    def _on_export_clicked(self, button):
        if not self._result_pixbuf:
            return

        fmt = self._output_format
        ext = fmt
        ext_map = {"jpeg": "jpg"}
        ext = ext_map.get(fmt, fmt)
        mime_map = {
            "png": "image/png",
            "jpeg": "image/jpeg",
            "tiff": "image/tiff",
            "bmp": "image/bmp",
            "webp": "image/webp",
        }

        file_filter = Gtk.FileFilter()
        file_filter.set_name(_("{} Image").format(fmt.upper()))
        file_filter.add_mime_type(mime_map.get(fmt, "image/png"))

        dialog = Gtk.FileDialog(
            title=_("Export Result"),
            default_filter=file_filter,
            modal=True,
            initial_name=f"output.{ext}",
        )
        dialog.save(self, None, self._on_export_response)

    def _on_export_response(self, dialog, result):
        try:
            file = dialog.save_finish(result)
            if not file:
                return
            fmt = self._output_format
            path = file.get_path()

            if len(self._result_pixbufs) > 1:
                base, ext = os.path.splitext(path)
                if not ext:
                    ext = f".{fmt}"
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
            all_f = gmic_f + im_f
            self._all_filter_defs = all_f
            self._filter_def_map = {f"{f.engine}:{f.name}": f for f in all_f}
            if self._filter_browser:
                self._filter_browser = FilterBrowser(
                    self._builder.get_object("filter_list"), all_f
                )
                self._filter_browser.connect("filter-selected", self._on_filter_selected)
            if self._canvas:
                self._canvas.set_filter_defs(all_f)
            total = len(all_f)
            self._set_status(_("{} filters loaded").format(total) if total else _("No filters available"))

        def work():
            result = load()
            GLib.idle_add(done, result)

        Thread(target=work, daemon=True).start()

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
