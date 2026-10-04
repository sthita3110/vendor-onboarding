"""Seed demo cases on startup — pre-populated history, NOT an execution.

When the database is empty (fresh deploy, or the free tier's disk was reset), store each demo case with
its submission v1, its real PDFs, and one completed run of type "seed" whose extractions, check results,
stage summaries and decision are derived from the sample's existing data:

- Extractions = the sample's ground-truth document fields (no OpenAI call).
- Check results = the deterministic rules applied to those fields (a pure function; mock providers at 0 ms).
- The derived outcome must equal the sample's expected outcome, or seeding stops (SeedMismatchError).

The pipeline runner is never invoked here. To demonstrate the real 10-stage execution on a seeded case,
use Replay (app.pipeline.runner.replay_case), which creates a new run and executes it normally.

E3R is deliberately not seeded: it is E3's corrected resubmission, so E3 is seeded as "awaiting vendor"
and the resubmission can be demonstrated live with E3R's files.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.adapters.mock import MockGstRegistry, MockPennyDrop
from app.db import models as m
from app.db.audit import audit
from app.db.engine import session_scope
from app.db.repository import create_case, create_run, save_evaluation
from app.domain.models import CaseInput, DocumentInput, Evaluation
from app.llm.extract import Extraction
from app.pipeline.runner import STAGES, notify_note, summarize_decision, summarize_rules
from app.reference.data import REFERENCE_DIR, load_reference
from app.rules.checks import EvaluationContext
from app.rules.evaluate import evaluate
from app.samples import load_sample, sample_submission, sample_uploads

log = logging.getLogger(__name__)

SEED_IDS = ["H1", "E1", "E2", "E3", "E4", "E5"]
SEED_ACTOR = "system (seed)"
SEED_LABEL = "Seeded sample"

# Rule stage (CheckResult.stage) -> display stage it is summarized under.
_DISPLAY_STAGE = {"completeness": "completeness", "doc_processing": "doc_checks", "extraction": "doc_checks",
                  "validation": "validation", "cross_check": "cross_check", "external_verify": "external_verify",
                  "risk": "risk"}


class SeedMismatchError(RuntimeError):
    """The rules no longer produce a sample's expected outcome — seeding refuses to store wrong history."""


def _seed_context() -> EvaluationContext:
    return EvaluationContext(  # 0 ms: simulated latency is for the live view, not for seeding
        ref=load_reference(),
        registry=MockGstRegistry.from_file(REFERENCE_DIR / "gst_registry.json", 0),
        bank=MockPennyDrop.from_file(REFERENCE_DIR / "penny_drop.json", 0),
    )


def _check_expected(cid: str, sample: dict, ev: Evaluation) -> None:
    exp, d = sample["expected"], ev.decision
    got = (d.status.value, d.sub_state.value if d.sub_state else None, set(d.failing_rules))
    want = (exp["status"], exp["sub_state"], set(exp["failing_rules"]))
    if got != want:
        raise SeedMismatchError(f"{cid}: rules produce {got}, sample expects {want}")


def _stage_rows(run: m.Run, ev: Evaluation, n_docs: int) -> list[m.StageEvent]:
    now = m.utcnow()
    rows = []
    for seq, (key, label) in enumerate(STAGES):
        if key == "intake":
            outcome, summary, details = "pass", f"{SEED_LABEL}: {n_docs} document(s) loaded", {"seeded": True}
        elif key == "read_documents":
            outcome, summary, details = ("pass", f"{SEED_LABEL}: fields taken from the sample's known data, "
                                         "not read live. Use Replay to run the AI.", {"seeded": True})
        elif key == "decision":
            outcome, summary, details = summarize_decision(ev.decision)
        elif key == "notify":
            outcome, summary, details = "pass", notify_note(ev.decision), {}
        else:
            outcome, summary, details = summarize_rules(key, [r for r in ev.results if _DISPLAY_STAGE[r.stage] == key])
        rows.append(m.StageEvent(run_id=run.id, seq=seq, stage=key, label=label, status="done", outcome=outcome,
                                 summary=summary, details=details, started_at=now, finished_at=now))
    return rows


def seed_demo_cases() -> list[int]:
    """Seed only into an empty database. Returns the new case ids ([] if anything already exists)."""
    with session_scope() as s:
        if s.scalars(select(m.Case.id).limit(1)).first() is not None:
            return []

    ctx = _seed_context()
    prepared = []
    for cid in SEED_IDS:  # derive and verify everything before writing anything
        sample = load_sample(cid)
        ev = evaluate(CaseInput.model_validate(sample["case"]), ctx)
        _check_expected(cid, sample, ev)
        prepared.append((cid, sample, ev))

    case_ids = []
    with session_scope() as s:  # one transaction: all seeded cases or none
        for cid, sample, ev in prepared:
            case = create_case(s, sample_submission(sample), sample_uploads(sample), submitted_by=SEED_ACTOR,
                               source="seed", sample_id=cid)
            run = create_run(s, case, case.submissions[0], trigger="seed")
            run.started_at = run.finished_at = m.utcnow()
            run.status = "completed"
            extractions = {slot: Extraction(document=DocumentInput.model_validate(doc), raw=None,
                                            meta={"source": "seed", "note": "sample ground truth; not read by the model"})
                           for slot, doc in sample["case"]["documents"].items()}
            s.add_all(_stage_rows(run, ev, len(extractions)))
            save_evaluation(s, run, extractions, ev)
            audit(s, case.id, "seed.loaded", actor=SEED_ACTOR, run_id=run.id, sample_id=cid,
                  note="Pre-populated demo history; the pipeline was not executed and no model was called.")
            case_ids.append(case.id)
    log.info("Seeded %d demo cases", len(case_ids))
    return case_ids
