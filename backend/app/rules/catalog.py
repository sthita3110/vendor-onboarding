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
    name: str  # what we checked, phrased as the passing condition ("What we checked" list)
    issue: str  # short label when it fails (dashboard / review-queue chips)
    outcome: OutcomeClass  # outcome when the rule fails
    required: bool = True  # must have status "pass" for approval


_RULES = [
    Rule("COMP-01", "completeness", "Documents", "All required details provided", "Missing details", V),
    Rule("COMP-02", "completeness", "Documents", "All required documents uploaded", "Missing document", V),
    Rule("FILE-01", "doc_processing", "Documents", "Files can be opened", "File can't be opened", V),
    Rule("DOC-01", "doc_processing", "Documents", "Each document is the right type", "Wrong document", V),
    Rule("DOC-02", "extraction", "Documents", "Documents are readable", "Unreadable document", V),
    Rule("DOC-03", "extraction", "Documents", "Documents were read reliably", "Unreliable read", R),
    Rule("TAX-01", "validation", "Tax", "GSTIN and PAN are valid", "Invalid GSTIN/PAN", V),
    Rule("BANK-01", "validation", "Bank", "Bank details are valid", "Invalid bank details", V),
    Rule("TAX-02", "cross_check", "Tax", "Tax IDs match the documents", "Tax ID mismatch", R),
    Rule("TAX-03", "cross_check", "Tax", "GSTIN belongs to the same PAN", "GSTIN/PAN conflict", R),
    Rule("TAX-04", "cross_check", "Tax", "GSTIN is registered in the vendor's state", "GSTIN wrong state", V),
    Rule("TAX-05", "cross_check", "Tax", "PAN type matches the business type", "PAN type mismatch", R),
    Rule("ID-01", "cross_check", "Identity", "Company name is consistent", "Name mismatch", R),
    Rule("BANK-02", "cross_check", "Bank", "Bank details match the bank proof", "Bank proof mismatch", R),
    Rule("TAX-06", "external_verify", "Tax", "GST registration is active", "GST not active", R),
    Rule("BANK-04", "external_verify", "Bank", "Bank account exists", "Bank account not verified", V),
    Rule("BANK-03", "external_verify", "Bank", "Bank account belongs to the company", "Bank holder mismatch", R),
    Rule("RISK-01", "risk", "Risk", "Not on the debarred list", "Debarred", X),
    Rule("RISK-02", "risk", "Risk", "No name match on the debarred list", "Possible debarred match", R),
    Rule("DUP-01", "risk", "Risk", "Not already a registered vendor", "Existing vendor", R),
    Rule("DUP-02", "risk", "Risk", "Bank account not used by another vendor", "Shared bank account", R),
    Rule("PRIOR-01", "risk", "Risk", "No earlier application was rejected", "Previously rejected", R),
    Rule("SYS-01", "any", "System", "All checks completed", "System check failed", R, required=False),
]

RULES: dict[str, Rule] = {r.id: r for r in _RULES}
RULE_ORDER: dict[str, int] = {r.id: i for i, r in enumerate(_RULES)}
REQUIRED_RULES: list[str] = [r.id for r in _RULES if r.required]

SEVERITY = {OutcomeClass.REJECT: 0, OutcomeClass.REVIEW: 1, OutcomeClass.VENDOR_ACTION: 2, OutcomeClass.INFO: 3}
