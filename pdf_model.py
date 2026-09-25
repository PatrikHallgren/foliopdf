"""PDF editing operations for Folio PDF. Coordinates are PDF points."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import tempfile

import pymupdf as fitz


@dataclass(frozen=True)
class PageItem:
    kind: str
    rect: tuple[float, float, float, float]
    text: str = ""
    image: bytes = b""
    extension: str = "png"
    font_size: float = 11.0
    color: tuple[float, float, float] = (0, 0, 0)
    ocr: bool = False
    word: bool = False
    baseline: float | None = None


def _rgb(value: int) -> tuple[float, float, float]:
    return ((value >> 16 & 255) / 255, (value >> 8 & 255) / 255, (value & 255) / 255)


class PdfProject:
    def __init__(self, path: str | None = None):
        self.doc = fitz.open(path) if path else fitz.open()
        if self.doc.needs_pass:
            self.doc.close()
            raise ValueError("Password-protected PDFs are not supported yet.")
        self.path = Path(path) if path else None
        self.dirty = False
        self._undo: list[bytes] = []
        self._redo: list[bytes] = []
        if not path:
            self.doc.new_page(width=595, height=842)

    @property
    def page_count(self) -> int:
        return len(self.doc)

    def close(self) -> None:
        self.doc.close()

    def _snapshot(self) -> bytes:
        return self.doc.tobytes(garbage=4, deflate=True)

    def _change(self, operation) -> None:
        before = self._snapshot()
        try:
            operation()
        except Exception:
            self.doc.close()
            self.doc = fitz.open(stream=before, filetype="pdf")
            raise
        self._undo.append(before)
        self._undo = self._undo[-20:]
        self._redo.clear()
        self.dirty = True

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._snapshot())
        self.doc.close()
        self.doc = fitz.open(stream=self._undo.pop(), filetype="pdf")
        self.dirty = True
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._snapshot())
        self.doc.close()
        self.doc = fitz.open(stream=self._redo.pop(), filetype="pdf")
        self.dirty = True
        return True

    def save(self, path: str | None = None) -> Path:
        destination = Path(path) if path else self.path
        if destination is None:
            raise ValueError("Choose a destination first.")
        destination = destination.expanduser().resolve()
        if destination.suffix.lower() != ".pdf":
            destination = destination.with_suffix(".pdf")
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".folio-", suffix=".pdf", dir=destination.parent)
        os.close(fd)
        try:
            self.doc.save(temporary, garbage=4, deflate=True)
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self.path = destination
        self.dirty = False
        return destination

    def render(self, page_index: int, scale: float = 1.5) -> tuple[bytes, int, int]:
        pix = self.doc[page_index].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        return pix.tobytes("png"), pix.width, pix.height

    def page_size(self, page_index: int) -> tuple[float, float]:
        rect = self.doc[page_index].rect
        return rect.width, rect.height

    def items(self, page_index: int, *, ocr: bool = False) -> list[PageItem]:
        page = self.doc[page_index]
        textpage = page.get_textpage_ocr(language="eng", dpi=150, full=True) if ocr else None
        content = page.get_text("dict", textpage=textpage) if textpage else page.get_text("dict")
        result: list[PageItem] = []
        for block in content["blocks"]:
            rect = tuple(float(v) for v in block["bbox"])
            if block["type"] == 0:
                lines = []
                spans = []
                for line in block.get("lines", []):
                    parts = line.get("spans", [])
                    lines.append("".join(s.get("text", "") for s in parts))
                    spans.extend(parts)
                value = "\n".join(lines).strip()
                if value:
                    lead = spans[0] if spans else {}
                    result.append(PageItem("text", rect, value, font_size=float(lead.get("size", 11)), color=_rgb(int(lead.get("color", 0))), ocr=ocr))
            elif block["type"] == 1 and not ocr:
                result.append(PageItem("image", rect, image=block.get("image", b""), extension=block.get("ext", "png")))
        # MuPDF can merge distant cells on one row into a single text block.
        # Keep the blocks for Shift-click, and expose individual words for precise edits.
        for x0, y0, x1, y1, value, block_no, line_no, _ in page.get_text("words", textpage=textpage):
            if not value.strip():
                continue
            spans = []
            try:
                spans = content["blocks"][block_no]["lines"][line_no]["spans"]
            except (IndexError, KeyError, TypeError):
                pass
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            def distance(span):
                sx0, sy0, sx1, sy1 = span["bbox"]
                return max(sx0 - cx, 0, cx - sx1) ** 2 + max(sy0 - cy, 0, cy - sy1) ** 2
            span = min(spans, key=distance) if spans else {}
            baseline = float(span.get("origin", (x0, y1))[1])
            result.append(PageItem("text", (x0, y0, x1, y1), value,
                                   font_size=float(span.get("size", 11)),
                                   color=_rgb(int(span.get("color", 0))),
                                   ocr=ocr, word=True, baseline=baseline))
        return result

    def replace_text(self, page_index: int, rect: tuple[float, float, float, float], text: str,
                     font_size: float = 11, color: tuple[float, float, float] = (0, 0, 0),
                     new_rect: tuple[float, float, float, float] | None = None,
                     baseline: float | None = None) -> None:
        def edit():
            page = self.doc[page_index]
            area = fitz.Rect(rect)
            page.add_redact_annot(area, fill=(1, 1, 1), cross_out=False)
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                                  graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                                  text=fitz.PDF_REDACT_TEXT_REMOVE)
            if text.strip():
                destination = fitz.Rect(new_rect or rect)
                if baseline is not None and "\n" not in text:
                    self._write_word(page, area, destination, text, font_size, color, baseline)
                else:
                    self._write_text(page, destination, text, font_size, color)
        self._change(edit)

    @staticmethod
    def _write_word(page, source, destination, value, size, color, baseline) -> None:
        if destination.is_empty or destination.is_infinite:
            raise ValueError("The text area has no usable size.")
        fontfile = Path("/usr/share/fonts/noto/NotoSans-Regular.ttf")
        if fontfile.exists():
            page.insert_font(fontname="FolioNoto", fontfile=str(fontfile))
            font = fitz.Font(fontfile=str(fontfile))
            name = "FolioNoto"
        else:
            font = fitz.Font("helv")
            name = "helv"
        size = max(6, min(float(size), 72))
        width = font.text_length(value, fontsize=size)
        allowance = destination.width + 2
        if width > allowance:
            size *= allowance / width
        if size < 6:
            raise ValueError("Text is wider than this word. Increase its width or shorten the text.")
        new_baseline = destination.y0 + (baseline - source.y0)
        new_baseline = min(max(new_baseline, destination.y0 + size * .65), destination.y1)
        page.insert_text((destination.x0, new_baseline), value, fontsize=size,
                         fontname=name, color=color, overlay=True)

    def add_text(self, page_index: int, rect: tuple[float, float, float, float], text: str,
                 font_size: float = 12, color: tuple[float, float, float] = (0, 0, 0)) -> None:
        if not text.strip():
            raise ValueError("Enter some text first.")
        self._change(lambda: self._write_text(self.doc[page_index], fitz.Rect(rect), text, font_size, color))

    @staticmethod
    def _write_text(page, rect, value, size, color) -> None:
        if rect.is_empty or rect.is_infinite:
            raise ValueError("The text area has no usable size.")
        # Noto Sans keeps non-Latin text editable and extractable on Omarchy.
        fontfile = Path("/usr/share/fonts/noto/NotoSans-Regular.ttf")
        if fontfile.exists():
            page.insert_font(fontname="FolioNoto", fontfile=str(fontfile))
            name = "FolioNoto"
        else:
            name = "helv"
        # Try smaller sizes if the replacement is longer than the source block.
        size = max(6, min(float(size), 72))
        for candidate in [size, size * .9, size * .8, size * .7, size * .6, 6]:
            if candidate < 6:
                continue
            remaining = page.insert_textbox(rect, value, fontname=name, fontsize=candidate,
                                            color=color, overlay=True)
            if remaining >= 0:
                return
        raise ValueError("Text does not fit in this area. Shorten it or make the area larger.")

    def add_image(self, page_index: int, rect: tuple[float, float, float, float], image_path: str) -> None:
        if not Path(image_path).is_file():
            raise FileNotFoundError(image_path)
        self._change(lambda: self.doc[page_index].insert_image(fitz.Rect(rect), filename=image_path, keep_proportion=True))

    def replace_image(self, page_index: int, rect: tuple[float, float, float, float], image_path: str | None,
                      new_rect: tuple[float, float, float, float] | None = None,
                      image_bytes: bytes | None = None) -> None:
        if image_path is not None and not Path(image_path).is_file():
            raise FileNotFoundError(image_path)
        def edit():
            page = self.doc[page_index]
            area = fitz.Rect(rect)
            page.add_redact_annot(area, fill=(1, 1, 1), cross_out=False)
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE,
                                  graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                                  text=fitz.PDF_REDACT_TEXT_NONE)
            if image_path or image_bytes:
                destination = fitz.Rect(new_rect or rect)
                if destination.is_empty or destination.is_infinite:
                    raise ValueError("The picture area has no usable size.")
                page.insert_image(destination, filename=image_path, stream=image_bytes,
                                  keep_proportion=True, overlay=True)
        self._change(edit)

    def insert_blank(self, after_index: int, width: float | None = None, height: float | None = None) -> int:
        if width is None or height is None:
            width, height = self.page_size(max(0, after_index))
        position = after_index + 1
        self._change(lambda: self.doc.new_page(pno=position, width=width, height=height))
        return position

    def insert_scanned_page(self, after_index: int, image: bytes) -> int:
        """Place a feeder scan on a Letter page, replacing a pristine first page."""
        if not image.startswith(b"\xff\xd8") or not image.endswith(b"\xff\xd9"):
            raise ValueError("The scanner did not return a complete JPEG image.")
        replace_first = self.path is None and not self.dirty and len(self.doc) == 1
        position = 0 if replace_first else after_index + 1

        def edit():
            if replace_first:
                page = self.doc[0]
                page.set_mediabox(fitz.Rect(0, 0, 612, 792))
            else:
                page = self.doc.new_page(pno=position, width=612, height=792)
            page.insert_image(fitz.Rect(0, 0, 612, 792), stream=image,
                              keep_proportion=False)

        self._change(edit)
        return position

    def insert_pdf(self, after_index: int, path: str) -> int:
        source = fitz.open(path)
        try:
            if source.needs_pass:
                raise ValueError("The inserted PDF is password protected.")
            count = len(source)
            if count == 0:
                raise ValueError("The selected PDF has no pages.")
            self._change(lambda: self.doc.insert_pdf(source, start_at=after_index + 1))
            return count
        finally:
            source.close()

    def delete_page(self, page_index: int) -> None:
        if len(self.doc) <= 1:
            raise ValueError("A PDF needs at least one page.")
        self._change(lambda: self.doc.delete_page(page_index))

    def extract_pages(self, first: int, last: int, path: str) -> Path:
        if first < 0 or last >= len(self.doc) or first > last:
            raise ValueError("Choose a valid page range.")
        output = fitz.open()
        try:
            output.insert_pdf(self.doc, from_page=first, to_page=last)
            destination = Path(path).expanduser().resolve()
            if destination.suffix.lower() != ".pdf":
                destination = destination.with_suffix(".pdf")
            if self.path and destination == self.path.resolve():
                raise ValueError("Choose a different name from the open PDF for extracted pages.")
            output.save(str(destination), garbage=4, deflate=True)
            return destination
        finally:
            output.close()

    def extract_text(self, path: str, *, use_ocr: bool = True) -> Path:
        sections = []
        for index, page in enumerate(self.doc):
            value = page.get_text().strip()
            if not value and use_ocr:
                tp = page.get_textpage_ocr(language="eng", dpi=150, full=True)
                value = page.get_text(textpage=tp).strip()
            sections.append(f"Page {index + 1}\n\n{value}")
        destination = Path(path).expanduser().resolve()
        destination.write_text("\n\n".join(sections) + "\n", encoding="utf-8")
        return destination

    def make_searchable(self, page_index: int) -> int:
        page = self.doc[page_index]
        if page.get_text().strip():
            raise ValueError("This page already has selectable text. Scan page to inspect it without adding another text layer.")
        tp = page.get_textpage_ocr(language="eng", dpi=150, full=True)
        words = page.get_text("words", textpage=tp)
        if not words:
            return 0
        def edit():
            page = self.doc[page_index]
            for x0, y0, x1, y1, word, *_ in words:
                if not word.strip():
                    continue
                size = max(4, min(16, (y1 - y0) * .75))
                page.insert_text((x0, y1), word, fontsize=size, fontname="helv", render_mode=3)
        self._change(edit)
        return len(words)
