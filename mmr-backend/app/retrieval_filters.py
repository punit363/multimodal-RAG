"""Validated retrieval scope and exact metadata matching for PDF chunks."""

import json
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class RetrievalFilters(BaseModel):
    pages: list[int] = Field(default_factory=list, max_length=30)
    content_types: list[Literal["text", "table", "image"]] = Field(default_factory=list)
    created_from: date | None = None
    created_to: date | None = None
    tags: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_scope(self):
        if any(type(page) is not int or page < 1 for page in self.pages):
            raise ValueError("Pages must be positive integers.")
        if self.created_from and self.created_to and self.created_from > self.created_to:
            raise ValueError("created_from must not be after created_to.")
        if any(not tag.strip() or len(tag) > 40 for tag in self.tags):
            raise ValueError("Tags must be non-empty and at most 40 characters.")
        return self

    def active(self) -> bool:
        return bool(self.pages or self.content_types or self.created_from or self.created_to or self.tags)


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, list) else []
        except ValueError:
            return []
    return []


def eligible_chunk_ids(
    ids: list[str],
    metadatas: list[dict[str, Any] | None],
    documents: list[dict[str, Any]],
    filters: RetrievalFilters,
) -> list[str]:
    """Return only chunks with explicit metadata satisfying every active filter."""
    registry = {}
    for document in documents:
        registry[document["id"]] = document
        if document.get("storage_name") == document.get("filename"):
            registry[document["filename"]] = document

    selected: list[str] = []
    requested_tags = {tag.casefold().strip() for tag in filters.tags}
    requested_types = set(filters.content_types)
    for chunk_id, metadata in zip(ids, metadatas):
        if not metadata:
            continue
        if filters.pages and not set(filters.pages).intersection(_json_list(metadata.get("page_numbers"))):
            continue
        if requested_types and not requested_types.intersection(_json_list(metadata.get("content_types"))):
            continue
        if filters.created_from or filters.created_to or requested_tags:
            document = registry.get(metadata.get("document_id") or metadata.get("filename"))
            if not document or document.get("status") not in (None, "ready"):
                continue
            created = str(document.get("created_at") or "")[:10]
            if (filters.created_from and (not created or created < filters.created_from.isoformat())) or (
                filters.created_to and (not created or created > filters.created_to.isoformat())
            ):
                continue
            if requested_tags and not requested_tags.issubset(
                {str(tag).casefold().strip() for tag in document.get("tags", [])}
            ):
                continue
        selected.append(chunk_id)
    return selected
