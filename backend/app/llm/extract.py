"""Turn uploaded files into `DocumentInput`s — the exact shape the Phase 1 rules consume.

Per document:  file intake check -> cache lookup -> model call -> map fields -> grounding.

- Unusable file (unsupported, damaged, password-protected): `file_problem`, no model call -> FILE-01 (vendor).
- Model/system failure: `extraction_error` -> SYS-01 (internal review, fail closed).
- The model never sees form values (blind extraction).
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from app.documents.grounding import apply_grounding
from app.documents.inspect import inspect_file
from app.domain.models import CaseInput, DocumentInput, ExtractedField, Submission
from app.llm.cache import ExtractionCache, cache_key
from app.llm.client import DocumentReader
from app.llm.prompts import PROMPT_VERSION
from app.llm.schema import FIELDS_BY_TYPE

MIME_BY_EXT = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


@dataclass
class UploadedFile:
    slot: str  # where the user uploaded it: gst_certificate | pan_card | bank_proof
    filename: str
    data: bytes
    mime: str = ""  # browser-declared; informational only — the real type is sniffed from content


@dataclass
class Extraction:
    document: DocumentInput
    raw: dict[str, Any] | None = None  # model output as returned (for audit / debugging)
    meta: dict[str, Any] = field(default_factory=dict)  # model, prompt version, latency, tokens, cached


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


def _failed(upload: UploadedFile, meta: dict[str, Any], **problem: str) -> Extraction:
    doc = DocumentInput(slot=upload.slot, filename=upload.filename, classified_type=None, **problem)  # type: ignore[arg-type]
    return Extraction(document=doc, meta=meta)


def read_document(reader: DocumentReader, upload: UploadedFile, cache: ExtractionCache | None = None) -> Extraction:
    meta: dict[str, Any] = {"model": reader.model, "prompt_version": PROMPT_VERSION}

    inspection = inspect_file(upload.data)
    if inspection.problem:
        meta["file_problem"] = inspection.problem
        return _failed(upload, meta, file_problem=inspection.problem)
    mime = inspection.mime
    assert mime is not None

    key = cache_key(upload.data, reader.model)
    entry = cache.get(key) if cache else None
    if entry:
        raw = entry["raw"]
        meta.update(entry["meta"], cached=True)
    else:
        start = time.monotonic()
        try:
            result = reader.read(upload.data, upload.filename, mime)
        except Exception as e:  # network, timeout, refusal, bad JSON — all fail closed
            meta["error"] = f"{type(e).__name__}: {e}"
            meta["latency_ms"] = int((time.monotonic() - start) * 1000)
            return _failed(upload, meta, extraction_error=meta["error"])
        raw = result.data
        meta.update(latency_ms=result.latency_ms, input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens, cached=False)

    try:
        doc = to_document(upload.slot, upload.filename, raw)
    except (KeyError, TypeError, ValueError) as e:  # schema drift; strict mode should prevent this
        meta["error"] = f"Unexpected extraction shape: {e}"
        return _failed(upload, meta, extraction_error=meta["error"])

    if cache and not entry:  # only cache outputs that mapped cleanly
        cache.put(key, {"raw": raw, "meta": {k: meta[k] for k in ("model", "prompt_version", "latency_ms",
                                                                    "input_tokens", "output_tokens")}})
    return Extraction(document=apply_grounding(doc, upload.data, mime), raw=raw, meta=meta)


def read_documents(reader: DocumentReader, uploads: list[UploadedFile],
                   cache: ExtractionCache | None = None) -> dict[str, Extraction]:
    """Read all uploads in parallel; a case takes about as long as its slowest document."""
    if not uploads:
        return {}
    with ThreadPoolExecutor(max_workers=len(uploads)) as pool:
        results = list(pool.map(lambda u: read_document(reader, u, cache), uploads))
    return {u.slot: r for u, r in zip(uploads, results)}


def extract_case(submission: Submission, uploads: list[UploadedFile], reader: DocumentReader,
                 cache: ExtractionCache | None = None) -> tuple[CaseInput, dict[str, Extraction]]:
    """Single entry point: submission + uploaded files -> a CaseInput ready for the rules."""
    extractions = read_documents(reader, uploads, cache)
    case = CaseInput(submission=submission, documents={slot: ex.document for slot, ex in extractions.items()})
    return case, extractions
