"""Step 3b: pipeline runner — stage-by-stage persistence, parity with evaluate(), fail-closed paths."""

import threading
import time

import pytest
from sqlalchemy import select

from app.adapters.mock import MockPennyDrop

from app.db import models as m
from app.db.engine import get_engine, init_db, session_scope
from app.db.repository import create_case, create_run
from app.domain.models import CaseInput
from app.pipeline import runner
from app.pipeline.runner import STAGES, PipelineDeps, recover_interrupted_runs, resubmit_case, submit_case
from app.rules.evaluate import evaluate
from app.samples import load_sample, sample_ids, sample_submission, sample_uploads
from tests.test_extract import FakeReader, raw_from_truth


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
    init_db(f"sqlite:///{tmp_path / 'test.db'}")
    yield
    get_engine().dispose()


def deps_for(cid: str, ctx, **kw) -> PipelineDeps:
    sample = load_sample(cid)
    reader = FakeReader({d["filename"]: raw_from_truth(d) for d in sample["case"]["documents"].values()}, **kw)
    return PipelineDeps(reader_factory=lambda: reader, cache=None, ctx=ctx)


def run_sample(cid: str, ctx, **kw) -> tuple[int, int]:
    sample = load_sample(cid)
    return submit_case(sample_submission(sample), sample_uploads(sample), sample_id=cid, background=False,
                       deps=deps_for(cid, ctx, **kw))


@pytest.mark.parametrize("cid", sample_ids())
def test_runner_matches_evaluate_and_golden(cid, db, ctx):
    """The staged runner must reach exactly the same results as the synchronous evaluate()."""
    case_id, run_id = run_sample(cid, ctx)
    sample = load_sample(cid)
    with session_scope() as s:
        case, run = s.get(m.Case, case_id), s.get(m.Run, run_id)
        assert run.status == "completed"
        assert case.status == sample["expected"]["status"] and case.sub_state == sample["expected"]["sub_state"]
        assert set(case.failing_rules) == set(sample["expected"]["failing_rules"])
        persisted = [(r.rule_id, r.status, r.subject) for r in run.check_results]
    reference = evaluate(CaseInput.model_validate(sample["case"]), ctx)
    assert persisted == [(r.rule_id, r.status, r.subject) for r in reference.results]


def test_every_stage_is_recorded_in_order(db, ctx):
    _, run_id = run_sample("E3", ctx)
    with session_scope() as s:
        evs = s.get(m.Run, run_id).stage_events
        assert [e.stage for e in evs] == [k for k, _ in STAGES]
        assert all(e.status == "done" and e.started_at and e.finished_at for e in evs)
        by = {e.stage: e for e in evs}
        assert by["doc_checks"].outcome == "issues" and "invoice" in by["doc_checks"].summary
        assert by["cross_check"].outcome == "issues" and by["cross_check"].details["failing_rules"] == ["TAX-04"]
        assert by["external_verify"].outcome == "pass" and "simulated" in by["external_verify"].summary
        assert by["notify"].summary == "2 item(s) to request from the vendor"


def test_read_stage_summary_mentions_scan(db, ctx):
    _, run_id = run_sample("H1", ctx)
    with session_scope() as s:
        read = next(e for e in s.get(m.Run, run_id).stage_events if e.stage == "read_documents")
        assert read.outcome == "pass" and "3 documents (1 scanned)" in read.summary


def test_progress_is_visible_while_running(db, ctx):
    """A reader that blocks lets us observe the run mid-flight, as the polling UI would."""
    gate, entered = threading.Event(), threading.Event()
    sample = load_sample("H1")
    inner = deps_for("H1", ctx)
    real = inner.reader_factory()

    class SlowReader:
        model = "fake"

        def read(self, *a):
            entered.set()
            gate.wait(5)
            return real.read(*a)

    deps = PipelineDeps(reader_factory=SlowReader, cache=None, ctx=ctx)
    _, run_id = submit_case(sample_submission(sample), sample_uploads(sample), deps=deps)  # background
    assert entered.wait(5)
    with session_scope() as s:
        statuses = {e.stage: e.status for e in s.get(m.Run, run_id).stage_events}
        assert s.get(m.Run, run_id).status == "running"
    assert statuses["completeness"] == "done" and statuses["read_documents"] == "running"
    assert statuses["decision"] == "pending"
    gate.set()
    for _ in range(50):
        with session_scope() as s:
            if s.get(m.Run, run_id).status == "completed":
                break
        threading.Event().wait(0.1)
    with session_scope() as s:
        assert s.get(m.Case, s.get(m.Run, run_id).case_id).status == "APPROVED"


def test_no_api_key_fails_closed(db, ctx):
    sample = load_sample("H1")

    def no_reader():
        raise RuntimeError("OPENAI_API_KEY is not set")

    case_id, run_id = submit_case(sample_submission(sample), sample_uploads(sample), background=False,
                                  deps=PipelineDeps(reader_factory=no_reader, cache=None, ctx=ctx))
    with session_scope() as s:
        case, run = s.get(m.Case, case_id), s.get(m.Run, run_id)
        assert run.status == "completed"  # pipeline handled it; the decision itself fails closed
        assert (case.status, case.sub_state, case.failing_rules) == ("PENDING", "INTERNAL_REVIEW", ["SYS-01"])
        assert next(e for e in run.stage_events if e.stage == "read_documents").outcome == "error"


def test_unexpected_crash_fails_closed(db, ctx, monkeypatch):
    def boom(state):
        raise ValueError("bug in a rule")

    monkeypatch.setitem(runner.RULE_STAGES, "cross_check", [boom])
    case_id, run_id = run_sample("H1", ctx)
    with session_scope() as s:
        case, run = s.get(m.Case, case_id), s.get(m.Run, run_id)
        assert run.status == "failed" and "bug in a rule" in run.error
        assert (case.status, case.sub_state, case.failing_rules) == ("PENDING", "INTERNAL_REVIEW", ["SYS-01"])
        ev = {e.stage: e for e in run.stage_events}
        assert ev["cross_check"].status == "failed" and ev["decision"].status == "pending"
        assert "run.failed" in [a.event for a in s.scalars(select(m.AuditEvent).where(m.AuditEvent.case_id == case_id))]


def test_interrupted_runs_recovered_at_startup(db):
    sample = load_sample("H1")
    with session_scope() as s:  # simulate a run cut off mid-way by a restart
        case = create_case(s, sample_submission(sample), sample_uploads(sample))
        run = create_run(s, case, case.submissions[0])
        run.status = "running"
        s.add(m.StageEvent(run_id=run.id, seq=2, stage="read_documents", label="Reading documents", status="running"))
        case_id, run_id = case.id, run.id
    assert recover_interrupted_runs() == [run_id]
    with session_scope() as s:
        case, run = s.get(m.Case, case_id), s.get(m.Run, run_id)
        assert run.status == "interrupted" and case.sub_state == "INTERNAL_REVIEW"
        assert run.stage_events[0].status == "failed"
    assert recover_interrupted_runs() == []  # idempotent


def test_resubmission_runs_again_on_same_case(db, ctx):
    e3r = load_sample("E3R")
    case_id, _ = run_sample("E3", ctx)
    fixed = [u for u in sample_uploads(e3r) if u.slot in ("gst_certificate", "bank_proof")]
    reader = FakeReader({d["filename"]: raw_from_truth(d) for d in e3r["case"]["documents"].values()})
    run2 = resubmit_case(case_id, sample_submission(e3r), fixed, background=False,
                         deps=PipelineDeps(reader_factory=lambda: reader, cache=None, ctx=ctx))
    with session_scope() as s:
        case = s.get(m.Case, case_id)
        assert case.status == "APPROVED" and [r.id for r in case.runs][-1] == run2
        assert [r.decision.status for r in case.runs] == ["PENDING", "APPROVED"]
        events = [a.event for a in s.scalars(select(m.AuditEvent).where(m.AuditEvent.case_id == case_id))]
        assert events.count("decision.made") == 2


def test_simulated_latency_is_applied_and_labelled():
    bank = MockPennyDrop({}, latency_ms=150)
    start = time.monotonic()
    resp = bank.verify("50200074561238", "HDFC0000075", "X")
    assert time.monotonic() - start >= 0.15 and resp.simulated is True
