import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_pdf_minus", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PdfMinusTests(unittest.TestCase):
    """M91. The PDF export must not hand U+2212 MINUS SIGN to the renderer.

    The regular print font (Noto Serif) has no glyph for it, so the chapter
    XHTML handed to the renderer uses U+2013 EN DASH instead.
    """

    def setUp(self):
        self.bf = load_module()

    def test_a_minus_sign_becomes_an_en_dash(self):
        self.assertEqual(self.bf._print_safe("a −18 b"), "a –18 b")

    def test_text_without_a_minus_sign_is_unchanged(self):
        text = "a -18 b — c… €"
        self.assertEqual(self.bf._print_safe(text), text)

    def test_markdown_xhtml_has_no_minus_sign_after_print_safe(self):
        rendered = self.bf._print_safe(self.bf._markdown_xhtml("Drop: −18 GPU"))
        self.assertNotIn("−", rendered)
        self.assertIn("–18", rendered)


if __name__ == "__main__":
    unittest.main()
