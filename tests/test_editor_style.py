import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from editor_style import FALLBACK, fit_scale, omarchy_colors


class EditorStyleTests(unittest.TestCase):
    def test_fit_portrait_and_landscape_in_small_and_large_windows(self):
        for page in ((595, 842), (842, 595)):
            for viewport in ((420, 500), (1600, 1100)):
                scale = fit_scale(page, viewport)
                self.assertLessEqual(page[0] * scale, viewport[0] - 40 + .001)
                self.assertLessEqual(page[1] * scale, viewport[1] - 40 + .001)
                self.assertAlmostEqual(max(page[0] * scale / (viewport[0] - 40),
                                           page[1] * scale / (viewport[1] - 40)), 1)

    def test_width_mode_fills_width(self):
        self.assertAlmostEqual(fit_scale((595, 842), (1200, 700), 'width') * 595, 1160)

    def test_active_palette_and_live_reload(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            root = Path(directory)
            palette = root / '.local/state/omarchy/current/theme/colors.toml'
            palette.parent.mkdir(parents=True)
            palette.write_text('accent = "#123456"\nbackground = "invalid"\nmode = "light"')
            colors = omarchy_colors(root)
            self.assertEqual(colors['accent'], '#123456')
            self.assertEqual(colors['background'], FALLBACK['background'])
            self.assertEqual(colors['mode'], 'light')
            palette.write_text('accent = "#abcdef"')
            self.assertEqual(omarchy_colors(root)['accent'], '#abcdef')
            palette.write_text('broken = [')
            self.assertEqual(omarchy_colors(root), FALLBACK)

    def test_legacy_palette(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            root = Path(directory)
            palette = root / '.config/omarchy/current/theme/colors.toml'
            palette.parent.mkdir(parents=True)
            palette.write_text('accent = "#abcdef"')
            self.assertEqual(omarchy_colors(root)['accent'], '#abcdef')
