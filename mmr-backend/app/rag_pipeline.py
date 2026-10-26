# app/rag_pipeline.py

import os
import json
import math
import re
from types import SimpleNamespace
from typing import List, Dict, Any, Generator, Optional, Tuple

from dotenv import load_dotenv

from unstructured.partition.pdf import partition_pdf
from unstructured.chunking.title import chunk_by_title

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_chroma import Chroma
from app.security import sanitize_table_html
from app.source_metadata import source_location
from app.grounding import INSUFFICIENT_EVIDENCE_ANSWER, minimum_relevance_score, supported_results
from app.database import list_documents
from app.retrieval_filters import RetrievalFilters, eligible_chunk_ids
from app.ranking import cosine_similarity, keyword_rank, reciprocal_rank_fusion, rerank_diverse, tokenize
from app.query_rewrite import rewrite_followup_query
from app.structured_index import structured_chunks, table_search_text
from app.language import ocr_languages, language_instruction, insufficient_evidence_message
from app.workspace import bind_vector_directory

load_dotenv()

PERSIST_DIR = os.getenv("RAG_VECTOR_DIR", "db/chroma_db")
bind_vector_directory(PERSIST_DIR, os.getenv("RAG_WORKSPACE_ID", "default"))
UNVERIFIED_COMPARISON_ANSWER = "The comparison could not be verified against every selected document. Try a more specific question."

embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
vectorstore = Chroma(
    persist_directory=PERSIST_DIR,
    embedding_function=embeddings,
    collection_metadata={"hnsw:space": "cosine"},
)
llm = ChatOpenAI(model="gpt-4o", streaming=True, temperature=0.2)


# ---------------------------------------------------------------------------
# Index inspection / deletion
# ---------------------------------------------------------------------------

def get_indexed_documents() -> List[Dict[str, Any]]:
    """Unique PDF filenames stored in Chroma, with chunk counts."""
    results = vectorstore._collection.get(include=["metadatas"])
    doc_stats: Dict[str, int] = {}
    for meta in results.get("metadatas") or []:
        if meta and "filename" in meta:
            fn = meta["filename"]
            doc_stats[fn] = doc_stats.get(fn, 0) + 1
    return [{"filename": fn, "chunk_count": n} for fn, n in doc_stats.items()]


def delete_document_vectors(document_id: str) -> bool:
    """Delete every chunk that belongs to an immutable document id."""
    vectorstore._collection.delete(
        where={
            "$or": [
                {"document_id": document_id},
                {"filename": document_id},
            ]
        }
    )
    return True


# Backwards-compatible alias for the old name
delete_document_from_chroma = delete_document_vectors


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

def partition_documents(file_path: str):
    """Extract elements from a PDF using unstructured."""
    return partition_pdf(
        filename=file_path,
        strategy="hi_res",
        infer_table_structure=True,
        extract_image_block_types=["Image"],
        extract_image_block_to_payload=True,
        languages=ocr_languages(),
    )


def create_chunks_by_title(elements):
    """Create chunks within PDF page and section boundaries."""
    return structured_chunks(elements, lambda group: chunk_by_title(
        group, max_characters=3000, new_after_n_chars=2400,
        combine_text_under_n_chars=500,
    ))


def separate_content_types(chunk) -> Dict[str, Any]:
    """Pull text, tables and images out of a chunk."""
    content_data: Dict[str, Any] = {
        "text": chunk.text,
        "tables": [],
        "images": [],
        "types": ["text"],
    }

    if hasattr(chunk, "metadata") and hasattr(chunk.metadata, "orig_elements"):
        for element in chunk.metadata.orig_elements or []:
            element_type = type(element).__name__
            if element_type == "Table":
                content_data["types"].append("table")
                table_html = sanitize_table_html(
                    getattr(element.metadata, "text_as_html", element.text)
                )
                content_data["tables"].append(table_html)
            elif element_type == "Image":
                if hasattr(element, "metadata") and hasattr(element.metadata, "image_base64"):
                    content_data["types"].append("image")
                    content_data["images"].append(
                        getattr(element.metadata, "image_base64", element.text)
                    )

    content_data["types"] = list(set(content_data["types"]))
    return content_data


def create_ai_enhanced_summary(text: str, tables: List[str], images: List[str]) -> str:
    """Searchable description for mixed (text + table + image) content."""
    try:
        summary_llm = ChatOpenAI(model="gpt-4o", temperature=0)
        prompt = (
            "You are creating a searchable description for document content retrieval."
            f"\n\nTEXT CONTENT:\n{text}"
        )
        if tables:
            prompt += "\nTABLES:\n"
            for i, table in enumerate(tables):
                prompt += f"Table {i + 1}:\n{table}\n\n"
        prompt += (
            "\nGenerate a detailed, searchable description covering key facts, "
            "numbers, visual content, and concepts."
        )

        message_content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        for img_b64 in images:
            message_content.append(
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
            )

        response = summary_llm.invoke([HumanMessage(content=message_content)])
        return response.content
    except Exception as e:
        print(f"Summary generation error: {e}")
        return text[:300]


def build_documents(
    chunks, filename: str, document_id: Optional[str] = None
) -> List[Document]:
    """Index text, tables, and image descriptions with their PDF evidence."""
    source_id = document_id or filename
    documents: List[Document] = []
    for i, chunk in enumerate(chunks):
        content_data = separate_content_types(chunk)
        metadata = getattr(chunk, "metadata", None)
        elements = list(getattr(metadata, "orig_elements", None) or [])
        section_index = getattr(metadata, "section_index", i)
        section_title = getattr(metadata, "section_title", "Untitled section")
        parent_id = f"{source_id}::section:{section_index}"
        text_elements = [element for element in elements if type(element).__name__ not in {"Table", "Image"}]
        text = "\n".join(str(element.text) for element in text_elements if getattr(element, "text", "").strip())
        if not elements:
            text = content_data["text"]
        representations: List[Tuple[str, str, Any, Dict[str, Any]]] = []
        if text.strip():
            representations.append(("text", text, text_elements or chunk, {
                "raw_text": text, "tables_html": [], "images_base64": [],
            }))
        for index, table in enumerate(content_data["tables"]):
            table_elements = [element for element in elements if type(element).__name__ == "Table"]
            evidence = table_elements[index] if index < len(table_elements) else chunk
            search_text = table_search_text(table) or str(getattr(evidence, "text", ""))
            representations.append(("table", search_text, evidence, {
                "raw_text": "", "tables_html": [table], "images_base64": [],
            }))
        for index, image in enumerate(content_data["images"]):
            image_elements = [element for element in elements if type(element).__name__ == "Image"]
            evidence = image_elements[index] if index < len(image_elements) else chunk
            description = create_ai_enhanced_summary("", [], [image]) or str(getattr(evidence, "text", "")) or "Image"
            representations.append(("image", description, evidence, {
                "raw_text": "", "tables_html": [], "images_base64": [image],
            }))

        for representation_index, (kind, search_text, evidence, original) in enumerate(representations):
            if not search_text.strip():
                continue
            location = source_location(
                SimpleNamespace(metadata=SimpleNamespace(orig_elements=evidence))
                if isinstance(evidence, list) else evidence
            )
            chunk_id = f"{parent_id}::chunk:{i}::{kind}:{representation_index}"
            documents.append(Document(page_content=search_text, metadata={
                "filename": filename,
                "document_id": source_id,
                "chunk_index": i,
                "chunk_id": chunk_id,
                "parent_id": parent_id,
                "section_title": section_title,
                "representation_type": kind,
                "page_numbers": json.dumps(location["page_numbers"]),
                "page_location_status": location["page_location_status"],
                "element_types": json.dumps(location["element_types"]),
                "content_types": json.dumps([kind]),
                "highlight_rect": json.dumps(location["highlight_rect"]),
                "original_content": json.dumps(original),
            }))
    return documents


def store_documents(documents: List[Document]) -> None:
    """Embed and persist documents in the shared vector store."""
    if not documents:
        return
    ids = [d.metadata["chunk_id"] for d in documents]
    vectorstore.add_documents(documents, ids=ids)


def summarize_evidence(document_ids: List[str], section_title: Optional[str] = None) -> Dict[str, Any]:
    """Build a bounded extractive overview with resolvable source chunk IDs."""
    items = []
    for document_id in document_ids:
        result = vectorstore._collection.get(where={"document_id": document_id}, include=["documents", "metadatas"])
        for text, metadata in zip(result.get("documents") or [], result.get("metadatas") or []):
            if not metadata or metadata.get("representation_type") != "text":
                continue
            if section_title is not None and metadata.get("section_title") != section_title:
                continue
            excerpt = " ".join((text or "").split())[:300]
            if excerpt:
                items.append({"text": excerpt, "filename": metadata.get("filename", ""),
                              "document_id": document_id, "chunk_id": metadata.get("chunk_id", ""),
                              "section_title": metadata.get("section_title", "")})
    return {"kind": "extractive", "items": items[:12], "total_matching_chunks": len(items)}


def indexed_evidence(document_ids: List[str]) -> List[Dict[str, str]]:
    """Read a bounded set of original, citable text from selected indexed sources."""
    evidence = []
    for document_id in document_ids:
        results = vectorstore._collection.get(
            where={"document_id": document_id}, include=["documents", "metadatas"], limit=100
        )
        for text, metadata in zip(results.get("documents") or [], results.get("metadatas") or []):
            if not metadata or metadata.get("representation_type") not in {"text", "table"}:
                continue
            chunk_id = metadata.get("chunk_id")
            if text and chunk_id:
                evidence.append({"text": text[:3000], "document_id": document_id,
                                 "filename": metadata.get("filename", ""), "chunk_id": chunk_id,
                                 "section_title": metadata.get("section_title", "")})
    return evidence


def process_and_store_documents(pdf_path: str) -> None:
    """Convenience wrapper: partition -> chunk -> summarise -> store."""
    filename = os.path.basename(pdf_path)
    elements = partition_documents(pdf_path)
    chunks = create_chunks_by_title(elements)
    document_id = os.path.splitext(filename)[0]
    delete_document_vectors(document_id)
    store_documents(build_documents(chunks, filename, document_id))


# ---------------------------------------------------------------------------
# Retrieval helpers
# ---------------------------------------------------------------------------

def _source_filter(sources: Optional[List[str]]) -> Optional[Dict[str, Any]]:
    if not sources:
        return None
    return {
        "$or": [
            {"document_id": {"$in": list(sources)}},
            {"filename": {"$in": list(sources)}},
        ]
    }


def _original_content(doc: Document) -> Dict[str, Any]:
    raw = doc.metadata.get("original_content") or doc.metadata.get("orignal_content")
    if isinstance(raw, str):
        try:
            content = json.loads(raw)
        except Exception:
            content = {}
    else:
        content = raw or {}
    content["tables_html"] = [
        sanitize_table_html(table) for table in content.get("tables_html", [])
    ]
    return content


def _semantic_candidates(
    query: str, k: int, sources: Optional[List[str]], allowed_ids: Optional[List[str]]
) -> List[Tuple[Document, float]]:
    """Return normalized cosine scores, honoring an exact allowed chunk set."""
    if allowed_ids is None:
        return supported_results(vectorstore.similarity_search_with_relevance_scores(
            query, k=k, filter=_source_filter(sources)
        ))
    if not allowed_ids:
        return []
    query_vector = embeddings.embed_query(query)
    normalize_score = vectorstore._select_relevance_score_fn()
    results: List[Tuple[Document, float]] = []
    for offset in range(0, len(allowed_ids), 500):
        batch = allowed_ids[offset:offset + 500]
        results.extend(
            (document, normalize_score(distance))
            for document, distance in vectorstore.similarity_search_by_vector_with_relevance_scores(
                query_vector, k=min(k, len(batch)), filter={"chunk_id": {"$in": batch}}
            )
        )
    results.sort(key=lambda item: item[1], reverse=True)
    return supported_results(results[:k])


def _retrieve(
    query: str, k: int, sources: Optional[List[str]], filters: Optional[RetrievalFilters] = None
) -> List[Tuple[Document, float]]:
    """Combine safe semantic and exact-term hits, then diversify bounded evidence."""
    mode = os.getenv("RAG_RETRIEVAL_MODE", "hybrid").strip().lower()
    if mode not in {"semantic", "hybrid"}:
        raise ValueError("RAG_RETRIEVAL_MODE must be semantic or hybrid.")
    active_filters = bool(filters and filters.active())
    if mode == "semantic" and not active_filters:
        return _semantic_candidates(query, k, sources, None)

    candidates = vectorstore._collection.get(
        where=_source_filter(sources), include=["documents", "metadatas"]
    )
    all_ids = candidates.get("ids") or []
    all_metadata = candidates.get("metadatas") or []
    allowed_ids = eligible_chunk_ids(all_ids, all_metadata, list_documents(), filters) if active_filters else all_ids
    if not allowed_ids:
        return []
    semantic = _semantic_candidates(query, min(max(k * 5, 20), len(allowed_ids)), sources, allowed_ids if active_filters else None)
    if mode == "semantic":
        return semantic[:k]

    allowed = set(allowed_ids)
    texts = {
        chunk_id: content or ""
        for chunk_id, content in zip(all_ids, candidates.get("documents") or [])
        if chunk_id in allowed
    }
    lexical = keyword_rank(query, texts, limit=20)
    semantic_by_id = {
        doc.metadata.get("chunk_id") or doc.id: (doc, score)
        for doc, score in semantic
    }
    lexical_ids = [chunk_id for chunk_id, _, coverage in lexical if len(set(tokenize(query))) >= 2 and coverage >= 0.75]
    lexical_scores: Dict[str, float] = {}
    if lexical_ids:
        query_vector = embeddings.embed_query(query)
        stored = vectorstore._collection.get(ids=lexical_ids, include=["embeddings"])
        stored_embeddings = stored.get("embeddings")
        if stored_embeddings is not None:
            lexical_scores = {
                chunk_id: cosine_similarity(query_vector, vector)
                for chunk_id, vector in zip(stored.get("ids") or [], stored_embeddings)
            }
    metadata_by_id = dict(zip(all_ids, all_metadata))
    merged = dict(semantic_by_id)
    lexical_floor = max(0.0, minimum_relevance_score() - 0.1)
    for chunk_id in lexical_ids:
        score = lexical_scores.get(chunk_id)
        if score is not None and math.isfinite(score) and score >= lexical_floor and chunk_id not in merged:
            merged[chunk_id] = (
                Document(id=chunk_id, page_content=texts[chunk_id], metadata=metadata_by_id[chunk_id] or {}),
                score,
            )
    semantic_ids = list(semantic_by_id)
    lexical_ids = [chunk_id for chunk_id in lexical_ids if chunk_id in merged]
    ranked = reciprocal_rank_fusion([semantic_ids, lexical_ids])
    if os.getenv("RAG_RERANK_ENABLED", "true").strip().lower() == "true":
        ranked = rerank_diverse(ranked, texts, k)
    return [merged[chunk_id] for chunk_id in ranked[:k]]


def _build_context(
    docs: List[Tuple[Document, float]],
) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return (context_text, image_parts, sources_for_the_ui)."""
    context = ""
    image_parts: List[Dict[str, Any]] = []
    sources: List[Dict[str, Any]] = []

    for i, (doc, score) in enumerate(docs):
        original = _original_content(doc)
        filename = doc.metadata.get("filename", "Unknown Document")
        document_id = doc.metadata.get("document_id", filename)
        chunk_id = doc.metadata.get("chunk_id") or f"{document_id}::{doc.metadata.get('chunk_index', i)}"
        try:
            page_numbers = json.loads(doc.metadata.get("page_numbers") or "[]")
            element_types = json.loads(doc.metadata.get("element_types") or "[]")
            highlight_rect = json.loads(doc.metadata.get("highlight_rect") or "null")
        except (TypeError, ValueError):
            page_numbers, element_types, highlight_rect = [], [], None
        page_location_status = doc.metadata.get("page_location_status") or (
            "complete" if page_numbers else "unavailable"
        )
        page_label = f", p.{page_numbers[0]}" if len(page_numbers) == 1 else ""

        context += f"--- Source [[source:{chunk_id}]] [{filename}{page_label}] ---\n"
        if doc.metadata.get("section_title"):
            context += f"SECTION: {doc.metadata['section_title']}\n"
        if doc.metadata.get("representation_type"):
            context += f"EVIDENCE TYPE: {doc.metadata['representation_type']}\n"
        if original.get("raw_text"):
            context += f"TEXT:\n{original['raw_text']}\n\n"
        for j, table in enumerate(original.get("tables_html", [])):
            context += f"Table {j + 1}:\n{table}\n\n"

        for img_b64 in original.get("images_base64", []):
            image_parts.append(
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
            )

        # Superset shape so the UI works whichever fields the citation card reads
        sources.append(
            {
                "chunk_id": chunk_id,
                "parent_id": doc.metadata.get("parent_id"),
                "section_title": doc.metadata.get("section_title"),
                "representation_type": doc.metadata.get("representation_type"),
                "document_id": document_id,
                "filename": filename,
                "page_numbers": page_numbers,
                "page_location_status": page_location_status,
                "element_types": element_types,
                "highlight_rect": highlight_rect,
                "relevance_score": score,
                "content": doc.page_content,
                "enhanced_content": doc.page_content,
                "tables": original.get("tables_html", []),
                "images": original.get("images_base64", []),
                "metadata": {
                    "document_id": document_id,
                    "filename": filename,
                    "original_content": original,
                },
            }
        )

    return context, image_parts, sources


# ---------------------------------------------------------------------------
# Answering
# ---------------------------------------------------------------------------

def _retrieval_query(query: str, history: Optional[List[Dict[str, str]]]) -> str:
    if os.getenv("RAG_QUERY_REWRITE_ENABLED", "true").strip().lower() != "true":
        return query
    return rewrite_followup_query(
        query, history, lambda prompt: llm.invoke([HumanMessage(content=prompt)]).content
    )


def _answer_evidence(
    query: str, k: int, sources: Optional[List[str]],
    filters: Optional[RetrievalFilters], history: Optional[List[Dict[str, str]]],
    mode: str,
) -> List[Tuple[Document, float]]:
    """Collect evidence from every selected document in comparison mode."""
    retrieval_query = _retrieval_query(query, history)
    if mode != "compare":
        return _retrieve(retrieval_query, k, sources, filters)
    if not sources or not 2 <= len(sources) <= 4 or len(set(sources)) != len(sources):
        raise ValueError("Comparison requires two to four distinct selected documents.")
    evidence: List[Tuple[Document, float]] = []
    for source_id in sources:
        matches = _retrieve(retrieval_query, min(k, 3), [source_id], filters)
        if not matches:
            return []
        evidence.extend(matches)
    return evidence


def _answer_instruction(mode: str) -> str:
    if mode == "compare":
        return (
            "Compare the selected documents in a concise table with one row per document, "
            "then state similarities and differences. Cite each document-specific claim "
            "with its exact [[source:chunk_id]] marker. Mark missing facts as unavailable; "
            "do not infer agreement or differences without evidence from both documents."
        )
    return "Cite supported claims using the exact [[source:chunk_id]] marker shown with each source."


def _comparison_is_cited(answer: str, sources: List[Dict[str, Any]], selected: List[str]) -> bool:
    """Require at least one registered citation from each compared document."""
    cited = set(re.findall(r"\[\[source:([^\]]+)\]\]", answer))
    registered = {str(source["chunk_id"]): source["document_id"] for source in sources}
    return bool(cited) and cited.issubset(registered) and set(selected).issubset(
        {registered[chunk_id] for chunk_id in cited}
    )

def answer_query(
    query: str, k: int = 3, sources: Optional[List[str]] = None,
    filters: Optional[RetrievalFilters] = None,
    history: Optional[List[Dict[str, str]]] = None,
    mode: str = "answer", language: str = "auto",
) -> Dict[str, Any]:
    """Non-streaming answer."""
    instruction = language_instruction(query, language)
    docs = _answer_evidence(query, k, sources, filters, history, mode)
    if not docs:
        return {"answer": insufficient_evidence_message(query, language), "sources": [], "insufficient_evidence": True}
    context, image_parts, formatted_sources = _build_context(docs)

    prompt_text = (
        f"Based on the following documents, please answer this question: {query}\n\n"
        f"CONTENT TO ANALYZE:\n{context}\n"
        f"{_answer_instruction(mode)}\n{instruction}\nANSWER:"
    )
    message_content = [{"type": "text", "text": prompt_text}, *image_parts]
    response = llm.invoke([HumanMessage(content=message_content)])

    if mode == "compare" and not _comparison_is_cited(str(response.content), formatted_sources, sources or []):
        return {"answer": UNVERIFIED_COMPARISON_ANSWER, "sources": formatted_sources, "insufficient_evidence": True}

    return {"answer": response.content, "sources": formatted_sources}


def answer_query_stream(
    query: str,
    k: int = 3,
    sources: Optional[List[str]] = None,
    filters: Optional[RetrievalFilters] = None,
    history: Optional[List[Dict[str, str]]] = None,
    mode: str = "answer",
    language: str = "auto",
) -> Generator[str, None, None]:
    """Stream SSE events: one `sources` event, many `token` events, then `done`.

    If `sources` (a list of filenames) is given, retrieval is restricted to them.
    """
    try:
        instruction = language_instruction(query, language)
        docs = _answer_evidence(query, k, sources, filters, history, mode)
        if not docs:
            yield f"data: {json.dumps({'type': 'sources', 'sources': []})}\n\n"
            yield f"data: {json.dumps({'type': 'token', 'token': insufficient_evidence_message(query, language)}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'insufficient_evidence': True})}\n\n"
            return
        context, image_parts, formatted_sources = _build_context(docs)

        yield f"data: {json.dumps({'type': 'sources', 'sources': formatted_sources})}\n\n"

        system_prompt = (
            "You are an expert AI assistant performing RAG analysis over multi-modal context.\n"
            "Answer the user query based ONLY on the provided contextual chunks.\n"
            f"{_answer_instruction(mode)}\n"
            f"{instruction}\n"
            "If the context does not contain the answer, say so.\n\n"
            f"Context:\n{context or 'No matching document context found.'}"
        )
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=[{"type": "text", "text": query}, *image_parts]),
        ]

        if mode == "compare":
            answer = "".join(str(chunk.content) for chunk in llm.stream(messages) if chunk.content)
            if not _comparison_is_cited(answer, formatted_sources, sources or []):
                yield f"data: {json.dumps({'type': 'token', 'token': UNVERIFIED_COMPARISON_ANSWER})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'insufficient_evidence': True})}\n\n"
                return
            yield f"data: {json.dumps({'type': 'token', 'token': answer})}\n\n"
        else:
            for chunk in llm.stream(messages):
                if chunk.content:
                    yield f"data: {json.dumps({'type': 'token', 'token': chunk.content})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
