"""FastAPI app. Exposes the decision core and (step 2d) an upload endpoint that runs real extraction.
Phase 3 replaces the upload endpoint with stored cases, background runs, and review."""

from __future__ import annotations

import hmac
import json
from functools import lru_cache

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from pydantic import ValidationError

from app.config import get_settings
from app.documents.inspect import MAX_BYTES
from app.domain.models import CaseInput, Evaluation, Submission
from app.llm.cache import make_cache
from app.llm.client import DocumentReader, make_reader
from app.llm.extract import UploadedFile, extract_case
from app.reference.data import SAMPLES_DIR
from app.rules.catalog import CATALOG_VERSION, RULES
from app.rules.checks import EvaluationContext
from app.rules.evaluate import default_context, evaluate

app = FastAPI(title="Vendor Onboarding", version="0.1.0")


@lru_cache
def context() -> EvaluationContext:
    return default_context()


def _samples() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text()) for p in sorted(SAMPLES_DIR.glob("*.json"))}


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "rule_catalog_version": CATALOG_VERSION}


@app.get("/api/rules")
def rules() -> list[dict]:
    return [
        {"id": r.id, "stage": r.stage, "group": r.group, "name": r.name,
         "outcome": r.outcome.value, "required": r.required}
        for r in RULES.values()
    ]


@app.get("/api/samples")
def list_samples() -> list[dict]:
    return [{"id": s["id"], "title": s["title"], "description": s["description"]} for s in _samples().values()]


@app.get("/api/samples/{sample_id}")
def get_sample(sample_id: str) -> dict:
    sample = _samples().get(sample_id)
    if sample is None:
        raise HTTPException(404, f"Unknown sample '{sample_id}'")
    return {k: sample[k] for k in ("id", "title", "description", "case")}  # expected outcome not exposed


@app.post("/api/evaluate")
def evaluate_case(case: CaseInput) -> Evaluation:
    return evaluate(case, context())


@app.post("/api/samples/{sample_id}/evaluate")
def evaluate_sample(sample_id: str) -> Evaluation:
    return evaluate_case(CaseInput.model_validate(get_sample(sample_id)["case"]))


# ---------- step 2d: real extraction ----------

def require_passcode(x_app_passcode: str | None = Header(default=None)) -> None:
    """Endpoints that spend money on the OpenAI key are gated when APP_PASSCODE is set (always, in prod)."""
    expected = get_settings().app_passcode
    if expected and not hmac.compare_digest(x_app_passcode or "", expected):
        raise HTTPException(401, "Missing or wrong passcode")


def get_reader() -> DocumentReader:
    try:
        return make_reader()
    except RuntimeError as e:  # no API key configured
        raise HTTPException(503, f"Document reading is unavailable: {e}") from e


def _read_upload(slot: str, f: UploadFile | None) -> UploadedFile | None:
    if f is None:
        return None
    # Read at most MAX_BYTES + 1 so an oversized file is detected (FILE-01) without loading all of it.
    return UploadedFile(slot, f.filename or slot, f.file.read(MAX_BYTES + 1), f.content_type or "")


@app.post("/api/evaluate-upload", dependencies=[Depends(require_passcode)])
def evaluate_upload(
    submission: str = Form(..., description="Submission JSON (same shape as CaseInput.submission)"),
    gst_certificate: UploadFile | None = File(None),
    pan_card: UploadFile | None = File(None),
    bank_proof: UploadFile | None = File(None),
    reader: DocumentReader = Depends(get_reader),
) -> dict:
    """Form + up to three files -> extraction -> rules -> decision. A missing file is allowed: it becomes COMP-02."""
    try:
        sub = Submission.model_validate_json(submission)
    except ValidationError as e:
        raise HTTPException(422, f"Invalid submission JSON: {e.errors()[:3]}") from e
    uploads = [u for u in (_read_upload("gst_certificate", gst_certificate), _read_upload("pan_card", pan_card),
                           _read_upload("bank_proof", bank_proof)) if u]
    case, extractions = extract_case(sub, uploads, reader, make_cache())
    ev = evaluate(case, context())
    return {
        **ev.model_dump(mode="json"),
        "extractions": {
            slot: {"filename": ex.document.filename, "classified_type": ex.document.classified_type,
                   "fields": {k: f.model_dump() for k, f in ex.document.fields.items()}, "meta": ex.meta}
            for slot, ex in extractions.items()
        },
    }
