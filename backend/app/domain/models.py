"""Domain models shared by the rule engine, adapters, and API.

Phase 1 feeds `CaseInput` from JSON with pre-filled extracted document fields.
Phase 2 replaces the hand-written `documents` with LLM extraction output of the same shape.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------- Submission (what the vendor claims) ----------

class Address(BaseModel):
    line1: str | None = None
    city: str | None = None
    state: str | None = None
    pin_code: str | None = None


class BankDetails(BaseModel):
    account_holder_name: str | None = None
    account_number: str | None = None
    ifsc: str | None = None
    bank_name: str | None = None


EntityType = Literal["company", "llp", "partnership", "proprietorship"]


class Submission(BaseModel):
    """All fields optional so incomplete submissions can be represented and flagged (COMP-01)."""

    legal_name: str | None = None
    trade_name: str | None = None
    entity_type: EntityType | None = None
    address: Address = Field(default_factory=Address)
    contact_name: str | None = None
    contact_email: str | None = None
    gstin: str | None = None
    pan: str | None = None
    bank: BankDetails = Field(default_factory=BankDetails)


# ---------- Documents (what the evidence says) ----------

DocSlot = Literal["gst_certificate", "pan_card", "bank_proof"]
DocType = Literal["gst_certificate", "pan_card", "bank_proof", "invoice", "other", "unknown"]


class ExtractedField(BaseModel):
    value: str | None = None
    quote: str | None = None  # verbatim text from the document supporting the value
    page: int | None = None
    grounded: Literal["text", "image", "unverified"] | None = None


class DocumentInput(BaseModel):
    slot: DocSlot
    filename: str | None = None
    classified_type: DocType | None = None  # None = classification failed (system error)
    readable: bool = True
    fields: dict[str, ExtractedField] = Field(default_factory=dict)
    extraction_error: str | None = None  # set when the LLM call failed (system error)

    def value(self, name: str) -> str | None:
        f = self.fields.get(name)
        if f is None or f.value is None or not str(f.value).strip():
            return None
        return str(f.value).strip()


class CaseInput(BaseModel):
    submission: Submission
    documents: dict[DocSlot, DocumentInput] = Field(default_factory=dict)


# ---------- Check results and decision ----------

class OutcomeClass(str, Enum):
    VENDOR_ACTION = "VENDOR_ACTION"
    REVIEW = "REVIEW"
    REJECT = "REJECT"
    INFO = "INFO"


CheckStatus = Literal["pass", "fail", "blocked", "error"]


class CheckResult(BaseModel):
    rule_id: str
    stage: str
    status: CheckStatus
    outcome_class: OutcomeClass | None = None  # set when status == "fail"
    subject: str | None = None  # what was checked, e.g. "PAN card name"
    title: str  # business-language one-liner
    detail: str | None = None  # reviewer-facing explanation
    vendor_text: str | None = None  # only for VENDOR_ACTION fails
    evidence: dict[str, Any] = Field(default_factory=dict)
    blocked_by: str | None = None


class Status(str, Enum):
    APPROVED = "APPROVED"
    PENDING = "PENDING"
    REJECTED = "REJECTED"


class SubState(str, Enum):
    AWAITING_VENDOR = "AWAITING_VENDOR"
    INTERNAL_REVIEW = "INTERNAL_REVIEW"


class Decision(BaseModel):
    status: Status
    sub_state: SubState | None = None
    failing_rules: list[str]  # ordered by severity; errors appear as SYS-01
    reasons: list[CheckResult]  # fail + error results, ordered by severity
    vendor_actions: list[str]  # vendor-safe asks; empty when rejected
    summary: str
    rule_catalog_version: str


class Evaluation(BaseModel):
    decision: Decision
    results: list[CheckResult]
