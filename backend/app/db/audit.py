"""Audit trail: who did what, when, on what evidence. Append-only.

Every state change in the system goes through `audit()`. The ORM refuses to update or delete
an AuditEvent, so history can't be rewritten through the application.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.db.models import AuditEvent


class AuditImmutableError(RuntimeError):
    pass


@event.listens_for(AuditEvent, "before_update")
def _no_update(*_args) -> None:
    raise AuditImmutableError("Audit events are append-only")


@event.listens_for(AuditEvent, "before_delete")
def _no_delete(*_args) -> None:
    raise AuditImmutableError("Audit events are append-only")


def audit(session: Session, case_id: int, event_name: str, *, actor: str = "system",
          run_id: int | None = None, **data: Any) -> AuditEvent:
    row = AuditEvent(case_id=case_id, run_id=run_id, actor=actor, event=event_name, data=data)
    session.add(row)
    return row
