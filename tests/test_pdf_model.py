"""Regression checks for editing dense PDF rows."""

import tempfile
import unittest
from pathlib import Path

import pymupdf

from pdf_model import PdfProject


class TextEditingTests(unittest.TestCase):
    def test_edit_one_number_in_grouped_row(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "invoice.pdf"
            doc = pymupdf.open()
            page = doc.new_page(width=620, height=420)
            for x, value in ((216, "1"), (270, "0.00"), (540, "0.00")):
                page.insert_text((x, 340), value, fontsize=9)
            doc.save(source)
            doc.close()

            project = PdfProject(str(source))
            items = project.items(0)
            self.assertTrue(any(item.text == "1\n0.00\n0.00" for item in items))
            quantity = next(item for item in items if item.word and item.text == "1")
            project.replace_text(0, quantity.rect, "2", quantity.font_size,
                                 quantity.color, quantity.rect, quantity.baseline)
            self.assertEqual(sorted(word[4] for word in project.doc[0].get_text("words")),
                             ["0.00", "0.00", "2"])
            project.undo()
            self.assertIn("1", [word[4] for word in project.doc[0].get_text("words")])
            project.redo()
            saved = project.save(str(Path(directory) / "edited.pdf"))
            project.close()

            reopened = pymupdf.open(saved)
            self.assertEqual(sorted(word[4] for word in reopened[0].get_text("words")),
                             ["0.00", "0.00", "2"])
            reopened.close()


if __name__ == "__main__":
    unittest.main()
