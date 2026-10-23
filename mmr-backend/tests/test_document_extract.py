import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from app.document_extract import extract_sections
from app import rag_pipeline


class FormatExtractionTests(unittest.TestCase):
    def _archive(self, root, name, parts):
        path = Path(root) / name
        with zipfile.ZipFile(path, "w") as archive:
            for filename, content in parts.items():
                archive.writestr(filename, content)
        return str(path)

    def test_office_formats_yield_retrievable_text_and_sections(self):
        with tempfile.TemporaryDirectory() as root:
            fixtures = [
                ("docx", {"word/document.xml": '<w:document xmlns:w="w"><w:p><w:t>Quantum battery capacity is 42 kWh.</w:t></w:p></w:document>'}, "Quantum battery", "Document"),
                ("pptx", {"ppt/presentation.xml": "<p:presentation/>", "ppt/slides/slide1.xml": '<p:sld xmlns:p="p" xmlns:a="a"><a:t>Launch date is May 2030.</a:t></p:sld>'}, "Launch date", "Slide 1"),
                ("xlsx", {"xl/workbook.xml": "<workbook/>", "xl/worksheets/sheet1.xml": '<worksheet><row><c r="A1"><v>125</v></c></row></worksheet>'}, "125", "Sheet 1"),
            ]
            for kind, parts, expected, section in fixtures:
                with self.subTest(kind=kind):
                    chunks = extract_sections(self._archive(root, f"source.{kind}", parts), kind)
                    self.assertIn(expected, chunks[0].text)
                    self.assertEqual(chunks[0].metadata.section_title, section)
                    indexed = rag_pipeline.build_documents(chunks, f"source.{kind}", f"fixture-{kind}")
                    self.assertTrue(any(expected in document.page_content for document in indexed))
                    self.assertTrue(all(document.metadata["document_id"] == f"fixture-{kind}" for document in indexed))

    def test_html_drops_script_and_preserves_section(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "page.html"
            path.write_text("<h1>Results</h1><p>Revenue grew 12 percent.</p><script>secret()</script>")
            chunks = extract_sections(str(path), "html")
            self.assertEqual(chunks[0].metadata.section_title, "Results")
            self.assertIn("Revenue grew", chunks[0].text)
            self.assertNotIn("secret", chunks[0].text)
            indexed = rag_pipeline.build_documents(chunks, "page.html", "fixture-html")
            self.assertIn("Revenue grew", indexed[0].page_content)

    def test_zip_bomb_and_empty_sources_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path = self._archive(root, "empty.docx", {"word/document.xml": "<document/>"})
            with self.assertRaisesRegex(ValueError, "No extractable"):
                extract_sections(path, "docx")

    def test_image_ocr_yields_indexable_text(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "scan.png"
            Image.new("RGB", (20, 20), "white").save(path)
            with patch("app.document_extract.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="Invoice total 87 dollars.")):
                chunks = extract_sections(str(path), "png")
            indexed = rag_pipeline.build_documents(chunks, "scan.png", "fixture-image")
            self.assertIn("Invoice total", indexed[0].page_content)
