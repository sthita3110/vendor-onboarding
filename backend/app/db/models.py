"""Persistence models (ARCHITECTURE.md §7).

A case is one vendor onboarding attempt. It has versioned submissions (resubmission = new version);
each submission gets a run; a run stores its stage events, extractions, check results and decision.
Reference data (vendor master, debarred list, adapter fixtures) is NOT here — it lives in versioned files.
All timestamps are UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)  # SQLite has no tz type; stored values are UTC by convention


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_name: Mapped[str | None] = mapped_column(String(300))
    gstin: Mapped[str | None] = mapped_column(String(20), index=True)
    pan: Mapped[str | None] = mapped_column(String(10), index=True)
    # Current state, denormalized from the latest decision / review action for dashboard queries.
    # Only app.db.repository.set_case_status() changes these (and it always writes an audit event).
    status: Mapped[str] = mapped_column(String(20), default="RECEIVED", index=True)
    sub_state: Mapped[str | None] = mapped_column(String(20), index=True)
    failing_rules: Mapped[list[Any]] = mapped_column(default=list)
    source: Mapped[str] = mapped_column(String(20), default="form")  # form | seed
    sample_id: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    decided_at: Mapped[datetime | None]

    submissions: Mapped[list[Submission]] = relationship(back_populates="case", order_by="Submission.version")
    runs: Mapped[list[Run]] = relationship(back_populates="case", order_by="Run.id")

    @property
    def reference(self) -> str:
        return f"VO-{self.id:04d}"


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("case_id", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]]  # the form, as app.domain.models.Submission JSON
    submitted_by: Mapped[str] = mapped_column(String(100), default="vendor")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    case: Mapped[Case] = relationship(back_populates="submissions")
    documents: Mapped[list[Document]] = relationship(back_populates="submission", order_by="Document.id")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), index=True)
    slot: Mapped[str] = mapped_column(String(30))
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size: Mapped[int]
    path: Mapped[str] = mapped_column(String(500))  # relative to settings.uploads_dir
    carried_over: Mapped[bool] = mapped_column(default=False)  # reused unchanged from the previous version

    submission: Mapped[Submission] = relationship(back_populates="documents")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"))
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|completed|failed|interrupted
    # What started it: submission | resubmission | replay (pipeline executed) | seed (pre-populated, not executed)
    trigger: Mapped[str] = mapped_column(String(20), default="submission")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]

    case: Mapped[Case] = relationship(back_populates="runs")
    submission: Mapped[Submission] = relationship()
    stage_events: Mapped[list[StageEvent]] = relationship(order_by="StageEvent.seq")
    extractions: Mapped[list[ExtractionRecord]] = relationship(order_by="ExtractionRecord.id")
    check_results: Mapped[list[CheckResultRecord]] = relationship(order_by="CheckResultRecord.seq")
    decision: Mapped[DecisionRecord | None] = relationship(back_populates="run", uselist=False)


class StageEvent(Base):
    """One row per pipeline stage per run; drives the live run view (step 3b)."""

    __tablename__ = "stage_events"
    __table_args__ = (UniqueConstraint("run_id", "stage"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    seq: Mapped[int]
    stage: Mapped[str] = mapped_column(String(30))
    label: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|running|done|failed
    # How the stage went, for the UI icon: pass | issues | blocked | error (set when status == done/failed)
    outcome: Mapped[str | None] = mapped_column(String(10))
    summary: Mapped[str | None] = mapped_column(Text)  # one business-language line
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)  # rule ids, counts, timings
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class ExtractionRecord(Base):
    __tablename__ = "extractions"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    slot: Mapped[str] = mapped_column(String(30))
    document: Mapped[dict[str, Any]]  # DocumentInput JSON as fed to the rules (fields, grounding, errors)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # model output as returned
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)  # model, prompt version, latency, tokens, cached


class CheckResultRecord(Base):
    __tablename__ = "check_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    seq: Mapped[int]
    rule_id: Mapped[str] = mapped_column(String(10), index=True)
    stage: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(10))
    outcome_class: Mapped[str | None] = mapped_column(String(20))
    subject: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str | None] = mapped_column(Text)
    vendor_text: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict[str, Any]] = mapped_column(default=dict)
    blocked_by: Mapped[str | None] = mapped_column(String(10))


class DecisionRecord(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), unique=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    status: Mapped[str] = mapped_column(String(20))
    sub_state: Mapped[str | None] = mapped_column(String(20))
    failing_rules: Mapped[list[Any]] = mapped_column(default=list)
    vendor_actions: Mapped[list[Any]] = mapped_column(default=list)
    summary: Mapped[str] = mapped_column(Text)
    rule_catalog_version: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    run: Mapped[Run] = relationship(back_populates="decision")


class ReviewAction(Base):
    """Human decisions on internal-review cases (Phase 5). A reason is mandatory."""

    __tablename__ = "review_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"))
    action: Mapped[str] = mapped_column(String(20))  # approve | request_info | reject
    reason: Mapped[str] = mapped_column(Text)
    message: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(100))
    previous_status: Mapped[str] = mapped_column(String(40))
    new_status: Mapped[str] = mapped_column(String(40))
    overridden_rules: Mapped[list[Any]] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Communication(Base):
    """Messages to the vendor (Phase 5). Delivery is simulated: status 'sent (simulated)'."""

    __tablename__ = "communications"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"))
    kind: Mapped[str] = mapped_column(String(30))  # approved | awaiting_vendor | under_review | rejected | request_info
    recipient: Mapped[str | None] = mapped_column(String(300))
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    generated_by: Mapped[str] = mapped_column(String(50))  # llm:<model> | template
    status: Mapped[str] = mapped_column(String(30), default="sent (simulated)")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AuditEvent(Base):
    """Append-only: rows are inserted, never updated or deleted (enforced in app.db.audit)."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"))
    at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(100))  # "system" or a reviewer's name
    event: Mapped[str] = mapped_column(String(50))  # e.g. case.created, run.completed, decision.made
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)
