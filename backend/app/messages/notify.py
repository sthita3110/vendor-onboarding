"""Send (simulated) the vendor message for a decision, and record it in the outbox and audit trail.

Three short steps so a slow AI call never holds a database transaction: read the vendor-safe context →
compose (AI or template) → record. A system decision whose outcome and requested items are unchanged since the
last message sends nothing — a replay shouldn't email the vendor again.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.audit import audit
from app.db.engine import session_scope
from app.messages.compose import Message, MessageContext, MessageWriter, compose, kind_for

NO_CHANGE = "No change for the vendor — no new message sent"


def context_for(case: m.Case, status: str, sub_state: str | None, items: list[str]) -> MessageContext:
    payload = case.submissions[-1].payload if case.submissions else {}
    return MessageContext(kind=kind_for(status, sub_state), company=case.vendor_name or payload.get("legal_name") or "your company",
                          contact_name=payload.get("contact_name"), reference=case.reference, items=items)


def last_message(session: Session, case_id: int) -> m.Communication | None:
    return session.scalars(select(m.Communication).where(m.Communication.case_id == case_id)
                           .order_by(m.Communication.id.desc()).limit(1)).first()


def record_message(session: Session, case: m.Case, run_id: int | None, msg: Message, source: str) -> m.Communication:
    payload = case.submissions[-1].payload if case.submissions else {}
    row = m.Communication(case_id=case.id, run_id=run_id, kind=msg.kind, recipient=payload.get("contact_email"),
                          subject=msg.subject, body=msg.body, generated_by=msg.generated_by, source=source,
                          items=msg.items)
    session.add(row)
    session.flush()
    audit(session, case.id, "message.sent", run_id=run_id, kind=msg.kind, subject=msg.subject,
          recipient=row.recipient, generated_by=msg.generated_by, source=source, items=len(msg.items))
    return row


def describe(msg: Message) -> str:
    how = ("AI-drafted wording, checklist from the rules" if msg.generated_by.startswith("llm:")
           else msg.generated_by[:1].upper() + msg.generated_by[1:])
    return f"Message sent to the vendor (simulated) · {how}"


def send_vendor_message(case_id: int, run_id: int | None, status: str, sub_state: str | None, items: list[str], *,
                        source: str, writer: MessageWriter | None, private_terms: set[str]) -> tuple[Message | None, str]:
    """Returns (message or None if skipped, one-line summary for the run view)."""
    with session_scope() as s:
        case = s.get(m.Case, case_id)
        ctx = context_for(case, status, sub_state, items)
        prev = last_message(s, case_id)
        if source == "decision" and prev and prev.kind == ctx.kind and (prev.items or []) == ctx.items:
            return None, NO_CHANGE
    msg = compose(ctx, writer, private_terms)  # outside any transaction
    with session_scope() as s:
        record_message(s, s.get(m.Case, case_id), run_id, msg, source)
    return msg, describe(msg)
