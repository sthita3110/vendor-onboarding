"""Human decisions on internal-review cases: Approve, Request info, Reject.

A reviewer can overrule a judgement finding (the reason is recorded and the finding marked overridden), but can't
approve past evidence that doesn't exist: Approve is refused when any check on the latest run was blocked or
errored (it never ran), or when the vendor still owes items. Every action needs a reviewer and a reason, and is
written to review_actions and the audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.db import models as m
from app.db.audit import audit
from app.db.engine import session_scope
from app.db.repository import set_case_status
from app.llm.messages import make_message_writer
from app.messages.compose import private_terms_from
from app.messages.notify import send_vendor_message

ACTIONS = {"approve", "request_info", "reject"}


class ReviewInvalid(ValueError):
    """Missing reviewer, reason or message, or an unknown action (HTTP 422)."""


class ReviewNotAllowed(RuntimeError):
    """The case can't take this action right now (HTTP 409)."""


@dataclass
class ReviewOptions:
    can_review: bool
    can_approve: bool
    approve_blocked_reason: str | None


def latest_run(case: m.Case) -> m.Run | None:
    return case.runs[-1] if case.runs else None


def human_decided_since_last_run(case: m.Case, actions: list[m.ReviewAction]) -> bool:
    """True once a reviewer has acted on the case's latest run (Replay would override them)."""
    run = latest_run(case)
    return bool(run and any(a.run_id == run.id for a in actions))


def review_options(case: m.Case, actions: list[m.ReviewAction]) -> ReviewOptions:
    run = latest_run(case)
    active = bool(run and run.status in ("queued", "running"))
    can_review = (case.status == "PENDING" and case.sub_state == "INTERNAL_REVIEW" and not active
                  and not human_decided_since_last_run(case, actions))
    if not can_review:
        return ReviewOptions(False, False, None)
    # Positive evidence first: an interrupted or failed run has *no* results, so "nothing blocked" proves nothing.
    if run is None or run.status != "completed" or run.decision is None or "SYS-01" in (case.failing_rules or []):
        return ReviewOptions(True, False, "The latest checks didn't complete. Replay the case before approving — "
                                          "a vendor can't be approved on checks that never ran.")
    not_run = sorted({r.rule_id for r in run.check_results if r.status in ("blocked", "error")}) if run else []
    if not_run:
        return ReviewOptions(True, False, f"Some checks didn't run ({', '.join(not_run)}). Replay, request a "
                                          "clearer document, or reject — a case can't be approved unchecked.")
    asks = run.decision.vendor_actions if run and run.decision else []
    if asks:
        return ReviewOptions(True, False, f"The vendor still owes {len(asks)} item(s). Request them first — an "
                                          "incomplete application can't be approved.")
    return ReviewOptions(True, True, None)


def review_case(case_id: int, action: str, *, reviewer: str, reason: str, message: str | None = None,
                writer_factory=make_message_writer) -> m.ReviewAction:
    reviewer, reason, message = (reviewer or "").strip(), (reason or "").strip(), (message or "").strip() or None
    if action not in ACTIONS:
        raise ReviewInvalid(f"Unknown action '{action}'")
    if not reviewer:
        raise ReviewInvalid("A reviewer name is required")
    if not reason:
        raise ReviewInvalid("A reason is required — an unexplained decision can't be audited")
    if action == "request_info" and not message:
        raise ReviewInvalid("Request info needs the message to send to the vendor")

    with session_scope() as s:
        case = s.get(m.Case, case_id)
        if case is None:
            raise LookupError(f"Case {case_id} not found")
        actions = list(s.query(m.ReviewAction).filter(m.ReviewAction.case_id == case_id))
        opts = review_options(case, actions)
        if not opts.can_review:
            raise ReviewNotAllowed(f"{case.reference} isn't waiting for review")
        if action == "approve" and not opts.can_approve:
            raise ReviewNotAllowed(opts.approve_blocked_reason or "Can't approve")

        run = latest_run(case)
        previous = f"{case.status}/{case.sub_state}" if case.sub_state else case.status
        findings = list(case.failing_rules or [])
        if action == "approve":
            new_status, new_sub, failing = "APPROVED", None, []
        elif action == "reject":
            new_status, new_sub, failing = "REJECTED", None, findings
        else:
            new_status, new_sub, failing = "PENDING", "AWAITING_VENDOR", findings

        row = m.ReviewAction(
            case_id=case.id, run_id=run.id if run else None, action=action, reason=reason, message=message,
            actor=reviewer, previous_status=previous,
            new_status=f"{new_status}/{new_sub}" if new_sub else new_status,
            overridden_rules=findings if action == "approve" else [],
        )
        s.add(row)
        audit(s, case.id, f"review.{action}", actor=reviewer, run_id=row.run_id, reason=reason, message=message,
              findings=findings, overridden_rules=row.overridden_rules)
        set_case_status(s, case, new_status, new_sub, failing, actor=reviewer, run_id=row.run_id,
                        reason=f"Reviewer {action.replace('_', ' ')}: {reason}")
        s.flush()
        # Vendor message: outstanding vendor asks plus, for request info, the reviewer's own words.
        items = list(run.decision.vendor_actions) if run and run.decision and action == "request_info" else []
        if action == "request_info":
            items.append(message)
        private = private_terms_from([r.evidence for r in run.check_results]) if run else set()
        case_id_, run_id_ = case.id, row.run_id

    try:
        writer = writer_factory()
    except Exception:
        writer = None
    send_vendor_message(case_id_, run_id_, new_status, new_sub, items, source="review", writer=writer,
                        private_terms=private)
    return row
