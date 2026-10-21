"""Page/section boundaries and type-specific search text for PDF elements."""

from dataclasses import dataclass
from html.parser import HTMLParser
from types import SimpleNamespace
from typing import Any


@dataclass
class StructuredChunk:
    text: str
    metadata: Any


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def table_search_text(html: str) -> str:
    """Turn a sanitized table into searchable cell text without HTML markup."""
    parser = _VisibleText()
    parser.feed(html)
    return " ".join(parser.parts)


def structured_chunks(elements: list[Any], chunker) -> list[StructuredChunk]:
    """Chunk each page/section independently and retain stable parent position."""
    groups: list[tuple[int | None, str, list[Any]]] = []
    current: list[Any] = []
    page: int | None = None
    title = "Untitled section"

    def flush() -> None:
        if current:
            groups.append((page, title, current.copy()))
            current.clear()

    for element in elements:
        element_page = getattr(getattr(element, "metadata", None), "page_number", None)
        element_page = element_page if type(element_page) is int and element_page > 0 else None
        is_title = type(element).__name__ == "Title"
        if current and (element_page != page or is_title):
            flush()
        if not current:
            page = element_page
            if element_page != (groups[-1][0] if groups else None):
                title = "Untitled section"
        if is_title:
            title = (getattr(element, "text", "") or "Untitled section").strip()
        current.append(element)
    flush()

    output: list[StructuredChunk] = []
    for section_index, (section_page, section_title, group) in enumerate(groups):
        for part_index, chunk in enumerate(chunker(group)):
            original = getattr(getattr(chunk, "metadata", None), "orig_elements", None) or group
            output.append(StructuredChunk(
                text=chunk.text,
                metadata=SimpleNamespace(
                    orig_elements=original,
                    page_number=section_page,
                    section_title=section_title,
                    section_index=section_index,
                    part_index=part_index,
                ),
            ))
    return output
