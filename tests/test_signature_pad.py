"""Optional GTK integration checks: FOLIO_GTK_TESTS=1 with a test display."""
import os
import unittest


@unittest.skipUnless(os.environ.get('FOLIO_GTK_TESTS') == '1', 'requires a GTK test display')
class SignaturePadTests(unittest.TestCase):
    def test_touchpad_strokes_clear_undo_and_focus_loss(self):
        from signature_pad import SignaturePad, Gdk, Gtk
        window = Gtk.Window()
        pad = SignaturePad(lambda: None)
        window.set_child(pad)
        try:
            pad._enter(None, 10, 10)
            pad._key_press(None, Gdk.KEY_space, 0, 0)
            pad._key_press(None, Gdk.KEY_space, 0, 0)  # key repeat must not toggle
            self.assertTrue(pad.armed)
            pad._motion(None, 30, 20)
            pad._key_release(None, Gdk.KEY_space)
            pad._key_press(None, Gdk.KEY_space, 0, 0)
            pad._key_release(None, Gdk.KEY_space)
            pad._motion(None, 90, 90)
            self.assertEqual(pad.strokes, [[(10, 10), (30, 20)]])
            pad._key_press(None, Gdk.KEY_space, 0, 0)
            pad._motion(None, 100, 100)
            pad._leave()
            self.assertFalse(pad.armed)
            pad._motion(None, 120, 120)
            self.assertEqual(pad.strokes[-1], [(90, 90), (100, 100)])
            pad.undo()
            self.assertEqual(len(pad.strokes), 1)
            pad.clear()
            self.assertEqual(pad.strokes, [])
            pad._press(None, 10, 10)
            pad._motion(None, 20, 20)
            pad._release()
            pad._motion(None, 30, 30)
            self.assertEqual(pad.strokes, [[(10, 10), (20, 20)]])
        finally:
            window.destroy()

    def test_dialog_cancel_and_place(self):
        from app import Folio, Gtk, GLib
        from signature_pad import SignaturePad
        app = Folio()
        app.register(None)
        app.activate()
        context = GLib.MainContext.default()
        def drain():
            while context.pending():
                context.iteration(False)
        def dialog():
            app._signature_dialog()
            drain()
            return next(w for w in Gtk.Window.get_toplevels() if w.get_title() == 'Sign document')
        try:
            d = dialog()
            self.assertFalse(d.get_widget_for_response(Gtk.ResponseType.ACCEPT).get_sensitive())
            d.response(Gtk.ResponseType.CANCEL)
            self.assertFalse(app.project.dirty)
            d = dialog()
            pad = d.get_content_area().get_first_child()
            while not isinstance(pad, SignaturePad):
                pad = pad.get_next_sibling()
            pad._press(None, 10, 10)
            pad._motion(None, 120, 60)
            pad._release()
            drain()
            self.assertTrue(d.get_widget_for_response(Gtk.ResponseType.ACCEPT).get_sensitive())
            d.response(Gtk.ResponseType.ACCEPT)
            drain()
            self.assertTrue(app.project.dirty)
            self.assertEqual(len(app.project.doc[0].get_drawings()), 1)
            app._undo()
            self.assertEqual(len(app.project.doc[0].get_drawings()), 0)
        finally:
            app.project.close()
            app.window.destroy()
            app.quit()
