"""Checks for the HP feeder transport and scanned PDF pages."""

import struct
import tempfile
import unittest
from pathlib import Path

import pymupdf

from hp_scanner import ScanError, _dime_image
from pdf_model import PdfProject


def dime_record(flags: int, kind: bytes, body: bytes) -> bytes:
    identifier = b"id1"
    header = struct.pack(">BBHHHI", flags, 0x10, 0, len(identifier), len(kind), len(body))
    pad = lambda value: b"\0" * (-len(value) % 4)
    return header + identifier + pad(identifier) + kind + pad(kind) + body + pad(body)


class ScannerTests(unittest.TestCase):
    def test_dime_image_joins_chunks_without_transport_headers(self):
        image = b"\xff\xd8" + b"document data" + b"\xff\xd9"
        payload = (
            dime_record(0x0C, b"text/xml", b"<response/>")
            + dime_record(0x09, b"image/jpeg", image[:8])
            + dime_record(0x0A, b"", image[8:])
        )
        self.assertEqual(_dime_image(payload), image)
        with self.assertRaises(ScanError):
            _dime_image(payload[:-1])

    def test_scanned_page_replaces_initial_blank_and_inserts_next(self):
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 10, 10), False)
        pixmap.clear_with(255)
        jpeg = pixmap.tobytes("jpeg")
        project = PdfProject()
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(project.insert_scanned_page(0, jpeg), 0)
            self.assertEqual(project.page_count, 1)
            self.assertEqual(project.page_size(0), (612.0, 792.0))
            self.assertEqual(project.insert_scanned_page(0, jpeg), 1)
            self.assertEqual(project.page_count, 2)
            output = project.save(str(Path(directory) / "scans.pdf"))
            with pymupdf.open(output) as saved:
                self.assertEqual(len(saved), 2)
                self.assertTrue(all(page.get_images() for page in saved))
        project.close()


if __name__ == "__main__":
    unittest.main()
