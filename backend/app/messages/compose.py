"""Compose the message a vendor receives about their application.

Defence in depth:
1. The AI writer only ever sees vendor-safe facts (company, contact, reference, number of items) — never findings.
2. The checklist of what to provide is rendered by code from the decision's vendor actions (or the reviewer's
   message), so the AI can't drop, add or reword an item.
3. Whatever the AI writes is filtered: internal vocabulary, rule IDs, and this case's private values (e.g. the
   bank's account-holder name) block the draft, and the fixed template is used instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from app.rules.names import normalize_name

Kind = Literal["approved", "action_needed", "under_review", "rejected"]

SIGNATURE = "Vendor Onboarding Team"

# Words that reveal internal checks or suspicion. Matched case-insensitively as substrings.
FORBIDDEN_TERMS = [
    "debar", "sanction", "blacklist", "blocklist", "black list", "watchlist", "fraud", "penny", "suspici",
    "risk", "flagged", "mismatch", "holder name", "vendor master", "duplicate", "rule", "score", "ai ",
]
RULE_ID = re.compile(r"\b[A-Z]{2,6}-\d{2}\b")

MAX_SUBJECT, MAX_PARAGRAPH = 120, 600


@dataclass
class MessageContext:
    """Vendor-safe facts only. `items` are already vendor-facing sentences produced by the rules or a reviewer."""

    kind: Kind
    company: str
    contact_name: str | None
    reference: str
    items: list[str] = field(default_factory=list)


@dataclass
class Draft:
    subject: str
    intro: str
    closing: str


@dataclass
class Message:
    kind: Kind
    subject: str
    body: str
    items: list[str]
    generated_by: str  # "llm:<model>" | "template" | "template (…reason…)"


class MessageWriter(Protocol):
    model: str

    def write(self, facts: dict[str, Any]) -> Draft: ...


# ---------- template ----------

def template_draft(ctx: MessageContext) -> Draft:
    n = len(ctx.items)
    if ctx.kind == "approved":
        return Draft(f"Your vendor onboarding is complete ({ctx.reference})",
                     f"Thank you for completing your onboarding with us. {ctx.company} is now approved as a vendor.",
                     "There is nothing further you need to do. We look forward to working with you.")
    if ctx.kind == "action_needed":
        return Draft(f"Action needed to complete your vendor onboarding ({ctx.reference})",
                     f"Thank you for your application for {ctx.company}. To complete your onboarding, we need "
                     f"{'the following' if n != 1 else 'one more thing'} from you:",
                     "Once you send these, we will continue processing your application. Thank you for your help.")
    if ctx.kind == "under_review":
        intro = f"Thank you for your application for {ctx.company}. It is currently being reviewed by our team."
        if n:
            intro += " In the meantime, please send us the following:"
        return Draft(f"Your vendor application is under review ({ctx.reference})", intro,
                     "We will be in touch as soon as the review is complete.")
    return Draft(f"Update on your vendor application ({ctx.reference})",
                 f"Thank you for your interest in becoming a vendor. After careful consideration, we are unable to "
                 f"proceed with the application for {ctx.company} at this time.",
                 "If you have any questions, please reply to this email and our team will get back to you.")


# ---------- safety ----------

def unsafe_reason(draft: Draft, private_terms: set[str]) -> str | None:
    """Why an AI draft can't be sent, or None if it's safe."""
    if not draft.subject.strip() or not draft.intro.strip() or not draft.closing.strip():
        return "empty section"
    if len(draft.subject) > MAX_SUBJECT or len(draft.intro) > MAX_PARAGRAPH or len(draft.closing) > MAX_PARAGRAPH:
        return "too long"
    text = f"{draft.subject}\n{draft.intro}\n{draft.closing}"
    lowered = text.lower()
    for term in FORBIDDEN_TERMS:
        if term in lowered:
            return f"internal term '{term.strip()}'"
    if RULE_ID.search(text):
        return "rule identifier"
    for term in private_terms:
        if term and len(term) >= 4 and term.lower() in lowered:
            return "a private case value"
    return None


# ---------- assembly ----------

LEADING_GREETING = re.compile(r"^\s*(dear|hello|hi|greetings)\b[^,\n]*,\s*", re.IGNORECASE)


def render(ctx: MessageContext, draft: Draft) -> str:
    greeting = f"Dear {ctx.contact_name}," if ctx.contact_name else f"Dear {ctx.company} team,"
    intro = LEADING_GREETING.sub("", draft.intro.strip(), count=1)  # the greeting line is ours, not the model's
    intro = intro[:1].upper() + intro[1:]
    parts = [greeting, "", intro]
    if ctx.items:
        parts += [""] + [f"  {i}. {item}" for i, item in enumerate(ctx.items, 1)]
    parts += ["", draft.closing.strip(), "", "Kind regards,", SIGNATURE, f"Reference: {ctx.reference}"]
    return "\n".join(parts)


def compose(ctx: MessageContext, writer: MessageWriter | None, private_terms: set[str] | None = None) -> Message:
    """AI-drafted subject/intro/closing when available and safe; the template otherwise. Never raises."""
    generated_by = "template"
    draft = template_draft(ctx)
    # A "private" value equal to the vendor's own name (e.g. a bank holder that matches the company) isn't secret.
    own = normalize_name(ctx.company)
    private_terms = {t for t in (private_terms or set()) if normalize_name(t) != own}
    if writer is not None:
        facts = {"kind": ctx.kind, "vendor_company": ctx.company, "contact_name": ctx.contact_name,
                 "reference": ctx.reference, "item_count": len(ctx.items)}
        try:
            ai = writer.write(facts)
        except Exception as e:  # network, timeout, bad output — fall back, never block a decision
            generated_by = f"template (AI unavailable: {type(e).__name__})"
        else:
            reason = unsafe_reason(ai, private_terms)
            if reason:
                generated_by = f"template (AI draft blocked: {reason})"
            else:
                draft, generated_by = ai, f"llm:{writer.model}"
    return Message(kind=ctx.kind, subject=draft.subject.strip(), body=render(ctx, draft), items=list(ctx.items),
                   generated_by=generated_by)


def kind_for(status: str, sub_state: str | None) -> Kind:
    if status == "APPROVED":
        return "approved"
    if status == "REJECTED":
        return "rejected"
    return "action_needed" if sub_state == "AWAITING_VENDOR" else "under_review"


def private_terms_from(evidence_items: list[dict[str, Any]]) -> set[str]:
    """Values from check evidence the vendor must never see: the account holder the bank reported, and names of
    other entities (debarred list, vendor master). Not the GST registry's legal name — that is the vendor's own."""
    terms: set[str] = set()
    for ev in evidence_items:
        resp = ev.get("adapter_response") or {}
        if resp.get("holder_name"):
            terms.add(str(resp["holder_name"]))
        for match in ev.get("matches") or []:
            for key in ("entity_name", "legal_name", "vendor_id"):
                if match.get(key):
                    terms.add(str(match[key]))
    return terms
