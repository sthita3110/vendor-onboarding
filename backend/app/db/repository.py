"""Named persistence operations. The pipeline and API call these instead of touching tables directly,
so every state change is paired with its audit event in one place."""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.audit import audit
from app.db.storage import read_file, store_file
from app.domain.models import Evaluation
from app.domain.models import Submission as SubmissionForm
from app.llm.extract import Extraction, UploadedFile
from app.rules.validators import clean_id


def _store_documents(session: Session, case: m.Case, sub: m.Submission, uploads: list[UploadedFile]) -> None:
    for up in uploads:
        sha, path = store_file(case.id, up.data)
        session.add(m.Document(submission=sub, slot=up.slot, filename=up.filename, sha256=sha,
                               size=len(up.data), path=path))


def _doc_summary(sub: m.Submission) -> list[dict[str, Any]]:
    return [{"slot": d.slot, "filename": d.filename, "sha256": d.sha256, "carried_over": d.carried_over}
            for d in sub.documents]


def entity_keys(form: SubmissionForm) -> tuple[set[str], str | None]:
    """PANs and GSTIN identifying the legal entity on a submission. The PAN embedded in the GSTIN counts,
    so the same company submitting its registration from another state still matches."""
    pans = {p for p in (clean_id(form.pan), clean_id(form.gstin)[2:12] if len(clean_id(form.gstin)) >= 12 else "") if p}
    return pans, clean_id(form.gstin) or None


def find_cases_for_entity(session: Session, form: SubmissionForm) -> list[m.Case]:
    """Existing cases (any status) for the same legal entity, by PAN or GSTIN."""
    pans, gstin = entity_keys(form)
    conditions = [m.Case.pan.in_(pans)] if pans else []
    if gstin:
        conditions.append(m.Case.gstin == gstin)
    if not conditions:
        return []  # nothing identifies the entity yet (COMP-01 will ask for it)
    return list(session.scalars(select(m.Case).where(or_(*conditions)).order_by(m.Case.id)))


def create_case(session: Session, form: SubmissionForm, uploads: list[UploadedFile], *,
                submitted_by: str = "vendor", source: str = "form", sample_id: str | None = None) -> m.Case:
    case = m.Case(vendor_name=form.legal_name, gstin=clean_id(form.gstin) or None, pan=clean_id(form.pan) or None,
                  source=source, sample_id=sample_id)
    session.add(case)
    session.flush()  # assigns case.id (needed for the file store path)
    sub = m.Submission(case=case, version=1, payload=form.model_dump(mode="json"), submitted_by=submitted_by)
    session.add(sub)
    _store_documents(session, case, sub, uploads)
    session.flush()
    audit(session, case.id, "case.created", actor=submitted_by, reference=case.reference, source=source,
          sample_id=sample_id)
    audit(session, case.id, "submission.received", actor=submitted_by, version=1, documents=_doc_summary(sub))
    return case


def add_submission(session: Session, case: m.Case, form: SubmissionForm, uploads: list[UploadedFile], *,
                   submitted_by: str = "vendor") -> m.Submission:
    """Resubmission: a new version. Slots not re-uploaded carry over the previous version's file unchanged."""
    prev = case.submissions[-1]
    sub = m.Submission(case=case, version=prev.version + 1, payload=form.model_dump(mode="json"),
                       submitted_by=submitted_by)
    session.add(sub)
    _store_documents(session, case, sub, uploads)
    replaced = {u.slot for u in uploads}
    for d in prev.documents:
        if d.slot not in replaced:
            session.add(m.Document(submission=sub, slot=d.slot, filename=d.filename, sha256=d.sha256,
                                   size=d.size, path=d.path, carried_over=True))
    case.vendor_name, case.gstin, case.pan = form.legal_name, clean_id(form.gstin) or None, clean_id(form.pan) or None
    session.flush()
    audit(session, case.id, "submission.received", actor=submitted_by, version=sub.version,
          documents=_doc_summary(sub))
    return sub


def load_uploads(sub: m.Submission) -> list[UploadedFile]:
    """Read a submission's files back from storage, as the pipeline consumes them."""
    return [UploadedFile(d.slot, d.filename, read_file(d.path)) for d in sub.documents]


def create_run(session: Session, case: m.Case, sub: m.Submission, trigger: str = "submission") -> m.Run:
    run = m.Run(case=case, submission=sub, trigger=trigger)
    session.add(run)
    session.flush()
    audit(session, case.id, "run.created", run_id=run.id, submission_version=sub.version, trigger=trigger)
    return run


def set_case_status(session: Session, case: m.Case, status: str, sub_state: str | None,
                    failing_rules: list[str], *, actor: str = "system", run_id: int | None = None,
                    reason: str | None = None) -> None:
    """The only place a case's current status changes; always audited with from/to."""
    before = {"status": case.status, "sub_state": case.sub_state}
    case.status, case.sub_state, case.failing_rules = status, sub_state, failing_rules
    case.decided_at = m.utcnow()
    audit(session, case.id, "status.changed", actor=actor, run_id=run_id, before=before,
          after={"status": status, "sub_state": sub_state}, failing_rules=failing_rules, reason=reason)


def save_evaluation(session: Session, run: m.Run, extractions: dict[str, Extraction],
                    evaluation: Evaluation) -> m.DecisionRecord:
    """Persist everything a run produced: extractions, every check result, the decision; update the case."""
    doc_ids = {d.slot: d.id for d in run.submission.documents}
    for slot, ex in extractions.items():
        session.add(m.ExtractionRecord(run_id=run.id, document_id=doc_ids.get(slot), slot=slot,
                                       document=ex.document.model_dump(mode="json"), raw=ex.raw, meta=ex.meta))
    for seq, r in enumerate(evaluation.results):
        session.add(m.CheckResultRecord(
            run_id=run.id, seq=seq, rule_id=r.rule_id, stage=r.stage, status=r.status,
            outcome_class=r.outcome_class.value if r.outcome_class else None, subject=r.subject, title=r.title,
            detail=r.detail, vendor_text=r.vendor_text, evidence=r.evidence, blocked_by=r.blocked_by,
        ))
    d = evaluation.decision
    record = m.DecisionRecord(
        run_id=run.id, case_id=run.case_id, status=d.status.value,
        sub_state=d.sub_state.value if d.sub_state else None, failing_rules=d.failing_rules,
        vendor_actions=d.vendor_actions, summary=d.summary, rule_catalog_version=d.rule_catalog_version,
    )
    session.add(record)
    audit(session, run.case_id, "decision.made", run_id=run.id, status=record.status, sub_state=record.sub_state,
          failing_rules=d.failing_rules, rule_catalog_version=d.rule_catalog_version, summary=d.summary)
    set_case_status(session, run.case, record.status, record.sub_state, d.failing_rules, run_id=run.id)
    session.flush()
    return record
