import os
import json
from typing import List, Dict, Any
from dotenv import load_dotenv

from unstructured.partition.pdf import partition_pdf
from unstructured.chunking.title import chunk_by_title

from langchain_core.documents import Document
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain_core.messages import HumanMessage

load_dotenv()

PERSIST_DIR = "db/chroma_db"

def partition_documents(file_path: str):
    """Extract Elements from PDF using unstructured"""
    elements = partition_pdf(
        filename=file_path,
        strategy="hi_res",
        infer_table_structure=True,
        extract_image_block_types=["Image"],
        extract_image_block_to_payload=True
    )
    return elements

def create_chunks_by_title(elements):
    """Create intelligent chunks using title-based strategy"""
    return chunk_by_title(
        elements,
        max_characters=3000,
        new_after_n_chars=2400,
        combine_text_under_n_chars=500
    )

def separate_content_types(chunk) -> Dict[str, Any]:
    """Analyse and extract content types from chunk"""
    content_data = {
        'text': chunk.text,
        'tables': [],
        'images': [],
        'types': ['text']
    }

    if hasattr(chunk, 'metadata') and hasattr(chunk.metadata, 'orig_elements'):
        for element in chunk.metadata.orig_elements:
            element_type = type(element).__name__
            if element_type == 'Table':
                content_data['types'].append('table')
                table_html = getattr(element.metadata, 'text_as_html', element.text)
                content_data['tables'].append(table_html)
            elif element_type == 'Image':
                if hasattr(element, 'metadata') and hasattr(element.metadata, 'image_base64'):
                    content_data['types'].append('image')
                    image_base64 = getattr(element.metadata, 'image_base64', element.text)
                    content_data['images'].append(image_base64)

    content_data['types'] = list(set(content_data['types']))
    return content_data

def create_ai_enhanced_summary(text: str, tables: List[str], images: List[str]) -> str:
    """Create AI enhanced summary for mixed content using gpt-4o"""
    try:
        llm = ChatOpenAI(model="gpt-4o", temperature=0)
        prompt = f"You are creating a searchable description for document content retrieval.\n\nTEXT CONTENT:\n{text}"
        
        if tables:
            prompt += "\nTABLES:\n"
            for i, table in enumerate(tables):
                prompt += f"Table {i+1}:\n{table}\n\n"

        prompt += "\nGenerate a detailed, searchable description covering key facts, numbers, visual content, and concepts."

        message_content = [{"type": "text", "text": prompt}]
        for img_b64 in images:
            message_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
            })

        response = llm.invoke([HumanMessage(content=message_content)])
        return response.content
    except Exception as e:
        print(f"Summary generation error: {e}")
        return text[:300]

def process_and_store_documents(pdf_path: str):
    """Full ingestion pipeline to create and persist vector store"""
    elements = partition_documents(pdf_path)
    chunks = create_chunks_by_title(elements)
    
    langchain_documents = []
    for chunk in chunks:
        content_data = separate_content_types(chunk)
        
        if content_data['tables'] or content_data['images']:
            enhanced_content = create_ai_enhanced_summary(
                content_data['text'],
                content_data['tables'],
                content_data['images']
            )
        else:
            enhanced_content = content_data['text']

        doc = Document(
            page_content=enhanced_content,
            metadata={
                "original_content": json.dumps({
                    "raw_text": content_data['text'],
                    "tables_html": content_data['tables'],
                    "images_base64": content_data['images']
                })
            }
        )
        langchain_documents.append(doc)

    embedding_model = OpenAIEmbeddings(model="text-embedding-3-small")
    db = Chroma.from_documents(
        documents=langchain_documents,
        embedding=embedding_model,
        persist_directory=PERSIST_DIR,
        collection_metadata={"hnsw:space": "cosine"}
    )
    return db

def answer_query(query: str, k: int = 3) -> Dict[str, Any]:
    """Query ChromaDB and generate final response"""
    embedding_model = OpenAIEmbeddings(model="text-embedding-3-small")
    db = Chroma(
        persist_directory=PERSIST_DIR,
        embedding_function=embedding_model
    )
    
    retriever = db.as_retriever(search_kwargs={"k": k})
    chunks = retriever.invoke(query)

    llm = ChatOpenAI(model="gpt-4o", temperature=0)
    
    prompt_text = f"Based on the following documents, please answer this question: {query}\n\nCONTENT TO ANALYZE:\n"
    formatted_sources = []

    message_content = []

    for i, chunk in enumerate(chunks):
        raw_content = chunk.metadata.get("original_content") or chunk.metadata.get("orignal_content")
        original_data = json.loads(raw_content) if isinstance(raw_content, str) else (raw_content or {})
        
        prompt_text += f"--- Document {i+1} ---\n"
        if original_data.get("raw_text"):
            prompt_text += f"TEXT:\n{original_data['raw_text']}\n\n"
        if original_data.get("tables_html"):
            for j, table in enumerate(original_data["tables_html"]):
                prompt_text += f"Table {j+1}:\n{table}\n\n"

        # Collect images for GPT-4o vision
        for img_b64 in original_data.get("images_base64", []):
            message_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
            })

        formatted_sources.append({
            "chunk_id": i + 1,
            "enhanced_content": chunk.page_content,
            "metadata": {"original_content": original_data}
        })

    prompt_text += "\nANSWER:"
    message_content.insert(0, {"type": "text", "text": prompt_text})

    response = llm.invoke([HumanMessage(content=message_content)])

    return {
        "answer": response.content,
        "sources": formatted_sources
    }