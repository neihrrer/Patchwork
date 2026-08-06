import math
import os
import gettext
from typing import Optional, Callable

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
    Node, NodeGraph, Edge, Port, PortDirection, PortType, FilterNode, InputNode, VideoInputNode, TimeNode, RawInputNode, RawDecodeNode, OutputNode, BlendNode,
    OpacityNode, MaskNode,
    BrightnessContrastNode, LevelsNode, HSLNode,
    ColorSourceNode, GradientNode, NoiseNode,
    ColorBalanceNode, ExposureGammaNode, CurvesNode,
    CropNode, ResizeNode, RotateNode, FlipNode, DistortNode,
    BlurNode, SharpenNode, EdgeDetectNode,
    ConstantNode, AddNode, SubtractNode, MultiplyNode, DivideNode,
    CeilNode, FloorNode, RoundNode, SumNode, ProductNode,
    ModuloNode, PowerNode, SquareRootNode, AbsoluteNode, LogNode, ExpNode, RandomNode,
    LabelNode, CommentNode,
    HistogramNode, WaveformMonitorNode, VectorscopeNode, FrequencyDomainNode,
    NotNode, AndNode, OrNode, NandNode, NorNode, XorNode, XnorNode,
    CompareNode, ClampNode, MapRangeNode,
)
from nodes.node_types import LABEL_COLORS, NODE_CATEGORY_MAP, CATEGORY_GDK_RGBA, HistogramNode, WaveformMonitorNode, VectorscopeNode, FrequencyDomainNode
from models.filter import FilterDef, ParamKind
from .filter_browser import get_pending_drag_text, peek_pending_drag_text

# ─── Analysis node types for Cairo rendering ────────────────────────────────

_ANALYSIS_NODE_TYPES = (
    HistogramNode, WaveformMonitorNode, VectorscopeNode, FrequencyDomainNode,
)

_ANALYSIS_RED    = (0.88, 0.11, 0.14)
_ANALYSIS_GREEN  = (0.18, 0.76, 0.49)
_ANALYSIS_BLUE   = (0.11, 0.44, 0.85)
_ANALYSIS_YELLOW = (0.96, 0.83, 0.18)
_ANALYSIS_WHITE  = (1.0,  1.0,  1.0)

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
        a = (_compute_numeric_value(a_edge.src_node, graph, visited) or 0.0) if a_edge else 0.0
        b = (_compute_numeric_value(b_edge.src_node, graph, visited) or 0.0) if b_edge else 0.0
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
        return math.ceil(a) if a is not None else 0.0

    if isinstance(node, FloorNode):
        a_edge = graph.get_connected_input(node_id, "a")
        a = _compute_numeric_value(a_edge.src_node, graph, visited) if a_edge else 0.0
        return math.floor(a) if a is not None else 0.0

    if isinstance(node, RoundNode):
        a_edge = graph.get_connected_input(node_id, "a")
        a = _compute_numeric_value(a_edge.src_node, graph, visited) if a_edge else 0.0
        return round(a) if a is not None else 0.0

    if isinstance(node, NotNode):
        a_edge = graph.get_connected_input(node_id, "a")
        a = _compute_numeric_value(a_edge.src_node, graph, visited) or 0.0 if a_edge else 0.0
        return 1.0 if a == 0.0 else 0.0

    if isinstance(node, (AndNode, OrNode, NandNode, NorNode, XorNode, XnorNode)):
        a_edge = graph.get_connected_input(node_id, "a")
        b_edge = graph.get_connected_input(node_id, "b")
        a = (_compute_numeric_value(a_edge.src_node, graph, visited) or 0.0) if a_edge else 0.0
        b = (_compute_numeric_value(b_edge.src_node, graph, visited) or 0.0) if b_edge else 0.0
        a_bool = a != 0.0
        b_bool = b != 0.0
        if isinstance(node, AndNode):
            return 1.0 if a_bool and b_bool else 0.0
        if isinstance(node, OrNode):
            return 1.0 if a_bool or b_bool else 0.0
        if isinstance(node, NandNode):
            return 0.0 if a_bool and b_bool else 1.0
        if isinstance(node, NorNode):
            return 0.0 if a_bool or b_bool else 1.0
        if isinstance(node, XorNode):
            return 1.0 if a_bool != b_bool else 0.0
        if isinstance(node, XnorNode):
            return 1.0 if a_bool == b_bool else 0.0

    if isinstance(node, CompareNode):
        a_edge = graph.get_connected_input(node_id, "a")
        b_edge = graph.get_connected_input(node_id, "b")
        a = (_compute_numeric_value(a_edge.src_node, graph, visited) or 0.0) if a_edge else 0.0
        b = (_compute_numeric_value(b_edge.src_node, graph, visited) or 0.0) if b_edge else 0.0
        op = node.operator
        if op == "==":
            return 1.0 if a == b else 0.0
        if op == "!=":
            return 1.0 if a != b else 0.0
        if op == "<":
            return 1.0 if a < b else 0.0
        if op == ">":
            return 1.0 if a > b else 0.0
        if op == "<=":
            return 1.0 if a <= b else 0.0
        if op == ">=":
            return 1.0 if a >= b else 0.0
        return 0.0

    if isinstance(node, ClampNode):
        a_edge = graph.get_connected_input(node_id, "a")
        a = _compute_numeric_value(a_edge.src_node, graph, visited) if a_edge else 0.0
        if a is not None:
            return max(node.min_val, min(node.max_val, a))
        return node.min_val

    if isinstance(node, MapRangeNode):
        a_edge = graph.get_connected_input(node_id, "a")
        a = _compute_numeric_value(a_edge.src_node, graph, visited) if a_edge else 0.0
        if a is not None:
            in_range = node.in_max - node.in_min
            if in_range == 0.0:
                return node.out_min
            t = (a - node.in_min) / in_range
            return node.out_min + t * (node.out_max - node.out_min)
        return node.out_min

    if isinstance(node, ModuloNode):
        a_edge = graph.get_connected_input(node_id, "a")
        b_edge = graph.get_connected_input(node_id, "b")
        a = (_compute_numeric_value(a_edge.src_node, graph, visited) or 0.0) if a_edge else 0.0
        b = (_compute_numeric_value(b_edge.src_node, graph, visited) or 1.0) if b_edge else 1.0
        return a % b if b != 0 else None

    if isinstance(node, PowerNode):
        a_edge = graph.get_connected_input(node_id, "a")
        b_edge = graph.get_connected_input(node_id, "b")
        a = (_compute_numeric_value(a_edge.src_node, graph, visited) or 0.0) if a_edge else 0.0
        b = (_compute_numeric_value(b_edge.src_node, graph, visited) or 1.0) if b_edge else 1.0
        return a ** b

    if isinstance(node, SquareRootNode):
        a_edge = graph.get_connected_input(node_id, "a")
        a = _compute_numeric_value(a_edge.src_node, graph, visited) if a_edge else 0.0
        if a is not None and a >= 0:
            return math.sqrt(a)
        return 0.0

    if isinstance(node, AbsoluteNode):
        a_edge = graph.get_connected_input(node_id, "a")
        a = _compute_numeric_value(a_edge.src_node, graph, visited) if a_edge else 0.0
        return abs(a) if a is not None else 0.0

    if isinstance(node, LogNode):
        a_edge = graph.get_connected_input(node_id, "a")
        a = _compute_numeric_value(a_edge.src_node, graph, visited) if a_edge else 1.0
        if a is not None and a > 0:
            return math.log(a)
        return 0.0

    if isinstance(node, ExpNode):
        a_edge = graph.get_connected_input(node_id, "a")
        a = _compute_numeric_value(a_edge.src_node, graph, visited) if a_edge else 0.0
        return math.exp(a) if a is not None else 1.0

    if isinstance(node, RandomNode):
        return node.value

    return None


_NODE_PREVIEW_INFO = {
    "blend:": (_("Blend"), "blend"),
    "opacity:": (_("Opacity"), "opacity"),
    "mask:": (_("Mask"), "mask"),
    "brightness_contrast:": (_("Brightness/Contrast"), "brightness_contrast"),
    "levels:": (_("Levels"), "levels"),
    "hsl:": (_("HSL"), "hsl"),
    "color_balance:": (_("Color Balance"), "color_balance"),
    "exposure_gamma:": (_("Exposure/Gamma"), "exposure_gamma"),
    "curves:": (_("Curves"), "curves"),
    "crop:": (_("Crop"), "crop"),
    "resize:": (_("Resize"), "resize"),
    "rotate:": (_("Rotate"), "rotate"),
    "flip:": (_("Flip"), "flip"),
    "distort:": (_("Distort"), "distort"),
    "blur:": (_("Blur"), "blur"),
    "sharpen:": (_("Sharpen"), "sharpen"),
    "edge_detect:": (_("Edge Detect"), "edge_detect"),
    "color_source:": (_("Color Source"), "color_source"),
    "gradient:": (_("Gradient"), "gradient"),
    "noise:": (_("Noise"), "noise"),
    "input:": (_("Input"), "input"),
    "video_input:": (_("Video Input"), "video_input"),
    "time:": (_("Clock"), "time"),
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
    "not:": (_("NOT"), "not"),
    "and:": (_("AND"), "and"),
    "or:": (_("OR"), "or"),
    "nand:": (_("NAND"), "nand"),
    "nor:": (_("NOR"), "nor"),
    "xor:": (_("XOR"), "xor"),
    "xnor:": (_("XNOR"), "xnor"),
    "compare:": (_("Compare"), "compare"),
    "clamp:": (_("Clamp"), "clamp"),
    "map_range:": (_("Map Range"), "map_range"),
    "modulo:": (_("Modulo"), "modulo"),
    "power:": (_("Power"), "power"),
    "square_root:": (_("Square Root"), "square_root"),
    "absolute:": (_("Absolute"), "absolute"),
    "log:": (_("Log"), "log"),
    "exp:": (_("Exp"), "exp"),
    "random:": (_("Random"), "random"),
    "raw_input:": (_("Raw Input"), "raw_input"),
    "raw_decode:": (_("Raw Decode"), "raw_decode"),
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


def _is_analysis_node(node) -> bool:
    return isinstance(node, _ANALYSIS_NODE_TYPES)


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
        self._analysis_area: Optional[Gtk.DrawingArea] = None
        self._analysis_data: Optional[dict] = None
        self._time_value_label: Optional[Gtk.Label] = None
        self._image_aspect: Optional[float] = None
        self._anim_frames: list[str] = []
        self._anim_fps: int = 1
        self._anim_index: int = 0
        self._anim_playing: bool = False
        self._anim_timer_id: int = 0
        self._anim_bar: Optional[Gtk.Box] = None
        self._anim_scale: Optional[Gtk.Scale] = None
        self._anim_frame_label: Optional[Gtk.Label] = None
        self._anim_seek_guard: bool = False
        self._anim_min_w = 340
        self._anim_bar_h = 52
        self._resize_start_w = 0
        self._resize_start_h = 0
        self._resize_start_px = 0.0
        self._resize_start_py = 0.0
        self._min_node_w = 180
        self._min_node_h = 160
        self._has_image = False
        self._logical_w = int(self._node.width or 240)
        self._logical_h = int(self._node.height or 200)
        self._saved_logical_h: int = self._logical_h
        self._saved_logical_w: int = self._logical_w
        self._screen_x = 0.0
        self._screen_y = 0.0
        self._minimize_btn: Optional[Gtk.ToggleButton] = None
        self._ports_box: Optional[Gtk.Box] = None
        self._saved_port_offsets: dict[str, tuple[float, float]] = {}

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
        category = NODE_CATEGORY_MAP.get(self._node.node_type)
        if category:
            ctx.add_class(f"category-{category}")
        self._header = header

        self._title = Gtk.Label(label=self._node.label, xalign=0, hexpand=True)
        self._title.set_css_classes(["node-title"])
        header.append(self._title)

        self._minimize_btn = Gtk.ToggleButton()
        self._minimize_btn.set_css_classes(["node-minimize-btn"])
        self._minimize_btn.set_active(self._node.minimized)
        self._minimize_btn.connect("toggled", self._on_minimize_toggled)
        icon_name = "window-restore-symbolic" if self._node.minimized else "window-minimize-symbolic"
        self._minimize_icon = Gtk.Image(icon_name=icon_name)
        self._minimize_btn.set_child(self._minimize_icon)
        header.append(self._minimize_btn)

        self.append(header)

        self._ports_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        ports_box = self._ports_box
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

        is_analysis = _is_analysis_node(self._node)

        self._thumb_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._thumb_box.set_hexpand(True)
        self._thumb_box.set_vexpand(True)
        self._thumb_box.set_visible(is_analysis)

        self._thumb_overlay = Gtk.Overlay()
        self._thumb_overlay.set_hexpand(True)
        self._thumb_overlay.set_vexpand(True)

        self._thumb_sizer: Optional[Gtk.Widget] = None

        if is_analysis:
            self._analysis_area = Gtk.DrawingArea()
            self._analysis_area.set_hexpand(True)
            self._analysis_area.set_vexpand(True)
            self._analysis_area.set_draw_func(self._on_analysis_draw)
            self._thumb_overlay.set_child(self._analysis_area)
            self._thumb_picture = None
        else:
            self._thumb_picture = Gtk.Picture()
            self._thumb_picture.set_hexpand(True)
            self._thumb_picture.set_vexpand(True)
            self._thumb_picture.set_keep_aspect_ratio(True)
            self._thumb_picture.set_can_shrink(True)

            self._thumb_sizer = Gtk.Box()
            self._thumb_overlay.set_child(self._thumb_sizer)
            self._thumb_overlay.add_overlay(self._thumb_picture)

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

        if self._node.minimized:
            self._apply_minimize_state()

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
                f" {{ background: {hex_color}; color: rgba(0, 0, 0, 0.8); }}\n"
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

    # ─── Minimize / Expand ────────────────────────────────────────────

    def _on_minimize_toggled(self, btn: Gtk.ToggleButton):
        self._node.minimized = btn.get_active()
        self._minimize_icon.props.icon_name = (
            "window-restore-symbolic" if self._node.minimized else "window-minimize-symbolic"
        )
        self._apply_minimize_state()
        self._canvas._update_port_centers(self._node)
        self._canvas.queue_gl_render()

    def toggle_minimize(self):
        if self._minimize_btn is None:
            return
        self._minimize_btn.set_active(not self._minimize_btn.get_active())

    def _save_port_offsets(self):
        for name, pw in self._input_port_widgets.items():
            pw.update_center()
            self._saved_port_offsets[name] = (pw._offset_x, pw._offset_y)
        for name, pw in self._output_port_widgets.items():
            pw.update_center()
            self._saved_port_offsets[name] = (pw._offset_x, pw._offset_y)

    def _apply_minimize_state(self):
        minimized = self._node.minimized
        zoom = self._canvas._zoom
        if minimized:
            self._saved_logical_h = self._logical_h
            self._saved_logical_w = self._logical_w
            self._save_port_offsets()
            for pw in self._input_port_widgets.values():
                pw.set_visible(False)
            for pw in self._output_port_widgets.values():
                pw.set_visible(False)
            if self._ports_box:
                self._ports_box.set_visible(False)
            if self._thumb_box:
                self._thumb_box.set_visible(False)
            for row in self._param_controls:
                row.set_visible(False)
            if self._resize_handle:
                self._resize_handle.set_visible(False)
            self._logical_h = 30
            self._title.set_hexpand(False)
            self._header.add_css_class("minimized")
            self.set_size_request(
                -1,
                max(1, int(30 * zoom)),
            )
        else:
            self._logical_h = self._saved_logical_h
            self._logical_w = self._saved_logical_w
            for pw in self._input_port_widgets.values():
                pw.set_visible(True)
            for pw in self._output_port_widgets.values():
                pw.set_visible(True)
            if self._ports_box:
                self._ports_box.set_visible(True)
            if self._thumb_box:
                self._thumb_box.set_visible(self._has_image or _is_analysis_node(self._node))
            for row in self._param_controls:
                row.set_visible(True)
            self._resize_handle.set_visible(self._has_image)
            self._saved_port_offsets.clear()
            self._title.set_hexpand(True)
            self._header.remove_css_class("minimized")
            if self._has_image:
                if self._image_aspect:
                    self._logical_w = max(self._logical_w, 240)
                    self._logical_h = max(self._logical_h, int(240 / self._image_aspect))
                else:
                    self._logical_w = max(self._logical_w, 220)
                    self._logical_h = max(self._logical_h, 200)
                self._node.width = self._logical_w
                self._node.height = self._logical_h
                self.apply_zoom(zoom)
            else:
                self.set_size_request(
                    max(1, int(self._logical_w * zoom)),
                    max(1, int(self._logical_h * zoom)),
                )

    def _build_params(self):
        if isinstance(self._node, FilterNode):
            self._build_filter_params()
        elif isinstance(self._node, BlendNode):
            self._build_blend_params()
        elif isinstance(self._node, OpacityNode):
            self._build_opacity_params()
        elif isinstance(self._node, MaskNode):
            self._build_mask_params()
        elif isinstance(self._node, BrightnessContrastNode):
            self._build_brightness_contrast_params()
        elif isinstance(self._node, LevelsNode):
            self._build_levels_params()
        elif isinstance(self._node, HSLNode):
            self._build_hsl_params()
        elif isinstance(self._node, ColorSourceNode):
            self._build_color_source_params()
        elif isinstance(self._node, GradientNode):
            self._build_gradient_params()
        elif isinstance(self._node, NoiseNode):
            self._build_noise_params()
        elif isinstance(self._node, ColorBalanceNode):
            self._build_color_balance_params()
        elif isinstance(self._node, ExposureGammaNode):
            self._build_exposure_gamma_params()
        elif isinstance(self._node, CurvesNode):
            self._build_curves_params()
        elif isinstance(self._node, CropNode):
            self._build_crop_params()
        elif isinstance(self._node, ResizeNode):
            self._build_resize_params()
        elif isinstance(self._node, RotateNode):
            self._build_rotate_params()
        elif isinstance(self._node, FlipNode):
            self._build_flip_params()
        elif isinstance(self._node, DistortNode):
            self._build_distort_params()
        elif isinstance(self._node, BlurNode):
            self._build_blur_params()
        elif isinstance(self._node, SharpenNode):
            self._build_sharpen_params()
        elif isinstance(self._node, EdgeDetectNode):
            self._build_edge_detect_params()
        elif isinstance(self._node, ConstantNode):
            self._build_constant_params()
        elif isinstance(self._node, TimeNode):
            self._build_time_params()
        elif isinstance(self._node, CompareNode):
            self._build_compare_params()
        elif isinstance(self._node, ClampNode):
            self._build_clamp_params()
        elif isinstance(self._node, MapRangeNode):
            self._build_map_range_params()
        elif isinstance(self._node, RandomNode):
            self._build_random_params()
        elif isinstance(self._node, RawDecodeNode):
            self._build_raw_decode_params()

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

    def _build_brightness_contrast_params(self):
        node: BrightnessContrastNode = self._node
        for label, attr, lo, hi in [
            ("Brightness", "brightness", -100.0, 100.0),
            ("Contrast", "contrast", -100.0, 100.0),
        ]:
            adj = Gtk.Adjustment(value=getattr(node, attr), lower=lo, upper=hi, step_increment=1)
            spin = Gtk.SpinButton(adjustment=adj, climb_rate=1, digits=1)
            spin.connect("value-changed", lambda s, a=attr: setattr(node, a, s.get_value()))
            spin.set_css_classes(["node-param-control"])
            self._ctrl_widgets.append(spin)
            self._port_spin_buttons[attr] = spin
            self._make_control_row(label, attr, spin)

    def _build_levels_params(self):
        node: LevelsNode = self._node
        for label, attr, lo, hi in [
            ("Black Point", "black_point", 0.0, 100.0),
            ("White Point", "white_point", 0.0, 100.0),
            ("Gamma", "gamma", 0.01, 10.0),
        ]:
            adj = Gtk.Adjustment(value=getattr(node, attr), lower=lo, upper=hi, step_increment=0.1)
            spin = Gtk.SpinButton(adjustment=adj, climb_rate=0.1, digits=2)
            spin.connect("value-changed", lambda s, a=attr: setattr(node, a, s.get_value()))
            spin.set_css_classes(["node-param-control"])
            self._ctrl_widgets.append(spin)
            self._port_spin_buttons[attr] = spin
            self._make_control_row(label, attr, spin)

    def _build_hsl_params(self):
        node: HSLNode = self._node
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

    def _build_color_source_params(self):
        node: ColorSourceNode = self._node
        adj_w = Gtk.Adjustment(value=node.source_width, lower=1, upper=10000, step_increment=1)
        spin_w = Gtk.SpinButton(adjustment=adj_w, climb_rate=1, digits=0)
        spin_w.connect("value-changed", lambda s: setattr(node, "source_width", int(s.get_value())))
        spin_w.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin_w)
        self._make_control_row("Width", "source_width", spin_w)
        adj_h = Gtk.Adjustment(value=node.source_height, lower=1, upper=10000, step_increment=1)
        spin_h = Gtk.SpinButton(adjustment=adj_h, climb_rate=1, digits=0)
        spin_h.connect("value-changed", lambda s: setattr(node, "source_height", int(s.get_value())))
        spin_h.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin_h)
        self._make_control_row("Height", "source_height", spin_h)
        entry = Gtk.Entry(text=node.color)
        entry.connect("changed", lambda e: setattr(node, "color", e.get_text()))
        entry.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(entry)
        self._make_control_row("Color", "color", entry)

    def _build_gradient_params(self):
        node: GradientNode = self._node
        adj_w = Gtk.Adjustment(value=node.source_width, lower=1, upper=10000, step_increment=1)
        spin_w = Gtk.SpinButton(adjustment=adj_w, climb_rate=1, digits=0)
        spin_w.connect("value-changed", lambda s: setattr(node, "source_width", int(s.get_value())))
        spin_w.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin_w)
        self._make_control_row("Width", "source_width", spin_w)
        adj_h = Gtk.Adjustment(value=node.source_height, lower=1, upper=10000, step_increment=1)
        spin_h = Gtk.SpinButton(adjustment=adj_h, climb_rate=1, digits=0)
        spin_h.connect("value-changed", lambda s: setattr(node, "source_height", int(s.get_value())))
        spin_h.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin_h)
        self._make_control_row("Height", "source_height", spin_h)
        dd = Gtk.DropDown()
        dd.set_model(Gtk.StringList.new(["Linear", "Radial"]))
        idx = 0 if node.gradient_type == "linear" else 1
        dd.set_selected(idx)
        dd.set_valign(Gtk.Align.CENTER)
        dd.connect("notify::selected", lambda d, ps: setattr(node, "gradient_type",
                    "linear" if d.get_selected() == 0 else "radial"))
        dd.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(dd)
        self._make_control_row("Type", "gradient_type", dd)
        for label, attr in [("Start Color", "start_color"), ("End Color", "end_color")]:
            entry = Gtk.Entry(text=getattr(node, attr))
            entry.connect("changed", lambda e, a=attr: setattr(node, a, e.get_text()))
            entry.set_css_classes(["node-param-control"])
            self._ctrl_widgets.append(entry)
            self._make_control_row(label, attr, entry)
        adj_a = Gtk.Adjustment(value=node.angle, lower=0.0, upper=360.0, step_increment=1)
        spin_a = Gtk.SpinButton(adjustment=adj_a, climb_rate=1, digits=1)
        spin_a.connect("value-changed", lambda s: setattr(node, "angle", s.get_value()))
        spin_a.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin_a)
        self._port_spin_buttons["angle"] = spin_a
        self._make_control_row("Angle", "angle", spin_a)

    def _build_noise_params(self):
        node: NoiseNode = self._node
        adj_w = Gtk.Adjustment(value=node.source_width, lower=1, upper=10000, step_increment=1)
        spin_w = Gtk.SpinButton(adjustment=adj_w, climb_rate=1, digits=0)
        spin_w.connect("value-changed", lambda s: setattr(node, "source_width", int(s.get_value())))
        spin_w.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin_w)
        self._make_control_row("Width", "source_width", spin_w)
        adj_h = Gtk.Adjustment(value=node.source_height, lower=1, upper=10000, step_increment=1)
        spin_h = Gtk.SpinButton(adjustment=adj_h, climb_rate=1, digits=0)
        spin_h.connect("value-changed", lambda s: setattr(node, "source_height", int(s.get_value())))
        spin_h.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin_h)
        self._make_control_row("Height", "source_height", spin_h)
        dd = Gtk.DropDown()
        dd.set_model(Gtk.StringList.new(["Gaussian", "Uniform"]))
        idx = 0 if node.noise_type == "gaussian" else 1
        dd.set_selected(idx)
        dd.set_valign(Gtk.Align.CENTER)
        dd.connect("notify::selected", lambda d, ps: setattr(node, "noise_type",
                    "gaussian" if d.get_selected() == 0 else "uniform"))
        dd.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(dd)
        self._make_control_row("Type", "noise_type", dd)
        adj_s = Gtk.Adjustment(value=node.scale, lower=0.0, upper=255.0, step_increment=1)
        spin_s = Gtk.SpinButton(adjustment=adj_s, climb_rate=1, digits=1)
        spin_s.connect("value-changed", lambda s: setattr(node, "scale", s.get_value()))
        spin_s.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin_s)
        self._make_control_row("Scale", "scale", spin_s)
        adj_seed = Gtk.Adjustment(value=node.seed, lower=-1, upper=999999, step_increment=1)
        spin_seed = Gtk.SpinButton(adjustment=adj_seed, climb_rate=1, digits=0)
        spin_seed.connect("value-changed", lambda s: setattr(node, "seed", int(s.get_value())))
        spin_seed.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin_seed)
        self._make_control_row("Seed", "seed", spin_seed)

    def _build_color_balance_params(self):
        node: ColorBalanceNode = self._node
        for label, attr, lo, hi in [
            ("Cyan/Red", "cyan_red", -100.0, 100.0),
            ("Magenta/Green", "magenta_green", -100.0, 100.0),
            ("Yellow/Blue", "yellow_blue", -100.0, 100.0),
        ]:
            adj = Gtk.Adjustment(value=getattr(node, attr), lower=lo, upper=hi, step_increment=1)
            spin = Gtk.SpinButton(adjustment=adj, climb_rate=1, digits=1)
            spin.connect("value-changed", lambda s, a=attr: setattr(node, a, s.get_value()))
            spin.set_css_classes(["node-param-control"])
            self._ctrl_widgets.append(spin)
            self._port_spin_buttons[attr] = spin
            self._make_control_row(label, attr, spin)

    def _build_exposure_gamma_params(self):
        node: ExposureGammaNode = self._node
        adj_e = Gtk.Adjustment(value=node.exposure, lower=-5.0, upper=5.0, step_increment=0.1)
        spin_e = Gtk.SpinButton(adjustment=adj_e, climb_rate=0.1, digits=2)
        spin_e.connect("value-changed", lambda s: setattr(node, "exposure", s.get_value()))
        spin_e.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin_e)
        self._port_spin_buttons["exposure"] = spin_e
        self._make_control_row("Exposure", "exposure", spin_e)
        adj_g = Gtk.Adjustment(value=node.gamma, lower=0.01, upper=10.0, step_increment=0.1)
        spin_g = Gtk.SpinButton(adjustment=adj_g, climb_rate=0.1, digits=2)
        spin_g.connect("value-changed", lambda s: setattr(node, "gamma", s.get_value()))
        spin_g.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin_g)
        self._port_spin_buttons["gamma"] = spin_g
        self._make_control_row("Gamma", "gamma", spin_g)

    def _build_curves_params(self):
        node: CurvesNode = self._node
        for label, attr, lo, hi in [
            ("Shadows", "shadows", 0.0, 255.0),
            ("Dark Midtones", "dark_midtones", 0.0, 255.0),
            ("Midtones", "midtones", 0.0, 255.0),
            ("Light Midtones", "light_midtones", 0.0, 255.0),
            ("Highlights", "highlights", 0.0, 255.0),
        ]:
            adj = Gtk.Adjustment(value=getattr(node, attr), lower=lo, upper=hi, step_increment=1)
            spin = Gtk.SpinButton(adjustment=adj, climb_rate=1, digits=1)
            spin.connect("value-changed", lambda s, a=attr: setattr(node, a, s.get_value()))
            spin.set_css_classes(["node-param-control"])
            self._ctrl_widgets.append(spin)
            self._port_spin_buttons[attr] = spin
            self._make_control_row(label, attr, spin)

    def _build_crop_params(self):
        node: CropNode = self._node
        for label, attr, lo, hi in [
            ("X", "crop_x", 0.0, 10000.0),
            ("Y", "crop_y", 0.0, 10000.0),
            ("Width", "crop_width", 1.0, 10000.0),
            ("Height", "crop_height", 1.0, 10000.0),
        ]:
            adj = Gtk.Adjustment(value=getattr(node, attr), lower=lo, upper=hi, step_increment=1)
            spin = Gtk.SpinButton(adjustment=adj, climb_rate=1, digits=1)
            spin.connect("value-changed", lambda s, a=attr: setattr(node, a, s.get_value()))
            spin.set_css_classes(["node-param-control"])
            self._ctrl_widgets.append(spin)
            self._port_spin_buttons[attr] = spin
            self._make_control_row(label, attr, spin)

    def _build_resize_params(self):
        node: ResizeNode = self._node
        adj_w = Gtk.Adjustment(value=node.resize_width, lower=1, upper=10000, step_increment=1)
        spin_w = Gtk.SpinButton(adjustment=adj_w, climb_rate=1, digits=1)
        spin_w.connect("value-changed", lambda s: setattr(node, "resize_width", s.get_value()))
        spin_w.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin_w)
        self._port_spin_buttons["width"] = spin_w
        self._make_control_row("Width", "resize_width", spin_w)
        adj_h = Gtk.Adjustment(value=node.resize_height, lower=1, upper=10000, step_increment=1)
        spin_h = Gtk.SpinButton(adjustment=adj_h, climb_rate=1, digits=1)
        spin_h.connect("value-changed", lambda s: setattr(node, "resize_height", s.get_value()))
        spin_h.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin_h)
        self._port_spin_buttons["height"] = spin_h
        self._make_control_row("Height", "resize_height", spin_h)
        dd = Gtk.DropDown()
        dd.set_model(Gtk.StringList.new(["Stretch", "Fit", "Fill"]))
        idx = {"stretch": 0, "fit": 1, "fill": 2}.get(node.resize_mode, 0)
        dd.set_selected(idx)
        dd.set_valign(Gtk.Align.CENTER)
        dd.connect("notify::selected", lambda d, ps: setattr(node, "resize_mode",
                    ["stretch", "fit", "fill"][d.get_selected()]))
        dd.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(dd)
        self._make_control_row("Mode", "resize_mode", dd)

    def _build_rotate_params(self):
        node: RotateNode = self._node
        adj = Gtk.Adjustment(value=node.angle, lower=-360.0, upper=360.0, step_increment=1)
        spin = Gtk.SpinButton(adjustment=adj, climb_rate=1, digits=1)
        spin.connect("value-changed", lambda s: setattr(node, "angle", s.get_value()))
        spin.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin)
        self._port_spin_buttons["angle"] = spin
        self._make_control_row("Angle", "angle", spin)

    def _build_flip_params(self):
        node: FlipNode = self._node
        dd = Gtk.DropDown()
        dd.set_model(Gtk.StringList.new(["Horizontal", "Vertical"]))
        idx = 0 if node.direction == "horizontal" else 1
        dd.set_selected(idx)
        dd.set_valign(Gtk.Align.CENTER)
        dd.connect("notify::selected", lambda d, ps: setattr(node, "direction",
                    "horizontal" if d.get_selected() == 0 else "vertical"))
        dd.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(dd)
        self._make_control_row("Direction", "direction", dd)

    def _build_distort_params(self):
        node: DistortNode = self._node
        for label, attr, lo, hi in [
            ("Top-Left X", "dist_x0", 0.0, 10000.0),
            ("Top-Left Y", "dist_y0", 0.0, 10000.0),
            ("Top-Right X", "dist_x1", 0.0, 10000.0),
            ("Top-Right Y", "dist_y1", 0.0, 10000.0),
            ("Bottom-Right X", "dist_x2", 0.0, 10000.0),
            ("Bottom-Right Y", "dist_y2", 0.0, 10000.0),
            ("Bottom-Left X", "dist_x3", 0.0, 10000.0),
            ("Bottom-Left Y", "dist_y3", 0.0, 10000.0),
        ]:
            adj = Gtk.Adjustment(value=getattr(node, attr), lower=lo, upper=hi, step_increment=1)
            spin = Gtk.SpinButton(adjustment=adj, climb_rate=1, digits=1)
            spin.connect("value-changed", lambda s, a=attr: setattr(node, a, s.get_value()))
            spin.set_css_classes(["node-param-control"])
            self._ctrl_widgets.append(spin)
            self._port_spin_buttons[attr] = spin
            self._make_control_row(label, attr, spin)

    def _build_blur_params(self):
        node: BlurNode = self._node
        adj = Gtk.Adjustment(value=node.radius, lower=0.0, upper=500.0, step_increment=0.5)
        spin = Gtk.SpinButton(adjustment=adj, climb_rate=0.5, digits=1)
        spin.connect("value-changed", lambda s: setattr(node, "radius", s.get_value()))
        spin.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin)
        self._port_spin_buttons["radius"] = spin
        self._make_control_row("Radius", "radius", spin)

    def _build_sharpen_params(self):
        node: SharpenNode = self._node
        adj_a = Gtk.Adjustment(value=node.amount, lower=0.0, upper=10.0, step_increment=0.1)
        spin_a = Gtk.SpinButton(adjustment=adj_a, climb_rate=0.1, digits=2)
        spin_a.connect("value-changed", lambda s: setattr(node, "amount", s.get_value()))
        spin_a.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin_a)
        self._port_spin_buttons["amount"] = spin_a
        self._make_control_row("Amount", "amount", spin_a)
        adj_r = Gtk.Adjustment(value=node.radius, lower=0.0, upper=500.0, step_increment=0.5)
        spin_r = Gtk.SpinButton(adjustment=adj_r, climb_rate=0.5, digits=1)
        spin_r.connect("value-changed", lambda s: setattr(node, "radius", s.get_value()))
        spin_r.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin_r)
        self._port_spin_buttons["radius"] = spin_r
        self._make_control_row("Radius", "radius", spin_r)

    def _build_edge_detect_params(self):
        node: EdgeDetectNode = self._node
        adj = Gtk.Adjustment(value=node.threshold, lower=0.0, upper=1.0, step_increment=0.05)
        spin = Gtk.SpinButton(adjustment=adj, climb_rate=0.05, digits=2)
        spin.connect("value-changed", lambda s: setattr(node, "threshold", s.get_value()))
        spin.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin)
        self._port_spin_buttons["threshold"] = spin
        self._make_control_row("Threshold", "threshold", spin)

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

    def _build_time_params(self):
        node: TimeNode = self._node
        modes = [_("Frame number"), _("Time (seconds)")]
        mode_map = {
            0: TimeNode.TIME_MODE_FRAME,
            1: TimeNode.TIME_MODE_SECONDS,
        }
        combo = Gtk.DropDown.new_from_strings(modes)
        keys = list(mode_map.keys())
        values = list(mode_map.values())
        combo.set_selected(keys[values.index(node.mode)] if node.mode in values else 0)
        combo.connect("notify::selected",
                      lambda c, _: self._set_time_mode(mode_map.get(c.get_selected(),
                                TimeNode.TIME_MODE_FRAME)))
        combo.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(combo)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        row.set_css_classes(["node-param-row"])
        row.set_margin_end(4)
        lbl = Gtk.Label(label=_("Mode"), xalign=0)
        lbl.set_css_classes(["node-param-label"])
        row.append(lbl)
        row.append(combo)
        self.append(row)
        self._param_controls.append(row)

        fps_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        fps_lbl = Gtk.Label(label=_("FPS"), xalign=0)
        fps_lbl.set_css_classes(["node-param-label"])
        fps_row.append(fps_lbl)
        fps_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=node.fps, lower=1, upper=120, step_increment=1), climb_rate=1, digits=1)
        fps_spin.set_css_classes(["node-param-control"])
        fps_spin.connect("value-changed", lambda s: setattr(node, "fps", s.get_value()))
        fps_row.append(fps_spin)
        len_lbl = Gtk.Label(label=_("Length"), xalign=0)
        len_lbl.set_css_classes(["node-param-label"])
        fps_row.append(len_lbl)
        len_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=node.length, lower=1, upper=100000, step_increment=1), climb_rate=1, digits=0)
        len_spin.set_css_classes(["node-param-control"])
        len_spin.connect("value-changed", lambda s: setattr(node, "length", int(s.get_value())))
        fps_row.append(len_spin)
        self.append(fps_row)
        self._param_controls.append(fps_row)

        out_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        out_lbl = Gtk.Label(label=_("Output"), xalign=0)
        out_lbl.set_css_classes(["node-param-label"])
        out_row.append(out_lbl)
        self._time_value_label = Gtk.Label(label=self._format_time_value(node))
        self._time_value_label.set_css_classes(["node-param-value"])
        out_row.append(self._time_value_label)
        self.append(out_row)
        self._param_controls.append(out_row)

    def _set_time_mode(self, mode: str):
        if isinstance(self._node, TimeNode):
            self._node.mode = mode
            self._refresh_time_value()
        self._canvas._update_all_port_colors()

    def _format_time_value(self, node) -> str:
        if node is None:
            return ""
        return f"{node.value_for(node._last_frame):.4g}"

    def _refresh_time_value(self):
        if self._time_value_label is not None and isinstance(self._node, TimeNode):
            self._time_value_label.set_label(self._format_time_value(self._node))

    def set_animation(self, frames: list[str], fps: int):
        self.free_animation()
        self._anim_frames = list(frames)
        self._anim_fps = max(1, int(fps or 1))
        self._anim_index = 0
        if not self._anim_frames or not self._thumb_box or not self._thumb_overlay:
            return
        if self._anim_bar is None:
            self._build_animation_bar()
        self._anim_bar.set_visible(True)
        if not self._node.minimized:
            self._logical_w = max(int(self._node.width or 240), self._anim_min_w)
            self._node.width = self._logical_w
        self._update_animation_frame(0)

    def free_animation(self):
        self._anim_playing = False
        if self._anim_timer_id:
            GLib.source_remove(self._anim_timer_id)
            self._anim_timer_id = 0
        if self._anim_bar is not None:
            self._anim_bar.set_visible(False)
        self._anim_frames = []
        self._anim_index = 0

    def _build_animation_bar(self):
        negate = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        negate.set_halign(Gtk.Align.FILL)
        negate.set_valign(Gtk.Align.END)
        negate.set_hexpand(True)
        negate.add_css_class("animation-player-bar")

        to_start = Gtk.Button(icon_name="media-skip-backward-symbolic")
        to_start.set_css_classes(["player-btn"])
        to_start.connect("clicked", lambda b: self._seek_animation(0))
        back = Gtk.Button(icon_name="media-seek-backward-symbolic")
        back.set_css_classes(["player-btn"])
        back.connect("clicked", lambda b: self._step_animation(-1))
        self._play_btn = Gtk.ToggleButton(icon_name="media-playback-start-symbolic")
        self._play_btn.set_css_classes(["player-btn"])
        self._play_btn.connect("toggled", self._on_play_toggled)
        fwd = Gtk.Button(icon_name="media-seek-forward-symbolic")
        fwd.set_css_classes(["player-btn"])
        fwd.connect("clicked", lambda b: self._step_animation(1))
        to_end = Gtk.Button(icon_name="media-skip-forward-symbolic")
        to_end.set_css_classes(["player-btn"])
        to_end.connect("clicked", lambda b: self._seek_animation(len(self._anim_frames) - 1))

        negate.append(to_start)
        negate.append(back)
        negate.append(self._play_btn)
        negate.append(fwd)
        negate.append(to_end)

        max_idx = max(0, len(self._anim_frames) - 1)
        adj = Gtk.Adjustment(value=0, lower=0, upper=max_idx, step_increment=1, page_increment=5)
        self._anim_scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj)
        self._anim_scale.set_draw_value(False)
        self._anim_scale.set_hexpand(True)
        self._anim_scale.connect("value-changed", self._on_anim_scale_changed)
        negate.append(self._anim_scale)

        self._anim_frame_label = Gtk.Label(label=f"1/{len(self._anim_frames)}")
        self._anim_frame_label.add_css_class("dim-label")
        negate.append(self._anim_frame_label)

        self.append(negate)
        if self._thumb_box:
            self.reorder_child_after(negate, self._thumb_box)
        self._anim_bar = negate

    def _step_animation(self, delta: int):
        self._seek_animation(self._anim_index + delta)

    def _seek_animation(self, index: int):
        if not self._anim_frames:
            return
        self._update_animation_frame(index)

    def _on_anim_scale_changed(self, scale):
        if self._anim_seek_guard or not self._anim_frames:
            return
        self._update_animation_frame(int(scale.get_value()))

    def _on_play_toggled(self, btn):
        if btn.get_active():
            if not self._anim_playing:
                self._anim_playing = True
                if not self._anim_frames:
                    btn.set_active(False)
                    return
                delay = max(16, int(round(1000.0 / self._anim_fps)))
                self._anim_timer_id = GLib.timeout_add(delay, self._anim_tick)
                self._play_btn.set_icon_name("media-playback-pause-symbolic")
        else:
            self._anim_playing = False
            if self._anim_timer_id:
                GLib.source_remove(self._anim_timer_id)
                self._anim_timer_id = 0
            self._play_btn.set_icon_name("media-playback-start-symbolic")

    def _anim_tick(self):
        if not self._anim_playing or not self._anim_frames:
            self._anim_timer_id = 0
            return GLib.SOURCE_REMOVE
        n = len(self._anim_frames)
        if self._anim_index + 1 >= n:
            self._anim_playing = False
            self._anim_index = n - 1
            if self._play_btn:
                self._play_btn.set_active(False)
                self._play_btn.set_icon_name("media-playback-start-symbolic")
            self._anim_timer_id = 0
            return GLib.SOURCE_REMOVE
        self._update_animation_frame(self._anim_index + 1)
        return GLib.SOURCE_CONTINUE

    def _update_animation_frame(self, index: int):
        if not self._anim_frames:
            return
        n = len(self._anim_frames)
        index = max(0, min(n - 1, int(index)))
        self._anim_index = index
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(self._anim_frames[index])
        except Exception:
            pixbuf = None
        if pixbuf is not None and self._thumb_picture is not None:
            self._thumb_picture.set_paintable(Gdk.Texture.new_for_pixbuf(pixbuf))
            self._has_image = True
            if not self._node.minimized:
                self._thumb_box.set_visible(True)
                self._resize_handle.set_visible(True)
                if self._image_aspect is None:
                    w = pixbuf.get_width()
                    h = pixbuf.get_height()
                    if w > 0 and h > 0:
                        self._image_aspect = w / h
                        self._logical_w = max(int(self._node.width or 240), self._anim_min_w)
                        img_h = int(self._logical_w / self._image_aspect)
                        self._logical_h = max(160, img_h + self._anim_bar_h)
                        self._node.width = self._logical_w
                        self._node.height = self._logical_h
                        self.apply_zoom(self._canvas._zoom)
        if self._anim_scale is not None:
            self._anim_seek_guard = True
            self._anim_scale.set_value(index)
            self._anim_seek_guard = False
        if self._anim_frame_label is not None:
            self._anim_frame_label.set_label(f"{index + 1}/{n}")

    def _build_compare_params(self):
        node: CompareNode = self._node
        operators = ["==", "!=", "<", ">", "<=", ">="]
        combo = Gtk.DropDown.new_from_strings(operators)
        selected = operators.index(node.operator) if node.operator in operators else 0
        combo.set_selected(selected)
        combo.connect("notify::selected", lambda c, _: setattr(node, "operator", operators[c.get_selected()]))
        combo.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(combo)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        row.set_css_classes(["node-param-row"])
        row.set_margin_end(4)
        lbl = Gtk.Label(label="Operator", xalign=0)
        lbl.set_css_classes(["node-param-label"])
        row.append(lbl)
        row.append(combo)
        self.append(row)
        self._param_controls.append(row)

    def _build_clamp_params(self):
        node: ClampNode = self._node
        adj_min = Gtk.Adjustment(value=node.min_val, lower=-999999, upper=999999, step_increment=0.1)
        spin_min = Gtk.SpinButton(adjustment=adj_min, climb_rate=1, digits=2)
        spin_min.connect("value-changed", lambda s: setattr(node, "min_val", s.get_value()))
        spin_min.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin_min)
        self._make_control_row("Min", "", spin_min)
        adj_max = Gtk.Adjustment(value=node.max_val, lower=-999999, upper=999999, step_increment=0.1)
        spin_max = Gtk.SpinButton(adjustment=adj_max, climb_rate=1, digits=2)
        spin_max.connect("value-changed", lambda s: setattr(node, "max_val", s.get_value()))
        spin_max.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin_max)
        self._make_control_row("Max", "", spin_max)

    def _build_map_range_params(self):
        node: MapRangeNode = self._node
        def _row(label, attr, value):
            adj = Gtk.Adjustment(value=value, lower=-999999, upper=999999, step_increment=0.1)
            spin = Gtk.SpinButton(adjustment=adj, climb_rate=1, digits=2)
            spin.connect("value-changed", lambda s: setattr(node, attr, s.get_value()))
            spin.set_css_classes(["node-param-control"])
            self._ctrl_widgets.append(spin)
            self._make_control_row(label, "", spin)
        _row("In Min", "in_min", node.in_min)
        _row("In Max", "in_max", node.in_max)
        _row("Out Min", "out_min", node.out_min)
        _row("Out Max", "out_max", node.out_max)

    def _build_random_params(self):
        node: RandomNode = self._node
        adj_min = Gtk.Adjustment(value=node.min_val, lower=-999999, upper=999999, step_increment=0.1)
        spin_min = Gtk.SpinButton(adjustment=adj_min, climb_rate=1, digits=2)
        spin_min.connect("value-changed", lambda s: setattr(node, "min_val", s.get_value()))
        spin_min.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin_min)
        self._make_control_row("Min", "", spin_min)
        adj_max = Gtk.Adjustment(value=node.max_val, lower=-999999, upper=999999, step_increment=0.1)
        spin_max = Gtk.SpinButton(adjustment=adj_max, climb_rate=1, digits=2)
        spin_max.connect("value-changed", lambda s: setattr(node, "max_val", s.get_value()))
        spin_max.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin_max)
        self._make_control_row("Max", "", spin_max)
        btn = Gtk.Button(label="Randomize")
        btn.add_css_class("node-param-control")
        btn.connect("clicked", lambda b: self._on_randomize_clicked(node))
        row = Gtk.CenterBox()
        row.set_hexpand(True)
        row.set_center_widget(btn)
        self.append(row)
        self._param_controls.append(row)

    def _on_randomize_clicked(self, node: RandomNode):
        node.randomize()
        self._canvas._update_all_port_colors()

    def _build_raw_decode_params(self):
        node: RawDecodeNode = self._node

        dd = Gtk.DropDown()
        dd.set_model(Gtk.StringList.new(node.DECODE_METHODS))
        idx = node.DECODE_METHODS.index(node.decode_method) if node.decode_method in node.DECODE_METHODS else 0
        dd.set_selected(idx)
        dd.set_halign(Gtk.Align.START)
        dd.connect("notify::selected", lambda d, ps: setattr(node, "decode_method", node.DECODE_METHODS[d.get_selected()]))
        dd.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(dd)
        self._make_control_row("Method", "decode_method", dd)

        adj_w = Gtk.Adjustment(value=node.decode_width, lower=1, upper=100000, step_increment=1)
        spin_w = Gtk.SpinButton(adjustment=adj_w, climb_rate=1, digits=0)
        spin_w.connect("value-changed", lambda s: setattr(node, "decode_width", int(s.get_value())))
        spin_w.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin_w)
        self._make_control_row("Width", "decode_width", spin_w)

        adj_h = Gtk.Adjustment(value=node.decode_height, lower=1, upper=100000, step_increment=1)
        spin_h = Gtk.SpinButton(adjustment=adj_h, climb_rate=1, digits=0)
        spin_h.connect("value-changed", lambda s: setattr(node, "decode_height", int(s.get_value())))
        spin_h.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin_h)
        self._make_control_row("Height", "decode_height", spin_h)

        adj_o = Gtk.Adjustment(value=node.byte_offset, lower=0, upper=10000000, step_increment=1)
        spin_o = Gtk.SpinButton(adjustment=adj_o, climb_rate=1, digits=0)
        spin_o.connect("value-changed", lambda s: setattr(node, "byte_offset", int(s.get_value())))
        spin_o.set_css_classes(["node-param-control"])
        self._ctrl_widgets.append(spin_o)
        self._make_control_row("Offset", "byte_offset", spin_o)

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
            self._has_image = True
            if not self._node.minimized:
                self._thumb_box.set_visible(True)
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
            if not self._node.minimized:
                self._resize_handle.set_visible(False)
            self._resize_handle.set_visible(False)
            self._logical_w = int(self._node.width or 240)
            self._logical_h = int(self._node.height or 200)
            self._node.width = self._logical_w
            self._node.height = self._logical_h
            self.set_size_request(-1, -1)
        elif self._analysis_area:
            self._analysis_data = None
            self._has_image = False
            self._resize_handle.set_visible(False)
            self._analysis_area.queue_draw()

    def set_analysis_data(self, data: dict):
        self._analysis_data = data
        if self._analysis_area:
            self._has_image = True
            if not self._node.minimized:
                self._thumb_box.set_visible(True)
                self._resize_handle.set_visible(True)
                self._logical_w = max(220, int(self._node.width or 220))
                self._logical_h = max(200, int(self._node.height or 200))
                self._node.width = self._logical_w
                self._node.height = self._logical_h
                self._analysis_area.queue_draw()
                self.apply_zoom(self._canvas._zoom)
            self._analysis_area.queue_draw()

    # ─── Cairo analysis drawing ─────────────────────────────────────────────

    def _theme_colors(self, area):
        style = area.get_style_context()
        is_dark = True
        found, bg = style.lookup_color('theme_bg_color')
        if found:
            luminance = 0.299 * bg.red + 0.587 * bg.green + 0.114 * bg.blue
            is_dark = luminance < 0.5
        if is_dark:
            card = (0.13, 0.13, 0.14, 1.0)
            grid = (0.40, 0.40, 0.40)
            axis = (0.65, 0.65, 0.64)
        else:
            card = (0.91, 0.91, 0.92, 1.0)
            grid = (0.55, 0.55, 0.55)
            axis = (0.40, 0.40, 0.40)
        return card, grid, axis, is_dark

    def _on_analysis_draw(self, area: Gtk.DrawingArea, cr, w: int, h: int):
        card, grid, axis, is_dark = self._theme_colors(area)
        if isinstance(self._node, HistogramNode):
            self._draw_histogram(cr, w, h, card, grid, axis)
        elif isinstance(self._node, WaveformMonitorNode):
            self._draw_waveform(cr, w, h, card, grid, axis)
        elif isinstance(self._node, VectorscopeNode):
            self._draw_vectorscope(cr, w, h, card, grid, axis)
        elif isinstance(self._node, FrequencyDomainNode):
            self._draw_frequency_domain(cr, w, h, card, grid, is_dark)

    def _card_bg(self, cr, w: int, h: int, card):
        cr.set_source_rgba(*card)
        cr.rectangle(0, 0, w, h)
        cr.fill()

    def _draw_histogram(self, cr, w: int, h: int, card, grid, axis):
        self._card_bg(cr, w, h, card)
        data = self._analysis_data
        if not data:
            return

        ml = int(w * 0.08)
        mr = int(w * 0.03)
        mt = int(h * 0.1)
        mb = int(h * 0.15)
        pw = w - ml - mr
        ph = h - mt - mb
        if pw < 8 or ph < 8:
            return

        cr.set_source_rgba(*grid, 0.3)
        cr.set_line_width(1)
        for i in range(1, 4):
            y = mt + int(ph * i / 4)
            cr.move_to(ml, y)
            cr.line_to(w - mr, y)
            cr.stroke()

        cr.set_source_rgba(*axis, 0.5)
        cr.set_font_size(min(8, w // 28))
        for i in range(1, 4):
            y = mt + int(ph * i / 4)
            cr.move_to(2, y + 3)
            cr.show_text(f"{25 * i}")

        cr.set_source_rgba(*axis, 0.4)
        cr.set_font_size(min(7, w // 30))
        cr.move_to(ml - 3, h - mb + 10)
        cr.show_text("0")
        cr.move_to(w - mr - 12, h - mb + 10)
        cr.show_text("255")

        def _draw_channel(hist, color, fill_a=0.12, line_a=0.85):
            bins = len(hist)
            max_val = max(hist) or 0.01
            cr.move_to(ml, h - mb)
            for i in range(bins):
                x = ml + (i / bins) * pw
                y = h - mb - (hist[i] / max_val) * ph
                cr.line_to(x, y)
            cr.line_to(ml + pw, h - mb)
            cr.close_path()
            cr.set_source_rgba(*color, fill_a)
            cr.fill()
            cr.move_to(ml, h - mb - (hist[0] / max_val) * ph)
            for i in range(1, bins):
                x = ml + (i / bins) * pw
                y = h - mb - (hist[i] / max_val) * ph
                cr.line_to(x, y)
            cr.set_source_rgba(*color, line_a)
            cr.set_line_width(1.2)
            cr.stroke()

        _draw_channel(data["r"], _ANALYSIS_RED)
        _draw_channel(data["g"], _ANALYSIS_GREEN)
        _draw_channel(data["b"], _ANALYSIS_BLUE)
        _draw_channel(data["l"], _ANALYSIS_YELLOW, 0.08, 0.7)

        legend = [
            ("R", _ANALYSIS_RED), ("G", _ANALYSIS_GREEN),
            ("B", _ANALYSIS_BLUE), ("Y", _ANALYSIS_YELLOW),
        ]
        lx = ml + 4
        ly = mt - 16
        cr.set_font_size(min(8, w // 28))
        for txt, clr in legend:
            cr.set_source_rgba(*clr, 0.85)
            cr.rectangle(lx, ly, 7, 7)
            cr.fill()
            cr.set_source_rgba(*axis, 0.7)
            cr.move_to(lx + 10, ly + 6)
            cr.show_text(txt)
            lx += 22 * (w / 260) + 4

    def _draw_waveform(self, cr, w: int, h: int, card, grid, axis):
        self._card_bg(cr, w, h, card)
        data = self._analysis_data
        if not data:
            return

        margin = 6
        pw = w - 2 * margin
        ph = h - 2 * margin
        if pw < 4 or ph < 4:
            return

        cr.set_source_rgba(*grid, 0.2)
        cr.set_line_width(1)
        for i in range(1, 4):
            y = margin + int(ph * i / 4)
            cr.move_to(margin, y)
            cr.line_to(margin + pw, y)
            cr.stroke()

        env_low = data.get("envelope_low", [])
        env_high = data.get("envelope_high", [])
        avg = data.get("average", [])
        nc = len(env_low)
        if nc == 0:
            return

        cr.move_to(margin, margin + ph)
        for i, v in enumerate(env_low):
            x = margin + (i / nc) * pw
            y = margin + ph - v * ph
            cr.line_to(x, y)
        for i in range(nc - 1, -1, -1):
            x = margin + (i / nc) * pw
            y = margin + ph - env_high[i] * ph
            cr.line_to(x, y)
        cr.close_path()
        cr.set_source_rgba(*_ANALYSIS_GREEN, 0.06)
        cr.fill()

        cr.move_to(margin, margin + ph - avg[0] * ph)
        for i in range(1, nc):
            x = margin + (i / nc) * pw
            y = margin + ph - avg[i] * ph
            cr.line_to(x, y)
        cr.set_source_rgba(*_ANALYSIS_GREEN, 0.8)
        cr.set_line_width(1.2)
        cr.stroke()

    def _draw_vectorscope(self, cr, w: int, h: int, card, grid, axis):
        self._card_bg(cr, w, h, card)
        data = self._analysis_data
        if not data:
            return

        cx = w / 2
        cy = h / 2
        radius = min(w, h) / 2 - 10
        if radius < 4:
            return

        cr.set_source_rgba(*grid, 0.4)
        cr.set_line_width(1)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.stroke()
        cr.set_source_rgba(*grid, 0.15)
        cr.arc(cx, cy, radius / 2, 0, 2 * math.pi)
        cr.stroke()

        cr.set_source_rgba(*grid, 0.25)
        cr.set_line_width(1)
        cr.move_to(cx - radius, cy)
        cr.line_to(cx + radius, cy)
        cr.stroke()
        cr.move_to(cx, cy - radius)
        cr.line_to(cx, cy + radius)
        cr.stroke()

        labels = [("R", 0), ("G", 120), ("B", 240), ("Y", 300)]
        cr.set_font_size(min(8, w // 26))
        for txt, deg in labels:
            a = math.radians(deg)
            lx = cx + (radius + 8) * math.cos(a)
            ly = cy + (radius + 8) * math.sin(a)
            cr.set_source_rgba(*axis, 0.6)
            cr.move_to(lx - 4, ly + 3)
            cr.show_text(txt)

        points = data.get("points", [])
        if not points:
            return

        s = radius / 128.0
        for qx, qy, weight in points:
            dx = cx + (qx - 128) * s
            dy = cy + (128 - qy) * s
            if 0 <= dx < w and 0 <= dy < h:
                alpha = 0.08 + 0.6 * (weight ** 0.5)
                r = max(0.8, 1.3 * (weight ** 0.4))
                cr.set_source_rgba(*_ANALYSIS_WHITE, alpha)
                cr.arc(dx, dy, r, 0, 2 * math.pi)
                cr.fill()

    def _draw_frequency_domain(self, cr, w: int, h: int, card, _grid, is_dark):
        self._card_bg(cr, w, h, card)
        data = self._analysis_data
        if not data:
            return

        grid = data.get("mag_grid", [])
        if not grid:
            return

        fh = len(grid)
        fw = len(grid[0])
        if fw == 0 or fh == 0:
            return

        def _turbo(v):
            r = 0.5 + 0.5 * math.sin(2.0 * math.pi * (v * 0.85 - 0.5)) ** 8
            g = 0.3 + 0.7 * math.sin(2.0 * math.pi * (v * 0.70 + 0.1))
            b = 0.8 - 0.6 * math.sin(2.0 * math.pi * (v * 0.60 + 0.3))
            return (max(0, min(1, r)), max(0, min(1, g)), max(0, min(1, b)))

        cell_w = w / fw
        cell_h = h / fh
        for y in range(fh):
            for x in range(fw):
                r, g, b = _turbo(grid[y][x])
                cr.set_source_rgba(r, g, b, 1)
                cr.rectangle(x * cell_w, y * cell_h, cell_w + 0.5, cell_h + 0.5)
                cr.fill()

    # ─── Zoom scaling ─────────────────────────────────────────────────

    def apply_zoom(self, zoom: float):
        if not self._has_image and not self._node.minimized:
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
        if self._has_image or self._node.minimized or isinstance(self._node, (LabelNode, CommentNode)):
            w = -1 if self._node.minimized else max(1, int(self._logical_w * zoom))
            self.set_size_request(
                w,
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
        if isinstance(self._node, (InputNode, VideoInputNode, RawInputNode)) and not self._node.file_path:
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
        nt: Gdk.RGBA(*CATEGORY_GDK_RGBA[cat])
        for nt, cat in NODE_CATEGORY_MAP.items()
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


class FixedCanvas(Gtk.Widget):
    __gtype_name__ = "FixedCanvas"

    def __init__(self):
        super().__init__()
        self._children: list[Gtk.Widget] = []
        self._positions: dict[Gtk.Widget, tuple[int, int]] = {}
        self.set_overflow(Gtk.Overflow.VISIBLE)

    def put(self, child: Gtk.Widget, x: int, y: int):
        child.set_parent(self)
        self._children.append(child)
        self._positions[child] = (x, y)
        self.queue_resize()

    def move(self, child: Gtk.Widget, x: int, y: int):
        self._positions[child] = (x, y)
        child.set_child_visible(True)
        self.queue_resize()

    def remove(self, child: Gtk.Widget):
        if child in self._positions:
            del self._positions[child]
            self._children.remove(child)
            child.set_visible(False)
            child.unparent()
            self.queue_resize()

    def pick(self, x: float, y: float, flags: Gtk.PickFlags) -> Gtk.Widget | None:
        for child in reversed(self._children):
            if not child.get_visible():
                continue
            pos = self._positions.get(child)
            if pos is None:
                continue
            cx, cy = pos
            cw = child.get_allocated_width()
            ch = child.get_allocated_height()
            if cx <= x <= cx + cw and cy <= y <= cy + ch:
                return child
        return None

    def do_forall(self, include_internals: bool, callback: Callable):
        for child in list(self._children):
            callback(child)

    def do_measure(self, orientation: Gtk.Orientation, for_size: int):
        return 0, 100, -1, -1

    def do_size_allocate(self, width: int, height: int, baseline: int):
        for child in self._children:
            if not child.get_visible():
                continue
            x, y = self._positions.get(child, (0, 0))
            min_w, nat_w, _, _ = child.measure(Gtk.Orientation.HORIZONTAL, -1)
            min_h, nat_h, _, _ = child.measure(Gtk.Orientation.VERTICAL, -1)
            alloc = Gdk.Rectangle()
            alloc.x = x
            alloc.y = y
            alloc.width = nat_w if nat_w >= min_w else min_w
            alloc.height = nat_h if nat_h >= min_h else min_h
            child.size_allocate(alloc, -1)


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

        self._fixed = FixedCanvas()
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
        self._highlighted_replace_node: Optional[NodeWidget] = None

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

    def _find_node_widget_at(self, screen_x: float, screen_y: float) -> Optional[NodeWidget]:
        zoom = self._zoom
        for nid, w in reversed(list(self._node_widgets.items())):
            if not w.get_visible():
                continue
            node = self._graph.get_node(nid)
            if node is None:
                continue
            sx = int(node.x * zoom + self._pan_x)
            sy = int(node.y * zoom + self._pan_y)
            ww = w.get_width()
            wh = w.get_height()
            if ww < 1 or wh < 1:
                ww = max(1, int(w._logical_w * zoom))
                wh = max(1, int(w._logical_h * zoom))
            if sx <= screen_x <= sx + ww and sy <= screen_y <= sy + wh:
                return w
        return None

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
            w.free_animation()
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
            w.free_animation()
            self._fixed.remove(w)
            self._selected_widgets.discard(w)
            if self._dragging_node is w.graph_node:
                self._dragging_node = None
            if self._resizing_node is w.graph_node:
                self._resizing_node = None
        self._graph.remove_node_with_bypass(node_id)
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
        if node.minimized:
            zoom = self._zoom
            header_cy = w._screen_y + 15 * zoom
            nw = w.get_width()
            for inp in node.inputs:
                pw = w.get_input_port_widget(inp.name)
                if pw:
                    pw._center_x = w._screen_x + 3 * zoom
                    pw._center_y = header_cy
            for out in node.outputs:
                pw = w.get_output_port_widget(out.name)
                if pw:
                    pw._center_x = w._screen_x + nw - 3 * zoom
                    pw._center_y = header_cy
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
            f".node-header.minimized {{ border-radius: {hr}px; min-width: 0; min-height: 0; }}\n"
            f".port-label {{ font-size: {pfs}px; min-width: 0; min-height: 0; }}\n"
            f".node-title {{ font-size: {tfs}px; min-width: 0; min-height: 0; }}\n"
            f".node-param-row {{ padding: {rp}px 0px; min-width: 0; min-height: 0; }}\n"
            f".node-param-row.indented {{ padding-left: {ip}px; min-width: 0; min-height: 0; }}\n"
            f".node-param-label {{ font-size: {lfs}px; min-width: 0; min-height: 0; }}\n"
            f".node-param-control {{ margin-bottom: {cm}px; min-width: 0; min-height: 0; }}\n"
            f".resize-handle {{ border-top-left-radius: {max(1, int(4 * zoom))}px; border-bottom-right-radius: {max(1, int(7 * zoom))}px; }}\n"
            f".node-label-content, .node-comment-content {{ font-size: {tfs}px; min-width: 0; min-height: 0; }}\n"
        )
        self._zoom_css.load_from_data(css.encode())

    def _update_port_centers(self, node: Node):
        w = self._node_widgets.get(node.id)
        if not w:
            return
        if node.minimized:
            zoom = self._zoom
            header_cy = w._screen_y + 15 * zoom
            nw = w.get_width()
            for inp in node.inputs:
                pw = w.get_input_port_widget(inp.name)
                if pw:
                    pw._center_x = w._screen_x + 3 * zoom
                    pw._center_y = header_cy
            for out in node.outputs:
                pw = w.get_output_port_widget(out.name)
                if pw:
                    pw._center_x = w._screen_x + nw - 3 * zoom
                    pw._center_y = header_cy
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

        if _is_analysis_node(node) and hasattr(node, 'analysis_data') and node.analysis_data:
            w.set_analysis_data(node.analysis_data)
        elif isinstance(node, TimeNode):
            w._refresh_time_value()
        elif isinstance(node, (InputNode, VideoInputNode)):
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
            if _is_analysis_node(node) and hasattr(node, 'analysis_data') and node.analysis_data:
                w.set_analysis_data(node.analysis_data)
            else:
                wgt = pixbuf.get_width()
                hgt = pixbuf.get_height()
                max_long = 4096
                if max(wgt, hgt) > max_long:
                    scale = max_long / max(wgt, hgt)
                    pixbuf = pixbuf.scale_simple(int(wgt * scale), int(hgt * scale), GdkPixbuf.InterpType.TILES)
                w.set_thumbnail(pixbuf)
            self.queue_gl_render()

    def set_node_animation(self, node_id: str, frames: list[str], fps: int):
        w = self._node_widgets.get(node_id)
        if w:
            w.set_animation(frames, fps)
            self.queue_gl_render()

    def clear_node_animations(self):
        for w in self._node_widgets.values():
            w.free_animation()

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

            widget = self._find_node_widget_at(x, y)
            if widget:
                new_node = self._build_node_from_drag_text(text, 0, 0)
                if not new_node or not self._can_replace_node(widget, new_node):
                    widget = None
            if widget != self._highlighted_replace_node:
                if self._highlighted_replace_node:
                    self._highlighted_replace_node.set_selected(False)
                self._highlighted_replace_node = widget
                if widget:
                    widget.set_selected(True)

            return Gdk.DragAction.COPY
        return Gdk.DragAction.COPY

    def _on_drag_leave(self, target):
        self._hide_drag_preview()
        self._clear_drag_insert_edge()
        if self._highlighted_replace_node:
            self._highlighted_replace_node.set_selected(False)
            self._highlighted_replace_node = None

    # ─── Drop from sidebar ───────────────────────────────────────────────────────

    def _on_drop_accept(self, target, drop):
        formats = drop.get_formats()
        return formats.contain_mime_type("text/plain")

    # ─── Wire-insert helpers ───────────────────────────────────────────────────

    _INSERTABLE_PREFIXES = frozenset({"blend:", "opacity:", "mask:", "filter:", "brightness_contrast:", "levels:", "hsl:", "color_balance:", "exposure_gamma:", "curves:", "crop:", "resize:", "rotate:", "flip:", "distort:", "blur:", "sharpen:", "edge_detect:", "histogram:", "waveform_monitor:", "vectorscope:", "frequency_domain:"})

    _NUMERIC_INSERTABLE_PREFIXES = frozenset({"add:", "subtract:", "multiply:", "divide:", "ceil:", "floor:", "round:", "sum:", "product:", "not:", "and:", "or:", "nand:", "nor:", "xor:", "xnor:", "compare:", "clamp:", "map_range:", "modulo:", "power:", "square_root:", "absolute:", "log:", "exp:", "random:", "constant:"})

    def _node_insert_type(self, text: str) -> Optional[str]:
        if any(text.startswith(p) for p in self._NUMERIC_INSERTABLE_PREFIXES):
            return PortType.NUMERIC
        if any(text.startswith(p) for p in self._INSERTABLE_PREFIXES):
            return PortType.IMAGE
        return None

    def _node_insert_ports(self, new_node):
        for ptype in (PortType.IMAGE, PortType.NUMERIC):
            inp = next((p for p in new_node.inputs if p.port_type == ptype), None)
            if inp:
                outp = next((p for p in new_node.outputs if p.port_type == ptype), None)
                return inp, outp, ptype
        return None, None, None

    def _update_drag_insert_edge(self, text: str, x: float, y: float):
        prev = self._drag_insert_edge
        self._drag_insert_edge = None
        ptype = self._node_insert_type(text)
        if ptype is not None:
            edge = self._find_edge_at(x, y, threshold=30.0)
            if edge:
                src_n = self._graph.get_node(edge.src_node)
                dst_n = self._graph.get_node(edge.dst_node)
                if src_n and dst_n:
                    src_p = src_n.get_output_port(edge.src_port)
                    dst_p = dst_n.get_input_port(edge.dst_port)
                    if src_p and dst_p and src_p.port_type == ptype and dst_p.port_type == ptype:
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

    def _insert_new_node_into_edge(self, edge: Edge, new_node_id: str, ptype: str = PortType.IMAGE):
        graph = self._graph
        new_node = graph.get_node(new_node_id)
        if not new_node:
            return
        inp, outp, _ = self._node_insert_ports(new_node)
        if not inp:
            return

        src_node = graph.get_node(edge.src_node)
        dst_node = graph.get_node(edge.dst_node)
        if not src_node or not dst_node:
            return

        if not outp:
            e = graph.add_edge(edge.src_node, edge.src_port, new_node_id, inp.name)
            if e:
                self._update_all_port_colors()
                self.emit("graph-changed")
                self._maybe_process_analysis_node(new_node_id)
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
        e1 = graph.add_edge(edge.src_node, edge.src_port, new_node_id, inp.name)
        e2 = graph.add_edge(new_node_id, outp.name, edge.dst_node, edge.dst_port)
        if e1 and e2:
            self._update_all_port_colors()
            self.emit("graph-changed")
        elif e1 and not e2:
            graph.remove_edge(e1.id)
            graph.add_edge(edge.src_node, edge.src_port, edge.dst_node, edge.dst_port)

    def _try_insert_at(self, x: float, y: float, new_node_id: str):
        new_node = self._graph.get_node(new_node_id)
        if not new_node:
            return
        inp, outp, ptype = self._node_insert_ports(new_node)
        if not inp:
            return
        edge = self._find_edge_at(x, y, threshold=30.0)
        if not edge:
            return
        src_n = self._graph.get_node(edge.src_node)
        dst_n = self._graph.get_node(edge.dst_node)
        if not src_n or not dst_n:
            return
        src_p = src_n.get_output_port(edge.src_port)
        dst_p = dst_n.get_input_port(edge.dst_port)
        if not src_p or not dst_p or src_p.port_type != ptype or dst_p.port_type != ptype:
            return
        self._insert_new_node_into_edge(edge, new_node_id, ptype)

    def _build_node_from_drag_text(self, text: str, gx: float, gy: float) -> Optional[Node]:
        node = None
        if text.startswith("filter:"):
            parts = text.split(":", 2)
            if len(parts) == 3:
                key = f"{parts[1]}:{parts[2]}"
                fd = self._filter_def_map.get(key)
                if fd:
                    nid = "filter_" + str(GLib.get_monotonic_time())
                    node = FilterNode(nid, fd, gx, gy)
        elif text.startswith("blend:"):
            parts = text.split(":", 1)
            mode = parts[1] if len(parts) == 2 else "over"
            nid = "blend_" + mode + "_" + str(GLib.get_monotonic_time())
            node = BlendNode(nid, mode, gx, gy)
        elif text.startswith("opacity:"):
            nid = "opacity_" + str(GLib.get_monotonic_time())
            node = OpacityNode(nid, gx, gy)
        elif text.startswith("brightness_contrast:"):
            nid = "bc_" + str(GLib.get_monotonic_time())
            node = BrightnessContrastNode(nid, gx, gy)
        elif text.startswith("levels:"):
            nid = "levels_" + str(GLib.get_monotonic_time())
            node = LevelsNode(nid, gx, gy)
        elif text.startswith("hsl:"):
            nid = "hsl_" + str(GLib.get_monotonic_time())
            node = HSLNode(nid, gx, gy)
        elif text.startswith("raw_input:"):
            nid = "raw_input_" + str(GLib.get_monotonic_time())
            node = RawInputNode(nid, gx, gy)
        elif text.startswith("raw_decode:"):
            nid = "raw_decode_" + str(GLib.get_monotonic_time())
            node = RawDecodeNode(nid, gx, gy)
        elif text.startswith("input:"):
            nid = "input_" + str(GLib.get_monotonic_time())
            node = InputNode(nid, gx, gy)
        elif text.startswith("video_input:"):
            nid = "video_input_" + str(GLib.get_monotonic_time())
            node = VideoInputNode(nid, gx, gy)
        elif text.startswith("time:"):
            nid = "time_" + str(GLib.get_monotonic_time())
            node = TimeNode(nid, gx, gy)
        elif text.startswith("output:"):
            nid = "output_" + str(GLib.get_monotonic_time())
            node = OutputNode(nid, gx, gy)
        elif text.startswith("mask:"):
            nid = "mask_" + str(GLib.get_monotonic_time())
            node = MaskNode(nid, gx, gy)
        elif text.startswith("constant:"):
            nid = "constant_" + str(GLib.get_monotonic_time())
            node = ConstantNode(nid, gx, gy)
        elif text.startswith("add:"):
            nid = "add_" + str(GLib.get_monotonic_time())
            node = AddNode(nid, gx, gy)
        elif text.startswith("subtract:"):
            nid = "subtract_" + str(GLib.get_monotonic_time())
            node = SubtractNode(nid, gx, gy)
        elif text.startswith("multiply:"):
            nid = "multiply_" + str(GLib.get_monotonic_time())
            node = MultiplyNode(nid, gx, gy)
        elif text.startswith("divide:"):
            nid = "divide_" + str(GLib.get_monotonic_time())
            node = DivideNode(nid, gx, gy)
        elif text.startswith("ceil:"):
            nid = "ceil_" + str(GLib.get_monotonic_time())
            node = CeilNode(nid, gx, gy)
        elif text.startswith("floor:"):
            nid = "floor_" + str(GLib.get_monotonic_time())
            node = FloorNode(nid, gx, gy)
        elif text.startswith("round:"):
            nid = "round_" + str(GLib.get_monotonic_time())
            node = RoundNode(nid, gx, gy)
        elif text.startswith("sum:"):
            nid = "sum_" + str(GLib.get_monotonic_time())
            node = SumNode(nid, gx, gy)
        elif text.startswith("product:"):
            nid = "product_" + str(GLib.get_monotonic_time())
            node = ProductNode(nid, gx, gy)
        elif text.startswith("not:"):
            nid = "not_" + str(GLib.get_monotonic_time())
            node = NotNode(nid, gx, gy)
        elif text.startswith("and:"):
            nid = "and_" + str(GLib.get_monotonic_time())
            node = AndNode(nid, gx, gy)
        elif text.startswith("or:"):
            nid = "or_" + str(GLib.get_monotonic_time())
            node = OrNode(nid, gx, gy)
        elif text.startswith("nand:"):
            nid = "nand_" + str(GLib.get_monotonic_time())
            node = NandNode(nid, gx, gy)
        elif text.startswith("nor:"):
            nid = "nor_" + str(GLib.get_monotonic_time())
            node = NorNode(nid, gx, gy)
        elif text.startswith("xor:"):
            nid = "xor_" + str(GLib.get_monotonic_time())
            node = XorNode(nid, gx, gy)
        elif text.startswith("xnor:"):
            nid = "xnor_" + str(GLib.get_monotonic_time())
            node = XnorNode(nid, gx, gy)
        elif text.startswith("compare:"):
            nid = "compare_" + str(GLib.get_monotonic_time())
            node = CompareNode(nid, gx, gy)
        elif text.startswith("clamp:"):
            nid = "clamp_" + str(GLib.get_monotonic_time())
            node = ClampNode(nid, gx, gy)
        elif text.startswith("map_range:"):
            nid = "map_range_" + str(GLib.get_monotonic_time())
            node = MapRangeNode(nid, gx, gy)
        elif text.startswith("modulo:"):
            nid = "modulo_" + str(GLib.get_monotonic_time())
            node = ModuloNode(nid, gx, gy)
        elif text.startswith("power:"):
            nid = "power_" + str(GLib.get_monotonic_time())
            node = PowerNode(nid, gx, gy)
        elif text.startswith("square_root:"):
            nid = "sqrt_" + str(GLib.get_monotonic_time())
            node = SquareRootNode(nid, gx, gy)
        elif text.startswith("absolute:"):
            nid = "abs_" + str(GLib.get_monotonic_time())
            node = AbsoluteNode(nid, gx, gy)
        elif text.startswith("log:"):
            nid = "log_" + str(GLib.get_monotonic_time())
            node = LogNode(nid, gx, gy)
        elif text.startswith("exp:"):
            nid = "exp_" + str(GLib.get_monotonic_time())
            node = ExpNode(nid, gx, gy)
        elif text.startswith("random:"):
            nid = "random_" + str(GLib.get_monotonic_time())
            node = RandomNode(nid, gx, gy)
        elif text.startswith("label:"):
            nid = "label_" + str(GLib.get_monotonic_time())
            node = LabelNode(nid, gx, gy)
        elif text.startswith("comment:"):
            nid = "comment_" + str(GLib.get_monotonic_time())
            node = CommentNode(nid, gx, gy)
        elif text.startswith("color_source:"):
            nid = "color_source_" + str(GLib.get_monotonic_time())
            node = ColorSourceNode(nid, gx, gy)
        elif text.startswith("gradient:"):
            nid = "gradient_" + str(GLib.get_monotonic_time())
            node = GradientNode(nid, gx, gy)
        elif text.startswith("noise:"):
            nid = "noise_" + str(GLib.get_monotonic_time())
            node = NoiseNode(nid, gx, gy)
        elif text.startswith("histogram:"):
            nid = "histogram_" + str(GLib.get_monotonic_time())
            node = HistogramNode(nid, gx, gy)
        elif text.startswith("waveform_monitor:"):
            nid = "waveform_" + str(GLib.get_monotonic_time())
            node = WaveformMonitorNode(nid, gx, gy)
        elif text.startswith("vectorscope:"):
            nid = "vectorscope_" + str(GLib.get_monotonic_time())
            node = VectorscopeNode(nid, gx, gy)
        elif text.startswith("frequency_domain:"):
            nid = "freq_domain_" + str(GLib.get_monotonic_time())
            node = FrequencyDomainNode(nid, gx, gy)
        elif text.startswith("color_balance:"):
            nid = "color_balance_" + str(GLib.get_monotonic_time())
            node = ColorBalanceNode(nid, gx, gy)
        elif text.startswith("exposure_gamma:"):
            nid = "exposure_gamma_" + str(GLib.get_monotonic_time())
            node = ExposureGammaNode(nid, gx, gy)
        elif text.startswith("curves:"):
            nid = "curves_" + str(GLib.get_monotonic_time())
            node = CurvesNode(nid, gx, gy)
        elif text.startswith("crop:"):
            nid = "crop_" + str(GLib.get_monotonic_time())
            node = CropNode(nid, gx, gy)
        elif text.startswith("resize:"):
            nid = "resize_" + str(GLib.get_monotonic_time())
            node = ResizeNode(nid, gx, gy)
        elif text.startswith("rotate:"):
            nid = "rotate_" + str(GLib.get_monotonic_time())
            node = RotateNode(nid, gx, gy)
        elif text.startswith("flip:"):
            nid = "flip_" + str(GLib.get_monotonic_time())
            node = FlipNode(nid, gx, gy)
        elif text.startswith("distort:"):
            nid = "distort_" + str(GLib.get_monotonic_time())
            node = DistortNode(nid, gx, gy)
        elif text.startswith("blur:"):
            nid = "blur_" + str(GLib.get_monotonic_time())
            node = BlurNode(nid, gx, gy)
        elif text.startswith("sharpen:"):
            nid = "sharpen_" + str(GLib.get_monotonic_time())
            node = SharpenNode(nid, gx, gy)
        elif text.startswith("edge_detect:"):
            nid = "edge_detect_" + str(GLib.get_monotonic_time())
            node = EdgeDetectNode(nid, gx, gy)
        return node

    def _can_replace_node(self, old_widget: NodeWidget, new_node: Node) -> bool:
        old_node = old_widget.graph_node

        old_has_image = any(p.port_type == PortType.IMAGE for p in old_node.inputs) or any(p.port_type == PortType.IMAGE for p in old_node.outputs)
        new_has_image = any(p.port_type == PortType.IMAGE for p in new_node.inputs) or any(p.port_type == PortType.IMAGE for p in new_node.outputs)
        if old_has_image != new_has_image:
            return False
        old_has_raw = any(p.port_type == PortType.RAW for p in old_node.inputs) or any(p.port_type == PortType.RAW for p in old_node.outputs)
        new_has_raw = any(p.port_type == PortType.RAW for p in new_node.inputs) or any(p.port_type == PortType.RAW for p in new_node.outputs)
        if old_has_raw != new_has_raw:
            return False

        old_in_types = {p.port_type for p in old_node.inputs}
        old_out_types = {p.port_type for p in old_node.outputs}
        new_in_types = {p.port_type for p in new_node.inputs}
        new_out_types = {p.port_type for p in new_node.outputs}

        old_has_in = len(old_node.inputs) > 0
        old_has_out = len(old_node.outputs) > 0
        new_has_in = len(new_node.inputs) > 0
        new_has_out = len(new_node.outputs) > 0
        old_is_decor = not old_has_in and not old_has_out
        new_is_decor = not new_has_in and not new_has_out
        old_is_gen = not old_has_in and old_has_out
        new_is_gen = not new_has_in and new_has_out
        old_is_sink = old_has_in and not old_has_out
        new_is_sink = new_has_in and not new_has_out

        if old_is_decor or new_is_decor:
            if not (old_is_decor and new_is_decor):
                return False
        elif old_is_gen or new_is_gen:
            if not (old_is_gen and new_is_gen):
                return False
            if old_out_types != new_out_types:
                return False
        elif old_is_sink or new_is_sink:
            if not (old_is_sink and new_is_sink):
                return False
            if old_in_types != new_in_types:
                return False
        else:
            if not (old_in_types & new_in_types or old_out_types & new_out_types):
                return False
        return True

    def _do_replace_node(self, old_widget: NodeWidget, text: str, x: float, y: float) -> bool:
        old_node = old_widget.graph_node
        gx, gy = old_node.x, old_node.y

        new_node = self._build_node_from_drag_text(text, gx, gy)
        if not new_node or not self._can_replace_node(old_widget, new_node):
            return False

        incoming = list(self._graph.get_incoming_edges(old_node.id))
        outgoing = list(self._graph.get_outgoing_edges(old_node.id))

        nid = new_node.id
        self.add_node(new_node)

        self._graph.remove_node(old_node.id)
        self._node_widgets.pop(old_node.id, None)
        self._fixed.remove(old_widget)
        self._selected_widgets.discard(old_widget)

        new_ins_by_name = {p.name: p for p in new_node.inputs}
        new_outs_by_name = {p.name: p for p in new_node.outputs}
        new_ins_by_type = {}
        for p in new_node.inputs:
            new_ins_by_type.setdefault(p.port_type, []).append(p.name)
        new_outs_by_type = {}
        for p in new_node.outputs:
            new_outs_by_type.setdefault(p.port_type, []).append(p.name)
        used_ins = set()
        used_outs = set()

        for edge in incoming:
            name = edge.dst_port
            if name in new_ins_by_name and name not in used_ins:
                used_ins.add(name)
                self._graph.add_edge(edge.src_node, edge.src_port, nid, name)
            else:
                ptype = old_node.get_input_port(name).port_type if old_node.get_input_port(name) else PortType.IMAGE
                avail = [n for n in new_ins_by_type.get(ptype, []) if n not in used_ins]
                if avail:
                    used_ins.add(avail[0])
                    self._graph.add_edge(edge.src_node, edge.src_port, nid, avail[0])

        for edge in outgoing:
            name = edge.src_port
            if name in new_outs_by_name and name not in used_outs:
                used_outs.add(name)
                self._graph.add_edge(nid, name, edge.dst_node, edge.dst_port)
            else:
                ptype = old_node.get_output_port(name).port_type if old_node.get_output_port(name) else PortType.IMAGE
                avail = [n for n in new_outs_by_type.get(ptype, []) if n not in used_outs]
                if avail:
                    used_outs.add(avail[0])
                    self._graph.add_edge(nid, avail[0], edge.dst_node, edge.dst_port)

        w = self._node_widgets.get(nid)
        if w:
            self.select_node(w)

        self._update_all_port_colors()
        self.emit("graph-changed")
        return True

    def _on_drop(self, target, value, x, y):
        self._hide_drag_preview()
        self._clear_drag_insert_edge()
        if self._highlighted_replace_node:
            self._highlighted_replace_node.set_selected(False)
            self._highlighted_replace_node = None
        text = get_pending_drag_text()
        if not text:
            return False

        old_widget = self._find_node_widget_at(x, y)
        if old_widget:
            if self._do_replace_node(old_widget, text, x, y):
                return True
            return False

        if text.startswith("filter:"):
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
        elif text and text.startswith("brightness_contrast:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "bc_" + str(GLib.get_monotonic_time())
            node = BrightnessContrastNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("levels:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "levels_" + str(GLib.get_monotonic_time())
            node = LevelsNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("hsl:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "hsl_" + str(GLib.get_monotonic_time())
            node = HSLNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("raw_input:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "raw_input_" + str(GLib.get_monotonic_time())
            node = RawInputNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            return True
        elif text and text.startswith("raw_decode:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "raw_decode_" + str(GLib.get_monotonic_time())
            node = RawDecodeNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
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
        elif text and text.startswith("video_input:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "video_input_" + str(GLib.get_monotonic_time())
            node = VideoInputNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            return True
        elif text and text.startswith("time:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "time_" + str(GLib.get_monotonic_time())
            node = TimeNode(nid, gx, gy)
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
            self._try_insert_at(x, y, nid)
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
            self._try_insert_at(x, y, nid)
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
            self._try_insert_at(x, y, nid)
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
            self._try_insert_at(x, y, nid)
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
            self._try_insert_at(x, y, nid)
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
            self._try_insert_at(x, y, nid)
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
            self._try_insert_at(x, y, nid)
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
            self._try_insert_at(x, y, nid)
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
            self._try_insert_at(x, y, nid)
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
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("not:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "not_" + str(GLib.get_monotonic_time())
            node = NotNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("and:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "and_" + str(GLib.get_monotonic_time())
            node = AndNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("or:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "or_" + str(GLib.get_monotonic_time())
            node = OrNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("nand:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "nand_" + str(GLib.get_monotonic_time())
            node = NandNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("nor:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "nor_" + str(GLib.get_monotonic_time())
            node = NorNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("xor:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "xor_" + str(GLib.get_monotonic_time())
            node = XorNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("xnor:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "xnor_" + str(GLib.get_monotonic_time())
            node = XnorNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("compare:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "compare_" + str(GLib.get_monotonic_time())
            node = CompareNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("clamp:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "clamp_" + str(GLib.get_monotonic_time())
            node = ClampNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("map_range:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "map_range_" + str(GLib.get_monotonic_time())
            node = MapRangeNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("modulo:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "modulo_" + str(GLib.get_monotonic_time())
            node = ModuloNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("power:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "power_" + str(GLib.get_monotonic_time())
            node = PowerNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("square_root:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "sqrt_" + str(GLib.get_monotonic_time())
            node = SquareRootNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("absolute:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "abs_" + str(GLib.get_monotonic_time())
            node = AbsoluteNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("log:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "log_" + str(GLib.get_monotonic_time())
            node = LogNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("exp:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "exp_" + str(GLib.get_monotonic_time())
            node = ExpNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("random:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "random_" + str(GLib.get_monotonic_time())
            node = RandomNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
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
        elif text and text.startswith("color_source:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "color_source_" + str(GLib.get_monotonic_time())
            node = ColorSourceNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            return True
        elif text and text.startswith("gradient:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "gradient_" + str(GLib.get_monotonic_time())
            node = GradientNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            return True
        elif text and text.startswith("noise:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "noise_" + str(GLib.get_monotonic_time())
            node = NoiseNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            return True
        elif text and text.startswith("histogram:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "histogram_" + str(GLib.get_monotonic_time())
            node = HistogramNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("waveform_monitor:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "waveform_" + str(GLib.get_monotonic_time())
            node = WaveformMonitorNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("vectorscope:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "vectorscope_" + str(GLib.get_monotonic_time())
            node = VectorscopeNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("frequency_domain:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "freq_domain_" + str(GLib.get_monotonic_time())
            node = FrequencyDomainNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("color_balance:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "color_balance_" + str(GLib.get_monotonic_time())
            node = ColorBalanceNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("exposure_gamma:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "exposure_gamma_" + str(GLib.get_monotonic_time())
            node = ExposureGammaNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("curves:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "curves_" + str(GLib.get_monotonic_time())
            node = CurvesNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("crop:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "crop_" + str(GLib.get_monotonic_time())
            node = CropNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("resize:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "resize_" + str(GLib.get_monotonic_time())
            node = ResizeNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("rotate:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "rotate_" + str(GLib.get_monotonic_time())
            node = RotateNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("flip:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "flip_" + str(GLib.get_monotonic_time())
            node = FlipNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("distort:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "distort_" + str(GLib.get_monotonic_time())
            node = DistortNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("blur:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "blur_" + str(GLib.get_monotonic_time())
            node = BlurNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("sharpen:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "sharpen_" + str(GLib.get_monotonic_time())
            node = SharpenNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
            return True
        elif text and text.startswith("edge_detect:"):
            gx = (x - self._pan_x) / self._zoom
            gy = (y - self._pan_y) / self._zoom
            nid = "edge_detect_" + str(GLib.get_monotonic_time())
            node = EdgeDetectNode(nid, gx, gy)
            self.add_node(node)
            w = self.get_node_widget(nid)
            if w:
                self.select_node(w)
            self._try_insert_at(x, y, nid)
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
                self._maybe_process_analysis_node(dst_nid)
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
                self._maybe_process_analysis_node(dst_nid)
        self._clear_selected_port()
        self._drag_port = None
        self._drag_valid_target = None
        self.queue_gl_render()

    def _maybe_process_analysis_node(self, node_id: str):
        node = self._graph.get_node(node_id)
        if not node or not _is_analysis_node(node):
            return
        from processing.analysis import (
            compute_histogram_data, compute_waveform_data,
            compute_vectorscope_data, compute_frequency_data,
        )
        for e in self._graph.edges:
            if e.dst_node == node_id:
                src = self._graph.get_node(e.src_node)
                if src:
                    path = getattr(src, 'file_path', None) or getattr(src, 'cached_output_path', None)
                    if path and os.path.isfile(path):
                        if isinstance(node, HistogramNode):
                            node.analysis_data = compute_histogram_data(path)
                        elif isinstance(node, WaveformMonitorNode):
                            node.analysis_data = compute_waveform_data(path)
                        elif isinstance(node, VectorscopeNode):
                            node.analysis_data = compute_vectorscope_data(path)
                        elif isinstance(node, FrequencyDomainNode):
                            node.analysis_data = compute_frequency_data(path)
                        self.update_node_display(node_id)
                        return
        node.analysis_data = None
        w = self._node_widgets.get(node_id)
        if w:
            w.clear_thumbnail()

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
            dst_id = edge.dst_node
            self._graph.remove_edge(edge.id)
            self._update_all_port_colors()
            self.queue_gl_render()
            self.emit("graph-changed")
            self._maybe_process_analysis_node(dst_id)

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
                InputNode, FilterNode, BlendNode, OpacityNode, MaskNode,
                BrightnessContrastNode, LevelsNode, HSLNode,
                ColorSourceNode, GradientNode, NoiseNode,
                ColorBalanceNode, ExposureGammaNode, CurvesNode,
                CropNode, ResizeNode, RotateNode, FlipNode, DistortNode,
                BlurNode, SharpenNode, EdgeDetectNode,
                ConstantNode, LabelNode, CommentNode,
            )
            if isinstance(n, (InputNode, VideoInputNode)):
                nd["params"]["file_path"] = n.file_path
            elif isinstance(n, FilterNode):
                nd["params"]["filter_key"] = f"{n.filter_def.engine}:{n.filter_def.name}"
                nd["params"]["param_values"] = dict(n.param_values)
            elif isinstance(n, BlendNode):
                nd["params"]["mode"] = n.mode
                nd["params"]["extra_ports"] = len(n.inputs) - 2
            elif isinstance(n, BrightnessContrastNode):
                nd["params"]["brightness"] = n.brightness
                nd["params"]["contrast"] = n.contrast
            elif isinstance(n, LevelsNode):
                nd["params"]["black_point"] = n.black_point
                nd["params"]["white_point"] = n.white_point
                nd["params"]["gamma"] = n.gamma
            elif isinstance(n, HSLNode):
                nd["params"]["hue"] = n.hue
                nd["params"]["saturation"] = n.saturation
                nd["params"]["lightness"] = n.lightness
            elif isinstance(n, ColorSourceNode):
                nd["params"]["color"] = n.color
                nd["params"]["source_width"] = n.source_width
                nd["params"]["source_height"] = n.source_height
            elif isinstance(n, GradientNode):
                nd["params"]["gradient_type"] = n.gradient_type
                nd["params"]["start_color"] = n.start_color
                nd["params"]["end_color"] = n.end_color
                nd["params"]["angle"] = n.angle
                nd["params"]["source_width"] = n.source_width
                nd["params"]["source_height"] = n.source_height
            elif isinstance(n, NoiseNode):
                nd["params"]["noise_type"] = n.noise_type
                nd["params"]["scale"] = n.scale
                nd["params"]["seed"] = n.seed
                nd["params"]["source_width"] = n.source_width
                nd["params"]["source_height"] = n.source_height
            elif isinstance(n, ColorBalanceNode):
                nd["params"]["cyan_red"] = n.cyan_red
                nd["params"]["magenta_green"] = n.magenta_green
                nd["params"]["yellow_blue"] = n.yellow_blue
            elif isinstance(n, ExposureGammaNode):
                nd["params"]["exposure"] = n.exposure
                nd["params"]["gamma"] = n.gamma
            elif isinstance(n, CurvesNode):
                nd["params"]["shadows"] = n.shadows
                nd["params"]["dark_midtones"] = n.dark_midtones
                nd["params"]["midtones"] = n.midtones
                nd["params"]["light_midtones"] = n.light_midtones
                nd["params"]["highlights"] = n.highlights
            elif isinstance(n, CropNode):
                nd["params"]["crop_x"] = n.crop_x
                nd["params"]["crop_y"] = n.crop_y
                nd["params"]["crop_width"] = n.crop_width
                nd["params"]["crop_height"] = n.crop_height
            elif isinstance(n, ResizeNode):
                nd["params"]["resize_width"] = n.resize_width
                nd["params"]["resize_height"] = n.resize_height
                nd["params"]["resize_mode"] = n.resize_mode
            elif isinstance(n, RotateNode):
                nd["params"]["angle"] = n.angle
            elif isinstance(n, FlipNode):
                nd["params"]["direction"] = n.direction
            elif isinstance(n, DistortNode):
                for a in ("dist_x0","dist_y0","dist_x1","dist_y1","dist_x2","dist_y2","dist_x3","dist_y3"):
                    nd["params"][a] = getattr(n, a)
            elif isinstance(n, BlurNode):
                nd["params"]["radius"] = n.radius
            elif isinstance(n, SharpenNode):
                nd["params"]["amount"] = n.amount
                nd["params"]["radius"] = n.radius
            elif isinstance(n, EdgeDetectNode):
                nd["params"]["threshold"] = n.threshold
            elif isinstance(n, OpacityNode):
                nd["params"]["opacity"] = n.opacity
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
            InputNode, VideoInputNode, TimeNode, OutputNode, FilterNode, BlendNode,
            OpacityNode, MaskNode,
            BrightnessContrastNode, LevelsNode, HSLNode,
            ColorSourceNode, GradientNode, NoiseNode,
            ColorBalanceNode, ExposureGammaNode, CurvesNode,
            CropNode, ResizeNode, RotateNode, FlipNode, DistortNode,
            BlurNode, SharpenNode, EdgeDetectNode,
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
            elif typ == "video_input":
                node = VideoInputNode(nid, x, y)
                fp = params.get("file_path")
                if fp:
                    node.file_path = fp
            elif typ == "time":
                node = TimeNode(nid, x, y)
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
            elif typ == "brightness_contrast":
                node = BrightnessContrastNode(nid, x, y)
                node.brightness = params.get("brightness", 0.0)
                node.contrast = params.get("contrast", 0.0)
            elif typ == "levels":
                node = LevelsNode(nid, x, y)
                node.black_point = params.get("black_point", 0.0)
                node.white_point = params.get("white_point", 100.0)
                node.gamma = params.get("gamma", 1.0)
            elif typ == "hsl":
                node = HSLNode(nid, x, y)
                node.hue = params.get("hue", 0.0)
                node.saturation = params.get("saturation", 0.0)
                node.lightness = params.get("lightness", 0.0)
            elif typ == "color_source":
                node = ColorSourceNode(nid, x, y)
                node.color = params.get("color", "#808080")
                node.source_width = params.get("source_width", 512)
                node.source_height = params.get("source_height", 512)
            elif typ == "gradient":
                node = GradientNode(nid, x, y)
                node.gradient_type = params.get("gradient_type", "linear")
                node.start_color = params.get("start_color", "#ffffff")
                node.end_color = params.get("end_color", "#000000")
                node.angle = params.get("angle", 0.0)
                node.source_width = params.get("source_width", 512)
                node.source_height = params.get("source_height", 512)
            elif typ == "noise":
                node = NoiseNode(nid, x, y)
                node.noise_type = params.get("noise_type", "gaussian")
                node.scale = params.get("scale", 64.0)
                node.seed = params.get("seed", 0)
                node.source_width = params.get("source_width", 512)
                node.source_height = params.get("source_height", 512)
            elif typ == "color_balance":
                node = ColorBalanceNode(nid, x, y)
                node.cyan_red = params.get("cyan_red", 0.0)
                node.magenta_green = params.get("magenta_green", 0.0)
                node.yellow_blue = params.get("yellow_blue", 0.0)
            elif typ == "exposure_gamma":
                node = ExposureGammaNode(nid, x, y)
                node.exposure = params.get("exposure", 0.0)
                node.gamma = params.get("gamma", 1.0)
            elif typ == "curves":
                node = CurvesNode(nid, x, y)
                node.shadows = params.get("shadows", 0.0)
                node.dark_midtones = params.get("dark_midtones", 64.0)
                node.midtones = params.get("midtones", 128.0)
                node.light_midtones = params.get("light_midtones", 192.0)
                node.highlights = params.get("highlights", 255.0)
            elif typ == "crop":
                node = CropNode(nid, x, y)
                node.crop_x = params.get("crop_x", 0.0)
                node.crop_y = params.get("crop_y", 0.0)
                node.crop_width = params.get("crop_width", 256.0)
                node.crop_height = params.get("crop_height", 256.0)
            elif typ == "resize":
                node = ResizeNode(nid, x, y)
                node.resize_width = params.get("resize_width", 512.0)
                node.resize_height = params.get("resize_height", 512.0)
                node.resize_mode = params.get("resize_mode", "stretch")
            elif typ == "rotate":
                node = RotateNode(nid, x, y)
                node.angle = params.get("angle", 0.0)
            elif typ == "flip":
                node = FlipNode(nid, x, y)
                node.direction = params.get("direction", "horizontal")
            elif typ == "distort":
                node = DistortNode(nid, x, y)
                for a in ("dist_x0","dist_y0","dist_x1","dist_y1","dist_x2","dist_y2","dist_x3","dist_y3"):
                    setattr(node, a, params.get(a, 0.0))
            elif typ == "blur":
                node = BlurNode(nid, x, y)
                node.radius = params.get("radius", 5.0)
            elif typ == "sharpen":
                node = SharpenNode(nid, x, y)
                node.amount = params.get("amount", 1.0)
                node.radius = params.get("radius", 2.0)
            elif typ == "edge_detect":
                node = EdgeDetectNode(nid, x, y)
                node.threshold = params.get("threshold", 0.5)
            elif typ == "opacity":
                node = OpacityNode(nid, x, y)
                node.opacity = params.get("opacity", 1.0)
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
        if ctrl and keyval in (Gdk.KEY_M, Gdk.KEY_m):
            for w in list(self._selected_widgets):
                w.toggle_minimize()
            return True
        if not ctrl and keyval in (Gdk.KEY_M, Gdk.KEY_m):
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
                self._maybe_process_analysis_node(node_id)
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


