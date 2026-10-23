import json
import types
import unittest
from unittest.mock import patch

from langchain_core.documents import Document

from app import rag_pipeline
from app.structured_index import StructuredChunk


def element(name, text, page, **metadata):
    item = type(name, (), {})()
    item.text = text
    item.metadata = types.SimpleNamespace(page_number=page, **metadata)
    return item


class HighPriorityPipelineTests(unittest.TestCase):
    def test_extractive_summary_keeps_source_ids_and_section_scope(self):
        result = {"documents": ["Revenue rose 12 percent", "Margin grew 3 percent"],
                  "metadatas": [{"representation_type": "text", "filename": "report.pdf", "chunk_id": "chunk-1", "section_title": "Results"},
                                {"representation_type": "text", "filename": "report.pdf", "chunk_id": "chunk-2", "section_title": "Outlook"}]}
        with patch.object(rag_pipeline.vectorstore._collection, "get", return_value=result):
            summary = rag_pipeline.summarize_evidence(["doc-1"], "Results")
        self.assertEqual(summary["total_matching_chunks"], 1)
        self.assertEqual(summary["items"][0]["chunk_id"], "chunk-1")
        self.assertEqual(summary["items"][0]["document_id"], "doc-1")

    def test_ingestion_indexes_separate_evidence_with_shared_parent(self):
        text = element("NarrativeText", "Revenue increased", 2)
        table = element("Table", "Revenue 20", 2, text_as_html="<table><tr><td>Revenue</td><td>20</td></tr></table>")
        image = element("Image", "Figure", 2, image_base64="aW1hZ2U=")
        chunk = StructuredChunk("mixed", types.SimpleNamespace(
            orig_elements=[text, table, image], section_index=1,
            section_title="Results", page_number=2,
        ))
        with patch.object(rag_pipeline, "create_ai_enhanced_summary", return_value="Image shows a rising trend"):
            documents = rag_pipeline.build_documents([chunk], "report.pdf", "doc-1")
        self.assertEqual([doc.metadata["representation_type"] for doc in documents], ["text", "table", "image"])
        self.assertEqual(len({doc.metadata["chunk_id"] for doc in documents}), 3)
        self.assertEqual({doc.metadata["parent_id"] for doc in documents}, {"doc-1::section:1"})
        self.assertEqual([json.loads(doc.metadata["page_numbers"]) for doc in documents], [[2], [2], [2]])
        self.assertIn("Revenue 20", documents[1].page_content)
        self.assertEqual(documents[2].page_content, "Image shows a rising trend")
        self.assertIn("<td>Revenue</td><td>20</td>",
                      json.loads(documents[1].metadata["original_content"])["tables_html"][0])
        with patch.object(rag_pipeline.vectorstore, "add_documents") as add_documents:
            rag_pipeline.store_documents(documents)
        self.assertEqual(add_documents.call_args.kwargs["ids"],
                         [document.metadata["chunk_id"] for document in documents])
        context, image_parts, sources = rag_pipeline._build_context([(document, 0.8) for document in documents])
        self.assertEqual(len(image_parts), 1)
        self.assertEqual({source["representation_type"] for source in sources}, {"text", "table", "image"})
        self.assertTrue(all(source["document_id"] == "doc-1" and source["page_numbers"] == [2] for source in sources))
        self.assertTrue(all(f"[[source:{source['chunk_id']}]]" in context for source in sources))

    def test_comparison_requires_evidence_from_each_document(self):
        def match(source):
            doc = Document(page_content="Revenue 20", metadata={
                "chunk_id": f"{source}::1", "document_id": source,
                "filename": f"{source}.pdf", "original_content": json.dumps({"raw_text": "Revenue 20"}),
            })
            return [(doc, 0.8)]

        with patch.object(rag_pipeline, "_retrieve", side_effect=lambda query, k, sources, filters: match(sources[0])) as retrieve:
            results = rag_pipeline._answer_evidence("Compare revenue", 3, ["a", "b"], None, None, "compare")
        self.assertEqual([doc.metadata["document_id"] for doc, _ in results], ["a", "b"])
        self.assertEqual([call.args[2] for call in retrieve.call_args_list], [["a"], ["b"]])

        with patch.object(rag_pipeline, "_retrieve", side_effect=lambda query, k, sources, filters: [] if sources == ["b"] else match("a")):
            self.assertEqual(rag_pipeline._answer_evidence("Compare", 3, ["a", "b"], None, None, "compare"), [])

    def test_comparison_rejects_missing_or_unregistered_citations(self):
        sources = [{"chunk_id": "a::1", "document_id": "a"}, {"chunk_id": "b::1", "document_id": "b"}]
        self.assertTrue(rag_pipeline._comparison_is_cited(
            "A [[source:a::1]] differs from B [[source:b::1]].", sources, ["a", "b"]
        ))
        self.assertFalse(rag_pipeline._comparison_is_cited("A [[source:a::1]] only.", sources, ["a", "b"]))
        self.assertFalse(rag_pipeline._comparison_is_cited(
            "A [[source:a::1]], B [[source:b::1]], C [[source:unknown]].", sources, ["a", "b"]
        ))

    def test_stream_comparison_withholds_uncited_answer(self):
        evidence = [(
            Document(page_content="Revenue 20", metadata={
                "chunk_id": f"{source}::1", "document_id": source,
                "filename": f"{source}.pdf", "original_content": json.dumps({"raw_text": "Revenue 20"}),
            }), 0.8,
        ) for source in ("a", "b")]
        with patch.object(rag_pipeline, "_answer_evidence", return_value=evidence), patch.object(
            rag_pipeline, "llm"
        ) as model:
            model.stream.return_value = iter([types.SimpleNamespace(content="Only A [[source:a::1]]")])
            events = list(rag_pipeline.answer_query_stream("Compare", sources=["a", "b"], mode="compare"))
        self.assertTrue(any(rag_pipeline.UNVERIFIED_COMPARISON_ANSWER in event for event in events))
        self.assertFalse(any("Only A" in event for event in events))


if __name__ == "__main__":
    unittest.main()
