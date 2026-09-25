#!/usr/bin/env python3
"""Folio PDF: a native GTK editor for Omarchy."""

from __future__ import annotations

import math
from pathlib import Path
import re
import subprocess
import sys
import threading
import tomllib

import cairo
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk

from pdf_model import PdfProject, PageItem
from hp_scanner import scan_feeder_page


def omarchy_colors() -> dict[str, str]:
    fallback = {
        "background": "#151821", "dark_background": "#10131b", "lighter_background": "#242936",
        "foreground": "#e7e9ee", "dark_foreground": "#a5abb8", "accent": "#9bafff",
        "selection": "#3b526f", "red": "#ec7979", "mode": "dark",
    }
    try:
        name = subprocess.run(["omarchy", "theme", "current"], check=True, capture_output=True,
                              text=True, timeout=3).stdout.strip()
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        for root in (Path.home() / ".config/omarchy/themes", Path("/usr/share/omarchy/themes")):
            palette = root / slug / "colors.toml"
            if palette.is_file():
                with palette.open("rb") as stream:
                    return fallback | tomllib.load(stream)
    except Exception:
        pass
    return fallback


def apply_theme() -> None:
    c = omarchy_colors()
    css = f"""
    window, dialog {{ background: {c['background']}; color: {c['foreground']}; }}
    headerbar {{ background: {c['dark_background']}; color: {c['foreground']};
                 border-bottom: 1px solid {c['lighter_background']}; box-shadow: none; }}
    .toolbar, .statusbar {{ background: {c['dark_background']}; padding: 8px 12px;
                             border-bottom: 1px solid {c['lighter_background']}; }}
    .statusbar {{ border-top: 1px solid {c['lighter_background']}; border-bottom: none; }}
    .side-panel {{ background: {c['dark_background']}; padding: 12px; }}
    .canvas-back {{ background: {c['background']}; }}
    .panel-title {{ font-weight: 800; letter-spacing: .05em; color: {c['dark_foreground']}; }}
    .muted {{ color: {c['dark_foreground']}; }}
    button {{ background: {c['lighter_background']}; color: {c['foreground']};
              border: 1px solid {c['lighter_background']}; border-radius: 7px;
              padding: 6px 10px; box-shadow: none; }}
    button:hover {{ border-color: {c['accent']}; }}
    button:disabled {{ opacity: .45; }}
    button.suggested-action {{ background: {c['accent']}; color: {c['dark_background']};
                               border-color: {c['accent']}; font-weight: 700; }}
    button.destructive-action {{ color: {c['red']}; }}
    button.thumb {{ padding: 8px; background: transparent; border-color: transparent; }}
    button.thumb.selected {{ background: {c['selection']}; border-color: {c['accent']}; }}
    entry, textview, spinbutton {{ background: {c['lighter_background']}; color: {c['foreground']};
                                  border: 1px solid {c['lighter_background']}; border-radius: 6px; }}
    textview text {{ background: {c['lighter_background']}; color: {c['foreground']}; }}
    scrollbar slider {{ background: {c['dark_foreground']}; border-radius: 8px; }}
    """
    provider = Gtk.CssProvider()
    provider.load_from_data(css.encode())
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                               Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def label(text: str, css_class: str | None = None, *, wrap: bool = False) -> Gtk.Label:
    widget = Gtk.Label(label=text, xalign=0)
    widget.set_wrap(wrap)
    if css_class:
        widget.add_css_class(css_class)
    return widget


def button(text: str, callback, css_class: str | None = None) -> Gtk.Button:
    widget = Gtk.Button(label=text)
    widget.connect("clicked", callback)
    if css_class:
        widget.add_css_class(css_class)
    return widget


def clear_box(box: Gtk.Box) -> None:
    while child := box.get_first_child():
        box.remove(child)


class Folio(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="dev.folio.PDF", flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self.project = PdfProject()
        self.page_index = 0
        self.scale = .9
        self.items: list[PageItem] = []
        self.selected: PageItem | None = None
        self.click_point = (50.0, 50.0)
        self.ocr_mode = False
        self.window = None
        self._closing = False
        self._scanning = False

    def do_activate(self):
        if self.window:
            self.window.present()
            return
        apply_theme()
        self._build_window()
        self._setup_actions()
        self.refresh(pages=True)
        self.window.present()

    def do_open(self, files, n_files, hint):
        self.do_activate()
        if files:
            path = files[0].get_path()
            self._confirm_discard(lambda: self._open_path(path))

    def _build_window(self):
        self.window = Gtk.ApplicationWindow(application=self, title="Folio PDF")
        self.window.set_default_size(1320, 850)
        self.window.connect("close-request", self._on_close_request)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.window.set_child(root)

        header = Gtk.HeaderBar()
        header.set_title_widget(label("FOLIO  /  PDF EDITOR", "panel-title"))
        header.pack_start(button("Open", lambda *_: self._choose_open()))
        actions_menu = Gio.Menu()
        for title, action in [
            ("Save As…", "save-as"), ("Extract pages…", "extract-pages"),
            ("Extract text…", "extract-text"), ("Delete page", "delete-page"),
            ("Make page searchable", "searchable"),
        ]:
            actions_menu.append(title, f"app.{action}")
        menu_button = Gtk.MenuButton(label="More")
        menu_button.set_menu_model(actions_menu)
        header.pack_end(menu_button)
        header.pack_end(button("Save", lambda *_: self._save(), "suggested-action"))
        root.append(header)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        toolbar.add_css_class("toolbar")
        root.append(toolbar)
        toolbar.append(button("Pages", lambda *_: self._toggle_pages()))
        toolbar.append(button("‹", lambda *_: self._step_page(-1)))
        toolbar.append(button("›", lambda *_: self._step_page(1)))
        toolbar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        toolbar.append(button("+ Page", lambda *_: self._add_blank()))
        toolbar.append(button("+ PDF", lambda *_: self._choose_insert_pdf()))
        self.scan_button = button("Scan feeder", lambda *_: self._start_feeder_scan())
        toolbar.append(self.scan_button)
        toolbar.append(button("Scan OCR", lambda *_: self._scan_page()))
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        toolbar.append(spacer)
        self.undo_button = button("Undo", lambda *_: self._undo())
        self.redo_button = button("Redo", lambda *_: self._redo())
        toolbar.append(self.undo_button)
        toolbar.append(self.redo_button)
        toolbar.append(button("−", lambda *_: self._zoom(-.2)))
        self.zoom_label = label("125%")
        toolbar.append(self.zoom_label)
        toolbar.append(button("+", lambda *_: self._zoom(.2)))

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        body.set_vexpand(True)
        root.append(body)

        self.pages_revealer = Gtk.Revealer()
        self.pages_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_RIGHT)
        self.pages_revealer.set_reveal_child(False)
        body.append(self.pages_revealer)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        left.add_css_class("side-panel")
        left.set_size_request(170, -1)
        self.pages_revealer.set_child(left)
        left.append(label("PAGES", "panel-title"))
        left_scroll = Gtk.ScrolledWindow()
        left_scroll.set_vexpand(True)
        left.set_hexpand(False)
        left.append(left_scroll)
        self.thumbs = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        left_scroll.set_child(self.thumbs)

        self.canvas_scroll = Gtk.ScrolledWindow()
        self.canvas_scroll.add_css_class("canvas-back")
        self.canvas_scroll.set_hexpand(True)
        self.canvas_scroll.set_vexpand(True)
        self.canvas_scroll.set_size_request(140, -1)
        self.canvas_scroll.set_min_content_width(140)
        self.canvas_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.canvas_scroll.set_propagate_natural_width(False)
        body.append(self.canvas_scroll)
        self.canvas_holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.canvas_holder.set_halign(Gtk.Align.CENTER)
        self.canvas_holder.set_valign(Gtk.Align.START)
        self.canvas_holder.set_margin_top(24)
        self.canvas_holder.set_margin_bottom(24)
        self.canvas_scroll.set_child(self.canvas_holder)
        self.overlay = Gtk.Overlay()
        self.canvas_holder.append(self.overlay)
        self.picture = Gtk.Picture()
        self.picture.set_can_shrink(False)
        self.overlay.set_child(self.picture)
        self.markup = Gtk.DrawingArea()
        self.markup.set_draw_func(self._draw_overlay)
        self.overlay.add_overlay(self.markup)
        click = Gtk.GestureClick()
        click.set_button(1)
        click.connect("pressed", self._on_canvas_click)
        self.markup.add_controller(click)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        right.add_css_class("side-panel")
        right.set_size_request(290, -1)
        body.append(right)
        right.append(label("INSPECTOR", "panel-title"))
        right_scroll = Gtk.ScrolledWindow()
        right_scroll.set_vexpand(True)
        right.append(right_scroll)
        self.inspector = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        right_scroll.set_child(self.inspector)

        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        status_box.add_css_class("statusbar")
        root.append(status_box)
        self.status = label("Ready", "muted")
        status_box.append(self.status)
        self.page_status = label("")
        self.page_status.set_hexpand(True)
        self.page_status.set_xalign(1)
        status_box.append(self.page_status)

    def _setup_actions(self):
        for name, method, shortcut in [
            ("open", self._choose_open, "<Primary>o"),
            ("save", self._save, "<Primary>s"),
            ("save-as", self._choose_save_as, "<Primary><Shift>s"),
            ("undo", self._undo, "<Primary>z"),
            ("redo", self._redo, "<Primary><Shift>z"),
            ("extract-pages", self._extract_pages_dialog, None),
            ("extract-text", self._choose_extract_text, None),
            ("delete-page", self._delete_page, None),
            ("searchable", self._make_searchable, None),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _action, _param, fn=method: fn())
            self.add_action(action)
            if shortcut:
                self.set_accels_for_action(f"app.{name}", [shortcut])

    def _toggle_pages(self):
        self.pages_revealer.set_reveal_child(not self.pages_revealer.get_reveal_child())

    def _step_page(self, delta: int):
        index = max(0, min(self.page_index + delta, self.project.page_count - 1))
        if index != self.page_index:
            self._select_page(index)

    def _message(self, message: str, *, error: bool = False):
        self.status.set_text(message)
        if error:
            dialog = Gtk.AlertDialog()
            dialog.set_message("Folio PDF")
            dialog.set_detail(message)
            dialog.show(self.window)

    def _run(self, fn, success: str, *, pages: bool = False):
        try:
            result = fn()
            self.selected = None
            self.ocr_mode = False
            self.refresh(pages=pages)
            self._message(success)
            return result
        except Exception as exc:
            self._message(str(exc), error=True)
            return None

    def refresh(self, *, pages: bool = False):
        self.page_index = min(self.page_index, self.project.page_count - 1)
        try:
            self.items = self.project.items(self.page_index, ocr=self.ocr_mode)
            if self.ocr_mode:
                self.items.extend(item for item in self.project.items(self.page_index) if item.kind == "image")
            data, width, height = self.project.render(self.page_index, self.scale)
            texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
            self.picture.set_paintable(texture)
            self.picture.set_size_request(width, height)
            self.markup.set_size_request(width, height)
            self.markup.set_content_width(width)
            self.markup.set_content_height(height)
            self.overlay.set_size_request(width, height)
            self.markup.queue_draw()
            if pages:
                self._refresh_thumbs()
            else:
                self._highlight_thumb()
            self._refresh_inspector()
            self.undo_button.set_sensitive(self.project.can_undo)
            self.redo_button.set_sensitive(self.project.can_redo)
            self.zoom_label.set_text(f"{round(self.scale * 100)}%")
            self.page_status.set_text(f"Page {self.page_index + 1} of {self.project.page_count}")
            filename = self.project.path.name if self.project.path else "Untitled"
            self.window.set_title(f"Folio PDF · {filename}{' •' if self.project.dirty else ''}")
        except Exception as exc:
            self._message(str(exc), error=True)

    def _refresh_thumbs(self):
        clear_box(self.thumbs)
        for index in range(self.project.page_count):
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            data, _, _ = self.project.render(index, .23)
            texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
            preview = Gtk.Picture.new_for_paintable(texture)
            preview.set_can_shrink(True)
            preview.set_size_request(135, 170)
            outer.append(preview)
            number = Gtk.Label(label=f"{index + 1:02d}")
            outer.append(number)
            item_button = Gtk.Button()
            item_button.add_css_class("thumb")
            item_button.set_child(outer)
            item_button.connect("clicked", lambda _b, i=index: self._select_page(i))
            self.thumbs.append(item_button)
        self._highlight_thumb()

    def _highlight_thumb(self):
        child = self.thumbs.get_first_child()
        index = 0
        while child:
            if index == self.page_index:
                child.add_css_class("selected")
            else:
                child.remove_css_class("selected")
            child = child.get_next_sibling()
            index += 1

    def _select_page(self, index: int):
        self.page_index = index
        self.selected = None
        self.ocr_mode = False
        self.click_point = (50, 50)
        self.refresh()

    def _draw_overlay(self, area, cr: cairo.Context, width, height):
        if self.selected is None:
            return
        x0, y0, x1, y1 = self.selected.rect
        cr.set_source_rgba(.98, .55, .2, .16)
        cr.rectangle(x0 * self.scale, y0 * self.scale, (x1 - x0) * self.scale,
                     (y1 - y0) * self.scale)
        cr.fill_preserve()
        cr.set_source_rgba(.98, .55, .2, .95)
        cr.set_line_width(2)
        cr.stroke()

    def _on_canvas_click(self, gesture, n_press, x, y):
        px, py = x / self.scale, y / self.scale
        self.click_point = (px, py)
        matches = [item for item in self.items if item.rect[0] <= px <= item.rect[2]
                   and item.rect[1] <= py <= item.rect[3]]
        shift = bool(gesture.get_current_event_state() & Gdk.ModifierType.SHIFT_MASK)
        if shift:
            candidates = [item for item in matches if item.kind == "text" and not item.word]
        else:
            candidates = [item for item in matches if item.word]
        candidates = candidates or matches
        self.selected = min(candidates, key=lambda it: (it.rect[2] - it.rect[0]) * (it.rect[3] - it.rect[1])) if candidates else None
        self.markup.queue_draw()
        self._refresh_inspector()

    def _text_view(self, content: str = "", height: int = 120) -> Gtk.TextView:
        view = Gtk.TextView()
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        view.set_size_request(-1, height)
        view.get_buffer().set_text(content)
        return view

    @staticmethod
    def _view_text(view: Gtk.TextView) -> str:
        buffer = view.get_buffer()
        return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)

    def _geometry_controls(self, item: PageItem):
        page_width, page_height = self.project.page_size(self.page_index)
        x0, y0, x1, y1 = item.rect
        self.inspector.append(label("POSITION / SIZE  ·  PT", "panel-title"))
        grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        self.geometry = {}
        for index, (name, value, maximum) in enumerate([
            ("X", x0, page_width), ("Y", y0, page_height),
            ("Width", x1 - x0, page_width), ("Height", y1 - y0, page_height),
        ]):
            spin = Gtk.SpinButton.new_with_range(0 if index < 2 else .1, math.ceil(maximum), .1)
            spin.set_digits(2)
            spin.set_value(max(0, value))
            spin.set_hexpand(True)
            grid.attach(label(name, "muted"), index % 2, (index // 2) * 2, 1, 1)
            grid.attach(spin, index % 2, (index // 2) * 2 + 1, 1, 1)
            self.geometry[name] = spin
        self.inspector.append(grid)

    def _geometry_rect(self) -> tuple[float, float, float, float]:
        x = self.geometry["X"].get_value()
        y = self.geometry["Y"].get_value()
        width = self.geometry["Width"].get_value()
        height = self.geometry["Height"].get_value()
        page_width, page_height = self.project.page_size(self.page_index)
        if x + width > page_width + .01 or y + height > page_height + .01:
            raise ValueError("Keep the block inside the page. Reduce its position or size.")
        return (x, y, x + width, y + height)

    def _refresh_inspector(self):
        clear_box(self.inspector)
        selected = self.selected
        if selected is None:
            self.inspector.append(label("Click a word or picture to edit it. Shift-click text to select its whole block. Click empty space to set a placement point.",
                                        "muted", wrap=True))
            x, y = self.click_point
            self.inspector.append(label(f"Placement point  {round(x)} × {round(y)} pt", "muted"))
            self.inspector.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
            self.inspector.append(label("ADD TEXT", "panel-title"))
            self.add_text_view = self._text_view(height=135)
            self.inspector.append(self.add_text_view)
            self.add_font = Gtk.SpinButton.new_with_range(6, 72, 1)
            self.add_font.set_value(12)
            self.inspector.append(label("Font size"))
            self.inspector.append(self.add_font)
            self.inspector.append(button("Place text", lambda *_: self._add_text(), "suggested-action"))
            self.inspector.append(button("Place picture…", lambda *_: self._choose_add_image()))
            self.inspector.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
            self.inspector.append(label("Tip: Save As keeps your original PDF available.",
                                        "muted", wrap=True))
        elif selected.kind == "text":
            self.inspector.append(label("WORD" if selected.word else "TEXT BLOCK", "panel-title"))
            if selected.ocr:
                self.inspector.append(label("Recognized from this page. Applying an edit covers the original area and adds new text.",
                                            "muted", wrap=True))
            self.edit_text_view = self._text_view(selected.text, 210)
            self.inspector.append(self.edit_text_view)
            self.edit_font = Gtk.SpinButton.new_with_range(6, 72, 1)
            self.edit_font.set_value(min(72, max(6, selected.font_size)))
            self.inspector.append(label("Font size"))
            self.inspector.append(self.edit_font)
            self._geometry_controls(selected)
            self.inspector.append(button("Apply change", lambda *_: self._apply_text(), "suggested-action"))
            self.inspector.append(button("Remove text", lambda *_: self._remove_text(), "destructive-action"))
            self.inspector.append(label("Original fonts and complex layouts may look different after editing.",
                                        "muted", wrap=True))
        else:
            self.inspector.append(label("PICTURE", "panel-title"))
            self.inspector.append(label(f"{round(selected.rect[2]-selected.rect[0])} × {round(selected.rect[3]-selected.rect[1])} pt",
                                        "muted"))
            self._geometry_controls(selected)
            self.inspector.append(button("Apply position / size", lambda *_: self._move_image(), "suggested-action"))
            self.inspector.append(button("Replace picture…", lambda *_: self._choose_replace_image(), "suggested-action"))
            self.inspector.append(button("Extract picture…", lambda *_: self._choose_extract_image()))
            self.inspector.append(button("Remove picture", lambda *_: self._remove_image(), "destructive-action"))
            self.inspector.append(label("Replacement keeps the selected picture's page area.", "muted", wrap=True))

    def _dialog(self, title: str, action: Gtk.FileChooserAction, accept: str, callback,
                suggested: str | None = None, patterns: tuple[str, ...] = ()):
        chooser = Gtk.FileChooserNative.new(title, self.window, action, accept, "Cancel")
        if suggested:
            chooser.set_current_name(suggested)
        if patterns:
            filter_ = Gtk.FileFilter()
            filter_.set_name("Supported files")
            for pattern in patterns:
                filter_.add_pattern(pattern)
            chooser.add_filter(filter_)
        def response(dialog, code):
            if code == Gtk.ResponseType.ACCEPT:
                file = dialog.get_file()
                if file:
                    callback(file.get_path())
            dialog.destroy()
        chooser.connect("response", response)
        chooser.show()

    def _confirm_discard(self, callback):
        if not self.project.dirty:
            callback()
            return
        dialog = Gtk.MessageDialog(transient_for=self.window, modal=True,
                                   buttons=Gtk.ButtonsType.NONE,
                                   text="Discard unsaved changes?")
        dialog.format_secondary_text("Save this document first if you want to keep your edits.")
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Discard", Gtk.ResponseType.ACCEPT)
        dialog.connect("response", lambda d, r: (d.destroy(), callback() if r == Gtk.ResponseType.ACCEPT else None))
        dialog.show()

    def _choose_open(self):
        self._confirm_discard(lambda: self._dialog("Open PDF", Gtk.FileChooserAction.OPEN, "Open",
                                                   self._open_path, patterns=("*.pdf", "*.PDF")))

    def _open_path(self, path: str):
        try:
            new_project = PdfProject(path)
            old = self.project
            self.project = new_project
            old.close()
            self.page_index = 0
            self.selected = None
            self.ocr_mode = False
            self.refresh(pages=True)
            self._message(f"Opened {Path(path).name}")
        except Exception as exc:
            self._message(str(exc), error=True)

    def _save(self):
        if self.project.path is None:
            self._choose_save_as()
            return
        try:
            path = self.project.save()
            self.refresh()
            self._message(f"Saved {path.name}")
        except Exception as exc:
            self._message(str(exc), error=True)

    def _choose_save_as(self):
        suggested = self.project.path.name if self.project.path else "Untitled.pdf"
        self._dialog("Save PDF As", Gtk.FileChooserAction.SAVE, "Save",
                     lambda p: self._save_to(p), suggested)

    def _save_to(self, path: str):
        try:
            saved = self.project.save(path)
            self.refresh()
            self._message(f"Saved {saved.name}")
        except Exception as exc:
            self._message(str(exc), error=True)

    def _choose_insert_pdf(self):
        self._dialog("Insert PDF", Gtk.FileChooserAction.OPEN, "Insert",
                     lambda p: self._insert_pdf(p), patterns=("*.pdf", "*.PDF"))

    def _insert_pdf(self, path: str):
        count = self._run(lambda: self.project.insert_pdf(self.page_index, path),
                          f"Inserted pages from {Path(path).name}", pages=True)
        if count:
            self.page_index = min(self.page_index + 1, self.project.page_count - 1)
            self.refresh()

    def _add_blank(self):
        pos = self._run(lambda: self.project.insert_blank(self.page_index), "Added a blank page", pages=True)
        if pos is not None:
            self.page_index = pos
            self.refresh()

    def _start_feeder_scan(self):
        if self._scanning:
            return
        self._scanning = True
        self.scan_button.set_sensitive(False)
        self._message("Scanning Letter page from HP feeder…")

        def scan():
            try:
                image = scan_feeder_page()
            except Exception as exc:
                GLib.idle_add(self._finish_feeder_scan, None, str(exc))
            else:
                GLib.idle_add(self._finish_feeder_scan, image, None)

        threading.Thread(target=scan, daemon=True).start()

    def _finish_feeder_scan(self, image: bytes | None, error: str | None):
        self._scanning = False
        self.scan_button.set_sensitive(True)
        if error:
            self._message(error, error=True)
            return False
        pos = self._run(lambda: self.project.insert_scanned_page(self.page_index, image),
                        "Scanned a Letter page. Save the PDF to keep it.", pages=True)
        if pos is not None:
            self.page_index = pos
            self.refresh(pages=True)
        return False

    def _delete_page(self):
        self._run(lambda: self.project.delete_page(self.page_index), "Deleted page", pages=True)

    def _extract_pages_dialog(self):
        dialog = Gtk.Dialog(title="Extract pages", transient_for=self.window, modal=True)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Extract…", Gtk.ResponseType.ACCEPT)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(14); box.set_margin_bottom(14)
        box.set_margin_start(14); box.set_margin_end(14)
        box.append(label("Page range (inclusive)"))
        first = Gtk.SpinButton.new_with_range(1, self.project.page_count, 1)
        last = Gtk.SpinButton.new_with_range(1, self.project.page_count, 1)
        first.set_value(self.page_index + 1)
        last.set_value(self.page_index + 1)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.append(label("From")); row.append(first); row.append(label("to")); row.append(last)
        box.append(row)
        def response(d, code):
            a, b = first.get_value_as_int(), last.get_value_as_int()
            d.destroy()
            if code == Gtk.ResponseType.ACCEPT:
                if a > b:
                    self._message("The first page must be before the last page.", error=True)
                    return
                self._dialog("Save extracted pages", Gtk.FileChooserAction.SAVE, "Save",
                             lambda p: self._extract_pages(a - 1, b - 1, p),
                             f"pages-{a}-{b}.pdf")
        dialog.connect("response", response)
        dialog.show()

    def _extract_pages(self, a, b, path):
        try:
            output = self.project.extract_pages(a, b, path)
            self._message(f"Extracted pages to {output.name}")
        except Exception as exc:
            self._message(str(exc), error=True)

    def _choose_extract_text(self):
        self._dialog("Extract all text", Gtk.FileChooserAction.SAVE, "Export",
                     self._extract_text, "document-text.txt")

    def _extract_text(self, path):
        try:
            output = self.project.extract_text(path)
            self._message(f"Extracted text to {output.name}")
        except Exception as exc:
            self._message(str(exc), error=True)

    def _scan_page(self):
        if self.ocr_mode:
            self.ocr_mode = False
            self.selected = None
            self.refresh()
            self._message("Returned to normal page view")
            return
        self._message("Scanning page…")
        context = GLib.MainContext.default()
        while context.pending():
            context.iteration(False)
        try:
            self.ocr_mode = True
            self.selected = None
            self.refresh()
            count = sum(item.kind == "text" for item in self.items)
            self._message(f"OCR found {count} text blocks on this page")
        except Exception as exc:
            self.ocr_mode = False
            self._message(str(exc), error=True)

    def _make_searchable(self):
        count = self._run(lambda: self.project.make_searchable(self.page_index),
                          "Added a searchable OCR text layer")
        if count == 0:
            self._message("No words were found on this page")

    def _add_text(self):
        value = self._view_text(self.add_text_view)
        x, y = self.click_point
        w, h = self.project.page_size(self.page_index)
        x = min(max(x, 0), w - 30); y = min(max(y, 0), h - 25)
        rect = (x, y, min(x + 300, w - 5), min(y + 130, h - 5))
        self._run(lambda: self.project.add_text(self.page_index, rect, value, self.add_font.get_value()),
                  "Added text")

    def _apply_text(self):
        item = self.selected
        if item is None:
            return
        value = self._view_text(self.edit_text_view)
        self._run(lambda: self.project.replace_text(self.page_index, item.rect, value,
                                                     self.edit_font.get_value(), item.color,
                                                     self._geometry_rect(), item.baseline if item.word else None),
                  "Updated text")

    def _remove_text(self):
        item = self.selected
        if item:
            self._run(lambda: self.project.replace_text(self.page_index, item.rect, ""), "Removed text")

    def _choose_add_image(self):
        self._dialog("Place picture", Gtk.FileChooserAction.OPEN, "Place",
                     self._add_image, patterns=("*.png", "*.jpg", "*.jpeg", "*.webp", "*.bmp"))

    def _add_image(self, path):
        x, y = self.click_point
        w, h = self.project.page_size(self.page_index)
        x = min(max(x, 0), w - 30); y = min(max(y, 0), h - 30)
        rect = (x, y, min(x + 260, w - 5), min(y + 185, h - 5))
        self._run(lambda: self.project.add_image(self.page_index, rect, path), "Placed picture")

    def _choose_replace_image(self):
        item = self.selected
        if item:
            self._dialog("Replace picture", Gtk.FileChooserAction.OPEN, "Replace",
                         lambda p: self._run(lambda: self.project.replace_image(self.page_index, item.rect, p,
                                                                                 self._geometry_rect()),
                                              "Replaced picture"),
                         patterns=("*.png", "*.jpg", "*.jpeg", "*.webp", "*.bmp"))

    def _move_image(self):
        item = self.selected
        if item:
            self._run(lambda: self.project.replace_image(self.page_index, item.rect, None,
                                                          self._geometry_rect(), item.image),
                      "Moved or resized picture")

    def _remove_image(self):
        item = self.selected
        if item:
            self._run(lambda: self.project.replace_image(self.page_index, item.rect, None), "Removed picture")

    def _choose_extract_image(self):
        item = self.selected
        if item:
            extension = item.extension if item.extension in ("png", "jpg", "jpeg", "webp", "bmp", "tiff") else "png"
            self._dialog("Extract picture", Gtk.FileChooserAction.SAVE, "Export",
                         lambda p: self._extract_image(item, p),
                         f"page-{self.page_index + 1}-picture.{extension}")

    def _extract_image(self, item: PageItem, path: str):
        try:
            Path(path).write_bytes(item.image)
            self._message(f"Extracted picture to {Path(path).name}")
        except Exception as exc:
            self._message(str(exc), error=True)

    def _zoom(self, change):
        self.scale = max(.5, min(3.0, round(self.scale + change, 2)))
        self.refresh()

    def _undo(self):
        if self.project.undo():
            self.selected = None
            self.ocr_mode = False
            self.refresh(pages=True)
            self._message("Undid last change")

    def _redo(self):
        if self.project.redo():
            self.selected = None
            self.ocr_mode = False
            self.refresh(pages=True)
            self._message("Redid change")

    def _on_close_request(self, *_):
        if self._scanning:
            self._message("Wait for the scanner to finish before closing Folio PDF.")
            return True
        if self._closing or not self.project.dirty:
            self.project.close()
            return False
        self._confirm_discard(self._close_after_confirm)
        return True

    def _close_after_confirm(self):
        self._closing = True
        self.window.close()


if __name__ == "__main__":
    app = Folio()
    raise SystemExit(app.run(sys.argv))
