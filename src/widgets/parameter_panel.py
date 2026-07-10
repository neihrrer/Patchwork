import gettext
from typing import Optional

import gi

try:
    _ = gettext.gettext
except Exception:
    _ = lambda s: s

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gtk, Gdk, GLib

from models.filter import ParamDef, ParamKind, ParamValue

KIND = ParamKind


class ParameterPanel:
    def __init__(
        self,
        container: Gtk.Box,
        param_defs: list[ParamDef],
        param_values: dict[str, ParamValue],
        filter_name: str = "",
    ):
        self._container = container
        self._param_defs = param_defs
        self._param_values = param_values
        self._filter_name = filter_name

        self._rebuild()

    def _rebuild(self):
        for child in list(self._container):
            self._container.remove(child)

        if self._filter_name:
            header = Gtk.Label(
                label=self._filter_name,
                xalign=0,
                margin_start=8,
                margin_top=8,
                margin_bottom=2,
            )
            header.add_css_class("heading")
            self._container.append(header)

        separator = Gtk.Separator(
            margin_start=8,
            margin_end=8,
            margin_bottom=2,
        )
        self._container.append(separator)

        if not self._param_defs:
            label = Gtk.Label(
                label=_("No parameters"),
                margin_top=16,
                margin_bottom=16,
            )
            label.add_css_class("dim-label")
            self._container.append(label)
            return

        for i, param_def in enumerate(self._param_defs):
            row = self._create_param_row(param_def)
            if row:
                self._container.append(row)

    def _create_param_row(self, param_def: ParamDef) -> Optional[Gtk.Widget]:
        row = Gtk.Box(
            orientation="vertical",
            spacing=4,
            margin_start=8,
            margin_end=8,
            margin_top=4,
            margin_bottom=4,
        )

        label = Gtk.Label(
            label=param_def.label,
            xalign=0,
        )
        row.append(label)

        if param_def.kind in (KIND.INT,):
            control = self._create_int_control(param_def)
            if control:
                row.append(control)

        elif param_def.kind in (KIND.FLOAT,):
            control = self._create_float_control(param_def)
            if control:
                row.append(control)

        elif param_def.kind == KIND.CHOICE:
            control = self._create_choice_control(param_def)
            if control:
                row.append(control)

        elif param_def.kind == KIND.BOOL:
            control = self._create_bool_control(param_def)
            if control:
                row.append(control)

        elif param_def.kind == KIND.COLOR:
            control = self._create_color_control(param_def)
            if control:
                row.append(control)

        elif param_def.kind == KIND.TEXT:
            control = self._create_text_control(param_def)
            if control:
                row.append(control)

        else:
            control = self._create_text_control(param_def)
            if control:
                row.append(control)

        return row

    def _create_int_control(self, param_def: ParamDef) -> Optional[Gtk.Widget]:
        lo = param_def.min_val or 0
        hi = param_def.max_val or 100
        val = int(param_def.default) if param_def.default is not None else 0
        adj = Gtk.Adjustment(
            value=val,
            lower=lo,
            upper=hi if hi > lo else lo + 1,
            step_increment=1,
            page_increment=10,
        )
        spin = Gtk.SpinButton(adjustment=adj, numeric=True)
        spin.set_halign(Gtk.Align.START)

        def on_changed(spin, name=param_def.name):
            self._param_values[name] = int(spin.get_value())

        spin.connect("value-changed", on_changed)
        return spin

    def _create_float_control(self, param_def: ParamDef) -> Optional[Gtk.Widget]:
        lo = param_def.min_val or 0.0
        hi = param_def.max_val or 100.0
        val = float(param_def.default) if param_def.default is not None else 0.0
        adj = Gtk.Adjustment(
            value=val,
            lower=lo,
            upper=hi if hi > lo else lo + 1.0,
            step_increment=0.1,
            page_increment=1.0,
        )
        spin = Gtk.SpinButton(adjustment=adj, digits=2, numeric=True)
        spin.set_halign(Gtk.Align.START)

        def on_changed(spin, name=param_def.name):
            self._param_values[name] = spin.get_value()

        spin.connect("value-changed", on_changed)
        return spin

    def _create_choice_control(self, param_def: ParamDef) -> Optional[Gtk.Widget]:
        choices = param_def.choices
        if not choices:
            return None

        store = Gtk.StringList.new(choices)
        control = Gtk.DropDown(model=store)
        control.set_halign(Gtk.Align.START)

        idx = int(param_def.default) if param_def.default is not None else 0
        if 0 <= idx < len(choices):
            control.set_selected(idx)

        def on_notify(dropdown, _pspec, name=param_def.name):
            sel = dropdown.get_selected()
            self._param_values[name] = sel

        control.connect("notify::selected", on_notify)
        return control

    def _create_bool_control(self, param_def: ParamDef) -> Optional[Gtk.Widget]:
        sw = Gtk.Switch()
        sw.set_active(bool(param_def.default))
        sw.set_halign(Gtk.Align.START)
        sw.set_valign(Gtk.Align.CENTER)

        def on_notify(switch, _pspec, name=param_def.name):
            self._param_values[name] = switch.get_active()

        sw.connect("notify::active", on_notify)
        return sw

    def _create_color_control(self, param_def: ParamDef) -> Optional[Gtk.Widget]:
        default = param_def.default
        if isinstance(default, list) and len(default) >= 3:
            r = min(255, max(0, int(default[0])))
            g = min(255, max(0, int(default[1])))
            b = min(255, max(0, int(default[2])))
            a = min(255, max(0, int(default[3]))) if len(default) > 3 else 255
        else:
            r, g, b, a = 0, 0, 0, 255

        btn = Gtk.ColorButton(rgba=Gdk.RGBA(red=r/255, green=g/255, blue=b/255, alpha=a/255))
        btn.set_halign(Gtk.Align.START)
        btn.set_valign(Gtk.Align.CENTER)

        def on_set(color_btn, name=param_def.name):
            rgba = color_btn.get_rgba()
            vals = [int(rgba.red * 255), int(rgba.green * 255), int(rgba.blue * 255)]
            if rgba.alpha < 1.0:
                vals.append(int(rgba.alpha * 255))
            self._param_values[name] = vals

        btn.connect("color-set", on_set)
        return btn

    def _create_text_control(self, param_def: ParamDef) -> Optional[Gtk.Widget]:
        val = str(param_def.default) if param_def.default is not None else ""
        entry = Gtk.Entry(text=val)
        entry.set_halign(Gtk.Align.START)

        def on_changed(entry, name=param_def.name):
            self._param_values[name] = entry.get_text()

        entry.connect("changed", on_changed)
        return entry
