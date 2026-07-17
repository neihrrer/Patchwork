import gettext
from typing import Optional

import cairo
import gi

try:
    _ = gettext.gettext
except Exception:
    _ = lambda s: s

gi.require_version("Gtk", "4.0")
gi.require_version("Gio", "2.0")
gi.require_version("Gdk", "4.0")

_pending_drag_text = None


def get_pending_drag_text():
    global _pending_drag_text
    t = _pending_drag_text
    _pending_drag_text = None
    return t


def peek_pending_drag_text():
    global _pending_drag_text
    return _pending_drag_text


def set_pending_drag_text(text: str):
    global _pending_drag_text
    _pending_drag_text = text

from gi.repository import GObject, Gtk, Gio, GLib, Gdk

from models.filter import FilterDef, ENGINE_GMIC, ENGINE_IMAGEMAGICK


_GUTTER_INDENT = 22

_ROOT_GMIC = "G'mic"
_ROOT_IMAGEMAGICK = "ImageMagick"
_ROOT_BASIC = "Basic"
_ROOT_MATH = "Math"

_BASIC_ITEMS = [
    ("input", "Input", "input"),
    ("output", "Output", "output"),
    ("blending", "Blending", "blend"),
    ("mask", "Mask", "mask"),
    ("coloring", "Coloring", "coloring"),
    ("opacity", "Opacity", "opacity"),
    ("label", "Label", "label"),
    ("comment", "Comment", "comment"),
]

_MATH_ITEMS = [
    ("constant", "Constant", "constant"),
    ("add", "Add", "add"),
    ("subtract", "Subtract", "subtract"),
    ("multiply", "Multiply", "multiply"),
    ("divide", "Divide", "divide"),
    ("ceil", "Ceiling", "ceil"),
    ("floor", "Floor", "floor"),
    ("round", "Round", "round"),
    ("sum", "Sum", "sum"),
    ("product", "Product", "product"),
]


class TreeItemNode(GObject.Object):
    __gtype_name__ = "TreeItemNode"

    def __init__(self, display_name: str = "", node_type: str = "filter", filter_def: Optional[FilterDef] = None):
        super().__init__()
        self._display_name = display_name
        self._node_type = node_type
        self._filter_def = filter_def
        self.is_last_child = False

    @GObject.Property(type=str)
    def display_name(self) -> str:
        return self._display_name

    @display_name.setter
    def display_name(self, value: str):
        self._display_name = value

    @GObject.Property(type=str)
    def node_type(self) -> str:
        return self._node_type

    @node_type.setter
    def node_type(self, value: str):
        self._node_type = value

    @property
    def filter_def(self) -> Optional[FilterDef]:
        return self._filter_def

    @filter_def.setter
    def filter_def(self, value: Optional[FilterDef]):
        self._filter_def = value


class FilterBrowser(GObject.Object):
    __gsignals__ = {
        "filter-selected": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, list_view: Gtk.ListView, filters: list[FilterDef]):
        super().__init__()
        self._list_view = list_view
        self._all_filters = filters
        self._selection: Optional[Gtk.SingleSelection] = None
        self._tree_model: Optional[Gtk.TreeListModel] = None
        self._setup_view()

    def _setup_view(self):
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_factory_setup)
        factory.connect("bind", self._on_factory_bind)

        self._list_view.set_factory(factory)
        self._list_view.connect("activate", self._on_list_activate)

        self._rebuild_model()

    def _is_excluded(self, f: FilterDef) -> bool:
        return bool(f.category and f.category[0].lower() == "about")

    def _rebuild_model(self, search_text: str = ""):
        root_store = Gio.ListStore.new(TreeItemNode)

        if search_text:
            lower = search_text.lower()
            matching = [
                f for f in self._all_filters
                if not self._is_excluded(f)
                and (lower in f.display_name.lower()
                     or lower in f.name.lower()
                     or any(lower in c.lower() for c in f.category))
            ]
            for f in matching:
                node = TreeItemNode(display_name=f.display_name, node_type="filter", filter_def=f)
                root_store.append(node)
        else:
            root_store.append(TreeItemNode(display_name=_ROOT_BASIC, node_type="root"))
            root_store.append(TreeItemNode(display_name=_ROOT_MATH, node_type="root"))
            root_store.append(TreeItemNode(display_name=_ROOT_GMIC, node_type="root"))
            root_store.append(TreeItemNode(display_name=_ROOT_IMAGEMAGICK, node_type="root"))

        tree_model = Gtk.TreeListModel.new(root_store, passthrough=False, create_func=self._create_children_func)
        self._tree_model = tree_model
        tree_model.connect("items-changed", self._on_model_items_changed)
        self._selection = Gtk.SingleSelection.new(tree_model)
        self._selection.set_can_unselect(True)
        self._selection.set_autoselect(False)
        self._list_view.set_model(self._selection)

        if not search_text:
            self._expand_all()

    def _expand_all(self):
        self._expand_recursive(self._tree_model)

    def _expand_recursive(self, model):
        if not model:
            return
        n = model.get_n_items()
        for i in range(n):
            try:
                row = model.get_row(i)
                if row and row.is_expandable():
                    row.set_expanded(True)
                    self._expand_recursive(row.get_model())
            except Exception:
                pass

    @staticmethod
    def _mark_last_child(store):
        n = store.get_n_items()
        if n > 0:
            store.get_item(n - 1).is_last_child = True
        return store

    def _create_children_func(self, item: TreeItemNode):
        if item.node_type == "root":
            if item.display_name == _ROOT_BASIC:
                store = Gio.ListStore.new(TreeItemNode)
                for _key, label, ntype in _BASIC_ITEMS:
                    node = TreeItemNode(display_name=label, node_type=ntype)
                    if ntype == "blend":
                        node._blend_mode = "over"
                    store.append(node)
                return self._mark_last_child(store)

            if item.display_name == _ROOT_MATH:
                store = Gio.ListStore.new(TreeItemNode)
                for _key, label, ntype in _MATH_ITEMS:
                    node = TreeItemNode(display_name=label, node_type=ntype)
                    store.append(node)
                return self._mark_last_child(store)

            if item.display_name == _ROOT_IMAGEMAGICK:
                engine = ENGINE_IMAGEMAGICK
            else:
                engine = ENGINE_GMIC

            seen = set()
            cats = []
            for f in self._all_filters:
                if self._is_excluded(f):
                    continue
                if f.engine != engine:
                    continue
                first = f.category[0] if f.category else "Various"
                if first not in seen:
                    seen.add(first)
                    cats.append(first)
            cats.sort(key=str.casefold)
            store = Gio.ListStore.new(TreeItemNode)
            for first in cats:
                node = TreeItemNode(display_name=first, node_type="category")
                node._category_path = [first]
                node._engine = engine
                store.append(node)
            return self._mark_last_child(store)
        elif item.node_type == "category":
            path = getattr(item, "_category_path", None)
            if path is None:
                return None

            depth = len(path)
            engine = getattr(item, '_engine', None)
            next_levels = set()
            same_level = []
            for f in self._all_filters:
                if self._is_excluded(f):
                    continue
                if engine is not None and f.engine != engine:
                    continue
                cat = f.category if f.category else ["Various"]
                if cat[:depth] == path:
                    if len(cat) > depth:
                        next_levels.add(cat[depth])
                    elif len(cat) == depth:
                        same_level.append(f)

            store = Gio.ListStore.new(TreeItemNode)
            for seg in sorted(next_levels, key=str.casefold):
                node = TreeItemNode(display_name=seg, node_type="category")
                node._category_path = path + [seg]
                node._engine = engine
                store.append(node)
            for f in same_level:
                node = TreeItemNode(display_name=f.display_name, node_type="filter", filter_def=f)
                store.append(node)
            return self._mark_last_child(store)
        return None

    def set_filter(self, text: str):
        self._rebuild_model(text)

    def _on_gutter_draw(self, area, cr, width, height, data):
        depth = getattr(area, '_depth', 0)
        is_last = getattr(area, '_is_last', False)
        if depth <= 0:
            return

        cr.set_line_cap(cairo.LineCap.ROUND)
        cr.set_line_join(cairo.LineJoin.ROUND)
        fg = area.get_color()
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 1.0)
        cr.set_line_width(1.5)

        cr.push_group()

        ancestor_last = getattr(area, '_ancestor_last', [])
        for d in range(1, depth):
            if d - 1 < len(ancestor_last) and ancestor_last[d - 1]:
                continue
            x = d * _GUTTER_INDENT - _GUTTER_INDENT // 2
            if d > 1:
                x -= 3
            cr.move_to(x, -3)
            cr.line_to(x, height + 3)
            cr.stroke()

        stem_x = depth * _GUTTER_INDENT - _GUTTER_INDENT // 2
        if depth > 1:
            stem_x -= 3

        if is_last:
            cr.move_to(stem_x, -3)
            cr.line_to(stem_x, height * 0.25)
            cr.stroke()
        else:
            cr.move_to(stem_x, -3)
            cr.line_to(stem_x, height + 3)
            cr.stroke()

        off = 8.0
        cr.move_to(stem_x, off)
        r = 8.0
        k = 0.5
        cr.curve_to(
            stem_x, off + r * k,
            stem_x + r * (1.0 - k), off + r,
            stem_x + r, off + r,
        )
        cr.stroke()

        cr.move_to(stem_x + r, off + r)
        cr.line_to(width, off + r)
        cr.stroke()
        cr.fill()

        cr.pop_group_to_source()
        cr.paint_with_alpha(0.15)

    def _on_factory_setup(self, factory, list_item):
        wrapper = Gtk.Box(orientation="horizontal", spacing=0)
        wrapper.set_margin_top(0)
        wrapper.set_margin_bottom(0)

        gutter = Gtk.DrawingArea()
        gutter.set_valign(Gtk.Align.FILL)
        gutter.set_margin_top(0)
        gutter.set_margin_bottom(0)
        gutter.add_css_class("tree-gutter")
        gutter.set_draw_func(self._on_gutter_draw, None)

        expander = Gtk.TreeExpander()
        expander.set_indent_for_depth(False)
        expander.set_indent_for_icon(False)
        expander.set_margin_top(0)
        expander.set_margin_bottom(0)

        hbox = Gtk.Box(orientation="horizontal", spacing=0)
        vbox = Gtk.Box(orientation="vertical", spacing=1, margin_start=4, margin_end=8)
        name_label = Gtk.Label(xalign=0, hexpand=True)
        vbox.append(name_label)
        hbox.append(vbox)
        expander.set_child(hbox)

        wrapper.append(gutter)
        wrapper.append(expander)
        list_item.set_child(wrapper)

        drag_src = Gtk.DragSource()
        drag_src.set_actions(Gdk.DragAction.COPY)
        drag_src.connect("prepare", self._on_drag_prepare)
        drag_src.connect("drag-begin", self._on_drag_begin)
        drag_src.connect("drag-end", self._on_drag_end)
        expander.add_controller(drag_src)

    def _on_factory_bind(self, factory, list_item):
        wrapper = list_item.get_child()
        if not wrapper:
            return
        gutter = wrapper.get_first_child()
        expander = gutter.get_next_sibling()
        if not expander:
            return

        try:
            pos = list_item.get_position()
            if self._tree_model and pos != Gtk.INVALID_LIST_POSITION:
                row = self._tree_model.get_row(pos)
                if row is not None:
                    expander.set_list_row(row)
        except Exception:
            pass

        item = list_item.get_item()
        if isinstance(item, Gtk.TreeListRow):
            node = item.get_item()
            depth = item.get_depth()
        else:
            node = item
            depth = 0
        if not node:
            return

        expander._tree_item_node = node
        expander._tree_item_pos = list_item.get_position()

        hbox = expander.get_child()
        vbox = hbox.get_first_child()
        name_label = vbox.get_first_child()

        name_label.set_label(node.display_name)
        name_label.set_tooltip_text(node.display_name)
        name_label.get_style_context().remove_class("heading")

        # collect ancestor last-child flags for correct stem rendering
        # stop at root (depth 0) so indices align with loop d=1,2,...
        ancestor_last = []
        if isinstance(item, Gtk.TreeListRow):
            row = item
            while True:
                parent = row.get_parent()
                if parent is None or parent.get_depth() == 0:
                    break
                parent_node = parent.get_item()
                ancestor_last.append(getattr(parent_node, 'is_last_child', False))
                row = parent
            ancestor_last.reverse()

        gutter.set_size_request(max(3, depth * _GUTTER_INDENT), -1)
        gutter._depth = depth
        gutter._is_last = getattr(node, 'is_last_child', False)
        gutter._ancestor_last = ancestor_last
        gutter.queue_draw()

        name_label.set_margin_top(8)
        name_label.set_margin_bottom(8)

    def _get_drag_text(self, node: TreeItemNode) -> Optional[str]:
        if node.node_type == "filter" and node.filter_def:
            fd = node.filter_def
            return f"filter:{fd.engine}:{fd.name}"
        text_map = {
            "blend": "blend:over",
            "opacity": "opacity:",
            "mask": "mask:",
            "coloring": "coloring:",
            "input": "input:",
            "output": "output:",
        }
        if node.node_type in text_map:
            return text_map[node.node_type]
        if node.node_type in ("constant", "add", "subtract", "multiply",
                               "divide", "ceil", "floor", "round",
                               "sum", "product", "label", "comment"):
            return f"{node.node_type}:"
        return None

    def _on_drag_prepare(self, drag_source, x, y):
        global _pending_drag_text
        widget = drag_source.get_widget()
        node = widget._tree_item_node if widget else None
        if node:
            text = self._get_drag_text(node)
            if text:
                _pending_drag_text = text
                data = GLib.Bytes.new(text.encode("utf-8"))
                return Gdk.ContentProvider.new_for_bytes("text/plain", data)
        return None

    def _on_drag_begin(self, source, drag):
        widget = source.get_widget()
        if widget and hasattr(widget, '_tree_item_pos'):
            self._selection.set_selected(widget._tree_item_pos)
        try:
            pixel = GLib.Bytes.new(b"\x00\x00\x00\x00")
            texture = Gdk.MemoryTexture.new(1, 1, Gdk.MemoryFormat.B8G8R8A8, pixel, 4)
            source.set_icon(texture, 0, 0)
        except Exception:
            pass

    def _on_drag_end(self, source, drag, delete_data):
        pass

    def _on_model_items_changed(self, model, position, removed, added):
        if removed == 0:
            return
        selected = self._selection.get_selected()
        if selected == Gtk.INVALID_LIST_POSITION:
            return
        if position <= selected < position + removed:
            GLib.idle_add(lambda: self.emit("filter-selected", None) or GLib.SOURCE_REMOVE)

    def set_filters(self, filters: list[FilterDef]):
        self._all_filters = filters
        self._rebuild_model()

    def _on_list_activate(self, list_view, position):
        item = self._selection.get_item(position)
        if isinstance(item, Gtk.TreeListRow):
            item = item.get_item()
        if item:
            text = self._get_drag_text(item)
            if text:
                self.emit("filter-selected", text)
