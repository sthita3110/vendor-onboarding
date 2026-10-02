"""Decision engine: check results -> status (ARCHITECTURE.md §5).

Precedence REJECT > REVIEW > VENDOR_ACTION > APPROVE. Errors fail closed to review (SYS-01).
Approval requires positive evidence: every required rule ran and every one of its results passed.
"""

from __future__ import annotations

from app.domain.models import CheckResult, Decision, OutcomeClass, Status, SubState
from app.rules.catalog import CATALOG_VERSION, REQUIRED_RULES, RULE_ORDER, SEVERITY


def _severity(r: CheckResult) -> tuple[int, int]:
    cls = OutcomeClass.REVIEW if r.status == "error" else r.outcome_class
    return SEVERITY[cls], RULE_ORDER[r.rule_id]  # type: ignore[index]


def _not_approvable(results: list[CheckResult]) -> list[str]:
    """Required rules that have no results or any non-pass result."""
    by_rule: dict[str, list[CheckResult]] = {}
    for r in results:
        by_rule.setdefault(r.rule_id, []).append(r)
    return [rid for rid in REQUIRED_RULES
            if not by_rule.get(rid) or any(r.status != "pass" for r in by_rule[rid])]


def decide(results: list[CheckResult]) -> Decision:
    fails = [r for r in results if r.status == "fail"]
    errors = [r for r in results if r.status == "error"]
    reasons = sorted(fails + errors, key=_severity)

    classes = {r.outcome_class for r in fails}
    failing_rules: list[str] = []
    for r in reasons:
        rid = "SYS-01" if r.status == "error" else r.rule_id
        if rid not in failing_rules:
            failing_rules.append(rid)

    vendor_actions = list(dict.fromkeys(
        r.vendor_text for r in reasons if r.outcome_class == OutcomeClass.VENDOR_ACTION and r.vendor_text
    ))

    if OutcomeClass.REJECT in classes:
        status, sub = Status.REJECTED, None
        vendor_actions = []  # nothing to fix; vendor gets a generic message
    elif errors or OutcomeClass.REVIEW in classes:
        status, sub = Status.PENDING, SubState.INTERNAL_REVIEW
    elif OutcomeClass.VENDOR_ACTION in classes:
        status, sub = Status.PENDING, SubState.AWAITING_VENDOR
    else:
        incomplete = _not_approvable(results)
        if incomplete:
            # Defensive: should not happen if every blocked check has a recorded cause. Fail closed.
            status, sub = Status.PENDING, SubState.INTERNAL_REVIEW
            failing_rules = ["SYS-01"]
            reasons = [CheckResult(
                rule_id="SYS-01", stage="decision", status="error",
                title="Some required checks did not complete",
                detail=f"Required checks without a passing result: {', '.join(incomplete)}.",
            )]
        else:
            status, sub = Status.APPROVED, None

    return Decision(
        status=status,
        sub_state=sub,
        failing_rules=failing_rules,
        reasons=reasons,
        vendor_actions=vendor_actions,
        summary=_summary(status, sub, reasons, vendor_actions),
        rule_catalog_version=CATALOG_VERSION,
    )


def _summary(status: Status, sub: SubState | None, reasons: list[CheckResult], asks: list[str]) -> str:
    """Deterministic one-paragraph summary. Phase 2 may add an LLM-written version alongside it."""
    if status == Status.APPROVED:
        return f"Approved. All {len(REQUIRED_RULES)} required checks passed."
    top = reasons[0].title if reasons else ""
    if status == Status.REJECTED:
        return f"Rejected. {top}."
    if sub == SubState.INTERNAL_REVIEW:
        n = len({r.rule_id for r in reasons if r.status == 'error' or r.outcome_class != OutcomeClass.VENDOR_ACTION})
        extra = f" The vendor has also been asked for {len(asks)} item(s)." if asks else ""
        return f"Needs internal review ({n} issue{'s' if n != 1 else ''}). {top}.{extra}"
    return f"Waiting on the vendor for {len(asks)} item{'s' if len(asks) != 1 else ''}. {top}."

