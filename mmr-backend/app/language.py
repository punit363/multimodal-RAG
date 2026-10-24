"""Supported response-language and OCR settings for the local workspace."""

import os
import re

LANGUAGE_NAMES = {"en": "English", "hi": "Hindi", "es": "Spanish", "fr": "French"}
OCR_CODES = {"en": "eng", "hi": "hin", "es": "spa", "fr": "fra"}
UNSUPPORTED_SCRIPTS = re.compile(r"[\u0400-\u052f\u0590-\u08ff\u0e00-\u0fff\u1100-\u11ff\u3040-\u30ff\u3400-\u9fff]")


def response_language(query: str, requested: str = "auto") -> str:
    """Resolve a supported answer language or reject an unsupported script."""
    if requested not in {"auto", *LANGUAGE_NAMES}:
        raise ValueError("Language must be auto, en, hi, es, or fr.")
    if requested != "auto":
        return requested
    if re.search(r"[\u0900-\u097f]", query):
        return "hi"
    if UNSUPPORTED_SCRIPTS.search(query):
        raise ValueError("This script is not supported yet; choose English, Hindi, Spanish, or French.")
    return "en"


def ocr_languages() -> list[str]:
    """Read a bounded configured OCR language set."""
    requested = [part.strip() for part in os.getenv("RAG_OCR_LANGUAGES", "en,hi,es,fr").split(",")]
    if not requested or any(part not in OCR_CODES for part in requested) or len(set(requested)) != len(requested):
        raise ValueError("RAG_OCR_LANGUAGES must contain unique supported codes: en, hi, es, fr.")
    return [OCR_CODES[part] for part in requested]


def language_instruction(query: str, requested: str = "auto") -> str:
    language = response_language(query, requested)
    return f"Answer in {LANGUAGE_NAMES[language]}. Preserve exact source citation markers and quoted source text."


def insufficient_evidence_message(query: str, requested: str = "auto") -> str:
    return {
        "en": "I don't have enough relevant evidence in the selected documents to answer that question.",
        "hi": "चुने गए दस्तावेज़ों में इस प्रश्न का उत्तर देने के लिए पर्याप्त प्रासंगिक प्रमाण नहीं मिला।",
        "es": "No encontré pruebas pertinentes suficientes en los documentos seleccionados para responder esta pregunta.",
        "fr": "Je n’ai pas trouvé assez de preuves pertinentes dans les documents sélectionnés pour répondre à cette question.",
    }[response_language(query, requested)]
