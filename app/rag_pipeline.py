# app/rag_pipeline.py

import os
import json
from typing import List, Dict, Any, Generator, Optional, Tuple

from dotenv import load_dotenv

from unstructured.partition.pdf import partition_pdf
from unstructured.chunking.title import chunk_by_title

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_chroma import Chroma

load_dotenv()

PERSIST_DIR = "db/chroma_db"

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


def delete_document_vectors(filename: str) -> bool:
    """Delete every chunk that belongs to `filename`. Safe to call if none exist."""
    vectorstore._collection.delete(where={"filename": filename})
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
    )


def create_chunks_by_title(elements):
    """Create title-based chunks."""
    return chunk_by_title(
        elements,
        max_characters=3000,
        new_after_n_chars=2400,
        combine_text_under_n_chars=500,
    )


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
                table_html = getattr(element.metadata, "text_as_html", element.text)
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


def build_documents(chunks, filename: str) -> List[Document]:
    """Turn chunks into LangChain Documents tagged with the source filename.

    The `filename` metadata is what source selection and delete rely on.
    """
    documents: List[Document] = []
    for i, chunk in enumerate(chunks):
        content_data = separate_content_types(chunk)

        if content_data["tables"] or content_data["images"]:
            enhanced_content = create_ai_enhanced_summary(
                content_data["text"], content_data["tables"], content_data["images"]
            )
        else:
            enhanced_content = content_data["text"]

        documents.append(
            Document(
                page_content=enhanced_content,
                metadata={
                    "filename": filename,
                    "chunk_index": i,
                    "chunk_id": f"{filename}::{i}",
                    "original_content": json.dumps(
                        {
                            "raw_text": content_data["text"],
                            "tables_html": content_data["tables"],
                            "images_base64": content_data["images"],
                        }
                    ),
                },
            )
        )
    return documents


def store_documents(documents: List[Document]) -> None:
    """Embed and persist documents in the shared vector store."""
    if not documents:
        return
    ids = [d.metadata["chunk_id"] for d in documents]
    vectorstore.add_documents(documents, ids=ids)


def process_and_store_documents(pdf_path: str) -> None:
    """Convenience wrapper: partition -> chunk -> summarise -> store."""
    filename = os.path.basename(pdf_path)
    elements = partition_documents(pdf_path)
    chunks = create_chunks_by_title(elements)
    delete_document_vectors(filename)  # replace any previous version
    store_documents(build_documents(chunks, filename))


# ---------------------------------------------------------------------------
# Retrieval helpers
# ---------------------------------------------------------------------------

def _source_filter(sources: Optional[List[str]]) -> Optional[Dict[str, Any]]:
    if not sources:
        return None
    return {"filename": {"$in": list(sources)}}


def _original_content(doc: Document) -> Dict[str, Any]:
    raw = doc.metadata.get("original_content") or doc.metadata.get("orignal_content")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return raw or {}


def _retrieve(query: str, k: int, sources: Optional[List[str]]) -> List[Document]:
    return vectorstore.similarity_search(query, k=k, filter=_source_filter(sources))


def _build_context(
    docs: List[Document],
) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return (context_text, image_parts, sources_for_the_ui)."""
    context = ""
    image_parts: List[Dict[str, Any]] = []
    sources: List[Dict[str, Any]] = []

    for i, doc in enumerate(docs):
        original = _original_content(doc)
        filename = doc.metadata.get("filename", "Unknown Document")

        context += f"--- Document {i + 1} [{filename}] ---\n"
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
                "chunk_id": i + 1,
                "filename": filename,
                "content": doc.page_content,
                "enhanced_content": doc.page_content,
                "tables": original.get("tables_html", []),
                "images": original.get("images_base64", []),
                "metadata": {"filename": filename, "original_content": original},
            }
        )

    return context, image_parts, sources


# ---------------------------------------------------------------------------
# Answering
# ---------------------------------------------------------------------------

def answer_query(
    query: str, k: int = 3, sources: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Non-streaming answer."""
    docs = _retrieve(query, k, sources)
    context, image_parts, formatted_sources = _build_context(docs)

    prompt_text = (
        f"Based on the following documents, please answer this question: {query}\n\n"
        f"CONTENT TO ANALYZE:\n{context or 'No matching document context found.'}\nANSWER:"
    )
    message_content = [{"type": "text", "text": prompt_text}, *image_parts]
    response = llm.invoke([HumanMessage(content=message_content)])

    return {"answer": response.content, "sources": formatted_sources}


def answer_query_stream(
    query: str,
    k: int = 3,
    sources: Optional[List[str]] = None,
) -> Generator[str, None, None]:
    """Stream SSE events: one `sources` event, many `token` events, then `done`.

    If `sources` (a list of filenames) is given, retrieval is restricted to them.
    """
    try:
        docs = _retrieve(query, k, sources)
        context, image_parts, formatted_sources = _build_context(docs)

        yield f"data: {json.dumps({'type': 'sources', 'sources': formatted_sources})}\n\n"

        system_prompt = (
            "You are an expert AI assistant performing RAG analysis over multi-modal context.\n"
            "Answer the user query based ONLY on the provided contextual chunks.\n"
            "Cite the document source (filename) when explaining findings.\n"
            "If the context does not contain the answer, say so.\n\n"
            f"Context:\n{context or 'No matching document context found.'}"
        )
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=[{"type": "text", "text": query}, *image_parts]),
        ]

        for chunk in llm.stream(messages):
            if chunk.content:
                yield f"data: {json.dumps({'type': 'token', 'token': chunk.content})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"