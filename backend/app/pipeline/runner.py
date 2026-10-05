"""Pipeline runner: executes a run stage by stage in the background, persisting progress for the live view.

Flow:
  submit_case()/resubmit_case()  -> stores the submission, creates a run + 10 pending stage rows, starts it
  replay_case()                  -> new run on the case's latest submission (same files), executed normally
  run_pipeline(run_id)           -> for each stage: mark running -> do the work -> mark done (outcome, summary)
  recover_interrupted_runs()     -> at startup: unfinished runs -> interrupted -> case to internal review

Heavy work (model calls, provider calls) happens outside DB transactions; each stage update is its own
short transaction, so a polling UI sees progress as it happens. Every failure path fails closed:
the case goes to internal review with SYS-01, never to approval.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace

from sqlalchemy import select

from app.db import models as m
from app.db.audit import audit
from app.db.engine import session_scope
from app.db.repository import (
    add_submission,
    create_case,
    create_run,
    find_cases_for_entity,
    is_open,
    load_uploads,
    prior_rejections,
    save_evaluation,
    superseded_by,
    set_case_status,
)
from app.domain.models import CaseInput, CheckResult, Decision, DocumentInput, Evaluation
from app.domain.models import Submission as SubmissionForm
from app.llm.cache import ExtractionCache, make_cache
from app.llm.client import DocumentReader, make_reader
from app.llm.extract import Extraction, UploadedFile, read_documents
from app.rules import checks
from app.rules.checks import EvaluationContext, RunState
from app.rules.engine import decide
from app.rules.evaluate import default_context

log = logging.getLogger(__name__)

# (key, label) in display order. Rule stages map to app.rules.checks stage functions below.
STAGES: list[tuple[str, str]] = [
    ("intake", "Submission received"),
    ("completeness", "Checking completeness"),
    ("read_documents", "Reading documents"),
    ("doc_checks", "Checking what we read"),
    ("validation", "Validating details"),
    ("cross_check", "Cross-checking"),
    ("external_verify", "Verifying with GST registry and bank"),
    ("risk", "Risk screening"),
    ("decision", "Deciding"),
    ("notify", "Notifying"),
]

RULE_STAGES: dict[str, list[Callable[[RunState], None]]] = {
    "completeness": [checks.stage_completeness],
    "doc_checks": [checks.stage_doc_processing, checks.stage_extraction],
    "validation": [checks.stage_validation],
    "cross_check": [checks.stage_cross_check],
    "external_verify": [checks.stage_external_verify],
    "risk": [checks.stage_risk],
}

PASS_SUMMARY = {
    "completeness": "All required details and documents provided",
    "doc_checks": "All documents opened, are the right type, and were read reliably",
    "validation": "GSTIN, PAN, IFSC and account number are valid",
    "cross_check": "Names, tax IDs and bank details are consistent across the form and documents",
    "risk": "Not on the debarred list · not an existing vendor · bank account not used by another vendor",
}

INTERRUPTED_REASON = "Run did not finish (server restarted or crashed); needs a manual re-run"


@dataclass
class PipelineDeps:
    """Injectable dependencies (tests pass fakes)."""

    reader_factory: Callable[[], DocumentReader] = make_reader
    cache: ExtractionCache | None = field(default_factory=make_cache)
    ctx: EvaluationContext = field(default_factory=default_context)
    background: bool = True  # tests set False to run synchronously


_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pipeline")
_default_deps: PipelineDeps | None = None


def default_deps() -> PipelineDeps:
    global _default_deps
    if _default_deps is None:
        _default_deps = PipelineDeps()
    return _default_deps


# ---------- submission entry points ----------

def _create_stage_rows(session, run: m.Run) -> None:
    for seq, (key, label) in enumerate(STAGES):
        session.add(m.StageEvent(run_id=run.id, seq=seq, stage=key, label=label))


class DuplicateCaseError(Exception):
    """The legal entity already has a case: continue on it (open, resubmit, replay) instead of a new one."""

    def __init__(self, case_ids: list[int]):
        super().__init__(f"Existing case(s) for this entity: {case_ids}")
        self.case_ids = case_ids


def submit_case(form: SubmissionForm, uploads: list[UploadedFile], *, submitted_by: str = "vendor",
                source: str = "form", sample_id: str | None = None, background: bool = True,
                deps: PipelineDeps | None = None) -> tuple[int, int]:
    """Store a new case and start its first run. Returns (case_id, run_id) immediately when background.

    Raises DuplicateCaseError, creating nothing (no case, no stored files, no model call), when the legal
    entity already has a case: reprocessing is a Replay (new run), a correction is a Resubmit (new version)."""
    with session_scope() as s:
        duplicates = [c.id for c in find_cases_for_entity(s, form)]
        for case_id in duplicates:  # leave a trace on the case someone tried to duplicate
            audit(s, case_id, "duplicate_submission.blocked", actor=submitted_by, sample_id=sample_id,
                  pan=form.pan, gstin=form.gstin)
    if duplicates:  # raised after the session commits, so the audit rows are kept
        raise DuplicateCaseError(duplicates)
    with session_scope() as s:
        case = create_case(s, form, uploads, submitted_by=submitted_by, source=source, sample_id=sample_id)
        run = create_run(s, case, case.submissions[0], trigger="submission")
        _create_stage_rows(s, run)
        case_id, run_id = case.id, run.id
    start_run(run_id, background=background, deps=deps)
    return case_id, run_id


def resubmit_case(case_id: int, form: SubmissionForm, uploads: list[UploadedFile], *,
                  submitted_by: str = "vendor", background: bool = True,
                  deps: PipelineDeps | None = None) -> int:
    """New submission version on an existing case (changed files only) and a new run. Returns run_id."""
    with session_scope() as s:
        case = s.get(m.Case, case_id)
        if case is None:
            raise LookupError(f"Case {case_id} not found")
        sub = add_submission(s, case, form, uploads, submitted_by=submitted_by)
        run = create_run(s, case, sub, trigger="resubmission")
        _create_stage_rows(s, run)
        set_case_status(s, case, "RECEIVED", None, [], actor=submitted_by, run_id=run.id,
                        reason=f"Resubmitted as version {sub.version}")
        run_id = run.id
    start_run(run_id, background=background, deps=deps)
    return run_id


class RunInProgressError(RuntimeError):
    pass


class ReapplyNotAllowedError(RuntimeError):
    """Reapply is only for a rejected case whose entity has no open case."""


class DifferentEntityError(ValueError):
    """The reapplication's PAN/GSTIN don't identify the rejected case's entity: that's a new vendor, not a reapply."""


def reapply_case(previous_case_id: int, form: SubmissionForm, uploads: list[UploadedFile], *,
                 submitted_by: str = "vendor", background: bool = True,
                 deps: PipelineDeps | None = None) -> tuple[int, int]:
    """A genuinely new application after rejection: a NEW case linked to the rejected one, which stays final.
    The run sees the rejection history, so PRIOR-01 sends it to internal review (never auto-approved)."""
    with session_scope() as s:
        prev = s.get(m.Case, previous_case_id)
        if prev is None:
            raise LookupError(f"Case {previous_case_id} not found")
        if prev.status != "REJECTED":
            raise ReapplyNotAllowedError(f"{prev.reference} is not rejected; resubmit or replay it instead")
        later = superseded_by(s, prev)
        if later:
            raise ReapplyNotAllowedError(
                f"{prev.reference} was already followed by {later[-1].reference}; continue from there instead")
        entity_cases = find_cases_for_entity(s, form)
        if prev.id not in {c.id for c in entity_cases}:
            raise DifferentEntityError(
                f"This PAN/GSTIN doesn't match {prev.reference}; submit it as a new vendor instead")
        open_cases = [c for c in entity_cases if is_open(c)]
        if open_cases:
            raise ReapplyNotAllowedError(
                f"{open_cases[0].reference} is already open for this entity; continue there instead")
        case = create_case(s, form, uploads, submitted_by=submitted_by, previous_case_id=prev.id)
        run = create_run(s, case, case.submissions[0], trigger="reapplication")
        _create_stage_rows(s, run)
        audit(s, prev.id, "case.reapplied", actor=submitted_by, new_case_id=case.id, new_reference=case.reference)
        case_id, run_id = case.id, run.id
    start_run(run_id, background=background, deps=deps)
    return case_id, run_id


def replay_case(case_id: int, *, requested_by: str = "operations", use_cache: bool = False,
                background: bool = True, deps: PipelineDeps | None = None) -> int:
    """Execute the full pipeline again on the case's latest submission (same files, new run).
    Fresh model calls by default (use_cache=False): a replay demonstrates real execution, not a cache hit."""
    with session_scope() as s:
        case = s.get(m.Case, case_id)
        if case is None:
            raise LookupError(f"Case {case_id} not found")
        if any(r.status in ("queued", "running") for r in case.runs):
            raise RunInProgressError(f"{case.reference} already has a run in progress")
        sub = case.submissions[-1]
        run = create_run(s, case, sub, trigger="replay")
        _create_stage_rows(s, run)
        audit(s, case.id, "run.replayed", actor=requested_by, run_id=run.id, submission_version=sub.version,
              use_cache=use_cache, previous_status=case.status)
        set_case_status(s, case, "RECEIVED", None, [], actor=requested_by, run_id=run.id,
                        reason=f"Replay of version {sub.version} requested")
        run_id = run.id
    deps = deps or default_deps()
    if not use_cache:
        deps = replace(deps, cache=None)
    start_run(run_id, background=background, deps=deps)
    return run_id


def start_run(run_id: int, *, background: bool = True, deps: PipelineDeps | None = None) -> Future | None:
    if background and (deps is None or deps.background):
        return _executor.submit(run_pipeline, run_id, deps)
    run_pipeline(run_id, deps)
    return None


# ---------- stage bookkeeping (each update is its own short transaction) ----------

def _mark(run_id: int, stage: str, **values) -> None:
    with session_scope() as s:
        ev = s.scalars(select(m.StageEvent).where(m.StageEvent.run_id == run_id, m.StageEvent.stage == stage)).one()
        for k, v in values.items():
            setattr(ev, k, v)


def summarize_rules(key: str, new: list[CheckResult]) -> tuple[str, str, dict]:
    fails = [r for r in new if r.status == "fail"]
    errors = [r for r in new if r.status == "error"]
    blocked = [r for r in new if r.status == "blocked"]
    details = {"rules": sorted({r.rule_id for r in new}),
               "failing_rules": sorted({r.rule_id for r in fails}),
               "counts": {"pass": sum(r.status == "pass" for r in new), "fail": len(fails),
                          "blocked": len(blocked), "error": len(errors)}}
    if errors:
        return "error", errors[0].title, details
    if fails:
        more = f" (+{len(fails) - 1} more)" if len(fails) > 1 else ""
        return "issues", fails[0].title + more, details
    if blocked and not any(r.status == "pass" for r in new):
        return "blocked", f"Skipped {len(blocked)} check(s) because of earlier findings", details
    if key == "external_verify":
        details["simulated"] = True
        return "pass", _external_summary(new), details
    summary = PASS_SUMMARY.get(key, "All checks passed")
    if blocked:
        summary += f" · {len(blocked)} skipped because of earlier findings"
    return "pass", summary, details


def _external_summary(results: list[CheckResult]) -> str:
    parts = []
    for r in results:
        resp = r.evidence.get("adapter_response") or {}
        if r.rule_id == "TAX-06" and r.status == "pass":
            parts.append("GST registration active")
        elif r.rule_id == "BANK-03" and r.status == "pass":
            parts.append(f"bank account holder '{resp.get('holder_name')}' matches")
    return (" · ".join(parts) or "Verified") + " (simulated providers)"


def _summarize_reading(extractions: dict[str, Extraction], seconds: float) -> tuple[str, str, dict]:
    docs = [ex.document for ex in extractions.values()]
    errors = [d for d in docs if d.extraction_error]
    unusable = [d for d in docs if d.file_problem]
    scanned = [d for d in docs if d.fields and all(f.grounded == "image" for f in d.fields.values())]
    cached = sum(bool(ex.meta.get("cached")) for ex in extractions.values())
    details = {
        "seconds": round(seconds, 1), "documents": len(docs), "scanned": len(scanned), "cached": cached,
        "per_document": {slot: {"filename": ex.document.filename, "type": ex.document.classified_type,
                                "scanned": bool(ex.document.fields) and all(
                                    f.grounded == "image" for f in ex.document.fields.values()),
                                "latency_ms": ex.meta.get("latency_ms"), "cached": ex.meta.get("cached"),
                                "error": ex.document.extraction_error, "file_problem": ex.document.file_problem}
                         for slot, ex in extractions.items()},
    }
    if errors:
        return "error", f"Couldn't read {len(errors)} document(s): {errors[0].extraction_error}", details
    read = len(docs) - len(unusable)
    summary = f"Read {read} document{'s' if read != 1 else ''}"
    if scanned:
        summary += f" ({len(scanned)} scanned)"
    summary += f" in {seconds:.1f}s"
    if cached:
        summary += f" · {cached} from cache"
    if unusable:
        return "issues", summary + f" · {len(unusable)} file(s) couldn't be opened", details
    return "pass", summary, details


def summarize_decision(decision: Decision) -> tuple[str, str, dict]:
    outcome = {"APPROVED": "pass", "REJECTED": "issues"}.get(decision.status.value, "issues")
    return outcome, decision.summary, {"status": decision.status.value,
                                       "sub_state": decision.sub_state.value if decision.sub_state else None,
                                       "failing_rules": decision.failing_rules}


def notify_note(decision: Decision) -> str:
    asks = len(decision.vendor_actions)
    vendor_note = f"{asks} item(s) to request from the vendor" if asks else ""
    if decision.sub_state and decision.sub_state.value == "INTERNAL_REVIEW":
        # Mixed case: review owns the status, but vendor-fixable items are requested in parallel.
        return "Added to the internal review queue" + (f" · {vendor_note}" if asks else "")
    if decision.sub_state and decision.sub_state.value == "AWAITING_VENDOR":
        return vendor_note
    return "No follow-up needed"


# ---------- the run ----------

def run_pipeline(run_id: int, deps: PipelineDeps | None = None) -> None:
    deps = deps or default_deps()
    current = "intake"
    try:
        with session_scope() as s:
            run = s.get(m.Run, run_id)
            run.status, run.started_at = "running", m.utcnow()
            case_id, version = run.case_id, run.submission.version
            form = SubmissionForm.model_validate(run.submission.payload)
            uploads = load_uploads(run.submission)
            reference = run.case.reference
            # Case history for PRIOR-01: earlier rejected applications by the same entity (not this case).
            prior = prior_rejections(s, form, exclude_case_id=case_id)
            audit(s, case_id, "run.started", run_id=run_id)

        # 0. intake
        _mark(run_id, "intake", status="running", started_at=m.utcnow())
        _mark(run_id, "intake", status="done", outcome="pass", finished_at=m.utcnow(),
              summary=f"{reference} version {version}: {len(uploads)} document(s) received",
              details={"documents": [{"slot": u.slot, "filename": u.filename} for u in uploads]})

        # Rule stages share one RunState. Completeness only needs to know which slots were uploaded,
        # so it runs on placeholders; real extracted documents replace them after reading.
        placeholders = {u.slot: DocumentInput(slot=u.slot, filename=u.filename) for u in uploads}  # type: ignore[arg-type]
        state = RunState(case=CaseInput(submission=form, documents=placeholders, prior_rejections=prior), ctx=deps.ctx)
        extractions: dict[str, Extraction] = {}

        for key, _label in STAGES[1:8]:
            current = key
            _mark(run_id, key, status="running", started_at=m.utcnow())
            if key == "read_documents":
                start = time.monotonic()
                try:
                    reader = deps.reader_factory()
                except Exception as e:  # e.g. no API key: every document fails -> SYS-01 later
                    extractions = {u.slot: Extraction(document=DocumentInput(
                        slot=u.slot, filename=u.filename, extraction_error=f"Reader unavailable: {e}"))  # type: ignore[arg-type]
                        for u in uploads}
                else:
                    extractions = read_documents(reader, uploads, deps.cache)
                state.case = CaseInput(submission=form, documents={s_: ex.document for s_, ex in extractions.items()},
                                       prior_rejections=prior)
                outcome, summary, details = _summarize_reading(extractions, time.monotonic() - start)
            else:
                before = len(state.results)
                for stage_fn in RULE_STAGES[key]:
                    stage_fn(state)
                outcome, summary, details = summarize_rules(key, state.results[before:])
            _mark(run_id, key, status="done", outcome=outcome, summary=summary, details=details,
                  finished_at=m.utcnow())

        # 8. decision
        current = "decision"
        _mark(run_id, "decision", status="running", started_at=m.utcnow())
        decision = decide(state.results)
        with session_scope() as s:
            run = s.get(m.Run, run_id)
            save_evaluation(s, run, extractions, Evaluation(decision=decision, results=state.results))
        outcome, summary, details = summarize_decision(decision)
        _mark(run_id, "decision", status="done", outcome=outcome, summary=summary, details=details,
              finished_at=m.utcnow())

        # 9. notify — vendor message generation arrives in Phase 5
        current = "notify"
        _mark(run_id, "notify", status="running", started_at=m.utcnow())
        _mark(run_id, "notify", status="done", outcome="pass", summary=notify_note(decision), finished_at=m.utcnow())

        with session_scope() as s:
            run = s.get(m.Run, run_id)
            run.status, run.finished_at = "completed", m.utcnow()
            audit(s, case_id, "run.completed", run_id=run_id, status=decision.status.value)

    except Exception as e:  # anything unexpected: fail closed
        log.exception("Run %s failed in stage %s", run_id, current)
        _fail_run(run_id, current, f"{type(e).__name__}: {e}")


def _fail_run(run_id: int, stage: str, error: str, *, interrupted: bool = False) -> None:
    with session_scope() as s:
        run = s.get(m.Run, run_id)
        run.status = "interrupted" if interrupted else "failed"
        run.error, run.finished_at = error, m.utcnow()
        for ev in run.stage_events:
            if ev.status == "running" or (ev.stage == stage and ev.status != "done"):
                ev.status, ev.outcome, ev.summary, ev.finished_at = "failed", "error", error, m.utcnow()
        audit(s, run.case_id, "run.interrupted" if interrupted else "run.failed", run_id=run_id,
              stage=stage, error=error)
        set_case_status(s, run.case, "PENDING", "INTERNAL_REVIEW", ["SYS-01"], run_id=run_id,
                        reason=INTERRUPTED_REASON if interrupted else f"Run failed: {error}")


def recover_interrupted_runs() -> list[int]:
    """At startup: no run can still be executing, so any queued/running run was cut off. Fail closed."""
    with session_scope() as s:
        stuck = [(r.id, next((e.stage for e in r.stage_events if e.status == "running"), "intake"))
                 for r in s.scalars(select(m.Run).where(m.Run.status.in_(("queued", "running"))))]
    for run_id, stage in stuck:
        _fail_run(run_id, stage, INTERRUPTED_REASON, interrupted=True)
    return [run_id for run_id, _ in stuck]
