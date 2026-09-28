"""Signature persistence, geometry, and preservation of existing PDF content."""
import tempfile
import unittest
from pathlib import Path

import pymupdf as fitz

from pdf_model import PdfProject


INK = [[(10, 20), (30, 0), (50, 40), (80, 10)], [(90, 30), (120, 30)], [(130, 5)]]


class SignatureTests(unittest.TestCase):
    def test_signature_preserves_content_and_round_trips_with_undo(self):
        project = PdfProject()
        self.addCleanup(project.close)
        page = project.doc[0]
        page.insert_text((70, 105), "Keep this text")
        page.draw_rect((50, 50, 300, 200), color=(1, 0, 0), fill=(1, .8, .8))
        before = project.render(0)[0]
        project.add_signature(0, (80, 80, 260, 160), INK)
        after = project.render(0)[0]
        self.assertNotEqual(before, after)
        self.assertEqual(project.doc[0].get_text().strip(), "Keep this text")
        self.assertEqual(len(project.doc[0].get_drawings()), 4)
        self.assertTrue(project.dirty)
        self.assertTrue(project.undo())
        self.assertEqual(project.render(0)[0], before)
        self.assertTrue(project.redo())
        self.assertEqual(project.render(0)[0], after)
        with tempfile.TemporaryDirectory() as folder:
            path = project.save(str(Path(folder) / "signed.pdf"))
            reopened = PdfProject(str(path))
            try:
                self.assertEqual(reopened.render(0)[0], after)
            finally:
                reopened.close()

    def test_rotated_cropped_pages_keep_ink_inside_displayed_destination(self):
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation):
                project = PdfProject()
                try:
                    page = project.doc[0]
                    page.set_cropbox(fitz.Rect(20, 30, 550, 800))
                    page.set_rotation(rotation)
                    destination = fitz.Rect(page.rect.width - 100, page.rect.height - 50,
                                            page.rect.width, page.rect.height)
                    project.add_signature(0, destination, INK)
                    page = project.doc[0]
                    for drawing in page.get_drawings():
                        bounds = drawing['rect'] * page.rotation_matrix
                        self.assertTrue(destination.contains(bounds), (rotation, bounds))
                    self.assertTrue(project.doc[0].get_drawings())
                finally:
                    project.close()

    def test_invalid_signatures_do_not_change_document_or_history(self):
        for rect, ink in [((0, 0, 100, 100), []),
                          ((0, 0, 100, 100), [[(1, 1)]]),
                          ((-1, 0, 100, 100), INK),
                          ((0, 0, 1000, 1000), INK),
                          ((0, 0, 0, 0), INK),
                          ((0, 0, 100, 100), [[(0, 0), (float('nan'), 1)]]),
                          ((0, 0, float('inf'), 100), INK)]:
            with self.subTest(rect=rect, ink=ink):
                project = PdfProject()
                try:
                    before = project.render(0)[0]
                    with self.assertRaises(ValueError):
                        project.add_signature(0, rect, ink)
                    self.assertFalse(project.dirty)
                    self.assertFalse(project.can_undo)
                    self.assertEqual(before, project.render(0)[0])
                finally:
                    project.close()


if __name__ == '__main__':
    unittest.main()
