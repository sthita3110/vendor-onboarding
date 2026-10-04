"""Step 3a: persistence — cases, versioned submissions, file store, run outputs, append-only audit."""

import hashlib

import pytest
from sqlalchemy import select, text

from app.db import models as m
from app.db.audit import AuditImmutableError
from app.db.engine import get_engine, init_db, session_scope
from app.db.repository import add_submission, create_case, create_run, load_uploads, save_evaluation
from app.db.storage import uploads_root
from app.llm.extract import UploadedFile, extract_case
from app.rules.evaluate import evaluate
from app.samples import load_sample, sample_submission, sample_uploads
from tests.test_extract import FakeReader, raw_from_truth


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
    init_db(f"sqlite:///{tmp_path / 'test.db'}")
    yield
    get_engine().dispose()


def perfect_reader(sample: dict) -> FakeReader:
    return FakeReader({d["filename"]: raw_from_truth(d) for d in sample["case"]["documents"].values()})


def events(session, case_id) -> list[str]:
    return [e.event for e in session.scalars(select(m.AuditEvent).where(m.AuditEvent.case_id == case_id)
                                             .order_by(m.AuditEvent.id))]


def test_sqlite_settings(db):
    with get_engine().connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_create_case_stores_submission_documents_and_audit(db):
    sample = load_sample("H1")
    with session_scope() as s:
        case = create_case(s, sample_submission(sample), sample_uploads(sample), sample_id="H1")
        case_id = case.id
    with session_scope() as s:
        case = s.get(m.Case, case_id)
        assert case.reference == "VO-0001" and case.status == "RECEIVED" and case.pan == "AAACL4821K"
        sub = case.submissions[0]
        assert sub.version == 1 and sub.payload["legal_name"] == "Lumen Analytics Private Limited"
        assert {d.slot for d in sub.documents} == {"gst_certificate", "pan_card", "bank_proof"}
        for d in sub.documents:  # stored bytes match the recorded hash; user filename isn't the path
            stored = (uploads_root() / d.path).read_bytes()
            assert hashlib.sha256(stored).hexdigest() == d.sha256 and d.filename not in d.path
        assert events(s, case_id) == ["case.created", "submission.received"]


def test_submission_payload_round_trips(db):
    sample = load_sample("E3")
    form = sample_submission(sample)
    with session_scope() as s:
        case_id = create_case(s, form, sample_uploads(sample)).id
    with session_scope() as s:
        assert type(form).model_validate(s.get(m.Case, case_id).submissions[0].payload) == form


def test_identical_files_stored_once(db):
    data = sample_uploads(load_sample("H1"))[0].data
    with session_scope() as s:
        case = create_case(s, sample_submission(load_sample("H1")),
                           [UploadedFile("gst_certificate", "a.pdf", data), UploadedFile("pan_card", "b.pdf", data)])
        case_id = case.id
    assert len(list((uploads_root() / str(case_id)).iterdir())) == 1


def test_resubmission_versions_and_carries_over_unchanged_files(db):
    e3, e3r = load_sample("E3"), load_sample("E3R")
    with session_scope() as s:
        case = create_case(s, sample_submission(e3), sample_uploads(e3))
        fixed = [u for u in sample_uploads(e3r) if u.slot in ("gst_certificate", "bank_proof")]
        sub2 = add_submission(s, case, sample_submission(e3r), fixed)
        case_id, carried = case.id, {d.slot: d.carried_over for d in sub2.documents}
        uploads_v2 = load_uploads(sub2)
    assert carried == {"gst_certificate": False, "bank_proof": False, "pan_card": True}
    assert {u.filename for u in uploads_v2} == {"gst_certificate.pdf", "cancelled_cheque.pdf", "pan_card.pdf"}
    with session_scope() as s:
        assert [x.version for x in s.get(m.Case, case_id).submissions] == [1, 2]
        assert s.get(m.Case, case_id).gstin.startswith("33")  # case reflects the latest version


def test_save_evaluation_persists_run_and_updates_case(db, ctx):
    sample = load_sample("E3")
    with session_scope() as s:
        case = create_case(s, sample_submission(sample), sample_uploads(sample))
        run = create_run(s, case, case.submissions[0])
        form_case, extractions = extract_case(sample_submission(sample), load_uploads(case.submissions[0]),
                                              perfect_reader(sample))
        ev = evaluate(form_case, ctx)
        save_evaluation(s, run, extractions, ev)
        case_id, run_id, n_results = case.id, run.id, len(ev.results)
    with session_scope() as s:
        case, run = s.get(m.Case, case_id), s.get(m.Run, run_id)
        assert (case.status, case.sub_state) == ("PENDING", "AWAITING_VENDOR")
        assert set(case.failing_rules) == {"DOC-01", "TAX-04"} and case.decided_at
        assert len(run.check_results) == n_results and len(run.extractions) == 3
        assert run.decision.vendor_actions and run.decision.rule_catalog_version == "v1"
        assert {x.slot: x.document["classified_type"] for x in run.extractions}["bank_proof"] == "invoice"
        assert events(s, case_id)[-3:] == ["run.created", "decision.made", "status.changed"]


def test_audit_is_append_only(db):
    sample = load_sample("H1")
    with session_scope() as s:
        case_id = create_case(s, sample_submission(sample), sample_uploads(sample)).id
    with pytest.raises(AuditImmutableError):
        with session_scope() as s:
            s.scalars(select(m.AuditEvent).where(m.AuditEvent.case_id == case_id)).first().actor = "someone else"
    with pytest.raises(AuditImmutableError):
        with session_scope() as s:
            s.delete(s.scalars(select(m.AuditEvent)).first())
    with session_scope() as s:  # nothing changed
        assert [e.actor for e in s.scalars(select(m.AuditEvent))] == ["vendor", "vendor"]


def test_failed_unit_of_work_rolls_back(db):
    sample = load_sample("H1")
    with pytest.raises(RuntimeError):
        with session_scope() as s:
            create_case(s, sample_submission(sample), sample_uploads(sample))
            raise RuntimeError("boom")
    with session_scope() as s:
        assert s.scalars(select(m.Case)).first() is None
