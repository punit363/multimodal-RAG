"""Bounded extraction for Office files, images, and saved HTML pages."""

import html
import re
import subprocess
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

from app.structured_index import StructuredChunk
from app.language import ocr_languages

MAX_UNCOMPRESSED_BYTES = 60 * 1024 * 1024
MAX_ZIP_ENTRIES = 2000
MAX_TEXT_CHARS = 2_000_000


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0
        self.block = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "nav", "footer", "head"}:
            self.skip += 1
        if tag in {"h1", "h2", "h3", "p", "li", "td", "th"}:
            self.block.append((tag, []))

    def handle_endtag(self, tag):
        if tag in {"script", "style", "nav", "footer", "head"} and self.skip:
            self.skip -= 1
        if self.block and self.block[-1][0] == tag:
            _, pieces = self.block.pop()
            value = " ".join(" ".join(pieces).split())
            if value and not self.skip:
                self.parts.append(("title" if tag.startswith("h") else "text", value))

    def handle_data(self, data):
        if self.block and not self.skip:
            self.block[-1][1].append(data)


def _safe_archive(path: str, required: str):
    try:
        archive = zipfile.ZipFile(path)
        entries = archive.infolist()
        if (required not in archive.namelist() or len(entries) > MAX_ZIP_ENTRIES
                or sum(item.file_size for item in entries) > MAX_UNCOMPRESSED_BYTES
                or any(item.filename.startswith("/") or ".." in Path(item.filename).parts for item in entries)):
            raise ValueError("Office file is incomplete or exceeds extraction limits.")
        return archive
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError("Office file is malformed or unreadable.") from exc


def _xml_text(data: bytes) -> str:
    root = ET.fromstring(data)
    return " ".join(text.strip() for node in root.iter() if node.tag.rsplit("}", 1)[-1] in {"t", "v"}
                    for text in [node.text or ""] if text.strip())


def extract_sections(path: str, source_format: str) -> list[StructuredChunk]:
    """Extract source-labelled sections without inventing PDF page coordinates."""
    sections: list[tuple[str, str]] = []
    if source_format in {"docx", "pptx", "xlsx"}:
        required = {"docx": "word/document.xml", "pptx": "ppt/presentation.xml", "xlsx": "xl/workbook.xml"}[source_format]
        with _safe_archive(path, required) as archive:
            names = archive.namelist()
            if source_format == "docx":
                root = ET.fromstring(archive.read(required))
                blocks = [" ".join(t.text or "" for t in element.iter() if t.tag.endswith("}t"))
                          for element in root.iter() if element.tag.endswith("}p")]
                sections = [("Document", "\n".join(blocks))]
            else:
                prefix, pattern = (("ppt/slides/", r"slide\d+\.xml") if source_format == "pptx"
                                   else ("xl/worksheets/", r"sheet\d+\.xml"))
                ordered = sorted((name for name in names if name.startswith(prefix) and re.fullmatch(pattern, name[len(prefix):])),
                                 key=lambda name: int(re.search(r"(\d+)\.xml$", name).group(1)))
                shared = []
                if source_format == "xlsx" and "xl/sharedStrings.xml" in names:
                    strings = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                    shared = ["".join(node.text or "" for node in item.iter() if node.tag.endswith("}t"))
                              for item in strings if item.tag.endswith("}si")]
                for index, name in enumerate(ordered, 1):
                    if source_format == "pptx":
                        body = _xml_text(archive.read(name))
                    else:
                        root = ET.fromstring(archive.read(name))
                        values = []
                        for cell in root.iter():
                            if cell.tag.rsplit("}", 1)[-1] != "c":
                                continue
                            value = next((node.text for node in cell if node.tag.rsplit("}", 1)[-1] == "v"), None)
                            if value is not None and cell.attrib.get("t") == "s":
                                try:
                                    value = shared[int(value)]
                                except (IndexError, ValueError):
                                    value = ""
                            if value is None:
                                value = " ".join(node.text or "" for node in cell.iter() if node.tag.rsplit("}", 1)[-1] == "t")
                            if value:
                                values.append(f"{cell.attrib.get('r', '')}: {value}")
                        body = "\n".join(values)
                    sections.append((f"{'Slide' if source_format == 'pptx' else 'Sheet'} {index}", body))
    elif source_format == "html":
        parser = _PageParser()
        parser.feed(Path(path).read_text(encoding="utf-8", errors="replace")[:MAX_TEXT_CHARS])
        title = "Web page"
        current = []
        for kind, value in parser.parts:
            if kind == "title" and current:
                sections.append((title, "\n".join(current)))
                current = []
            if kind == "title":
                title = value[:160]
            else:
                current.append(value)
        if current:
            sections.append((title, "\n".join(current)))
    elif source_format in {"png", "jpg", "jpeg", "webp", "tiff"}:
        from PIL import Image
        with Image.open(path) as image:
            if image.width * image.height > 40_000_000:
                raise ValueError("Image exceeds the 40 megapixel OCR limit.")
            image.verify()
        result = subprocess.run(["tesseract", path, "stdout", "-l", "+".join(ocr_languages())], capture_output=True, text=True, timeout=60, check=False)
        if result.returncode:
            raise ValueError("Image OCR failed; check that Tesseract is installed.")
        sections = [("Image OCR", result.stdout)]
    else:
        raise ValueError("Unsupported document format.")

    output = []
    for index, (title, body) in enumerate(sections):
        body = body.strip()[:MAX_TEXT_CHARS]
        if not body:
            continue
        for part, start in enumerate(range(0, len(body), 2400)):
            text = body[start:start + 2400]
            evidence = SimpleNamespace(text=text, metadata=SimpleNamespace(page_number=None))
            output.append(StructuredChunk(text=text, metadata=SimpleNamespace(
                orig_elements=[evidence], section_index=index, section_title=title,
                part_index=part, page_number=None)))
    if not output:
        raise ValueError("No extractable text was found; review the source or OCR quality.")
    return output
