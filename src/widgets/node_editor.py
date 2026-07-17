import math
import gettext
from typing import Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import GObject, Gtk, Gdk, GdkPixbuf, GLib, Gsk, Graphene, Adw

try:
    _ = gettext.gettext
except Exception:
    _ = lambda s: s

from nodes import (
    Node, NodeGraph, Edge, Port, PortDirection, PortType, FilterNode, InputNode, OutputNode, BlendNode,
    OpacityNode, ColoringNode, MaskNode,
    ConstantNode, AddNode, SubtractNode, MultiplyNode, DivideNode,
    CeilNode, FloorNode, RoundNode, SumNode, ProductNode,
    LabelNode, CommentNode,
)
from nodes.node_types import LABEL_COLORS
from models.filter import FilterDef, ParamKind
from .filter_browser import get_pending_drag_text, peek_pending_drag_text

CURVE_SEGMENTS = 48


def _compute_bezier_segments(x1, y1, x2, y2, segments=CURVE_SEGMENTS):
    dx = abs(x2 - x1)
    ctrl_offset = max(dx * 0.4, 60.0)
    p0, p3 = (x1, y1), (x2, y2)
    p1 = (x1 + ctrl_offset, y1)
    p2 = (x2 - ctrl_offset, y2)
    pts = []
    for i in range(segments + 1):
        t = i / segments
        u = 1 - t
        x = u*u*u*p0[0] + 3*u*u*t*p1[0] + 3*u*t*t*p2[0] + t*t*t*p3[0]
        y = u*u*u*p0[1] + 3*u*u*t*p1[1] + 3*u*t*t*p2[1] + t*t*t*p3[1]
        pts.extend([x, y])
    return pts


def _compute_numeric_value(node_id: str, graph: NodeGraph, visited: set = None):
    if visited is None:
        visited = set()
    if node_id in visited:
        return None
    visited.add(node_id)

    node = graph.get_node(node_id)
    if not node:
        return None

    if isinstance(node, ConstantNode):
        return node.value

    if isinstance(node, (AddNode, SubtractNode, MultiplyNode, DivideNode, SumNode, ProductNode)):
        a_edge = graph.get_connected_input(node_id, "a")
        b_edge = graph.get_connected_input(node_id, "b")
        a = _compute_numeric_value(a_edge.src_node, graph, visited) if a_edge else 0.0
        b = _compute_numeric_value(b_edge.src_node, graph, visited) if b_edge else 0.0
        if isinstance(node, (AddNode, SumNode)):
            return a + b
        if isinstance(node, SubtractNode):
            return a - b
        if isinstance(node, (MultiplyNode, ProductNode)):
            return a * b
        if isinstance(node, DivideNode):
            return a / b if b != 0 else None
        return None

    if isinstance(node, CeilNode):
        a_edge = graph.get_connected_input(node_id, "a")
        a = _compute_numeric_value(a_edge.src_node, graph, visited) if a_edge else 0.0
        return math.ceil(a)

    if isinstance(node, FloorNode):
        a_edge = graph.get_connected_input(node_id, "a")
        a = _compute_numeric_value(a_edge.src_node, graph, visited) if a_edge else 0.0
        return math.floor(a)

    if isinstance(node, RoundNode):
        a_edge = graph.get_connected_input(node_id, "a")
        a = _compute_numeric_value(a_edge.src_node, graph, visited) if a_edge else 0.0
        return round(a)

    return None


_NODE_PREVIEW_INFO = {
    "blend:": (_("Blend"), "blend"),
    "opacity:": (_("Opacity"), "opacity"),
    "mask:": (_("Mask"), "mask"),
    "coloring:": (_("Coloring"), "coloring"),
    "input:": (_("Input"), "input"),
    "output:": (_("Output"), "output"),
    "constant:": (_("Constant"), "constant"),
    "add:": (_("Add"), "add"),
    "subtract:": (_("Subtract"), "subtract"),
    "multiply:": (_("Multiply"), "multiply"),
    "divide:": (_("Divide"), "divide"),
    "ceil:": (_("Ceil"), "ceil"),
    "floor:": (_("Floor"), "floor"),
    "round:": (_("Round"), "round"),
    "sum:": (_("Sum"), "sum"),
    "product:": (_("Product"), "product"),
    "label:": (_("Label"), "label"),
    "comment:": (_("Comment"), "comment"),
}


class DragPreview(Gtk.Box):
    __gtype_name__ = "DragPreview"

    def __init__(self, label: str, css_class: str):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("node-widget")
        self.set_opacity(0.5)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.set_css_classes(["node-header", css_class])
        header.set_hexpand(True)
        title = Gtk.Label(label=label, xalign=0, hexpand=True)
        title.set_css_classes(["node-title"])
        header.append(title)
        self.append(header)

        body = Gtk.Box()
        body.set_size_request(180, 40)
        self.append(body)


class PortWidget(Gtk.Widget):
    __gtype_name__ = "PortWidget"

    def __init__(self, port: Port, node_widget: "NodeWidget"):
        super().__init__()
        self._port = port
        self._node_widget = node_widget
        self._canvas = node_widget._canvas
        self._hovered = False
        self._connected = False
        self._center_x: float = 0.0
        self._center_y: float = 0.0
        self._offset_x: float = 0.0
        self._offset_y: float = 0.0
        self.set_size_request(14, 14)
        self.set_valign(Gtk.Align.CENTER)
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.set_css_classes(["port-circle"])

        self._drag = Gtk.GestureDrag(button=1)
        self._drag.connect("drag-begin", self._on_drag_begin)
        self._drag.connect("drag-update", self._on_drag_update)
        self._drag.connect("drag-end", self._on_drag_end)
        self.add_controller(self._drag)

        enter = Gtk.EventControllerMotion()
        enter.connect("enter", lambda c, x, y: self._set_hover(True))
        enter.connect("leave", lambda c: self._set_hover(False))
        self.add_controller(enter)

    @property
    def port(self):
        return self._port

    @property
    def node_widget(self):
        return self._node_widget

    @property
    def center_x(self) -> float:
        return self._center_x

    @property
    def center_y(self) -> float:
        return self._center_y

    def set_connected(self, connected: bool):
        self._connected = connected
        if connected:
            self.add_css_class("connected")
        else:
            self.remove_css_class("connected")
        self.queue_draw()

    def update_center(self):
        alloc = self.get_allocation()
        x = alloc.x + alloc.width / 2
        y = alloc.y + alloc.height / 2
        p = self.get_parent()
        while p is not None and not isinstance(p, NodeWidget):
            pa = p.get_allocation()
            x += pa.x
            y += pa.y
            p = p.get_parent()
        if isinstance(p, NodeWidget):
            self._offset_x = x
            self._offset_y = y
            self._center_x = p._screen_x + x
            self._center_y = p._screen_y + y
        else:
            self._center_x = x
            self._center_y = y

    def _set_hover(self, hover: bool):
        self._hovered = hover
        self.queue_draw()

    def _on_drag_begin(self, gesture, start_x, start_y):
        if self._canvas:
            self.update_center()
            self._canvas.start_port_drag(self)

    def _on_drag_update(self, gesture, offset_x, offset_y):
        if self._canvas:
            self._canvas.update_port_drag(offset_x, offset_y)

    def _on_drag_end(self, gesture, offset_x, offset_y):
        if self._canvas:
            self._canvas.end_port_drag(offset_x, offset_y)

    def do_snapshot(self, snapshot):
        w, h = self.get_width(), self.get_height()
        if w < 3 or h < 3:
            return
        cr = max(1, int(min(w, h) / 3))
        bw = max(1, int(min(w, h) / 14))
        overhang = int(w * 0.4)
        shift_x = -overhang if self._port.direction == PortDirection.INPUT else overhang

        if self._canvas and self._canvas._selected_port is self:
            color = Gdk.RGBA(0.9, 0.7, 0.1, 1.0)
        elif self._hovered:
            color = Gdk.RGBA(0.8, 0.8, 0.8, 1.0)
        elif self._connected:
            color = Gdk.RGBA(0.35, 0.6, 0.95, 1.0)
        else:
            color = Gdk.RGBA(0.53, 0.53, 0.53, 1.0)

        if self._node_widget and self._node_widget._selected:
            border_color = Gdk.RGBA(0.208, 0.518, 0.894, 1.0)
        else:
            border_color = Gdk.RGBA(0.333, 0.333, 0.333, 1.0)

        rect = Graphene.Rect().init(1, 1, w - 2, h - 2)
        rounded = Gsk.RoundedRect()
        rounded.init_from_rect(rect, cr)

        snapshot.save()
        snapshot.translate(Graphene.Point().init(shift_x, 0))

        snapshot.push_rounded_clip(rounded)
        snapshot.append_color(border_color, rect)
        snapshot.pop()

        inner_rect = Graphene.Rect().init(
            1 + bw, 1 + bw, w - 2 - 2 * bw, h - 2 - 2 * bw
        )
        inner_rounded = Gsk.RoundedRect()
        inner_rounded.init_from_rect(inner_rect, max(1, cr - bw))
        snapshot.push_rounded_clip(inner_rounded)
        snapshot.append_color(color, inner_rect)
        snapshot.pop()

        snapshot.restore()


class NodeWidget(Gtk.Box):
    __gtype_name__ = "NodeWidget"

    def __init__(self, node: Node, canvas: "NodeCanvas"):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._node = node
        self._canvas = canvas
        self._selected = False
        self._input_port_widgets: dict[str, PortWidget] = {}
        self._output_port_widgets: dict[str, PortWidget] = {}
        self._param_controls: list[Gtk.Widget] = []
        self._ctrl_widgets: list[Gtk.Widget] = []
        self._inline_numeric_ports: set[str] = set()
        self._port_spin_buttons: dict[str, Gtk.SpinButton] = {}
        self._thumb_box: Optional[Gtk.Box] = None
        self._thumb_picture: Optional[Gtk.Picture] = None
        self._image_aspect: Optional[float] = None
        self._resize_start_w = 0
        self._resize_start_h = 0
        self._resize_start_px = 0.0
        self._resize_start_py = 0.0
        self._min_node_w = 180
        self._min_node_h = 160
        self._has_image = False
        self._logical_w = int(self._node.width or 240)
        self._logical_h = int(self._node.height or 200)
        self._screen_x = 0.0
        self._screen_y = 0.0

        self.set_css_classes(["node-widget"])
        self._build_ui()

        self._drag = Gtk.GestureDrag(button=1)
        self._drag.connect("drag-begin", self._on_drag_begin)
        self._drag.connect("drag-update", self._on_drag_update)
        self._drag.connect("drag-end", self._on_drag_end)
        self.add_controller(self._drag)

        self._click = Gtk.GestureClick(button=1)
        self._click.connect("pressed", self._on_click)
        self.add_controller(self._click)

        self._right_click = Gtk.GestureClick(button=3)
        self._right_click.connect("pressed", self._on_right_click)
        self.add_controller(self._right_click)

    @property
    def graph_node(self):
        return self._node

    @property
    def selected(self):
        return self._selected

    def set_selected(self, sel: bool):
        self._selected = sel
        if sel:
            self.add_css_class("selected")
        else:
            self.remove_css_class("selected")
        if isinstance(self._node, (LabelNode, CommentNode)):
            if hasattr(self, "_color_row"):
                self._color_row.set_visible(sel)
        self.queue_draw()
        for pw in self._input_port_widgets.values():
            pw.queue_draw()
        for pw in self._output_port_widgets.values():
            pw.queue_draw()

    def get_input_port_widget(self, name: str) -> Optional[PortWidget]:
        return self._input_port_widgets.get(name)

    def get_output_port_widget(self, name: str) -> Optional[PortWidget]:
        return self._output_port_widgets.get(name)

    def _add_input_port_widget(self, port: Port):
        if self._input_port_widgets.get(port.name):
            return
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        pw = PortWidget(port, self)
        self._input_port_widgets[port.name] = pw
        lbl = Gtk.Label(label=port.label, xalign=0)
        lbl.set_css_classes(["port-label"])
        row.append(pw)
        row.append(lbl)
        row._row_port = pw
        click = Gtk.GestureClick(button=1)
        click.connect("pressed", lambda g, n, x, y, pw=pw: (pw.update_center(), self._canvas.handle_port_click(pw))[-1])
        row.add_controller(click)
        self._left_box.append(row)
    def _build_ui(self):
        if isinstance(self._node, (LabelNode, CommentNode)):
            self._build_text_node_ui()
            return

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.set_css_classes(["node-header"])
        header.set_hexpand(True)
        ctx = header.get_style_context()
        ctx.add_class(self._node.node_type)
        self._header = header

        title = Gtk.Label(label=self._node.label, xalign=0, hexpand=True)
        title.set_css_classes(["node-title"])
        header.append(title)
        self.append(header)

        ports_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        ports_box.set_hexpand(True)

        self._left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._left_box.set_halign(Gtk.Align.START)
        self._left_box.set_margin_top(5)
        self._left_box.set_margin_bottom(5)
        self._right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._right_box.set_halign(Gtk.Align.END)
        self._right_box.set_margin_top(5)
        self._right_box.set_margin_bottom(5)

        for inp in self._node.inputs:
            if inp.port_type == PortType.NUMERIC:
                continue
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            pw = PortWidget(inp, self)
            self._input_port_widgets[inp.name] = pw

            lbl = Gtk.Label(label=inp.label, xalign=0)
            lbl.set_css_classes(["port-label"])
            row.append(pw)
            row.append(lbl)
            row._row_port = pw
            click = Gtk.GestureClick(button=1)
            click.connect("pressed", lambda g, n, x, y, pw=pw: (pw.update_center(), self._canvas.handle_port_click(pw))[-1])
            row.add_controller(click)
            self._left_box.append(row)

        for out in self._node.outputs:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            pw = PortWidget(out, self)
            self._output_port_widgets[out.name] = pw
            lbl = Gtk.Label(label=out.label, xalign=1)
            lbl.set_css_classes(["port-label"])
            row.append(lbl)
            row.append(pw)
            row._row_port = pw
            click = Gtk.GestureClick(button=1)
            click.connect("pressed", lambda g, n, x, y, pw=pw: (pw.update_center(), self._canvas.handle_port_click(pw))[-1])
            row.add_controller(click)
            self._right_box.append(row)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        spacer.set_size_request(24, -1)
        ports_box.append(self._left_box)
        ports_box.append(spacer)
        ports_box.append(self._right_box)
        self.append(ports_box)

        self._thumb_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._thumb_box.set_hexpand(True)
        self._thumb_box.set_vexpand(True)
        self._thumb_box.set_visible(False)

        self._thumb_overlay = Gtk.Overlay()
        self._thumb_overlay.set_hexpand(True)
        self._thumb_overlay.set_vexpand(True)

        self._thumb_picture = Gtk.Picture()
        self._thumb_picture.set_hexpand(True)
        self._thumb_picture.set_vexpand(True)
        self._thumb_picture.set_keep_aspect_ratio(True)
        self._thumb_picture.set_can_shrink(True)
        self._thumb_overlay.set_child(self._thumb_picture)

        self._resize_handle = Gtk.Box()
        self._resize_handle.set_size_request(12, 12)
        self._resize_handle.set_halign(Gtk.Align.END)
        self._resize_handle.set_valign(Gtk.Align.END)
        self._resize_handle.add_css_class("resize-handle")
        self._resize_handle.set_cursor(Gdk.Cursor.new_from_name("se-resize"))
        self._resize_handle.set_visible(False)

        self._thumb_overlay.add_overlay(self._resize_handle)
        self._thumb_box.append(self._thumb_overlay)
        self.append(self._thumb_box)

        self._build_params()

        for inp in self._node.inputs:
            if inp.port_type == PortType.NUMERIC and inp.name not in self._inline_numeric_ports:
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
                pw = PortWidget(inp, self)
                self._input_port_widgets[inp.name] = pw
                lbl = Gtk.Label(label=inp.label, xalign=0)
                lbl.set_css_classes(["port-label"])
                row.append(pw)
                row.append(lbl)
                row._row_port = pw
                click = Gtk.GestureClick(button=1)
                click.connect("pressed", lambda g, n, x, y, pw=pw: (pw.update_center(), self._canvas.handle_port_click(pw))[-1])
                row.add_controller(click)
                self._left_box.append(row)

    def _build_text_node_ui(self):
        is_label = isinstance(self._node, LabelNode)
        self._thumb_box = None
        self._thumb_picture = None

        outer_overlay = Gtk.Overlay()
        outer_overlay.set_hexpand(True)
        outer_overlay.set_vexpand(True)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        body.set_hexpand(True)
        body.set_vexpand(True)
        self._body = body
        body.set_name(f"node-body-{self._node.id.replace('-', '_')}")

        self._text_stack = Gtk.Stack()
        self._text_stack.set_hexpand(True)
        self._text_stack.set_vexpand(True)
        self._text_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        display_label = Gtk.Label(label=self._node.text)
        display_label.set_xalign(0.5)
        display_label.set_yalign(0.5)
        display_label.set_hexpand(True)
        display_label.set_vexpand(True)
        display_label.set_halign(Gtk.Align.FILL)
        display_label.set_valign(Gtk.Align.FILL)
        display_label.set_wrap(True)
        css_class = "node-label-content" if is_label else "node-comment-content"
        display_label.set_css_classes([css_class])
        display_label.set_margin_start(8)
        display_label.set_margin_end(8)
        display_label.set_margin_top(8)
        display_label.set_margin_bottom(8)
        self._display_label = display_label
        self._text_stack.add_child(display_label)

        if is_label:
            entry = Gtk.Entry()
            entry.set_text(self._node.text)
            entry.set_halign(Gtk.Align.FILL)
            entry.set_margin_start(8)
            entry.set_margin_end(8)
            entry.set_margin_top(8)
            entry.set_margin_bottom(8)
            entry.connect("activate", self._on_text_entry_activated)
            efocus = Gtk.EventControllerFocus()
            efocus.connect("leave", lambda ctrl: self._on_text_edit_focus_out())
            entry.add_controller(efocus)
            self._edit_entry = entry
            self._text_stack.add_child(entry)
            self._text_stack.set_visible_child(display_label)
        else:
            sw = Gtk.ScrolledWindow()
            sw.set_hexpand(True)
            sw.set_vexpand(True)
            sw.set_margin_start(8)
            sw.set_margin_end(8)
            sw.set_margin_top(8)
            sw.set_margin_bottom(8)
            tv = Gtk.TextView()
            tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            tv.set_hexpand(True)
            tv.set_vexpand(True)
            buf = tv.get_buffer()
            buf.set_text(self._node.text)
            vfocus = Gtk.EventControllerFocus()
            vfocus.connect("leave", lambda ctrl: self._on_text_edit_focus_out())
            tv.add_controller(vfocus)
            self._edit_view = tv
            sw.set_child(tv)
            self._text_stack.add_child(sw)
            self._text_stack.set_visible_child(display_label)

        body.append(self._text_stack)

        self._color_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._color_row.set_hexpand(True)
        self._color_row.set_margin_start(4)
        self._color_row.set_margin_end(4)
        self._color_row.set_margin_bottom(4)
        self._color_row.set_visible(False)

        color_label = Gtk.Label(label=_("Color:"))
        color_label.set_css_classes(["caption"])
        self._color_row.append(color_label)

        color_store = Gtk.StringList()
        for cname, _chex in LABEL_COLORS:
            color_store.append(cname)

        dd = Gtk.DropDown(model=color_store)
        current_color = self._node.color
        idx = 0
        if current_color:
            for i, (_cname, chex) in enumerate(LABEL_COLORS):
                if chex == current_color:
                    idx = i
                    break
        dd.set_selected(idx)
        dd.connect("notify::selected", self._on_color_changed)
        self._color_dropdown = dd
        self._color_row.append(dd)
        body.append(self._color_row)

        outer_overlay.set_child(body)

        self._resize_handle = Gtk.Box()
        self._resize_handle.set_size_request(12, 12)
        self._resize_handle.set_halign(Gtk.Align.END)
        self._resize_handle.set_valign(Gtk.Align.END)
        self._resize_handle.add_css_class("resize-handle")
        self._resize_handle.set_cursor(Gdk.Cursor.new_from_name("se-resize"))
        self._resize_handle.set_visible(True)
        outer_overlay.add_overlay(self._resize_handle)

        self.append(outer_overlay)
        self._min_node_w = 120
        self._min_node_h = 60

        click_ctrl = Gtk.GestureClick(button=1)
        click_ctrl.connect("pressed", self._on_click)
        self.add_controller(click_ctrl)

        right_click_ctrl = Gtk.GestureClick(button=3)
        right_click_ctrl.connect("pressed", self._on_right_click)
        self.add_controller(right_click_ctrl)

        self._apply_color_background(self._node.color)

    def _start_text_edit(self):
        is_label = isinstance(self._node, LabelNode)
        if is_label:
            self._edit_entry.set_text(self._node.text)
            self._text_stack.set_visible_child(self._edit_entry)
            self._edit_entry.grab_focus()
        else:
            buf = self._edit_view.get_buffer()
            buf.set_text(self._node.text)
            self._text_stack.set_visible_child(self._edit_view.get_parent())
            self._edit_view.grab_focus()

    def _finish_text_edit(self):
        is_label = isinstance(self._node, LabelNode)
        if is_label:
            text = self._edit_entry.get_text()
        else:
            buf = self._edit_view.get_buffer()
            start = buf.get_start_iter()
            end = buf.get_end_iter()
            text = buf.get_text(start, end, False)
        self._node.text = text
        self._display_label.set_label(text)
        self._text_stack.set_visible_child(self._display_label)
        self._canvas.emit("graph-changed")

    def _on_text_entry_activated(self, entry):
        self._finish_text_edit()

    def _on_text_edit_focus_out(self, *args):
        if self._text_stack.get_visible_child() is not self._display_label:
            self._finish_text_edit()

    def _on_color_changed(self, dd, pspec):
        idx = dd.get_selected()
        if idx != Gtk.INVALID_LIST_POSITION and idx < len(LABEL_COLORS):
            _cname, hex_color = LABEL_COLORS[idx]
            self._node.color = hex_color
            self._apply_color_background(hex_color)
            self._canvas.emit("graph-changed")

    def _apply_color_background(self, hex_color):
        if hasattr(self, "_bg_css_provider") and self._bg_css_provider:
            try:
                display = Gdk.Display.get_default()
                if display:
                    Gtk.StyleContext.remove_provider_for_display(display, self._bg_css_provider)
            except Exception:
                pass
            self._bg_css_provider = None
        if hex_color:
            bid = self._node.id.replace("-", "_")
            css = (
                f"#node-body-{bid}, #node-body-{bid} textview,"
                f" #node-body-{bid} textview text,"
                f" #node-body-{bid} entry,"
                f" #node-body-{bid} scrolledwindow"
                f" {{ background: {hex_color}; }}\n"
                f"#node-body-{bid} {{ border-radius: 8px; }}"
            )
            provider = Gtk.CssProvider()
            provider.load_from_data(css.encode())
            try:
                display = Gdk.Display.get_default()
                if display:
                    Gtk.StyleContext.add_provider_for_display(
                        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER
                    )
                    self._bg_css_provider = provider
            except Exception:
                self._bg_css_provider = None
        self.queue_draw()

    def _build_params(self):
        if isinstance(self._node, FilterNode):
            self._build_filter_params()
        elif isinstance(self._node, BlendNode):
            self._build_blend_params()
        elif isinstance(self._node, OpacityNode):
            self._build_opacity_params()
        elif isinstance(self._node, ColoringNode):
            self._build_coloring_params()
        elif isinstance(self._node, MaskNode):
            self._build_mask_params()
        elif isinstance(self._node, ConstantNode):
            self._build_constant_params()

    def _build_filter_params(self):
        fd = self._node.filter_def
        for p in fd.parameters:
            if p.is_hidden:
                continue
            ctrl = self._make_control(p)
            if ctrl:
                ctrl.set_css_classes(["node-param-control"])
                if p.kind in (ParamKind.INT, ParamKind.FLOAT):
                    self._make_control_row(p.label, p.name, ctrl)
                else:
                    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
                    row.set_css_classes(["node-param-row"])
                    row.add_css_class("indented")
                    lbl = Gtk.Label(label=p.label, xalign=0)
                    lbl.set_css_classes(["node-param-label"])
                    row.append(lbl)
                    row.append(ctrl)
                    self.append(row)
                    self._param_controls.append(row)

    def _build_blend_params(self):
        node: BlendNode = self._node

        mode_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        mode_row.set_css_classes(["node-param-row"])
        mode_row.add_css_class("indented")
        mlbl = Gtk.Label(label="Mode", xalign=0)
        mlbl.set_css_classes(["node-param-label"])
        mode_row.append(mlbl)
        dd = Gtk.DropDown()
        dd.set_model(Gtk.StringList.new(node.BLEND_LABELS))
        idx = node.BLEND_MODES.index(node.mode) if node.mode in node.BLEND_MODES else 0
        dd.set_selected(idx)
        dd.set_halign(Gtk.Align.START)
        dd.connect("notify::selected", lambda d, ps: setattr(node, "mode", node.BLEND_MODES[d.get_selected()]))
        dd.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(dd)
        mode_row.append(dd)
        self.append(mode_row)
        self._param_controls.append(mode_row)

    def _build_opacity_params(self):
        node: OpacityNode = self._node
        adj = Gtk.Adjustment(value=node.opacity, lower=0.0, upper=1.0, step_increment=0.05)
        spin = Gtk.SpinButton(adjustment=adj, climb_rate=0.05, digits=2)
        spin.connect("value-changed", lambda s: setattr(node, "opacity", s.get_value()))
        spin.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin)
        self._port_spin_buttons["opacity"] = spin
        self._make_control_row("Opacity", "opacity", spin)

    def _build_coloring_params(self):
        node: ColoringNode = self._node
        for label, attr, lo, hi in [
            ("Hue", "hue", -180.0, 180.0),
            ("Saturation", "saturation", -100.0, 100.0),
            ("Lightness", "lightness", -100.0, 100.0),
        ]:
            adj = Gtk.Adjustment(value=getattr(node, attr), lower=lo, upper=hi, step_increment=1)
            spin = Gtk.SpinButton(adjustment=adj, climb_rate=1, digits=1)
            spin.connect("value-changed", lambda s, a=attr: setattr(node, a, s.get_value()))
            spin.set_css_classes(["node-param-control"])
            self._ctrl_widgets.append(spin)
            self._port_spin_buttons[attr] = spin
            self._make_control_row(label, attr, spin)

    def _build_mask_params(self):
        node: MaskNode = self._node

        inv_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        inv_row.set_css_classes(["node-param-row"])
        inv_row.add_css_class("indented")
        ilbl = Gtk.Label(label="Invert", xalign=0)
        ilbl.set_css_classes(["node-param-label"])
        inv_row.append(ilbl)
        sw = Gtk.Switch()
        sw.set_active(node.invert)
        sw.set_halign(Gtk.Align.START)
        sw.connect("notify::active", lambda s, ps: setattr(node, "invert", s.get_active()))
        sw.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(sw)
        inv_row.append(sw)
        self.append(inv_row)
        self._param_controls.append(inv_row)

        adj = Gtk.Adjustment(value=node.threshold, lower=0.0, upper=1.0, step_increment=0.05)
        spin = Gtk.SpinButton(adjustment=adj, climb_rate=0.05, digits=2)
        spin.connect("value-changed", lambda s: setattr(node, "threshold", s.get_value()))
        spin.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin)
        self._port_spin_buttons["threshold"] = spin
        self._make_control_row("Threshold", "threshold", spin)

    def _get_numeric_port_widget(self, port_name: str) -> Optional[PortWidget]:
        if port_name in self._input_port_widgets:
            return self._input_port_widgets[port_name]
        for inp in self._node.inputs:
            if inp.name == port_name and inp.port_type == PortType.NUMERIC:
                pw = PortWidget(inp, self)
                self._input_port_widgets[port_name] = pw
                self._inline_numeric_ports.add(port_name)
                return pw
        return None

    def _make_control_row(self, label: str, port_name: str, control: Gtk.Widget) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        row.set_css_classes(["node-param-row"])
        row.set_margin_end(4)
        pw = self._get_numeric_port_widget(port_name)
        if pw is None:
            row.add_css_class("indented")
        if pw:
            row.append(pw)
        lbl = Gtk.Label(label=label, xalign=0)
        lbl.set_css_classes(["node-param-label"])
        row.append(lbl)
        row.append(control)
        self.append(row)
        self._param_controls.append(row)
        return row

    def _build_constant_params(self):
        node: ConstantNode = self._node
        adj = Gtk.Adjustment(value=node.value, lower=-999999, upper=999999, step_increment=1)
        spin = Gtk.SpinButton(adjustment=adj, climb_rate=1, digits=2)
        spin.connect("value-changed", lambda s: (setattr(node, "value", s.get_value()), self._canvas._update_all_port_colors()) or None)
        spin.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin)
        self._port_spin_buttons["value"] = spin
        self._make_control_row("Value", "value", spin)

    def _get_local_numeric_value(self, port_name: str) -> Optional[float]:
        node = self._node
        if isinstance(node, FilterNode):
            for p in node.filter_def.parameters:
                if p.name == port_name:
                    return node.param_values.get(p.name, p.default)
            return None
        return getattr(node, port_name, None)

    def update_numeric_controls(self, graph: NodeGraph):
        node_id = self._node.id
        for port_name, spin in self._port_spin_buttons.items():
            edge = graph.get_connected_input(node_id, port_name)
            if edge:
                val = _compute_numeric_value(edge.src_node, graph)
                if val is not None:
                    spin.set_sensitive(False)
                    adj = spin.get_adjustment()
                    adj.set_value(val)
                    spin.add_css_class("connected-numeric")
                else:
                    spin.set_sensitive(True)
                    spin.remove_css_class("connected-numeric")
                    local_val = self._get_local_numeric_value(port_name)
                    if local_val is not None:
                        spin.get_adjustment().set_value(local_val)
            else:
                spin.set_sensitive(True)
                spin.remove_css_class("connected-numeric")
                local_val = self._get_local_numeric_value(port_name)
                if local_val is not None:
                    spin.get_adjustment().set_value(local_val)

    def _make_control(self, p) -> Optional[Gtk.Widget]:
        node = self._node
        val = node.param_values.get(p.name, p.default)

        if p.kind == ParamKind.INT:
            lo = p.min_val or 0
            hi = p.max_val or 1000
            adj = Gtk.Adjustment(value=val or 0, lower=lo, upper=hi, step_increment=1)
            spin = Gtk.SpinButton(adjustment=adj, climb_rate=1, digits=0)
            spin.connect("value-changed", lambda s: node.set_param(p.name, int(s.get_value())))
            self._ctrl_widgets.append(spin)
            self._port_spin_buttons[p.name] = spin
            return spin
        elif p.kind == ParamKind.FLOAT:
            lo = p.min_val or 0
            hi = p.max_val or 1000
            adj = Gtk.Adjustment(value=val or 0, lower=lo, upper=hi, step_increment=0.1)
            spin = Gtk.SpinButton(adjustment=adj, climb_rate=0.1, digits=2)
            spin.connect("value-changed", lambda s: node.set_param(p.name, s.get_value()))
            self._ctrl_widgets.append(spin)
            self._port_spin_buttons[p.name] = spin
            return spin
        elif p.kind == ParamKind.BOOL:
            sw = Gtk.Switch()
            sw.set_active(bool(val))
            sw.set_halign(Gtk.Align.START)
            sw.connect("notify::active", lambda s, ps: node.set_param(p.name, s.get_active()))
            self._ctrl_widgets.append(sw)
            return sw
        elif p.kind == ParamKind.CHOICE:
            dd = Gtk.DropDown()
            dd.set_model(Gtk.StringList.new(p.choices))
            dd.set_selected(val if isinstance(val, int) else 0)
            dd.set_halign(Gtk.Align.START)
            dd.connect("notify::selected", lambda d, ps: node.set_param(p.name, d.get_selected()))
            self._ctrl_widgets.append(dd)
            return dd
        return None

    def set_thumbnail(self, pixbuf: GdkPixbuf.Pixbuf):
        if self._thumb_picture:
            w = pixbuf.get_width()
            h = pixbuf.get_height()
            if w > 0 and h > 0:
                self._image_aspect = w / h
            texture = Gdk.Texture.new_for_pixbuf(pixbuf)
            self._thumb_picture.set_paintable(texture)
            self._thumb_box.set_visible(True)
            self._has_image = True
            self._resize_handle.set_visible(True)
            cur_w, cur_h = self.get_size_request()
            if cur_w < 0 or cur_h < 0:
                self._logical_w = 240
                self._logical_h = max(160, int(240 / self._image_aspect))
            self._node.width = self._logical_w
            self._node.height = self._logical_h
            self.apply_zoom(self._canvas._zoom)

    def clear_thumbnail(self):
        if self._thumb_picture:
            self._thumb_picture.set_paintable(None)
            self._thumb_box.set_visible(False)
            self._has_image = False
            self._image_aspect = None
            self._resize_handle.set_visible(False)
            self._logical_w = int(self._node.width or 240)
            self._logical_h = int(self._node.height or 200)
            self._node.width = self._logical_w
            self._node.height = self._logical_h
            self.set_size_request(-1, -1)

    # ─── Zoom scaling ─────────────────────────────────────────────────

    def apply_zoom(self, zoom: float):
        if not self._has_image:
            self._logical_w = int(self._node.width)
            self._logical_h = int(self._node.height)
        for pw in self._input_port_widgets.values():
            pw.set_size_request(max(1, int(14 * zoom)), max(1, int(14 * zoom)))
        for pw in self._output_port_widgets.values():
            pw.set_size_request(max(1, int(14 * zoom)), max(1, int(14 * zoom)))
        if self._resize_handle:
            hs = max(1, int(12 * zoom))
            self._resize_handle.set_size_request(hs, hs)
        margin = max(1, int(5 * zoom))
        if hasattr(self, "_left_box") and self._left_box:
            self._left_box.set_margin_top(margin)
            self._left_box.set_margin_bottom(margin)
        if hasattr(self, "_right_box") and self._right_box:
            self._right_box.set_margin_top(margin)
            self._right_box.set_margin_bottom(margin)
        for ctrl in self._ctrl_widgets:
            if isinstance(ctrl, Gtk.SpinButton):
                ctrl.set_size_request(max(40, int(80 * zoom)), max(20, int(28 * zoom)))
            elif isinstance(ctrl, Gtk.DropDown):
                ctrl.set_size_request(max(60, int(120 * zoom)), max(20, int(28 * zoom)))
            elif isinstance(ctrl, Gtk.Switch):
                ctrl.set_size_request(max(24, int(40 * zoom)), max(14, int(22 * zoom)))
        if self._has_image:
            self.set_size_request(
                max(1, int(self._logical_w * zoom)),
                max(1, int(self._logical_h * zoom)),
            )

    # ─── Resize (handled via NodeWidget's own GestureDrag) ───────────────

    def _begin_resize(self, gesture, start_x, start_y):
        alloc = self.get_allocation()
        zoom = self._canvas._zoom
        self._resize_start_w = alloc.width / zoom
        self._resize_start_h = alloc.height / zoom
        event = gesture.get_last_event()
        if event:
            _, self._resize_start_px, self._resize_start_py = event.get_position()

    def _update_resize(self, gesture, offset_x, offset_y):
        event = gesture.get_last_event()
        if not event:
            return
        _, cx, cy = event.get_position()
        zoom = self._canvas._zoom
        dx = (cx - self._resize_start_px) / zoom
        dy = (cy - self._resize_start_py) / zoom
        if self._image_aspect is not None:
            aspect = self._image_aspect
            if abs(dx) >= abs(dy * aspect):
                dw = dx
            else:
                dw = dy * aspect
            new_w = max(self._min_node_w, self._resize_start_w + dw)
            new_h = max(self._min_node_h, int(new_w / aspect + 0.5))
        else:
            new_w = max(self._min_node_w, self._resize_start_w + dx)
            new_h = max(self._min_node_h, self._resize_start_h + dy)
        self._logical_w = int(new_w)
        self._logical_h = int(new_h)
        self._node.width = self._logical_w
        self._node.height = self._logical_h
        self.set_size_request(
            max(1, int(self._logical_w * zoom)),
            max(1, int(self._logical_h * zoom)),
        )

    def _end_resize(self):
        self._canvas._update_port_centers(self._node)
        self._canvas.queue_gl_render()
        self._canvas._clamp_pan()
        self._canvas._update_all_positions()

    def _on_drag_begin(self, gesture, start_x, start_y):
        child = self.pick(start_x, start_y, Gtk.PickFlags.DEFAULT)
        if child:
            p = child
            while p and p is not self:
                if isinstance(p, PortWidget):
                    return
                if self._resize_handle.get_visible() and p is self._resize_handle:
                    self._canvas._resizing_node = self._node
                    self._begin_resize(gesture, start_x, start_y)
                    return
                p = p.get_parent()
        event = gesture.get_last_event()
        if event:
            shift = bool(event.get_modifier_state() & Gdk.ModifierType.SHIFT_MASK)
        else:
            shift = False
        if not shift and not self._selected:
            self._canvas.select_node(self)
        self._canvas._dragging_node = self._node
        self._canvas._drag_start_x = self._node.x
        self._canvas._drag_start_y = self._node.y
        self._canvas._drag_group_starts = {
            w: (w.graph_node.x, w.graph_node.y)
            for w in self._canvas._selected_widgets
        }
        if event:
            _, sx, sy = event.get_position()
            self._canvas._drag_pointer_start_x = sx
            self._canvas._drag_pointer_start_y = sy

    def _on_drag_update(self, gesture, offset_x, offset_y):
        if self._canvas._resizing_node is self._node:
            self._update_resize(gesture, offset_x, offset_y)
            return
        if self._canvas._dragging_node is not self._node:
            return
        event = gesture.get_last_event()
        if not event:
            return
        _, sx, sy = event.get_position()
        dx = sx - self._canvas._drag_pointer_start_x
        dy = sy - self._canvas._drag_pointer_start_y
        zoom = self._canvas._zoom
        for w, (start_x, start_y) in self._canvas._drag_group_starts.items():
            w.graph_node.x = start_x + dx / zoom
            w.graph_node.y = start_y + dy / zoom
            self._canvas.update_node_position(w)

    def _on_drag_end(self, gesture, offset_x, offset_y):
        if self._canvas._resizing_node is self._node:
            self._canvas._resizing_node = None
            self._end_resize()
            return
        if self._canvas._dragging_node is self._node:
            self._canvas._dragging_node = None
        self._canvas._drag_group_starts.clear()

    def _on_click(self, gesture, n_press, x, y):
        event = gesture.get_last_event()
        shift = bool(event.get_modifier_state() & Gdk.ModifierType.SHIFT_MASK) if event else False
        if shift:
            if self._selected:
                self._canvas._remove_from_selection(self)
            else:
                self._canvas._add_to_selection(self)
        elif not self._selected:
            self._canvas.select_node(self)
        self._canvas.grab_focus()
        if isinstance(self._node, InputNode) and not self._node.file_path:
            if hasattr(self, '_header') and self._header:
                h = self._header.get_allocation().height
                if 0 <= y < h:
                    return
            self._canvas.emit("input-node-open", self._node.id)
        if isinstance(self._node, (LabelNode, CommentNode)) and n_press == 2:
            self._start_text_edit()

    def _on_right_click(self, gesture, n_press, x, y):
        a = self.get_allocation()
        self._canvas._on_canvas_right_click(gesture, n_press, a.x + x, a.y + y)


class WireOverlay(Gtk.Widget):
    __gtype_name__ = "WireOverlay"

    def __init__(self, canvas: "NodeCanvas"):
        super().__init__()
        self._canvas = canvas
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_css_classes(["wire-overlay"])

    def do_snapshot(self, snapshot):
        canvas = self._canvas
        canvas._update_all_port_centers()
        w = self.get_width()
        h = self.get_height()
        if w < 1 or h < 1:
            return

        zoom = canvas._zoom
        pan_x = canvas._pan_x
        pan_y = canvas._pan_y

        spacing = max(40 * zoom, 10)
        ox = pan_x % spacing
        oy = pan_y % spacing

        if canvas._grid_visible:
            b = canvas._grid_brightness
            grid_color = Gdk.RGBA(b, b, b + 0.01, 1.0)
            x = ox
            while x < w:
                snapshot.append_color(grid_color, Graphene.Rect().init(x, 0, 1, h))
                x += spacing
            y = oy
            while y < h:
                snapshot.append_color(grid_color, Graphene.Rect().init(0, y, w, 1))
                y += spacing

        # clip wires to widget bounds so they don't leak above the header bar
        snapshot.push_clip(Graphene.Rect().init(0, 0, w, h))
        self._draw_wires(snapshot, canvas)
        snapshot.pop()

        # rubber-band selection rectangle
        if canvas._rubber_band_rect:
            sx1, sy1, sx2, sy2 = canvas._rubber_band_rect
            rx = min(sx1, sx2)
            ry = min(sy1, sy2)
            rw = abs(sx2 - sx1)
            rh = abs(sy2 - sy1)
            if rw > 0 and rh > 0:
                fill = Gdk.RGBA(0.3, 0.5, 0.9, 0.15)
                snapshot.append_color(fill, Graphene.Rect().init(rx, ry, rw, rh))
                outline = Gdk.RGBA(0.3, 0.5, 0.9, 1.0)
                snapshot.append_color(outline, Graphene.Rect().init(rx, ry, rw, 1))
                snapshot.append_color(outline, Graphene.Rect().init(rx, ry + rh - 1, rw, 1))
                snapshot.append_color(outline, Graphene.Rect().init(rx, ry, 1, rh))
                snapshot.append_color(outline, Graphene.Rect().init(rx + rw - 1, ry, 1, rh))

    def _draw_wires(self, snapshot, canvas):
        graph = canvas._graph
        for edge in graph.edges:
            src_n = graph.get_node(edge.src_node)
            dst_n = graph.get_node(edge.dst_node)
            if not src_n or not dst_n:
                continue
            sw = canvas._node_widgets.get(edge.src_node)
            dw = canvas._node_widgets.get(edge.dst_node)
            if not sw or not dw:
                continue
            src_p = src_n.get_output_port(edge.src_port)
            dst_p = dst_n.get_input_port(edge.dst_port)
            if not src_p or not dst_p:
                continue
            spw = sw.get_output_port_widget(edge.src_port)
            dpw = dw.get_input_port_widget(edge.dst_port)
            if not spw or not dpw:
                continue
            x1, y1 = spw.center_x, spw.center_y
            x2, y2 = dpw.center_x, dpw.center_y
            pts = _compute_bezier_segments(x1, y1, x2, y2)
            if len(pts) >= 4:
                for i in range(0, len(pts) - 2, 2):
                    snapshot.append_color(
                        Gdk.RGBA(0.5, 0.5, 0.5, 0.8),
                        Graphene.Rect().init(pts[i], pts[i + 1], 2, 2),
                    )

        # drag wire
        if canvas._drag_port:
            x1, y1 = canvas._drag_port_start
            x2, y2 = canvas._drag_port_current
            pts = _compute_bezier_segments(x1, y1, x2, y2)
            color = Gdk.RGBA(0.3, 0.9, 0.3, 0.9) if canvas._drag_valid_target else Gdk.RGBA(0.7, 0.7, 0.7, 0.5)
            if len(pts) >= 4:
                for i in range(0, len(pts) - 2, 2):
                    snapshot.append_color(
                        color,
                        Graphene.Rect().init(pts[i], pts[i + 1], 2, 2),
                    )

        # highlight wire for drop-insert
        if canvas._drag_insert_edge:
            edge = canvas._drag_insert_edge
            sw = canvas._node_widgets.get(edge.src_node)
            dw = canvas._node_widgets.get(edge.dst_node)
            if sw and dw:
                spw = sw.get_output_port_widget(edge.src_port)
                dpw = dw.get_input_port_widget(edge.dst_port)
                if spw and dpw:
                    x1, y1 = spw.center_x, spw.center_y
                    x2, y2 = dpw.center_x, dpw.center_y
                    pts = _compute_bezier_segments(x1, y1, x2, y2)
                    for i in range(0, len(pts) - 2, 2):
                        snapshot.append_color(
                            Gdk.RGBA(0.21, 0.52, 0.89, 1.0),
                            Graphene.Rect().init(pts[i], pts[i + 1], 4, 4),
                        )
                    ix, iy = canvas._drag_insert_pos
                    marker_color = Gdk.RGBA(0.10, 0.37, 0.71, 1.0)
                    snapshot.append_color(marker_color, Graphene.Rect().init(ix - 5, iy - 5, 10, 10))


class Minimap(Gtk.Widget):
    __gtype_name__ = "Minimap"

    NODE_COLORS = {
        "input": Gdk.RGBA(0.18, 0.42, 0.18, 1.0),
        "output": Gdk.RGBA(0.48, 0.23, 0.23, 1.0),
        "filter": Gdk.RGBA(0.04, 0.28, 0.44, 1.0),
        "blend": Gdk.RGBA(0.42, 0.29, 0.18, 1.0),
        "mask": Gdk.RGBA(0.18, 0.35, 0.42, 1.0),
        "color": Gdk.RGBA(0.23, 0.42, 0.48, 1.0),
        "opacity": Gdk.RGBA(0.35, 0.23, 0.48, 1.0),
        "coloring": Gdk.RGBA(0.23, 0.42, 0.48, 1.0),
        "constant": Gdk.RGBA(0.70, 0.50, 0.15, 1.0),
        "add": Gdk.RGBA(0.30, 0.60, 0.20, 1.0),
        "subtract": Gdk.RGBA(0.60, 0.20, 0.35, 1.0),
        "multiply": Gdk.RGBA(0.15, 0.40, 0.65, 1.0),
        "divide": Gdk.RGBA(0.65, 0.15, 0.15, 1.0),
        "ceil": Gdk.RGBA(0.50, 0.30, 0.70, 1.0),
        "floor": Gdk.RGBA(0.30, 0.70, 0.50, 1.0),
        "round": Gdk.RGBA(0.70, 0.50, 0.30, 1.0),
        "sum": Gdk.RGBA(0.20, 0.70, 0.70, 1.0),
        "product": Gdk.RGBA(0.70, 0.20, 0.50, 1.0),
        "label": Gdk.RGBA(0.50, 0.50, 0.20, 1.0),
        "comment": Gdk.RGBA(0.30, 0.60, 0.30, 1.0),
    }

    SIZE = (180, 130)
    PAD = 8

    def __init__(self, canvas: "NodeCanvas"):
        super().__init__()
        self._canvas = canvas
        self.set_size_request(*self.SIZE)
        click = Gtk.GestureClick(button=1)
        click.connect("pressed", self._on_click)
        self.add_controller(click)

    def _get_bounds(self):
        nodes = list(self._canvas._graph.nodes.values())
        if not nodes:
            return None
        pad = 40
        mwx = min(n.x - pad for n in nodes)
        mwy = min(n.y - pad for n in nodes)
        mx = max(n.x + (n.width or 180) + pad for n in nodes)
        my = max(n.y + (n.height or 100) + pad for n in nodes)
        return mwx, mwy, mx, my

    def _on_click(self, gesture, n_press, x, y):
        bounds = self._get_bounds()
        if not bounds:
            return
        mwx, mwy, mx, my = bounds
        c = self._canvas
        mw = self.get_width()
        mh = self.get_height()
        iw = mw - 2 * self.PAD
        ih = mh - 2 * self.PAD
        cw = mx - mwx or 1
        ch = my - mwy or 1
        scale = min(iw / cw, ih / ch)
        cx = x - self.PAD
        cy = y - self.PAD
        wx = cx / scale + mwx
        wy = cy / scale + mwy
        parent = self.get_parent()
        vw = parent.get_width() if parent else 800
        vh = parent.get_height() if parent else 600
        c._pan_x = -wx * c._zoom + vw / 2
        c._pan_y = -wy * c._zoom + vh / 2
        c._clamp_pan()
        c._update_all_positions()

    def _draw_line(self, snapshot, x1, y1, x2, y2, color):
        dx = x2 - x1
        dy = y2 - y1
        dist = max(abs(dx), abs(dy))
        steps = max(int(dist / 2), 1)
        for i in range(steps + 1):
            t = i / steps
            snapshot.append_color(
                color,
                Graphene.Rect().init(x1 + dx * t, y1 + dy * t, 1, 1),
            )

    def do_snapshot(self, snapshot):
        c = self._canvas
        w = self.get_width()
        h = self.get_height()
        if w < 1 or h < 1:
            return
        bg = Gdk.RGBA(0, 0, 0, 0.45)
        border = Gdk.RGBA(1, 1, 1, 0.18)
        snapshot.append_color(bg, Graphene.Rect().init(0, 0, w, h))
        snapshot.append_color(border, Graphene.Rect().init(0, 0, w, 1))
        snapshot.append_color(border, Graphene.Rect().init(0, h - 1, w, 1))
        snapshot.append_color(border, Graphene.Rect().init(0, 0, 1, h))
        snapshot.append_color(border, Graphene.Rect().init(w - 1, 0, 1, h))

        bounds = self._get_bounds()
        if not bounds:
            return
        mwx, mwy, mx, my = bounds
        iw = w - 2 * self.PAD
        ih = h - 2 * self.PAD
        cw = mx - mwx or 1
        ch = my - mwy or 1
        scale = min(iw / cw, ih / ch)
        ox = self.PAD + (iw - cw * scale) / 2
        oy = self.PAD + (ih - ch * scale) / 2

        def to_mm(gx, gy):
            return (gx - mwx) * scale + ox, (gy - mwy) * scale + oy

        wire_color = Gdk.RGBA(0.5, 0.5, 0.5, 0.4)
        for edge in c._graph.edges:
            src_n = c._graph.get_node(edge.src_node)
            dst_n = c._graph.get_node(edge.dst_node)
            if not src_n or not dst_n:
                continue
            sx, sy = to_mm(src_n.x + src_n.width, src_n.y + src_n.height / 2)
            dx_, dy_ = to_mm(dst_n.x, dst_n.y + dst_n.height / 2)
            self._draw_line(snapshot, sx, sy, dx_, dy_, wire_color)

        colors = self.NODE_COLORS
        for node in c._graph.nodes.values():
            color = colors.get(node.node_type, Gdk.RGBA(0.3, 0.3, 0.3, 1))
            nx, ny = to_mm(node.x, node.y)
            nw = max(2, (node.width or 180) * scale)
            nh = max(2, (node.height or 100) * scale)
            snapshot.append_color(color, Graphene.Rect().init(nx, ny, nw, nh))

        vw = float(c._wire_overlay.get_width())
        vh = float(c._wire_overlay.get_height())
        if vw > 0 and vh > 0:
            vx = -c._pan_x / c._zoom
            vy = -c._pan_y / c._zoom
            vx2 = vx + vw / c._zoom
            vy2 = vy + vh / c._zoom
            vx_mm, vy_mm = to_mm(vx, vy)
            vx2_mm, vy2_mm = to_mm(vx2, vy2)
            vx_mm = max(ox, min(ox + (mx - mwx) * scale, vx_mm))
            vy_mm = max(oy, min(oy + (my - mwy) * scale, vy_mm))
            vx2_mm = max(ox, min(ox + (mx - mwx) * scale, vx2_mm))
            vy2_mm = max(oy, min(oy + (my - mwy) * scale, vy2_mm))
            vpw = max(2, vx2_mm - vx_mm)
            vph = max(2, vy2_mm - vy_mm)
            vpc = Gdk.RGBA(1, 1, 1, 0.7)
            snapshot.append_color(vpc, Graphene.Rect().init(vx_mm, vy_mm, 1, vph))
            snapshot.append_color(vpc, Graphene.Rect().init(vx_mm, vy_mm, vpw, 1))
            snapshot.append_color(vpc, Graphene.Rect().init(vx_mm, vy2_mm, vpw, 1))
            snapshot.append_color(vpc, Graphene.Rect().init(vx2_mm, vy_mm, 1, vph))


class NodeCanvas(Gtk.Overlay):
    __gtype_name__ = "NodeCanvas"

    __gsignals__ = {
        "node-selected": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "graph-changed": (GObject.SignalFlags.RUN_FIRST, None, []),
        "input-node-open": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, graph: NodeGraph):
        super().__init__()
        self._graph = graph
        self.set_focusable(True)
        self._extended_zoom: bool = False


        self._wire_overlay = WireOverlay(self)
        self._wire_overlay.set_hexpand(True)
        self._wire_overlay.set_vexpand(True)
        self.set_child(self._wire_overlay)
        self._wire_overlay.connect("notify::width", lambda *_: self._on_overlay_resize())
        self._wire_overlay.connect("notify::height", lambda *_: self._on_overlay_resize())

        self._fixed = Gtk.Fixed()
        self._fixed.set_hexpand(True)
        self._fixed.set_vexpand(True)
        self.add_overlay(self._fixed)
        self._fixed.set_halign(Gtk.Align.FILL)
        self._fixed.set_valign(Gtk.Align.FILL)

        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._grid_brightness: float = 0.22
        self._grid_visible: bool = True
        self._snap_to_grid: bool = False
        self._update_grid_brightness_for_theme()
        style_mgr = Adw.StyleManager.get_default()
        style_mgr.connect("notify::dark", self._on_color_scheme_changed)
        self._node_widgets: dict[str, NodeWidget] = {}
        self._selected_widgets: set[NodeWidget] = set()
        self._dragging_node: Optional[Node] = None
        self._resizing_node: Optional[Node] = None
        self._drag_start_x = 0.0
        self._drag_start_y = 0.0
        self._drag_pointer_start_x = 0.0
        self._drag_pointer_start_y = 0.0
        self._drag_group_starts: dict[NodeWidget, tuple[float, float]] = {}

        self._drag_port: Optional[PortWidget] = None
        self._drag_port_start = (0.0, 0.0)
        self._drag_port_current = (0.0, 0.0)
        self._drag_valid_target: Optional[PortWidget] = None
        self._selected_port: Optional[PortWidget] = None

        self._rubber_band_rect: Optional[tuple[float, float, float, float]] = None
        self._rubber_band_active: bool = False
        self._rubber_band_hovered: set[NodeWidget] = set()

        self._clipboard: Optional[dict] = None

        self._filter_def_map: dict[str, FilterDef] = {}
        self._drag_preview: Optional[DragPreview] = None
        self._drag_insert_edge: Optional[Edge] = None
        self._drag_insert_pos: tuple[float, float] = (0.0, 0.0)

        self._zoom_css = Gtk.CssProvider()
        self._zoom_css.load_from_data(b"")

        self._zoom_css_applied = False

        self._minimap = Minimap(self)
        self._minimap.set_halign(Gtk.Align.START)
        self._minimap.set_valign(Gtk.Align.END)
        self._minimap.set_margin_start(8)
        self._minimap.set_margin_bottom(8)
        self._minimap.set_visible(False)
        self.add_overlay(self._minimap)

        self._zoom_label = Gtk.Label(label="100%")
        self._zoom_label.set_css_classes(["zoom-label"])
        self._zoom_label.set_halign(Gtk.Align.END)
        self._zoom_label.set_valign(Gtk.Align.END)
        self._zoom_label.set_margin_end(8)
        self._zoom_label.set_margin_bottom(8)
        self.add_overlay(self._zoom_label)

        self._key_controller = Gtk.EventControllerKey()
        self._key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(self._key_controller)

        self._pan_drag = Gtk.GestureDrag(button=2)
        self._pan_drag.connect("drag-begin", self._on_pan_begin)
        self._pan_drag.connect("drag-update", self._on_pan_update)
        self._fixed.add_controller(self._pan_drag)

        self._canvas_click = Gtk.GestureClick(button=1)
        self._canvas_click.connect("pressed", self._on_canvas_click)
        self._fixed.add_controller(self._canvas_click)

        self._sel_drag = Gtk.GestureDrag(button=1)
        self._sel_drag.connect("drag-begin", self._on_sel_drag_begin)
        self._sel_drag.connect("drag-update", self._on_sel_drag_update)
        self._sel_drag.connect("drag-end", self._on_sel_drag_end)
        self._fixed.add_controller(self._sel_drag)

        self._last_cursor_x = 0.0
        self._last_cursor_y = 0.0
        self._motion = Gtk.EventControllerMotion()
        self._motion.connect("motion", self._on_motion)
        self._fixed.add_controller(self._motion)

        self._canvas_right_click = Gtk.GestureClick(button=3)
        self._canvas_right_click.connect("pressed", self._on_canvas_right_click)
        self._fixed.add_controller(self._canvas_right_click)

        self._scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL | Gtk.EventControllerScrollFlags.DISCRETE)
        self._scroll.connect("scroll", self._on_scroll)
        self._fixed.add_controller(self._scroll)

        # Drop target for sidebar drag
        self._drop_target = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.COPY)
        self._drop_target.connect("accept", self._on_drop_accept)
        self._drop_target.connect("motion", self._on_drag_motion)
        self._drop_target.connect("leave", self._on_drag_leave)
        self._drop_target.connect("drop", self._on_drop)
        self._drop_target.set_propagation_limit(Gtk.PropagationLimit.NONE)
        self.add_controller(self._drop_target)

        for node in self._graph.nodes.values():
            self._add_node_widget(node)
        self.connect("realize", lambda *_: self._apply_zoom_css(self._zoom))

    def _update_zoom_label(self):
        pct = int(round(self._zoom * 100))
        self._zoom_label.set_text(f"{pct}%")

    def queue_gl_render(self):
        self._wire_overlay.queue_draw()
        self._minimap.queue_draw()

    def get_node_widget(self, node_id: str) -> Optional[NodeWidget]:
        return self._node_widgets.get(node_id)

    def _clear_selection(self):
        for w in list(self._selected_widgets):
            w.set_selected(False)
        self._selected_widgets.clear()
        self.emit("node-selected", None)

    def _add_to_selection(self, widget: NodeWidget):
        widget.set_selected(True)
        self._selected_widgets.add(widget)

    def _remove_from_selection(self, widget: NodeWidget):
        widget.set_selected(False)
        self._selected_widgets.discard(widget)
        first = next(iter(self._selected_widgets), None)
        self.emit("node-selected", first.graph_node if first else None)

    def select_node(self, widget: Optional[NodeWidget]):
        for w in list(self._selected_widgets):
            w.set_selected(False)
        self._selected_widgets.clear()
        if widget:
            widget.set_selected(True)
            self._selected_widgets.add(widget)
        self.emit("node-selected", widget.graph_node if widget else None)

    def _select_nodes_in_rect(self, gx1, gy1, gx2, gy2):
        for w in list(self._selected_widgets):
            w.set_selected(False)
        self._selected_widgets.clear()
        min_gx, max_gx = min(gx1, gx2), max(gx1, gx2)
        min_gy, max_gy = min(gy1, gy2), max(gy1, gy2)
        for widget in self._node_widgets.values():
            node = widget.graph_node
            if (node.x < max_gx and node.x + (node.width or 1) > min_gx
                    and node.y < max_gy and node.y + (node.height or 1) > min_gy):
                widget.set_selected(True)
                self._selected_widgets.add(widget)
        first = next(iter(self._selected_widgets), None)
        self.emit("node-selected", first.graph_node if first else None)

    def add_node(self, node: Node):
        self._graph.add_node(node)
        self._add_node_widget(node)
        self.emit("graph-changed")

    def _add_node_widget(self, node: Node):
        existing = self._node_widgets.pop(node.id, None)
        if existing:
            self._fixed.remove(existing)
        w = NodeWidget(node, self)
        self._node_widgets[node.id] = w
        sx, sy = self._graph_to_screen(node.x, node.y)
        w._screen_x = sx
        w._screen_y = sy
        self._fixed.put(w, int(sx), int(sy))
        w.apply_zoom(self._zoom)
        self._update_node_port_colors(node)

        def defer():
            alloc = w.get_allocation()
            if alloc.width > 0 and alloc.height > 0:
                logical_w = int(alloc.width / self._zoom)
                logical_h = int(alloc.height / self._zoom)
                if logical_w != w._logical_w or logical_h != w._logical_h:
                    w._logical_w = logical_w
                    w._logical_h = logical_h
                    node.width = logical_w
                    node.height = logical_h
                self._update_port_centers(node)
                self.queue_gl_render()
                return False
            return True
        GLib.idle_add(defer)
        if isinstance(node, InputNode) and node.file_path:
            GLib.idle_add(lambda: self.update_node_display(node.id) or False)

    def clear_all(self):
        for w in self._node_widgets.values():
            self._fixed.remove(w)
        self._node_widgets.clear()
        self._selected_widgets.clear()
        self._selected_port = None
        self._drag_port = None
        self._graph.clear()
        self.queue_gl_render()
        self.emit("graph-changed")

    def remove_node(self, node_id: str):
        w = self._node_widgets.pop(node_id, None)
        if w:
            self._fixed.remove(w)
            self._selected_widgets.discard(w)
            if self._dragging_node is w.graph_node:
                self._dragging_node = None
            if self._resizing_node is w.graph_node:
                self._resizing_node = None
        self._graph.remove_node(node_id)
        self._update_all_port_colors()
        self.queue_gl_render()
        self.emit("graph-changed")

    SNAP_INCREMENT = 20

    def _snap(self, value: float) -> float:
        return round(value / self.SNAP_INCREMENT) * self.SNAP_INCREMENT

    def update_node_position(self, widget: NodeWidget):
        node = widget.graph_node
        if self._snap_to_grid:
            node.x = self._snap(node.x)
            node.y = self._snap(node.y)
        sx, sy = self._graph_to_screen(node.x, node.y)
        widget._screen_x = sx
        widget._screen_y = sy
        self._fixed.move(widget, int(sx), int(sy))
        self._update_port_centers(node)
        self.queue_gl_render()

    def _update_all_positions(self):
        orphans = []
        for nid, w in self._node_widgets.items():
            node = self._graph.get_node(nid)
            if node:
                sx, sy = self._graph_to_screen(node.x, node.y)
                w._screen_x = sx
                w._screen_y = sy
                self._fixed.move(w, int(sx), int(sy))
                w.apply_zoom(self._zoom)
                self._quick_port_centers(node)
            else:
                orphans.append(nid)
        for nid in orphans:
            self._fixed.remove(self._node_widgets.pop(nid))
        self._apply_zoom_css(self._zoom)
        self.queue_gl_render()
        self.queue_resize()

    def _quick_port_centers(self, node: Node):
        w = self._node_widgets.get(node.id)
        if not w:
            return
        for inp in node.inputs:
            pw = w.get_input_port_widget(inp.name)
            if pw:
                pw._center_x = w._screen_x + pw._offset_x
                pw._center_y = w._screen_y + pw._offset_y
        for out in node.outputs:
            pw = w.get_output_port_widget(out.name)
            if pw:
                pw._center_x = w._screen_x + pw._offset_x
                pw._center_y = w._screen_y + pw._offset_y

    def _update_all_port_centers(self):
        for node in self._graph.nodes.values():
            self._update_port_centers(node)

    def _apply_zoom_css(self, zoom: float):
        display = self.get_display()
        if not display:
            GLib.idle_add(lambda: self._apply_zoom_css(zoom) or False)
            return
        if not self._zoom_css_applied:
            self._zoom_css_applied = True
            self._zoom_css.connect("parsing-error", lambda p, section, error: print(f"CSS: {error}"))
            Gtk.StyleContext.add_provider_for_display(
                display, self._zoom_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
            )
        bw = max(1, int(1 * zoom))
        br = max(1, int(8 * zoom))
        hp = max(1, int(6 * zoom))
        hr = max(1, int(7 * zoom))
        rp = max(1, int(3 * zoom))
        ip = max(1, int(18 * zoom))
        cm = max(1, int(4 * zoom))
        fs = max(1, int(12 * zoom))
        pfs = max(1, int(0.85 * 12 * zoom))
        tfs = max(1, int(14 * zoom))
        lfs = max(1, int(0.80 * 12 * zoom))
        css = (
            f".node-widget {{ font-size: {fs}px; border-width: {bw}px; border-radius: {br}px; min-width: 0; min-height: 0; }}\n"
            f".node-widget spinbutton text {{ min-width: 0; min-height: 0; }}\n"
            f".node-widget spinbutton button {{ min-width: 0; min-height: 0; }}\n"
            f".node-widget switch trough {{ min-width: 0; min-height: 0; }}\n"
            f".node-widget switch slider {{ min-width: 0; min-height: 0; }}\n"
            f".node-widget dropdown button {{ min-width: 0; min-height: 0; }}\n"
            f".node-header {{ padding: {hp}px {max(1, int(10 * zoom))}px; border-radius: {hr}px {hr}px 0 0; min-width: 0; min-height: 0; }}\n"
            f".port-label {{ font-size: {pfs}px; min-width: 0; min-height: 0; }}\n"
            f".node-title {{ font-size: {tfs}px; min-width: 0; min-height: 0; }}\n"
            f".node-param-row {{ padding: {rp}px 0px; min-width: 0; min-height: 0; }}\n"
            f".node-param-row.indented {{ padding-left: {ip}px; min-width: 0; min-height: 0; }}\n"
            f".node-param-label {{ font-size: {lfs}px; min-width: 0; min-height: 0; }}\n"
            f".node-param-control {{ margin-bottom: {cm}px; min-width: 0; min-height: 0; }}\n"
            f".resize-handle {{ border-top-left-radius: {max(1, int(4 * zoom))}px; border-bottom-right-radius: {max(1, int(7 * zoom))}px; }}\n"
        )
        self._zoom_css.load_from_data(css.encode())

    def _update_port_centers(self, node: Node):
        w = self._node_widgets.get(node.id)
        if not w:
            return
        for inp in node.inputs:
            pw = w.get_input_port_widget(inp.name)
            if pw:
                pw.update_center()
        for out in node.outputs:
            pw = w.get_output_port_widget(out.name)
            if pw:
                pw.update_center()

    def _update_node_port_colors(self, node: Node):
        w = self._node_widgets.get(node.id)
        if not w:
            return
        for inp in node.inputs:
            pw = w.get_input_port_widget(inp.name)
            if pw:
                pw.set_connected(self._graph.get_connected_input(node.id, inp.name) is not None)
        w.update_numeric_controls(self._graph)

    def _update_all_port_colors(self):
        for node in self._graph.nodes.values():
            self._update_node_port_colors(node)

    def update_node_display(self, node_id: str):
        w = self._node_widgets.get(node_id)
        if not w:
            return
        node = self._graph.get_node(node_id)
        if not node:
            return

        if isinstance(node, InputNode):
            path = node.file_path
            if path:
                try:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
                    wgt = pixbuf.get_width()
                    hgt = pixbuf.get_height()
                    max_long = 4096
                    if max(wgt, hgt) > max_long:
                        scale = max_long / max(wgt, hgt)
                        pixbuf = pixbuf.scale_simple(int(wgt * scale), int(hgt * scale), GdkPixbuf.InterpType.TILES)
                    w.set_thumbnail(pixbuf)
                except Exception:
                    w.clear_thumbnail()
            else:
                w.clear_thumbnail()
        self.queue_gl_render()

    def set_output_thumbnail(self, node_id: str, pixbuf: GdkPixbuf.Pixbuf):
        node = self._graph.get_node(node_id)
        if not node or not self._graph.get_connected_input(node_id, "image"):
            return
        w = self._node_widgets.get(node_id)
        if w:
            wgt = pixbuf.get_width()
            hgt = pixbuf.get_height()
            max_long = 4096
            if max(wgt, hgt) > max_long:
                scale = max_long / max(wgt, hgt)
                pixbuf = pixbuf.scale_simple(int(wgt * scale), int(hgt * scale), GdkPixbuf.InterpType.TILES)
            w.set_thumbnail(pixbuf)
            self.queue_gl_render()

    def set_filter_defs(self, defs: list["FilterDef"]):
        self._filter_def_map.clear()
        for fd in defs:
            self._filter_def_map[f"{fd.engine}:{fd.name}"] = fd

    # ─── Drag preview ──────────────────────────────────────────────────────────

    def _show_drag_preview(self, text: str, screen_x: float, screen_y: float):
        label = None
        css_class = None
        if text.startswith("filter:"):
            parts = text.split(":", 2)
            if len(parts) == 3:
                key = f"{parts[1]}:{parts[2]}"
                fd = self._filter_def_map.get(key)
                if fd:
                    label = fd.display_name
                    css_class = "filter"
        else:
            for prefix, (lbl, cls) in _NODE_PREVIEW_INFO.items():
                if text.startswith(prefix):
                    label = lbl
                    css_class = cls
                    break
        if label is None:
            return
        if self._drag_preview is None:
            self._drag_preview = DragPreview(label, css_class)
            self._fixed.put(self._drag_preview, int(screen_x), int(screen_y))
            self._drag_preview.set_visible(True)
        else:
            self._fixed.move(self._drag_preview, int(screen_x), int(screen_y))

    def _hide_drag_preview(self):
        if self._drag_preview is not None:
            self._fixed.remove(self._drag_preview)
            self._drag_preview = None

    def _on_drag_motion(self, target, x, y):
        text = peek_pending_drag_text()
        if text:
            self._show_drag_preview(text, x, y)
            self._update_drag_insert_edge(text, x, y)
            return Gdk.DragAction.COPY
        return Gdk.DragAction.COPY

    def _on_drag_leave(self, target):
        self._hide_drag_preview()
        self._clear_drag_insert_edge()

    # ─── Drop from sidebar ───────────────────────────────────────────────────────

    def _on_drop_accept(self, target, drop):
        formats = drop.get_formats()
        return formats.contain_mime_type("text/plain")

    # ─── Wire-insert helpers ───────────────────────────────────────────────────

    _INSERTABLE_PREFIXES = frozenset({"blend:", "opacity:", "coloring:", "mask:", "filter:"})

    def _is_insertable_node(self, text: str) -> bool:
        return any(text.startswith(p) for p in self._INSERTABLE_PREFIXES)

    def _update_drag_insert_edge(self, text: str, x: float, y: float):
        prev = self._drag_insert_edge
        self._drag_insert_edge = None
        if self._is_insertable_node(text):
            edge = self._find_edge_at(x, y, threshold=30.0)
            if edge:
                src_n = self._graph.get_node(edge.src_node)
                dst_n = self._graph.get_node(edge.dst_node)
                if src_n and dst_n:
                    src_p = src_n.get_output_port(edge.src_port)
                    dst_p = dst_n.get_input_port(edge.dst_port)
                    if src_p and dst_p and src_p.port_type == PortType.IMAGE and dst_p.port_type == PortType.IMAGE:
                        self._drag_insert_edge = edge
                        self._drag_insert_pos = (x, y)
        if prev is not self._drag_insert_edge:
            self.queue_gl_render()

    def _clear_drag_insert_edge(self):
        if self._drag_insert_edge is not None:
            self._drag_insert_edge = None
            self.queue_gl_render()

    def _shift_downstream(self, from_node_id: str, dx: float):
        visited = {from_node_id}
        queue = [from_node_id]
        while queue:
            nid = queue.pop()
            for e in self._graph.edges:
                if e.src_node == nid and e.dst_node not in visited:
                    visited.add(e.dst_node)
                    queue.append(e.dst_node)
        for nid in visited:
            node = self._graph.get_node(nid)
            if node:
                node.x += dx
                w = self._node_widgets.get(nid)
                if w:
                    self.update_node_position(w)

    def _shift_upstream(self, from_node_id: str, dx: float):
        visited = {from_node_id}
        queue = [from_node_id]
        while queue:
            nid = queue.pop()
            for e in self._graph.edges:
                if e.dst_node == nid and e.src_node not in visited:
                    visited.add(e.src_node)
                    queue.append(e.src_node)
        for nid in visited:
            node = self._graph.get_node(nid)
            if node:
                node.x += dx
                w = self._node_widgets.get(nid)
                if w:
                    self.update_node_position(w)

    def _insert_new_node_into_edge(self, edge: Edge, new_node_id: str):
        graph = self._graph
        new_node = graph.get_node(new_node_id)
        if not new_node:
            return
        img_input = None
        for p in new_node.inputs:
            if p.port_type == PortType.IMAGE:
                img_input = p
                break
        img_output = None
        for p in new_node.outputs:
            if p.port_type == PortType.IMAGE:
                img_output = p
                break
        if not img_input or not img_output:
            return

        src_node = graph.get_node(edge.src_node)
        dst_node = graph.get_node(edge.dst_node)
        if not src_node or not dst_node:
            return

        # Space out source and destination (and their connected chains)
        # to make room for the new node
        gap = 25.0
        src_right = src_node.x + (src_node.width or 180)
        new_left = new_node.x
        new_right = new_node.x + (new_node.width or 220)
        dst_left = dst_node.x

        need_left = max(0.0, src_right + gap - new_left)
        need_right = max(0.0, new_right + gap - dst_left)

        if need_left > 0:
            self._shift_upstream(edge.src_node, -need_left)
        if need_right > 0:
            self._shift_downstream(edge.dst_node, need_right)

        graph.remove_edge(edge.id)
        e1 = graph.add_edge(edge.src_node, edge.src_port, new_node_id, img_input.name)
        e2 = graph.add_edge(new_node_id, img_output.name, edge.dst_node, edge.dst_port)
        if e1 and e2:
            self._update_all_port_colors()
            self.emit("graph-changed")
        elif e1 and not e2:
            graph.remove_edge(e1.id)
            graph.add_edge(edge.src_node, edge.src_port, edge.dst_node, edge.dst_port)

    def _try_insert_at(self, x: float, y: float, new_node_id: str):
        edge = self._find_edge_at(x, y, threshold=30.0)
        if not edge:
            return
        src_n = self._graph.get_node(edge.src_node)
        dst_n = self._graph.get_node(edge.dst_node)
        if not src_n or not dst_n:
            return
        src_p = src_n.get_output_port(edge.src_port)
        dst_p = dst_n.get_input_port(edge.dst_port)
        if not src_p or not dst_p or src_p.port_type != PortType.IMAGE or dst_p.port_type != PortType.IMAGE:
            return
        self._insert_new_node_into_edge(edge, new_node_id)

    def _on_drop(self, target, value, x, y):
        self._hide_drag_preview()
        text = get_pending_drag_text()
        if text and text.startswith("filter:"):
            parts = text.split(":", 2)
            if len(parts) == 3:
                key = f"{parts[1]}:{parts[2]}"
                fd = self._filter_def_map.get(key)
                if fd:
                    gx = (x - self._pan_x) / self._zoom
                    gy = (y - self._pan_y) / self._zoom
                    nid = "filter_" + str(GLib.get_monotonic_time())
                    node = FilterNode(nid, fd, gx, gy)
                    self.add_node(node)
                    w = self.get_node_widget(nid)
                    if w:
                        self.select_node(w)
                    self._try_insert_at(x, y, nid)
                    return True
        elif text and text.startswith("blend:"):
            parts = text.split(":", 1)
            mode = parts[1] if len(parts) == 2 else "over"
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "blend_" + mode + "_" + str(GLib.get_monotonic_time())
            node = BlendNode(nid, mode, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("opacity:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "opacity_" + str(GLib.get_monotonic_time())
            node = OpacityNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("coloring:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "coloring_" + str(GLib.get_monotonic_time())
            node = ColoringNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("input:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "input_" + str(GLib.get_monotonic_time())
            node = InputNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            return True
        elif text and text.startswith("output:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "output_" + str(GLib.get_monotonic_time())
            node = OutputNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            return True
        elif text and text.startswith("mask:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "mask_" + str(GLib.get_monotonic_time())
            node = MaskNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("constant:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "constant_" + str(GLib.get_monotonic_time())
            node = ConstantNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            return True
        elif text and text.startswith("add:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "add_" + str(GLib.get_monotonic_time())
            node = AddNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            return True
        elif text and text.startswith("subtract:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "subtract_" + str(GLib.get_monotonic_time())
            node = SubtractNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            return True
        elif text and text.startswith("multiply:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "multiply_" + str(GLib.get_monotonic_time())
            node = MultiplyNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            return True
        elif text and text.startswith("divide:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "divide_" + str(GLib.get_monotonic_time())
            node = DivideNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            return True
        elif text and text.startswith("ceil:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "ceil_" + str(GLib.get_monotonic_time())
            node = CeilNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            return True
        elif text and text.startswith("floor:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "floor_" + str(GLib.get_monotonic_time())
            node = FloorNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            return True
        elif text and text.startswith("round:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "round_" + str(GLib.get_monotonic_time())
            node = RoundNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            return True
        elif text and text.startswith("sum:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "sum_" + str(GLib.get_monotonic_time())
            node = SumNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            return True
        elif text and text.startswith("product:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "product_" + str(GLib.get_monotonic_time())
            node = ProductNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            return True
        elif text and text.startswith("label:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "label_" + str(GLib.get_monotonic_time())
            node = LabelNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            return True
        elif text and text.startswith("comment:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "comment_" + str(GLib.get_monotonic_time())
            node = CommentNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            return True
        return False

    # ─── Port click (connection creation) ─────────────────────────────────────

    def handle_port_click(self, port_widget: PortWidget):
        if self._selected_port is None:
            self._selected_port = port_widget
            port_widget.queue_draw()
            self._wire_overlay.queue_draw()
        elif self._selected_port is port_widget:
            self._clear_selected_port()
        else:
            src = self._selected_port
            dst = port_widget
            src_nid, src_pn = src.port.node_id, src.port.name
            dst_nid, dst_pn = dst.port.node_id, dst.port.name
            edge = self._graph.add_edge(src_nid, src_pn, dst_nid, dst_pn)
            if edge:
                self._update_all_port_colors()
                self.emit("graph-changed")
                self._maybe_add_blend_port(dst_nid, dst_pn)
            self._clear_selected_port()
            self._wire_overlay.queue_draw()

    def _clear_selected_port(self):
        if self._selected_port:
            self._selected_port.queue_draw()
            self._selected_port = None

    # ─── Port drag (connection creation) ───────────────────────────────────────

    def start_port_drag(self, port_widget: PortWidget):
        self._drag_port = port_widget
        self._drag_port_start = (port_widget.center_x, port_widget.center_y)
        self._drag_port_current = self._drag_port_start
        self._drag_valid_target = None

    def update_port_drag(self, offset_x, offset_y):
        if not self._drag_port:
            return
        cx, cy = self._drag_port_start
        self._drag_port_current = (cx + offset_x, cy + offset_y)
        self._drag_valid_target = self._find_port_at(cx + offset_x, cy + offset_y)
        self.queue_gl_render()

    def end_port_drag(self, offset_x, offset_y):
        if not self._drag_port:
            return
        target = self._drag_valid_target
        if target:
            src_port, dst_port = self._drag_port.port, target.port
            if src_port.direction == PortDirection.OUTPUT:
                src_nid, src_pn = src_port.node_id, src_port.name
                dst_nid, dst_pn = dst_port.node_id, dst_port.name
            else:
                src_nid, src_pn = dst_port.node_id, dst_port.name
                dst_nid, dst_pn = src_port.node_id, src_port.name
            edge = self._graph.add_edge(src_nid, src_pn, dst_nid, dst_pn)
            if edge:
                self._update_all_port_colors()
                self.emit("graph-changed")
                self._maybe_add_blend_port(dst_nid, dst_pn)
        self._clear_selected_port()
        self._drag_port = None
        self._drag_valid_target = None
        self.queue_gl_render()

    def _maybe_add_blend_port(self, node_id: str, port_name: str):
        node = self._graph.get_node(node_id)
        if isinstance(node, BlendNode) and port_name.startswith("blend"):
            new_port = node.add_input_port()
            widget = self._node_widgets.get(node_id)
            if widget:
                widget._add_input_port_widget(new_port)
                self._update_port_centers(node)

    def _find_port_at(self, x, y) -> Optional[PortWidget]:
        if not self._drag_port:
            return None
        src = self._drag_port.port
        for w in self._node_widgets.values():
            for name, pw in w._input_port_widgets.items():
                if src.direction == PortDirection.OUTPUT:
                    if abs(pw.center_x - x) < 10 and abs(pw.center_y - y) < 10:
                        return pw
            for name, pw in w._output_port_widgets.items():
                if src.direction == PortDirection.INPUT:
                    if abs(pw.center_x - x) < 10 and abs(pw.center_y - y) < 10:
                        return pw
        return None

    def _graph_to_screen(self, gx, gy):
        return (gx * self._zoom + self._pan_x, gy * self._zoom + self._pan_y)

    def _screen_to_graph(self, sx, sy):
        return ((sx - self._pan_x) / self._zoom, (sy - self._pan_y) / self._zoom)

    def _get_world_bounds(self):
        nodes = list(self._graph.nodes.values())
        pad = 500
        if not nodes:
            return -1200, -800, 1200, 800
        mwx = min(n.x - pad for n in nodes)
        mwy = min(n.y - pad for n in nodes)
        mx = max(n.x + (n.width or 180) + pad for n in nodes)
        my = max(n.y + (n.height or 100) + pad for n in nodes)
        return mwx, mwy, mx, my

    def _fit_content(self):
        nodes = list(self._graph.nodes.values())
        if not nodes:
            return
        # Use actual node bounds without padding for initial centering
        mwx = min(n.x for n in nodes)
        mwy = min(n.y for n in nodes)
        mx = max(n.x + (n.width or 180) for n in nodes)
        my = max(n.y + (n.height or 100) for n in nodes)
        cw = self._wire_overlay.get_width()
        ch = self._wire_overlay.get_height()
        if cw < 1 or ch < 1:
            return
        z = self._zoom
        cx = (mwx + mx) / 2
        cy = (mwy + my) / 2
        self._pan_x = -cx * z + cw / 2
        self._pan_y = -cy * z + ch / 2
        self._update_all_positions()

    def _on_overlay_resize(self):
        self._clamp_pan()
        self._update_all_positions()

    def _clamp_pan(self):
        cw = self._wire_overlay.get_width()
        ch = self._wire_overlay.get_height()
        if cw < 1 or ch < 1:
            return
        mwx, mwy, mx, my = self._get_world_bounds()
        z = self._zoom
        vw = cw / z
        vh = ch / z
        if mx - mwx >= vw:
            self._pan_x = max(-(mx - vw) * z, min(-mwx * z, self._pan_x))
        if my - mwy >= vh:
            self._pan_y = max(-(my - vh) * z, min(-mwy * z, self._pan_y))

    def _on_pan_begin(self, gesture, start_x, start_y):
        self._pan_start_x, self._pan_start_y = self._pan_x, self._pan_y

    def _on_pan_update(self, gesture, offset_x, offset_y):
        self._pan_x = self._pan_start_x + offset_x
        self._pan_y = self._pan_start_y + offset_y
        self._clamp_pan()
        self._update_all_positions()

    def _on_canvas_click(self, gesture, n_press, x, y):
        self._clear_selected_port()
        child = self._fixed.pick(x, y, Gtk.PickFlags.DEFAULT)
        if child is not None:
            p = child
            while p and p is not self._fixed:
                if isinstance(p, NodeWidget):
                    return
                p = p.get_parent()
        self._clear_selection()
        self.grab_focus()
        self.queue_gl_render()

    def _on_sel_drag_begin(self, gesture, start_x, start_y):
        child = self._fixed.pick(start_x, start_y, Gtk.PickFlags.DEFAULT)
        if child is not None:
            p = child
            while p and p is not self._fixed:
                if isinstance(p, NodeWidget):
                    self._rubber_band_active = False
                    return
                p = p.get_parent()
        self._rubber_band_active = True
        self._rubber_band_rect = (start_x, start_y, start_x, start_y)
        self._rubber_band_hovered.clear()
        self.queue_gl_render()

    def _on_sel_drag_update(self, gesture, offset_x, offset_y):
        if not self._rubber_band_active:
            return
        sx1, sy1, _, _ = self._rubber_band_rect
        self._rubber_band_rect = (sx1, sy1, sx1 + offset_x, sy1 + offset_y)
        sx2, sy2 = sx1 + offset_x, sy1 + offset_y
        gx1, gy1 = self._screen_to_graph(min(sx1, sx2), min(sy1, sy2))
        gx2, gy2 = self._screen_to_graph(max(sx1, sx2), max(sy1, sy2))
        if abs(gx2 - gx1) < 1 or abs(gy2 - gy1) < 1:
            self.queue_gl_render()
            return
        newly_in = set()
        for widget in self._node_widgets.values():
            node = widget.graph_node
            if (node.x < max(gx1, gx2) and node.x + (node.width or 1) > min(gx1, gx2)
                    and node.y < max(gy1, gy2) and node.y + (node.height or 1) > min(gy1, gy2)):
                if widget not in self._rubber_band_hovered:
                    widget.set_selected(True)
                    newly_in.add(widget)
            else:
                if widget in self._rubber_band_hovered:
                    widget.set_selected(False)
                    self._rubber_band_hovered.discard(widget)
        self._rubber_band_hovered.update(newly_in)
        self.queue_gl_render()

    def _on_sel_drag_end(self, gesture, offset_x, offset_y):
        if not self._rubber_band_active:
            return
        self._rubber_band_active = False
        self._rubber_band_rect = None
        for w in list(self._selected_widgets):
            if w not in self._rubber_band_hovered:
                w.set_selected(False)
        for w in self._rubber_band_hovered:
            w.set_selected(True)
        self._selected_widgets = set(self._rubber_band_hovered)
        self._rubber_band_hovered.clear()
        first = next(iter(self._selected_widgets), None)
        self.emit("node-selected", first.graph_node if first else None)
        self.queue_gl_render()

    def _on_motion(self, controller, x, y):
        self._last_cursor_x = x
        self._last_cursor_y = y

    def _on_canvas_right_click(self, gesture, n_press, x, y):
        edge = self._find_edge_at(x, y)
        if edge:
            self._graph.remove_edge(edge.id)
            self._update_all_port_colors()
            self.queue_gl_render()
            self.emit("graph-changed")

    def set_extended_zoom(self, enabled: bool):
        self._extended_zoom = enabled

    def set_grid_visible(self, visible: bool):
        self._grid_visible = visible
        self.queue_gl_render()

    def set_snap_to_grid(self, enabled: bool):
        self._snap_to_grid = enabled

    def _update_grid_brightness_for_theme(self):
        dark = Adw.StyleManager.get_default().get_dark()
        self._grid_brightness = 0.22 if dark else 0.78

    def _on_color_scheme_changed(self, manager, pspec):
        self._update_grid_brightness_for_theme()
        self.queue_gl_render()

    def set_minimap_visible(self, visible: bool):
        self._minimap.set_visible(visible)

    def toggle_minimap(self):
        self.set_minimap_visible(not self._minimap.get_visible())

    def _on_select_all(self):
        for w in list(self._selected_widgets):
            w.set_selected(False)
        self._selected_widgets.clear()
        for w in self._node_widgets.values():
            w.set_selected(True)
            self._selected_widgets.add(w)
        first = next(iter(self._selected_widgets), None)
        self.emit("node-selected", first.graph_node if first else None)

    def _on_copy(self):
        if not self._selected_widgets:
            return
        selected_ids = {w.graph_node.id for w in self._selected_widgets}
        nodes_data = []
        for w in self._selected_widgets:
            n = w.graph_node
            nd = {
                "id": n.id,
                "type": n.node_type,
                "label": n.label,
                "x": n.x,
                "y": n.y,
                "width": n.width,
                "height": n.height,
                "params": {},
            }
            from nodes.node_types import (
                InputNode, FilterNode, BlendNode, ColorNode,
                OpacityNode, ColoringNode, MaskNode,
                ConstantNode, LabelNode, CommentNode,
            )
            if isinstance(n, InputNode):
                nd["params"]["file_path"] = n.file_path
            elif isinstance(n, FilterNode):
                nd["params"]["filter_key"] = f"{n.filter_def.engine}:{n.filter_def.name}"
                nd["params"]["param_values"] = dict(n.param_values)
            elif isinstance(n, BlendNode):
                nd["params"]["mode"] = n.mode
                nd["params"]["extra_ports"] = len(n.inputs) - 2
            elif isinstance(n, ColorNode):
                nd["params"]["operation"] = n.operation
                nd["params"]["brightness"] = n.brightness
                nd["params"]["contrast"] = n.contrast
                nd["params"]["saturation"] = n.saturation
                nd["params"]["hue"] = n.hue
                nd["params"]["black_point"] = n.black_point
                nd["params"]["white_point"] = n.white_point
                nd["params"]["gamma"] = n.gamma
            elif isinstance(n, OpacityNode):
                nd["params"]["opacity"] = n.opacity
            elif isinstance(n, ColoringNode):
                nd["params"]["hue"] = n.hue
                nd["params"]["saturation"] = n.saturation
                nd["params"]["lightness"] = n.lightness
            elif isinstance(n, MaskNode):
                nd["params"]["invert"] = n.invert
                nd["params"]["threshold"] = n.threshold
            elif isinstance(n, ConstantNode):
                nd["params"]["value"] = n.value
            elif isinstance(n, (LabelNode, CommentNode)):
                nd["params"]["text"] = n.text
                nd["params"]["color"] = n.color
            nodes_data.append(nd)

        edges_data = []
        for e in self._graph.edges:
            if e.src_node in selected_ids and e.dst_node in selected_ids:
                edges_data.append({
                    "src_node": e.src_node,
                    "src_port": e.src_port,
                    "dst_node": e.dst_node,
                    "dst_port": e.dst_port,
                })

        self._clipboard = {"nodes": nodes_data, "edges": edges_data}

    def _on_paste(self):
        if not self._clipboard:
            return
        from nodes.node_types import (
            InputNode, OutputNode, FilterNode, BlendNode, ColorNode,
            OpacityNode, ColoringNode, MaskNode,
            ConstantNode, AddNode, SubtractNode, MultiplyNode, DivideNode,
            CeilNode, FloorNode, RoundNode, SumNode, ProductNode,
            LabelNode, CommentNode,
        )
        ts = str(GLib.get_monotonic_time())
        id_map = {}
        for nd in self._clipboard["nodes"]:
            old_id = nd["id"]
            new_id = f"pasted_{old_id}_{ts}"
            id_map[old_id] = new_id

        nodes_data = self._clipboard["nodes"]
        if not nodes_data:
            return

        # compute bounding box center of copied nodes
        min_cx = min(n["x"] for n in nodes_data)
        max_cx = max(n["x"] + (n.get("width") or 200) for n in nodes_data)
        min_cy = min(n["y"] for n in nodes_data)
        max_cy = max(n["y"] + (n.get("height") or 100) for n in nodes_data)
        center_x = (min_cx + max_cx) / 2
        center_y = (min_cy + max_cy) / 2

        # convert cursor screen position to graph coordinates
        cursor_gx = (self._last_cursor_x - self._pan_x) / self._zoom
        cursor_gy = (self._last_cursor_y - self._pan_y) / self._zoom

        dx = cursor_gx - center_x
        dy = cursor_gy - center_y

        new_widgets = []
        for nd in nodes_data:
            nid = id_map[nd["id"]]
            typ = nd["type"]
            params = nd.get("params", {})
            x = nd.get("x", 0) + dx
            y = nd.get("y", 0) + dy
            node = None
            if typ == "input":
                node = InputNode(nid, x, y)
                fp = params.get("file_path")
                if fp:
                    node.file_path = fp
            elif typ == "output":
                node = OutputNode(nid, x, y)
            elif typ == "filter":
                fkey = params.get("filter_key", "")
                fdef = self._filter_def_map.get(fkey)
                if fdef:
                    node = FilterNode(nid, fdef, x, y)
                    for k, v in params.get("param_values", {}).items():
                        node.set_param(k, v)
                else:
                    continue
            elif typ == "blend":
                mode = params.get("mode", "over")
                node = BlendNode(nid, mode, x, y)
                extra = params.get("extra_ports", 0)
                for _ in range(extra):
                    node.add_input_port()
            elif typ == "color":
                node = ColorNode(nid, x, y)
                node.operation = params.get("operation", "brightness_contrast")
                node.brightness = params.get("brightness", 0.0)
                node.contrast = params.get("contrast", 0.0)
                node.saturation = params.get("saturation", 0.0)
                node.hue = params.get("hue", 0.0)
                node.black_point = params.get("black_point", 0.0)
                node.white_point = params.get("white_point", 100.0)
                node.gamma = params.get("gamma", 1.0)
            elif typ == "opacity":
                node = OpacityNode(nid, x, y)
                node.opacity = params.get("opacity", 1.0)
            elif typ == "coloring":
                node = ColoringNode(nid, x, y)
                node.hue = params.get("hue", 0.0)
                node.saturation = params.get("saturation", 0.0)
                node.lightness = params.get("lightness", 0.0)
            elif typ == "mask":
                node = MaskNode(nid, x, y)
                node.invert = params.get("invert", False)
                node.threshold = params.get("threshold", 0.5)
            elif typ == "constant":
                node = ConstantNode(nid, x, y)
                node.value = params.get("value", 0.0)
            elif typ in ("add", "subtract", "multiply", "divide"):
                cls = {"add": AddNode, "subtract": SubtractNode, "multiply": MultiplyNode, "divide": DivideNode}[typ]
                node = cls(nid, x, y)
            elif typ in ("ceil", "floor", "round", "sum", "product"):
                cls = {"ceil": CeilNode, "floor": FloorNode, "round": RoundNode, "sum": SumNode, "product": ProductNode}[typ]
                node = cls(nid, x, y)
            elif typ == "label":
                node = LabelNode(nid, x, y)
                node.text = params.get("text", "Label")
                node.color = params.get("color")
            elif typ == "comment":
                node = CommentNode(nid, x, y)
                node.text = params.get("text", "Comment")
                node.color = params.get("color")

            if node:
                node.width = nd.get("width", node.width)
                node.height = nd.get("height", node.height)
                label = nd.get("label")
                if label and typ != "input":
                    node.label = label
                self.add_node(node)
                nw = self._node_widgets.get(nid)
                if nw:
                    new_widgets.append(nw)

        for ed in self._clipboard["edges"]:
            new_src = id_map.get(ed["src_node"])
            new_dst = id_map.get(ed["dst_node"])
            if new_src and new_dst:
                self._graph.add_edge(new_src, ed["src_port"], new_dst, ed["dst_port"])

        for w in list(self._selected_widgets):
            w.set_selected(False)
        self._selected_widgets.clear()
        for w in new_widgets:
            w.set_selected(True)
            self._selected_widgets.add(w)
        first = next(iter(self._selected_widgets), None)
        self.emit("node-selected", first.graph_node if first else None)
        self._update_all_port_colors()
        self.queue_gl_render()
        self.emit("graph-changed")

    def _on_key_pressed(self, controller, keyval, keycode, state):
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        if ctrl and keyval in (Gdk.KEY_C, Gdk.KEY_c):
            self._on_copy()
            return True
        if ctrl and keyval in (Gdk.KEY_V, Gdk.KEY_v):
            self._on_paste()
            return True
        if ctrl and keyval in (Gdk.KEY_A, Gdk.KEY_a):
            self._on_select_all()
            return True
        if keyval in (Gdk.KEY_M, Gdk.KEY_m):
            self.toggle_minimap()
            return True
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
            if self._selected_port:
                pw = self._selected_port
                node_id = pw.port.node_id
                port_name = pw.port.name
                direction = pw.port.direction
                if direction == PortDirection.INPUT:
                    edge = self._graph.get_connected_input(node_id, port_name)
                    if edge:
                        self._graph.remove_edge(edge.id)
                else:
                    self._graph.remove_edges_for_port(node_id, port_name, PortDirection.OUTPUT)
                self._clear_selected_port()
                self._update_all_port_colors()
                self.queue_gl_render()
                self.emit("graph-changed")
                return True
            if self._selected_widgets:
                for w in list(self._selected_widgets):
                    self.remove_node(w.graph_node.id)
                return True
        return False

    def _find_edge_at(self, x, y, threshold=20.0):
        closest = None
        closest_dist = threshold
        for edge in self._graph.edges:
            src_n = self._graph.get_node(edge.src_node)
            dst_n = self._graph.get_node(edge.dst_node)
            if not src_n or not dst_n:
                continue
            sw = self._node_widgets.get(edge.src_node)
            dw = self._node_widgets.get(edge.dst_node)
            if not sw or not dw:
                continue
            spw = sw.get_output_port_widget(edge.src_port)
            dpw = dw.get_input_port_widget(edge.dst_port)
            if not spw or not dpw:
                continue
            x1, y1 = spw.center_x, spw.center_y
            x2, y2 = dpw.center_x, dpw.center_y
            d1 = math.hypot(x - x1, y - y1)
            if d1 < closest_dist:
                closest_dist = d1
                closest = edge
            d2 = math.hypot(x - x2, y - y2)
            if d2 < closest_dist:
                closest_dist = d2
                closest = edge
            pts = _compute_bezier_segments(x1, y1, x2, y2, CURVE_SEGMENTS)
            for i in range(0, len(pts) - 2, 2):
                ex, ey = pts[i], pts[i + 1]
                d = math.hypot(x - ex, y - ey)
                if d < closest_dist:
                    closest_dist = d
                    closest = edge
        return closest

    def _on_scroll(self, controller, dx, dy) -> bool:
        alloc = self._wire_overlay.get_allocation()
        mx, my = alloc.x + alloc.width / 2, alloc.y + alloc.height / 2

        old_zoom = self._zoom
        step = 0.25 if dy < 0 else -0.25
        if self._extended_zoom:
            new_zoom = max(0.25, min(10.0, old_zoom + step))
        else:
            new_zoom = max(0.75, min(5.0, old_zoom + step))
        if new_zoom == old_zoom:
            return False

        self._pan_x = mx - new_zoom * (mx - self._pan_x) / old_zoom
        self._pan_y = my - new_zoom * (my - self._pan_y) / old_zoom
        self._zoom = new_zoom
        self._clamp_pan()
        self._update_zoom_label()
        self._update_all_positions()
        return True


