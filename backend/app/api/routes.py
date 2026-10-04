"""HTTP API used by the frontend. Every route here sits behind the passcode check (see app.main)."""

from __future__ import annotations

import statistics
from collections import Counter

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import select

from app.api import serializers as ser
from app.db import models as m
from app.db.engine import session_scope
from app.db.storage import uploads_root
from app.documents.inspect import MAX_BYTES
from app.domain.models import CaseInput, Evaluation, Submission
from app.llm.extract import UploadedFile
from app.pipeline.runner import PipelineDeps, default_deps, resubmit_case, submit_case
from app.reference.data import SAMPLES_DIR
from app.rules.catalog import RULES
from app.rules.evaluate import evaluate
from app.samples import load_sample, sample_ids

router = APIRouter(prefix="/api")

SLOTS = ("gst_certificate", "pan_card", "bank_proof")


def get_pipeline_deps() -> PipelineDeps:
    return default_deps()


def _parse_submission(raw: str) -> Submission:
    try:
        return Submission.model_validate_json(raw)
    except ValidationError as e:
        raise HTTPException(422, f"Invalid submission JSON: {e.errors()[:3]}") from e


def _uploads(files: dict[str, UploadFile | None]) -> list[UploadedFile]:
    # Read at most MAX_BYTES + 1 so an oversized file is detected (FILE-01) without loading all of it.
    return [UploadedFile(slot, f.filename or slot, f.file.read(MAX_BYTES + 1), f.content_type or "")
            for slot, f in files.items() if f is not None]


def _case_or_404(session, case_id: int) -> m.Case:
    case = session.get(m.Case, case_id)
    if case is None:
        raise HTTPException(404, f"Case {case_id} not found")
    return case


# ---------- reference ----------

@router.get("/rules")
def rules() -> list[dict]:
    return [{"id": r.id, "stage": r.stage, "group": r.group, "name": r.name, "issue": r.issue,
             "outcome": r.outcome.value, "required": r.required} for r in RULES.values()]


# ---------- samples ("Load sample" in the form) ----------

@router.get("/samples")
def list_samples() -> list[dict]:
    return [{"id": s["id"], "title": s["title"], "description": s["description"]}
            for s in map(load_sample, sample_ids())]


@router.get("/samples/{sample_id}")
def get_sample(sample_id: str) -> dict:
    if sample_id not in sample_ids():
        raise HTTPException(404, f"Unknown sample '{sample_id}'")
    s = load_sample(sample_id)
    return {"id": s["id"], "title": s["title"], "description": s["description"],
            "submission": s["case"]["submission"],
            "files": [{"slot": slot, "filename": d["filename"], "url": f"/api/samples/{sample_id}/files/{d['filename']}"}
                      for slot, d in s["case"]["documents"].items()]}  # expected outcome and ground truth not exposed


@router.get("/samples/{sample_id}/files/{filename}")
def get_sample_file(sample_id: str, filename: str) -> FileResponse:
    if sample_id not in sample_ids():
        raise HTTPException(404, "Unknown sample")
    allowed = {d["filename"] for d in load_sample(sample_id)["case"]["documents"].values()}
    if filename not in allowed:  # whitelist: never build a path from user input
        raise HTTPException(404, "Unknown file")
    return FileResponse(SAMPLES_DIR / sample_id / filename, media_type="application/pdf", filename=filename)


# ---------- cases ----------

@router.post("/cases", status_code=201)
def create_case_endpoint(
    submission: str = Form(..., description="Submission JSON"),
    gst_certificate: UploadFile | None = File(None),
    pan_card: UploadFile | None = File(None),
    bank_proof: UploadFile | None = File(None),
    sample_id: str | None = Form(None, description="Set when the form was filled from a demo sample"),
    submitted_by: str = Form("vendor"),
    deps: PipelineDeps = Depends(get_pipeline_deps),
) -> dict:
    """Store the submission and start the pipeline in the background; poll GET /api/runs/{run_id}."""
    form = _parse_submission(submission)
    uploads = _uploads({"gst_certificate": gst_certificate, "pan_card": pan_card, "bank_proof": bank_proof})
    if sample_id is not None and sample_id not in sample_ids():
        sample_id = None
    case_id, run_id = submit_case(form, uploads, submitted_by=submitted_by, sample_id=sample_id, deps=deps)
    return {"case_id": case_id, "reference": f"VO-{case_id:04d}", "run_id": run_id}


@router.post("/cases/{case_id}/resubmit", status_code=201)
def resubmit_endpoint(
    case_id: int,
    submission: str = Form(...),
    gst_certificate: UploadFile | None = File(None),
    pan_card: UploadFile | None = File(None),
    bank_proof: UploadFile | None = File(None),
    submitted_by: str = Form("operations (on behalf of vendor)"),
    deps: PipelineDeps = Depends(get_pipeline_deps),
) -> dict:
    """New version with only the changed files; unchanged documents carry over."""
    with session_scope() as s:
        case = _case_or_404(s, case_id)
        if not ser.case_detail_json(case)["can_resubmit"]:
            raise HTTPException(409, f"{case.reference} can't be resubmitted (status {case.status}, or a run is in progress)")
    form = _parse_submission(submission)
    uploads = _uploads({"gst_certificate": gst_certificate, "pan_card": pan_card, "bank_proof": bank_proof})
    run_id = resubmit_case(case_id, form, uploads, submitted_by=submitted_by, deps=deps)
    with session_scope() as s:
        version = s.get(m.Run, run_id).submission.version
    return {"case_id": case_id, "run_id": run_id, "version": version}


@router.get("/cases")
def list_cases(
    status: str | None = Query(None, description="APPROVED | AWAITING_VENDOR | INTERNAL_REVIEW | REJECTED | IN_PROGRESS"),
    rule: str | None = Query(None, description="Only cases currently failing this rule, e.g. BANK-03"),
    q: str | None = Query(None, description="Search vendor name, GSTIN or reference"),
    limit: int = Query(200, le=500),
) -> list[dict]:
    with session_scope() as s:
        rows = [ser.case_row_json(c) for c in s.scalars(select(m.Case).order_by(m.Case.id.desc()).limit(limit))]
    if status:
        rows = [r for r in rows if r["display_status"] == status]
    if rule:
        rows = [r for r in rows if any(x["rule_id"] == rule for x in r["reasons"])]
    if q:
        needle = q.strip().lower()
        rows = [r for r in rows if needle in (r["vendor_name"] or "").lower()
                or needle in (r["gstin"] or "").lower() or needle in r["reference"].lower()]
    return rows


@router.get("/cases/{case_id}")
def get_case(case_id: int, version: int | None = None) -> dict:
    with session_scope() as s:
        case = _case_or_404(s, case_id)
        try:
            return ser.case_detail_json(case, version)
        except KeyError:
            raise HTTPException(404, f"{case.reference} has no version {version}") from None


@router.get("/cases/{case_id}/documents/{doc_id}")
def get_document(case_id: int, doc_id: int) -> FileResponse:
    with session_scope() as s:
        doc = s.get(m.Document, doc_id)
        if doc is None or doc.submission.case_id != case_id:  # a document is only reachable via its own case
            raise HTTPException(404, "Document not found")
        path, filename = uploads_root() / doc.path, doc.filename
    media = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg"}.get(path.suffix, "application/octet-stream")
    return FileResponse(path, media_type=media, filename=filename, content_disposition_type="inline")


@router.get("/cases/{case_id}/audit")
def get_audit(case_id: int) -> list[dict]:
    with session_scope() as s:
        _case_or_404(s, case_id)
        return [ser.audit_json(e) for e in s.scalars(
            select(m.AuditEvent).where(m.AuditEvent.case_id == case_id).order_by(m.AuditEvent.id))]


@router.get("/runs/{run_id}")
def get_run(run_id: int) -> dict:
    with session_scope() as s:
        run = s.get(m.Run, run_id)
        if run is None:
            raise HTTPException(404, f"Run {run_id} not found")
        return ser.run_json(run)


@router.get("/review-queue")
def review_queue() -> list[dict]:
    """Cases waiting on a human, oldest decision first."""
    with session_scope() as s:
        cases = s.scalars(select(m.Case).where(m.Case.status == "PENDING", m.Case.sub_state == "INTERNAL_REVIEW")
                          .order_by(m.Case.decided_at.asc()))
        return [ser.case_row_json(c) for c in cases]


@router.get("/metrics")
def metrics() -> dict:
    with session_scope() as s:
        cases = list(s.scalars(select(m.Case)))
        reviewed = {cid for (cid,) in s.execute(select(m.ReviewAction.case_id))}
        first_runs = [c.runs[0] for c in cases if c.runs]
        by_status = Counter(ser.display_status(c.status, c.sub_state) for c in cases)
        decided = [c for c in cases if c.status in ("APPROVED", "PENDING", "REJECTED")]
        straight_through = [c for c in decided if c.status == "APPROVED" and len(c.runs) == 1 and c.id not in reviewed]
        times = [(r.finished_at - r.created_at).total_seconds() for r in first_runs
                 if r.status == "completed" and r.finished_at]
        reasons = Counter(rid for c in cases if c.status != "APPROVED" for rid in c.failing_rules)
    return {
        "total": len(cases),
        "by_status": {k: by_status.get(k, 0) for k in
                      ("APPROVED", "AWAITING_VENDOR", "INTERNAL_REVIEW", "REJECTED", "IN_PROGRESS")},
        # Approved on the first run with no human touch, as a share of all decided cases.
        "straight_through_rate": round(len(straight_through) / len(decided), 3) if decided else None,
        "median_seconds_to_decision": round(statistics.median(times), 1) if times else None,
        "top_reasons": [{"rule_id": rid, "issue": RULES[rid].issue, "count": n} for rid, n in reasons.most_common(5)],
    }


# ---------- developer tool ----------

@router.post("/evaluate")
def evaluate_json(case: CaseInput) -> Evaluation:
    """Rules only, on a JSON case with pre-filled extracted fields (no AI, nothing stored)."""
    return evaluate(case)
