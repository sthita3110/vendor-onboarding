"""Turn uploaded files into `DocumentInput`s — the exact shape the Phase 1 rules consume.

The model never sees form values (blind extraction). Any failure is recorded on the document as
`extraction_error`, which the rules treat as a system error -> SYS-01 -> internal review.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from app.domain.models import DocumentInput, ExtractedField
from app.llm.client import DocumentReader, ReadResult
from app.llm.prompts import PROMPT_VERSION
from app.llm.schema import FIELDS_BY_TYPE

MIME_BY_EXT = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


@dataclass
class UploadedFile:
    slot: str  # where the user uploaded it: gst_certificate | pan_card | bank_proof
    filename: str
    data: bytes
    mime: str


@dataclass
class Extraction:
    document: DocumentInput
    raw: dict[str, Any] | None = None  # model output as returned (for audit / debugging)
    meta: dict[str, Any] = field(default_factory=dict)  # model, prompt version, latency, tokens


def to_document(slot: str, filename: str, raw: dict[str, Any]) -> DocumentInput:
    """Map model output to a DocumentInput, keeping only fields that belong to the identified type."""
    doc_type = raw["doc_type"]
    fields: dict[str, ExtractedField] = {}
    for name in FIELDS_BY_TYPE.get(doc_type, []):
        f = raw["fields"].get(name) or {}
        value = f.get("value")
        if value is not None and str(value).strip():
            fields[name] = ExtractedField(value=str(value).strip(), quote=f.get("quote"), page=f.get("page"))
    return DocumentInput(
        slot=slot,  # type: ignore[arg-type]
        filename=filename,
        classified_type=doc_type,
        readable=bool(raw["readable"]),
        fields=fields,
    )


def read_document(reader: DocumentReader, upload: UploadedFile) -> Extraction:
    meta: dict[str, Any] = {"model": reader.model, "prompt_version": PROMPT_VERSION}
    try:
        result: ReadResult = reader.read(upload.data, upload.filename, upload.mime)
    except Exception as e:  # network, timeout, refusal, bad JSON — all fail closed
        meta["error"] = f"{type(e).__name__}: {e}"
        return Extraction(
            document=DocumentInput(slot=upload.slot, filename=upload.filename,  # type: ignore[arg-type]
                                   classified_type=None, extraction_error=meta["error"]),
            meta=meta,
        )
    meta.update(latency_ms=result.latency_ms, input_tokens=result.input_tokens, output_tokens=result.output_tokens)
    try:
        doc = to_document(upload.slot, upload.filename, result.data)
    except (KeyError, TypeError, ValueError) as e:  # schema drift; strict mode should prevent this
        meta["error"] = f"Unexpected extraction shape: {e}"
        doc = DocumentInput(slot=upload.slot, filename=upload.filename,  # type: ignore[arg-type]
                            classified_type=None, extraction_error=meta["error"])
    return Extraction(document=doc, raw=result.data, meta=meta)


def read_documents(reader: DocumentReader, uploads: list[UploadedFile]) -> dict[str, Extraction]:
    """Read all uploads in parallel; a case takes about as long as its slowest document."""
    if not uploads:
        return {}
    with ThreadPoolExecutor(max_workers=len(uploads)) as pool:
        results = list(pool.map(lambda u: read_document(reader, u), uploads))
    return {u.slot: r for u, r in zip(uploads, results)}
