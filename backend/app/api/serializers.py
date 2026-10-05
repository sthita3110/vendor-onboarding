"""DB rows -> JSON shapes the UI renders. Business labels come from the rule catalog; rule IDs are
included for the "technical details" view but are never the primary label."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import object_session

from app.db import models as m
from app.db.repository import can_reapply, superseded_by
from app.pipeline.review import human_decided_since_last_run, review_options
from app.rules.catalog import RULE_ORDER, RULES

GROUP_ORDER = ["Documents", "Tax", "Identity", "Bank", "Risk", "System"]
STATUS_RANK = {"fail": 0, "error": 1, "blocked": 2, "pass": 3}  # worst first


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") + "Z" if dt else None


def duration_ms(start: datetime | None, end: datetime | None) -> int | None:
    return int((end - start).total_seconds() * 1000) if start and end else None


def reasons(rule_ids: list[str]) -> list[dict[str, str]]:
    return [{"rule_id": r, "issue": RULES[r].issue if r in RULES else r} for r in rule_ids]


TRIGGER_LABEL = {"submission": "Submitted", "resubmission": "Resubmitted", "replay": "Replay",
                 "reapplication": "Reapplication", "seed": "Seeded sample (not executed)"}


def message_json(msg: m.Communication, case: m.Case | None = None) -> dict[str, Any]:
    return {"id": msg.id, "case_id": msg.case_id, "run_id": msg.run_id, "kind": msg.kind, "source": msg.source,
            "recipient": msg.recipient, "subject": msg.subject, "body": msg.body, "items": msg.items or [],
            "generated_by": msg.generated_by, "ai_drafted": msg.generated_by.startswith("llm:"),
            "status": msg.status, "created_at": iso(msg.created_at),
            **({"reference": case.reference, "vendor_name": case.vendor_name} if case else {})}


def review_json(a: m.ReviewAction) -> dict[str, Any]:
    return {"id": a.id, "action": a.action, "reason": a.reason, "message": a.message, "actor": a.actor,
            "run_id": a.run_id, "previous_status": a.previous_status, "new_status": a.new_status,
            "overridden_rules": reasons(a.overridden_rules or []), "at": iso(a.created_at)}


def case_link(c: m.Case) -> dict[str, Any]:
    """A reference to a related case (reapplication links), with enough to render a banner."""
    return {"id": c.id, "reference": c.reference, "vendor_name": c.vendor_name,
            "display_status": display_status(c.status, c.sub_state), "reasons": reasons(c.failing_rules),
            "decided_at": iso(c.decided_at)}


def source_label(c: m.Case) -> str:
    if c.source == "seed":
        return "Seeded sample"
    return f"Uploaded · from sample {c.sample_id}" if c.sample_id else "Uploaded"


def display_status(status: str, sub_state: str | None) -> str:
    """One label for badges: APPROVED | AWAITING_VENDOR | INTERNAL_REVIEW | REJECTED | IN_PROGRESS."""
    if status == "PENDING" and sub_state:
        return sub_state
    return "IN_PROGRESS" if status == "RECEIVED" else status


def stage_json(e: m.StageEvent) -> dict[str, Any]:
    return {"key": e.stage, "label": e.label, "status": e.status, "outcome": e.outcome, "summary": e.summary,
            "details": e.details, "started_at": iso(e.started_at), "finished_at": iso(e.finished_at),
            "duration_ms": duration_ms(e.started_at, e.finished_at)}


def decision_json(d: m.DecisionRecord | None) -> dict[str, Any] | None:
    if d is None:
        return None
    return {"status": d.status, "sub_state": d.sub_state, "display_status": display_status(d.status, d.sub_state),
            "summary": d.summary, "reasons": reasons(d.failing_rules), "vendor_actions": d.vendor_actions,
            "rule_catalog_version": d.rule_catalog_version, "decided_at": iso(d.created_at)}


def run_json(run: m.Run) -> dict[str, Any]:
    """Lightweight run view, polled by the live run screen."""
    return {
        "id": run.id, "case_id": run.case_id, "reference": run.case.reference,
        "vendor_name": run.case.vendor_name, "version": run.submission.version,
        "trigger": run.trigger, "trigger_label": TRIGGER_LABEL.get(run.trigger, run.trigger),
        "executed": run.trigger != "seed",
        "status": run.status, "active": run.status in ("queued", "running"), "error": run.error,
        "created_at": iso(run.created_at), "started_at": iso(run.started_at), "finished_at": iso(run.finished_at),
        "duration_ms": duration_ms(run.started_at, run.finished_at),
        "stages": [stage_json(e) for e in run.stage_events],
        "decision": decision_json(run.decision),
    }


def check_groups(results: list[m.CheckResultRecord]) -> list[dict[str, Any]]:
    """Results grouped by UI group, then by rule (worst status first within a rule's results)."""
    by_rule: dict[str, list[m.CheckResultRecord]] = {}
    for r in results:
        by_rule.setdefault(r.rule_id, []).append(r)
    groups: dict[str, list[dict[str, Any]]] = {}
    for rule_id in sorted(by_rule, key=lambda rid: RULE_ORDER.get(rid, 999)):
        rule, rows = RULES[rule_id], by_rule[rule_id]
        worst = min((r.status for r in rows), key=lambda st: STATUS_RANK[st])
        groups.setdefault(rule.group, []).append({
            "rule_id": rule_id, "name": rule.name, "issue": rule.issue, "required": rule.required,
            "outcome_if_failed": rule.outcome.value, "status": worst,
            "results": [{"status": r.status, "subject": r.subject, "title": r.title, "detail": r.detail,
                         "vendor_text": r.vendor_text, "outcome_class": r.outcome_class, "evidence": r.evidence,
                         "blocked_by": r.blocked_by,
                         "blocked_by_issue": RULES[r.blocked_by].issue if r.blocked_by in RULES else None}
                        for r in sorted(rows, key=lambda r: STATUS_RANK[r.status])],
        })
    return [{"group": g, "rules": groups[g]} for g in GROUP_ORDER if g in groups]


def extraction_json(x: m.ExtractionRecord) -> dict[str, Any]:
    doc = x.document
    return {"slot": x.slot, "document_id": x.document_id, "filename": doc.get("filename"),
            "classified_type": doc.get("classified_type"), "readable": doc.get("readable"),
            "file_problem": doc.get("file_problem"), "extraction_error": doc.get("extraction_error"),
            "fields": doc.get("fields", {}), "meta": x.meta}


def document_json(case_id: int, d: m.Document) -> dict[str, Any]:
    return {"id": d.id, "slot": d.slot, "filename": d.filename, "size": d.size, "carried_over": d.carried_over,
            "url": f"/api/cases/{case_id}/documents/{d.id}"}


def case_row_json(c: m.Case) -> dict[str, Any]:
    """Dashboard / queue row."""
    latest = c.runs[-1] if c.runs else None
    return {
        "id": c.id, "reference": c.reference, "vendor_name": c.vendor_name, "gstin": c.gstin,
        "status": c.status, "sub_state": c.sub_state, "display_status": display_status(c.status, c.sub_state),
        "reasons": reasons(c.failing_rules), "versions": len(c.submissions),
        "vendor_actions": len(latest.decision.vendor_actions) if latest and latest.decision else 0,
        "source": c.source, "source_label": source_label(c), "sample_id": c.sample_id,
        "previous_case_id": c.previous_case_id,
        "created_at": iso(c.created_at), "decided_at": iso(c.decided_at), "updated_at": iso(c.updated_at),
        "latest_run": {"id": latest.id, "status": latest.status} if latest else None,
    }


def case_detail_json(c: m.Case, version: int | None = None) -> dict[str, Any]:
    subs = {s.version: s for s in c.submissions}
    selected = subs.get(version) if version else c.submissions[-1]
    if selected is None:
        raise KeyError(version)
    runs_by_sub = {r.submission_id: r for r in c.runs}  # latest run per submission wins
    run = runs_by_sub.get(selected.id)
    latest_run = c.runs[-1] if c.runs else None
    session = object_session(c)
    previous = session.get(m.Case, c.previous_case_id) if session and c.previous_case_id else None
    later = superseded_by(session, c) if session else []
    actions = list(session.query(m.ReviewAction).filter(m.ReviewAction.case_id == c.id)
                   .order_by(m.ReviewAction.id)) if session else []
    opts = review_options(c, actions)
    decided_by_human = human_decided_since_last_run(c, actions)
    return {
        **case_row_json(c),
        "pan": c.pan,
        "can_resubmit": c.status == "PENDING" and not (latest_run and latest_run.status in ("queued", "running")),
        "can_replay": not (latest_run and latest_run.status in ("queued", "running")) and not decided_by_human,
        "can_review": opts.can_review,
        "can_approve": opts.can_approve,
        "approve_blocked_reason": opts.approve_blocked_reason,
        "review_actions": [review_json(a) for a in actions],
        "messages": [message_json(x) for x in (session.query(m.Communication).filter(m.Communication.case_id == c.id)
                                              .order_by(m.Communication.id.desc()) if session else [])],
        "human_decision": review_json(actions[-1]) if decided_by_human else None,
        "can_reapply": bool(session) and can_reapply(session, c),
        "previous_case": case_link(previous) if previous else None,
        "superseded_by": [case_link(x) for x in later],
        "runs_detail": [{"id": r.id, "version": r.submission.version, "trigger": r.trigger,
                         "trigger_label": TRIGGER_LABEL.get(r.trigger, r.trigger), "status": r.status,
                         "created_at": iso(r.created_at), "decision": decision_json(r.decision)} for r in c.runs],
        "selected_version": selected.version,
        "versions_detail": [
            {"version": s.version, "submitted_at": iso(s.created_at), "submitted_by": s.submitted_by,
             "run": ({"id": r.id, "status": r.status, "decision": decision_json(r.decision)}
                     if (r := runs_by_sub.get(s.id)) else None)}
            for s in c.submissions
        ],
        "submission": selected.payload,
        "documents": [document_json(c.id, d) for d in selected.documents],
        "run": run_json(run) if run else None,
        "checks": check_groups(run.check_results) if run else [],
        "extractions": {x.slot: extraction_json(x) for x in run.extractions} if run else {},
    }


def audit_json(e: m.AuditEvent) -> dict[str, Any]:
    return {"id": e.id, "at": iso(e.at), "actor": e.actor, "event": e.event, "run_id": e.run_id, "data": e.data}
