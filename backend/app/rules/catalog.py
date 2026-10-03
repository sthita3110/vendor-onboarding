"""Rule catalog v1 — single source of truth for rule IDs, outcome classes, and UI grouping.

Mirrors RULES.md §4. Changing an outcome here is a policy change: bump CATALOG_VERSION.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import OutcomeClass

CATALOG_VERSION = "v1"

V, R, X = OutcomeClass.VENDOR_ACTION, OutcomeClass.REVIEW, OutcomeClass.REJECT


@dataclass(frozen=True)
class Rule:
    id: str
    stage: str
    group: str  # UI grouping: Documents, Tax, Identity, Bank, Risk, System
    name: str  # short business label for "What we checked"
    outcome: OutcomeClass  # outcome when the rule fails
    required: bool = True  # must have status "pass" for approval


_RULES = [
    Rule("COMP-01", "completeness", "Documents", "All required details provided", V),
    Rule("COMP-02", "completeness", "Documents", "All required documents uploaded", V),
    Rule("FILE-01", "doc_processing", "Documents", "Files can be opened", V),
    Rule("DOC-01", "doc_processing", "Documents", "Each document is the right type", V),
    Rule("DOC-02", "extraction", "Documents", "Documents are readable", V),
    Rule("DOC-03", "extraction", "Documents", "Documents were read reliably", R),
    Rule("TAX-01", "validation", "Tax", "GSTIN and PAN are valid", V),
    Rule("BANK-01", "validation", "Bank", "Bank details are valid", V),
    Rule("TAX-02", "cross_check", "Tax", "Tax IDs match the documents", R),
    Rule("TAX-03", "cross_check", "Tax", "GSTIN belongs to the same PAN", R),
    Rule("TAX-04", "cross_check", "Tax", "GSTIN is registered in the vendor's state", V),
    Rule("TAX-05", "cross_check", "Tax", "PAN type matches the business type", R),
    Rule("ID-01", "cross_check", "Identity", "Company name is consistent", R),
    Rule("BANK-02", "cross_check", "Bank", "Bank details match the bank proof", R),
    Rule("TAX-06", "external_verify", "Tax", "GST registration is active", R),
    Rule("BANK-04", "external_verify", "Bank", "Bank account exists", V),
    Rule("BANK-03", "external_verify", "Bank", "Bank account belongs to the company", R),
    Rule("RISK-01", "risk", "Risk", "Not on the debarred list", X),
    Rule("RISK-02", "risk", "Risk", "No name match on the debarred list", R),
    Rule("DUP-01", "risk", "Risk", "Not already a registered vendor", R),
    Rule("DUP-02", "risk", "Risk", "Bank account not used by another vendor", R),
    Rule("SYS-01", "any", "System", "All checks completed", R, required=False),
]

RULES: dict[str, Rule] = {r.id: r for r in _RULES}
RULE_ORDER: dict[str, int] = {r.id: i for i, r in enumerate(_RULES)}
REQUIRED_RULES: list[str] = [r.id for r in _RULES if r.required]

SEVERITY = {OutcomeClass.REJECT: 0, OutcomeClass.REVIEW: 1, OutcomeClass.VENDOR_ACTION: 2, OutcomeClass.INFO: 3}
