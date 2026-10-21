import types
import unittest

from app.structured_index import structured_chunks, table_search_text


def element(name, text, page):
    element_type = type(name, (), {})
    item = element_type()
    item.text = text
    item.metadata = types.SimpleNamespace(page_number=page)
    return item


class StructuredIndexTests(unittest.TestCase):
    def test_pages_and_titles_form_distinct_parents(self):
        elements = [
            element("Title", "Overview", 1),
            element("NarrativeText", "First page", 1),
            element("NarrativeText", "Second page", 2),
            element("Title", "Results", 2),
            element("Table", "Revenue 20", 2),
        ]
        def chunker(group):
            return [types.SimpleNamespace(text=" ".join(item.text for item in group),
                                          metadata=types.SimpleNamespace(orig_elements=group))]

        chunks = structured_chunks(elements, chunker)
        self.assertEqual([chunk.metadata.section_index for chunk in chunks], [0, 1, 2])
        self.assertEqual([chunk.metadata.page_number for chunk in chunks], [1, 2, 2])
        self.assertEqual([chunk.metadata.section_title for chunk in chunks],
                         ["Overview", "Untitled section", "Results"])
        self.assertEqual(chunks[2].metadata.orig_elements, elements[3:])

    def test_table_cells_are_searchable_without_markup(self):
        self.assertEqual(table_search_text("<table><tr><td>Revenue</td><td>20</td></tr></table>"), "Revenue 20")


if __name__ == "__main__":
    unittest.main()
