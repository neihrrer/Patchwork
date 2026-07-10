from typing import Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")

from gi.repository import Gtk, Gdk, GdkPixbuf


class ComparisonWidget(Gtk.DrawingArea):
    MODE_ORIGINAL = 0
    MODE_RESULT = 1
    MODE_COMPARE = 2

    def __init__(self):
        super().__init__()
        self._original: Optional[GdkPixbuf.Pixbuf] = None
        self._result: Optional[GdkPixbuf.Pixbuf] = None
        self._mode = self.MODE_ORIGINAL
        self._split = 0.5
        self._hover_near_divider = False
        self._dragging = False

        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_draw_func(self._draw)

        click = Gtk.GestureClick()
        click.connect("pressed", self._on_click_pressed)
        click.connect("released", self._on_click_released)
        self.add_controller(click)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

    def _update_split_from_x(self, x: float):
        widget_width = self.get_width()
        if not self._original or widget_width <= 0:
            return
        pw = self._original.get_width()
        ph = self._original.get_height()
        scale = min(widget_width / pw, self.get_height() / ph)
        sw = pw * scale
        ox = (widget_width - sw) / 2
        rel_x = (x - ox) / sw
        self._split = max(0.0, min(1.0, rel_x))
        self.queue_draw()

    def set_original(self, pixbuf: Optional[GdkPixbuf.Pixbuf]):
        self._original = pixbuf
        self._mode = self.MODE_ORIGINAL
        self.queue_draw()

    def set_result(self, pixbuf: Optional[GdkPixbuf.Pixbuf]):
        self._result = pixbuf
        if pixbuf is not None:
            self._mode = self.MODE_RESULT
        self.queue_draw()

    def set_mode(self, mode: int):
        if mode in (self.MODE_ORIGINAL, self.MODE_RESULT, self.MODE_COMPARE):
            self._mode = mode
            self.queue_draw()

    def get_mode(self) -> int:
        return self._mode

    def _draw(self, area: Gtk.DrawingArea, cr, width: int, height: int):
        if self._mode == self.MODE_COMPARE and self._original and self._result:
            self._draw_split(cr, width, height)
        elif self._mode == self.MODE_RESULT and self._result:
            self._draw_pixbuf(cr, self._result, width, height)
        elif self._original:
            self._draw_pixbuf(cr, self._original, width, height)

    def _draw_pixbuf(self, cr, pixbuf: GdkPixbuf.Pixbuf, width: int, height: int):
        if not pixbuf:
            return
        pw = pixbuf.get_width()
        ph = pixbuf.get_height()
        if pw == 0 or ph == 0:
            return
        scale = min(width / pw, height / ph)
        sw = pw * scale
        sh = ph * scale
        ox = (width - sw) / 2
        oy = (height - sh) / 2
        cr.save()
        cr.translate(ox, oy)
        cr.scale(scale, scale)
        Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
        cr.paint()
        cr.restore()

    def _draw_split(self, cr, width: int, height: int):
        orig = self._original
        res = self._result
        if not orig or not res:
            return
        pw = orig.get_width()
        ph = orig.get_height()
        if pw == 0 or ph == 0:
            return
        scale = min(width / pw, height / ph)
        sw = pw * scale
        sh = ph * scale
        ox = (width - sw) / 2
        oy = (height - sh) / 2

        split_x = ox + self._split * sw

        cr.save()
        cr.translate(ox, oy)
        cr.scale(scale, scale)

        cr.rectangle(0, 0, pw * self._split, ph)
        cr.clip()
        Gdk.cairo_set_source_pixbuf(cr, res, 0, 0)
        cr.paint()

        cr.reset_clip()
        cr.rectangle(pw * self._split, 0, pw * (1 - self._split), ph)
        cr.clip()
        Gdk.cairo_set_source_pixbuf(cr, orig, 0, 0)
        cr.paint()

        cr.restore()

        cr.set_source_rgb(0.5, 0.5, 0.5)
        cr.set_line_width(2.0)
        cr.move_to(split_x, oy)
        cr.line_to(split_x, oy + sh)
        cr.stroke()

    def _on_click_pressed(self, gesture, n_press: float, x: float, y: float):
        if self._mode == self.MODE_COMPARE and self._original and self._result:
            self._dragging = True
            self._update_split_from_x(x)

    def _on_click_released(self, gesture, n_press: float, x: float, y: float):
        self._dragging = False

    def _on_motion(self, controller, x: float, y: float):
        if self._mode != self.MODE_COMPARE or not self._original or not self._result:
            return

        if self._dragging:
            self._update_split_from_x(x)
            return

        widget_width = self.get_width()
        widget_height = self.get_height()
        pw = self._original.get_width()
        ph = self._original.get_height()
        scale = min(widget_width / pw, widget_height / ph)
        sw = pw * scale
        ox = (widget_width - sw) / 2
        split_screen_x = ox + self._split * sw
        near = abs(x - split_screen_x) < 6
        if near != self._hover_near_divider:
            self._hover_near_divider = near
            cursor = Gdk.Cursor.new_from_name("col-resize") if near else None
            self.set_cursor(cursor)

    def _on_leave(self, controller):
        self._dragging = False
        if self._hover_near_divider:
            self._hover_near_divider = False
            self.set_cursor(None)
