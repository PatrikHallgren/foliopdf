# Folio PDF

A native GTK 4 PDF editor styled from the active Omarchy theme. It runs locally and keeps document content on your machine.

## Launch

The app targets Omarchy and other Arch Linux desktops with GTK 4, Python 3.11+, Python GObject/Cairo, and Tesseract. Run `./run.sh` from this folder, or pass a PDF path: `./run.sh /path/to/file.pdf`. On first launch, the script installs PyMuPDF into a user cache. A wheel bundled with a local copy works offline; the GitHub source downloads PyMuPDF from PyPI and needs internet once.

Run `./install-desktop.sh` from a permanent checkout to add Folio PDF to the desktop launcher. The launcher points to that checkout, so keep it in place.

## Edit

- Click a word or number to change, remove, move, or resize only that text. Shift-click text to select its whole block.
- Click a picture to replace, extract, remove, move, or resize it.
- Click a blank spot to place new text or a picture.
- Use `+ Page` or `+ PDF` to insert pages. `More` contains page extraction, text extraction, and page deletion.
- Use `Scan OCR` to recognize text on a scanned page. `More → Make page searchable` adds an invisible selectable text layer to an image-only page. Exported text uses OCR automatically when a page has no embedded text.
- Use `Save As` before modifying an important original. Undo and redo keep the most recent 20 changes during the session.

The app edits text blocks by replacing their area. Replacement text uses Noto Sans and a white patch, so complex typography, transparency, and layered designs can look different. Picture edits target raster images; vector drawings are outside the picture tools. Password-protected PDFs and signed-document preservation are not implemented.

## Testing

Run `python -m unittest discover -s tests` in the environment created by `run.sh` to check the PDF editing operations.

## License

Folio PDF is licensed under AGPL-3.0-only. It uses [PyMuPDF](https://pymupdf.readthedocs.io/en/latest/about.html), which is available under the GNU AGPL v3 or a separate commercial license. The GitHub repository contains application source, not PyMuPDF binaries. A local bundle may include an unmodified PyMuPDF wheel with its own notices.
