import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.language import language_instruction, ocr_languages, response_language
from app.document_extract import extract_sections


class LanguageTests(unittest.TestCase):
    def test_auto_detects_hindi_and_rejects_unsupported_scripts(self):
        self.assertEqual(response_language("राजस्व कितना था?"), "hi")
        self.assertEqual(response_language("¿Cuáles son los ingresos?", "es"), "es")
        self.assertIn("Spanish", language_instruction("Revenue?", "es"))
        with self.assertRaisesRegex(ValueError, "not supported"):
            response_language("收入是多少？")

    def test_ocr_setting_is_bounded_to_installed_languages(self):
        with patch.dict("os.environ", {"RAG_OCR_LANGUAGES": "en,hi"}):
            self.assertEqual(ocr_languages(), ["eng", "hin"])
        with patch.dict("os.environ", {"RAG_OCR_LANGUAGES": "en,xx"}):
            with self.assertRaises(ValueError):
                ocr_languages()

    def test_hindi_html_text_survives_extraction(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "hindi.html"
            path.write_text("<h1>परिणाम</h1><p>राजस्व 42 लाख था।</p>", encoding="utf-8")
            sections = extract_sections(str(path), "html")
            self.assertIn("राजस्व", sections[0].text)
            self.assertEqual(sections[0].metadata.section_title, "परिणाम")
