"""Grounding: is each extracted value actually printed in the document's text layer?

Strict structured output guarantees the *shape* of the model's answer, not that the values are on the
page. For digital PDFs we can check that deterministically. Scans and images have no text layer, so their
values are marked "image" (format checks in DOC-03 still apply to them).
"""

from __future__ import annotations

import re

from app.documents.inspect import open_pdf
from app.domain.models import DocumentInput


def pdf_text(data: bytes) -> str:
    try:
        return "\n".join(page.extract_text() or "" for page in open_pdf(data).pages)
    except Exception:
        return ""


def squash(text: str) -> str:
    """Letters and digits only, uppercased: tolerant of spacing, line wraps and punctuation,
    strict about the characters themselves."""
    return re.sub(r"[^0-9A-Z]", "", text.upper())


def apply_grounding(doc: DocumentInput, data: bytes, mime: str) -> DocumentInput:
    text = squash(pdf_text(data)) if mime == "application/pdf" else ""
    for f in doc.fields.values():
        if not text:
            f.grounded = "image"
        elif f.value and squash(f.value) and squash(f.value) in text:
            f.grounded = "text"
        else:
            f.grounded = "unverified"
    return doc
