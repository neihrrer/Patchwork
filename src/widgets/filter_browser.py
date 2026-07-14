import gettext
from typing import Optional

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

from gi.repository import GObject, Gtk, Gio, GLib, Gdk

from models.filter import FilterDef, ENGINE_GMIC, ENGINE_IMAGEMAGICK


_ROOT_GMIC = "G'mic"
_ROOT_IMAGEMAGICK = "ImageMagick"
_ROOT_BASIC = "Basic"
_ROOT_MATH = "Math"

_BASIC_ITEMS = [
    ("blending", "Blending", "blend"),
    ("opacity", "Opacity", "opacity"),
    ("coloring", "Coloring", "coloring"),
    ("mask", "Mask", "mask"),
    ("input", "Input", "input"),
    ("output", "Output", "output"),
]

_MATH_ITEMS = [
    ("constant", "Constant", "constant"),
    ("add", "Add", "add"),
    ("subtract", "Subtract", "subtract"),
    ("multiply", "Multiply", "multiply"),
    ("divide", "Divide", "divide"),
]


class TreeItemNode(GObject.Object):
    __gtype_name__ = "TreeItemNode"

    def __init__(self, display_name: str = "", node_type: str = "filter", filter_def: Optional[FilterDef] = None):
        super().__init__()
        self._display_name = display_name
        self._node_type = node_type
        self._filter_def = filter_def

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


def _format_category(cat: list[str]) -> str:
    if not cat:
        return "Various"
    if cat[0].lower() == "about":
        return ""
    return "/".join(cat)


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
        self._selection.connect("selection-changed", self._on_selection_changed)
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
                if row and row.get_expandable():
                    row.set_expanded(True)
                    self._expand_recursive(row.get_model())
            except Exception:
                pass

    def _create_children_func(self, item: TreeItemNode):
        if item.node_type == "root":
            if item.display_name == _ROOT_BASIC:
                store = Gio.ListStore.new(TreeItemNode)
                for _key, label, ntype in _BASIC_ITEMS:
                    node = TreeItemNode(display_name=label, node_type=ntype)
                    if ntype == "blend":
                        node._blend_mode = "over"
                    store.append(node)
                return store

            if item.display_name == _ROOT_MATH:
                store = Gio.ListStore.new(TreeItemNode)
                for _key, label, ntype in _MATH_ITEMS:
                    node = TreeItemNode(display_name=label, node_type=ntype)
                    store.append(node)
                return store

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
                cat_str = _format_category(f.category)
                if cat_str and cat_str not in seen:
                    seen.add(cat_str)
                    cats.append(cat_str)
            cats.sort(key=str.casefold)
            store = Gio.ListStore.new(TreeItemNode)
            for cat in cats:
                node = TreeItemNode(display_name=cat, node_type="category")
                store.append(node)
            return store
        elif item.node_type == "category":
            cat_name = item.display_name
            store = Gio.ListStore.new(TreeItemNode)
            for f in self._all_filters:
                if self._is_excluded(f):
                    continue
                if _format_category(f.category) == cat_name:
                    node = TreeItemNode(display_name=f.display_name, node_type="filter", filter_def=f)
                    store.append(node)
            return store
        return None

    def set_filter(self, text: str):
        self._rebuild_model(text)

    def _on_factory_setup(self, factory, list_item):
        expander = Gtk.TreeExpander()
        expander.set_indent_for_depth(True)
        expander.set_indent_for_icon(True)

        vbox = Gtk.Box(orientation="vertical", spacing=2, margin_start=12, margin_end=12)
        name_label = Gtk.Label(xalign=0, hexpand=True)
        cat_label = Gtk.Label(xalign=0, hexpand=True)
        cat_label.add_css_class("caption")
        cat_label.add_css_class("dim-label")

        vbox.append(name_label)
        vbox.append(cat_label)
        expander.set_child(vbox)
        list_item.set_child(expander)

        drag_src = Gtk.DragSource()
        drag_src.set_actions(Gdk.DragAction.COPY)
        drag_src.connect("prepare", self._on_drag_prepare)
        expander.add_controller(drag_src)

    def _on_factory_bind(self, factory, list_item):
        expander = list_item.get_child()

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
        else:
            node = item
        if not node:
            return

        expander._tree_item_node = node

        vbox = expander.get_child()
        name_label = vbox.get_first_child()
        cat_label = name_label.get_next_sibling()

        name_label.set_label(node.display_name)
        name_label.set_tooltip_text(node.display_name)
        name_label.get_style_context().remove_class("heading")

        if node.node_type == "category":
            name_label.set_margin_top(8)
            name_label.set_margin_bottom(4)
            cat_label.set_label("")
            cat_label.hide()
        elif node.node_type == "filter" and node.filter_def:
            name_label.set_margin_top(5)
            name_label.set_margin_bottom(4)
            cat_label.set_label("")
            cat_label.hide()
        else:
            name_label.set_margin_top(6)
            name_label.set_margin_bottom(4)
            cat_label.set_label("")
            cat_label.hide()

    def _on_drag_prepare(self, drag_source, x, y):
        global _pending_drag_text
        widget = drag_source.get_widget()
        node = widget._tree_item_node if widget else None
        if node:
            if node.node_type == "filter" and node.filter_def:
                fd = node.filter_def
                text = f"filter:{fd.engine}:{fd.name}"
                _pending_drag_text = text
                data = GLib.Bytes.new(text.encode("utf-8"))
                return Gdk.ContentProvider.new_for_bytes("text/plain", data)
            elif node.node_type == "blend":
                text = "blend:over"
                _pending_drag_text = text
                data = GLib.Bytes.new(text.encode("utf-8"))
                return Gdk.ContentProvider.new_for_bytes("text/plain", data)
            elif node.node_type == "opacity":
                text = "opacity:"
                _pending_drag_text = text
                data = GLib.Bytes.new(text.encode("utf-8"))
                return Gdk.ContentProvider.new_for_bytes("text/plain", data)
            elif node.node_type == "mask":
                text = "mask:"
                _pending_drag_text = text
                data = GLib.Bytes.new(text.encode("utf-8"))
                return Gdk.ContentProvider.new_for_bytes("text/plain", data)
            elif node.node_type == "coloring":
                text = "coloring:"
                _pending_drag_text = text
                data = GLib.Bytes.new(text.encode("utf-8"))
                return Gdk.ContentProvider.new_for_bytes("text/plain", data)
            elif node.node_type == "input":
                text = "input:"
                _pending_drag_text = text
                data = GLib.Bytes.new(text.encode("utf-8"))
                return Gdk.ContentProvider.new_for_bytes("text/plain", data)
            elif node.node_type == "output":
                text = "output:"
                _pending_drag_text = text
                data = GLib.Bytes.new(text.encode("utf-8"))
                return Gdk.ContentProvider.new_for_bytes("text/plain", data)
            elif node.node_type in ("constant", "add", "subtract", "multiply", "divide"):
                text = f"{node.node_type}:"
                _pending_drag_text = text
                data = GLib.Bytes.new(text.encode("utf-8"))
                return Gdk.ContentProvider.new_for_bytes("text/plain", data)
        return None

    def _on_model_items_changed(self, model, position, removed, added):
        if removed == 0:
            return
        selected = self._selection.get_selected()
        if selected == Gtk.INVALID_LIST_POSITION:
            return
        if position <= selected < position + removed:
            GLib.idle_add(lambda: self.emit("filter-selected", None) or GLib.SOURCE_REMOVE)

    def _on_selection_changed(self, selection, position, n_items):
        selected = selection.get_selected()
        if selected != Gtk.INVALID_LIST_POSITION:
            item = selection.get_selected_item()
            if isinstance(item, Gtk.TreeListRow):
                item = item.get_item()
            if item and item.node_type == "filter" and item.filter_def:
                self.emit("filter-selected", item.filter_def)
                return
        self.emit("filter-selected", None)
