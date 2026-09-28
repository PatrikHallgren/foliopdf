"""Local handwriting capture with click-free touchpad drawing."""

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk


class SignaturePad(Gtk.DrawingArea):
    def __init__(self, changed):
        super().__init__()
        self.strokes = []
        self.active = None
        self.armed = False
        self.pointer = None
        self.space_down = False
        self.changed = changed
        self.set_content_width(560)
        self.set_content_height(220)
        self.set_focusable(True)
        self.set_cursor_from_name("crosshair")
        self.set_draw_func(self._draw)
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", self._enter)
        motion.connect("motion", self._motion)
        motion.connect("leave", self._leave)
        self.add_controller(motion)
        click = Gtk.GestureDrag()
        click.set_button(1)
        click.connect("drag-begin", self._press)
        click.connect("drag-end", self._release)
        click.connect("cancel", self._leave)
        self.add_controller(click)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key_press)
        keys.connect("key-released", self._key_release)
        self.add_controller(keys)
        focus = Gtk.EventControllerFocus()
        focus.connect("leave", self._leave)
        self.add_controller(focus)

    def _notify(self):
        self.queue_draw()
        self.changed()

    def _begin(self, x, y):
        self.active = [(x, y)]
        self.strokes.append(self.active)
        self._notify()

    def _enter(self, _controller, x, y):
        self.grab_focus()
        self.pointer = (x, y)

    def _motion(self, _controller, x, y):
        self.pointer = (x, y)
        if self.active is not None:
            self.active.append((x, y))
            self._notify()

    def _press(self, _gesture, x, y):
        self.grab_focus()
        self.pointer = (x, y)
        if not self.armed:
            self._begin(x, y)

    def _release(self, *_):
        if not self.armed:
            self.active = None
            self._notify()

    def _leave(self, *_):
        self.active = None
        self.armed = False
        self.pointer = None
        self.space_down = False
        self._notify()

    def _key_press(self, _controller, key, _code, _state):
        if key != Gdk.KEY_space:
            return False
        if not self.space_down:
            self.space_down = True
            self.armed = not self.armed and self.pointer is not None
            if self.armed:
                self._begin(*self.pointer)
            else:
                self.active = None
            self._notify()
        return True

    def _key_release(self, _controller, key, *_):
        if key == Gdk.KEY_space:
            self.space_down = False

    def clear(self):
        self._leave()
        self.strokes.clear()
        self._notify()

    def undo(self):
        self._leave()
        if self.strokes:
            self.strokes.pop()
        self._notify()

    def _draw(self, _area, cr, width, height):
        cr.set_source_rgb(1, 1, 1)
        cr.paint()
        cr.set_source_rgb(.08, .08, .12)
        cr.set_line_width(2)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        for stroke in self.strokes:
            cr.move_to(*stroke[0])
            for point in stroke[1:]:
                cr.line_to(*point)
            if len(stroke) == 1:
                cr.line_to(*stroke[0])
            cr.stroke()
        if self.has_focus():
            cr.set_source_rgb(.2, .4, .8)
            cr.set_line_width(2)
            cr.rectangle(1, 1, width - 2, height - 2)
            cr.stroke()
