"""Deterministic checks, grouped by pipeline stage (ARCHITECTURE.md §4, RULES.md §4).

Each stage function reads the case and earlier results from `RunState` and appends
`CheckResult`s. Stages run in order; later stages consult earlier ones to decide whether
they are `blocked` (an input is missing for a reason already captured as a finding).

Result conventions:
- pass     the check ran and the condition holds
- fail     the check ran and the condition doesn't hold -> outcome class from the catalog
- blocked  the check couldn't run because of an earlier finding (`blocked_by`)
- error    the check couldn't run for a system reason -> SYS-01 (fail closed)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.adapters.base import BankVerification, BankVerifier, GstRegistry
from app.domain.models import CaseInput, CheckResult, DocumentInput, OutcomeClass, Submission
from app.reference.data import ReferenceData
from app.rules.catalog import RULES
from app.rules.names import NameTier, match_names
from app.rules.validators import (
    ENTITY_PAN_CHAR,
    Validation,
    PAN_HOLDER_TYPES,
    clean_account,
    clean_id,
    validate_account_number,
    validate_gstin,
    validate_ifsc,
    validate_pan,
)

# ---------- static configuration ----------

REQUIRED_FIELDS: list[tuple[str, str]] = [
    ("legal_name", "legal business name"),
    ("entity_type", "business type"),
    ("address.line1", "registered address"),
    ("address.city", "city"),
    ("address.state", "state"),
    ("address.pin_code", "PIN code"),
    ("contact_name", "contact name"),
    ("contact_email", "contact email"),
    ("gstin", "GSTIN"),
    ("pan", "PAN"),
    ("bank.account_holder_name", "bank account holder name"),
    ("bank.account_number", "bank account number"),
    ("bank.ifsc", "IFSC code"),
    ("bank.bank_name", "bank name"),
]

DOC_LABELS = {
    "gst_certificate": "GST registration certificate",
    "pan_card": "PAN card",
    "bank_proof": "cancelled cheque or bank letter",
    "invoice": "an invoice",
    "other": "a different document",
    "unknown": "an unrecognised document",
}

REQUIRED_DOCS = ["gst_certificate", "pan_card", "bank_proof"]

KEY_FIELDS: dict[str, list[tuple[str, str]]] = {
    "gst_certificate": [("legal_name", "legal name"), ("gstin", "GSTIN")],
    "pan_card": [("name", "name"), ("pan", "PAN")],
    "bank_proof": [
        ("account_holder_name", "account holder name"),
        ("account_number", "account number"),
        ("ifsc", "IFSC code"),
    ],
}


# Extracted values that must pass a format rule; failure means the document was misread (DOC-03).
EXTRACTED_FORMATS: dict[tuple[str, str], Callable[[str, dict[str, str]], Validation]] = {
    ("gst_certificate", "gstin"): lambda v, states: validate_gstin(v, states),
    ("pan_card", "pan"): lambda v, _: validate_pan(v),
    ("bank_proof", "ifsc"): lambda v, _: validate_ifsc(v),
    ("bank_proof", "account_number"): lambda v, _: validate_account_number(v),
}


def cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def lower_first(text: str) -> str:
    """Lowercase the first letter unless the first word is an acronym (GSTIN, IFSC, PAN)."""
    return text if text[:2].isupper() else text[:1].lower() + text[1:]


def mask(account: str | None) -> str:
    a = clean_account(account)
    return f"••••{a[-4:]}" if len(a) >= 4 else a


# ---------- run state ----------

@dataclass
class EvaluationContext:
    ref: ReferenceData
    registry: GstRegistry
    bank: BankVerifier


@dataclass
class RunState:
    case: CaseInput
    ctx: EvaluationContext
    results: list[CheckResult] = field(default_factory=list)
    # field path -> rule id that makes the form value unusable (COMP-01 / TAX-01 / BANK-01)
    form_blockers: dict[str, str] = field(default_factory=dict)
    # doc slot -> rule id that makes the document unusable (COMP-02 / DOC-01 / DOC-02)
    doc_blockers: dict[str, str] = field(default_factory=dict)

    @property
    def sub(self) -> Submission:
        return self.case.submission

    def form(self, path: str) -> str | None:
        obj: Any = self.sub
        for part in path.split("."):
            obj = getattr(obj, part, None)
        if obj is None or not str(obj).strip():
            return None
        return str(obj).strip()

    def doc(self, slot: str) -> DocumentInput | None:
        return self.case.documents.get(slot)  # type: ignore[arg-type]

    def usable_doc(self, slot: str) -> DocumentInput | None:
        return None if slot in self.doc_blockers else self.doc(slot)

    def form_blocker(self, *paths: str) -> str | None:
        for p in paths:
            if p in self.form_blockers:
                return self.form_blockers[p]
        return None

    def doc_blocker(self, *slots: str) -> str | None:
        for s in slots:
            if s in self.doc_blockers:
                return self.doc_blockers[s]
        return None

    # --- result constructors ---

    def _add(self, rule_id: str, status: str, title: str, **kw: Any) -> CheckResult:
        rule = RULES[rule_id]
        r = CheckResult(
            rule_id=rule_id,
            stage=rule.stage,
            status=status,  # type: ignore[arg-type]
            outcome_class=rule.outcome if status == "fail" else None,
            title=title,
            **kw,
        )
        self.results.append(r)
        return r

    def passed(self, rule_id: str, title: str, **kw: Any) -> CheckResult:
        return self._add(rule_id, "pass", title, **kw)

    def failed(self, rule_id: str, title: str, **kw: Any) -> CheckResult:
        return self._add(rule_id, "fail", title, **kw)

    def blocked(self, rule_id: str, by: str, subject: str | None = None) -> CheckResult:
        label = RULES[rule_id].name if subject is None else subject
        return self._add(
            rule_id, "blocked", f"Not checked: {lower_first(label)}",
            subject=subject, blocked_by=by,
            detail=f"Skipped because of an earlier finding ({by}).",
        )

    def errored(self, rule_id: str, title: str, detail: str, **kw: Any) -> CheckResult:
        return self._add(rule_id, "error", title, detail=detail, **kw)


# ---------- stage 1: completeness ----------

def stage_completeness(s: RunState) -> None:
    missing = [(path, label) for path, label in REQUIRED_FIELDS if s.form(path) is None]
    for path, label in missing:
        s.form_blockers[path] = "COMP-01"
        s.failed(
            "COMP-01", f"Missing {label}", subject=label,
            vendor_text=f"Please provide your {label}.", evidence={"field": path},
        )
    if not missing:
        s.passed("COMP-01", "All required details provided")

    missing_docs = [slot for slot in REQUIRED_DOCS if s.doc(slot) is None]
    for slot in missing_docs:
        s.doc_blockers[slot] = "COMP-02"
        s.failed(
            "COMP-02", f"Missing {DOC_LABELS[slot]}", subject=DOC_LABELS[slot],
            vendor_text=f"Please upload your {DOC_LABELS[slot]}.", evidence={"slot": slot},
        )
    if not missing_docs:
        s.passed("COMP-02", "All required documents uploaded")


# ---------- stage 2: document processing ----------

def stage_doc_processing(s: RunState) -> None:
    # FILE-01: the file itself can be used (checked before any AI call)
    for slot in REQUIRED_DOCS:
        label = DOC_LABELS[slot]
        if slot in s.doc_blockers:
            s.blocked("FILE-01", s.doc_blockers[slot], subject=label)
            continue
        doc = s.doc(slot)
        assert doc is not None
        if doc.file_problem:
            s.doc_blockers[slot] = "FILE-01"
            s.failed(
                "FILE-01", f"The file uploaded as {label} can't be opened", subject=label,
                detail=doc.file_problem, evidence={"slot": slot, "filename": doc.filename},
                vendor_text=(f"We couldn't open the file you uploaded as your {label}"
                             f"{f' ({doc.filename})' if doc.filename else ''}: {doc.file_problem}."),
            )
        else:
            s.passed("FILE-01", f"{cap(label)} file opened", subject=label)

    # DOC-01: each document is the type its slot expects
    for slot in REQUIRED_DOCS:
        label = DOC_LABELS[slot]
        if slot in s.doc_blockers:
            s.blocked("DOC-01", s.doc_blockers[slot], subject=label)
            continue
        doc = s.doc(slot)
        assert doc is not None
        ev = {"slot": slot, "filename": doc.filename, "classified_type": doc.classified_type}
        if doc.classified_type is None:
            s.doc_blockers[slot] = "DOC-01"
            s.errored("DOC-01", f"Couldn't identify the {label}", "Document classification did not complete.",
                      subject=label, evidence=ev)
        elif doc.classified_type != slot:
            s.doc_blockers[slot] = "DOC-01"
            found = DOC_LABELS.get(doc.classified_type, doc.classified_type)
            s.failed(
                "DOC-01", f"File uploaded as {label} appears to be {found}", subject=label, evidence=ev,
                vendor_text=(f"The file you uploaded as your {label}"
                             f"{f' ({doc.filename})' if doc.filename else ''} appears to be {found}. "
                             f"Please upload your {label}."),
            )
        else:
            s.passed("DOC-01", f"{cap(label)} is the right document type", subject=label, evidence=ev)


# ---------- stage 3: extraction ----------

def stage_extraction(s: RunState) -> None:
    for slot in REQUIRED_DOCS:
        label = DOC_LABELS[slot]
        if slot in s.doc_blockers:
            s.blocked("DOC-02", s.doc_blockers[slot], subject=label)
            continue
        doc = s.doc(slot)
        assert doc is not None
        if doc.extraction_error:
            s.doc_blockers[slot] = "DOC-02"
            s.errored("DOC-02", f"Couldn't read the {label}", f"Extraction failed: {doc.extraction_error}",
                      subject=label)
            continue
        if not doc.readable:
            s.doc_blockers[slot] = "DOC-02"
            s.failed("DOC-02", f"The {label} is unreadable", subject=label,
                     vendor_text=f"We couldn't read your {label}. Please upload a clear, complete copy.")
            continue
        missing = [lbl for name, lbl in KEY_FIELDS[slot] if doc.value(name) is None]
        if missing:
            s.doc_blockers[slot] = "DOC-02"
            s.failed(
                "DOC-02", f"Couldn't find {', '.join(missing)} on the {label}", subject=label,
                evidence={"missing_fields": missing},
                vendor_text=(f"We couldn't find the {', '.join(missing)} on your {label}. "
                             f"Please upload a clear, complete copy."),
            )
            continue
        s.passed("DOC-02", f"Read the {label}", subject=label,
                 evidence={name: doc.value(name) for name, _ in KEY_FIELDS[slot]})

    # DOC-03: what was read is trustworthy — printed on the page (grounding) and well-formed (format).
    # A misread is our problem, not the vendor's, so it goes to internal review, and the document is
    # blocked from cross-checks so a misread never masquerades as "doesn't match the form".
    for slot in REQUIRED_DOCS:
        label = DOC_LABELS[slot]
        if slot in s.doc_blockers:
            s.blocked("DOC-03", s.doc_blockers[slot], subject=label)
            continue
        doc = s.doc(slot)
        assert doc is not None
        problems: list[str] = []
        grounding: dict[str, str | None] = {}
        for name, field_label in KEY_FIELDS[slot]:
            f = doc.fields[name]
            grounding[name] = f.grounded
            # "unverified" = a text layer exists but the value isn't in it. ("image" = scan, can't check;
            # None = grounding not run, e.g. hand-built fixtures.)
            if f.grounded == "unverified":
                problems.append(f"{field_label} '{f.value}' was not found in the document's text")
            check = EXTRACTED_FORMATS.get((slot, name))
            if check:
                v = check(f.value or "", s.ctx.ref.state_codes)
                if not v.valid:
                    problems.append(f"{field_label} was read as '{f.value}', which is not valid: {v.reason}")
        ev = {"grounding": grounding, "problems": problems}
        if problems:
            s.doc_blockers[slot] = "DOC-03"
            s.failed("DOC-03", f"The {label} couldn't be read reliably", subject=label, evidence=ev,
                     detail="; ".join(problems) + ". Check the document manually; if it is unclear, "
                            "request a clearer copy from the vendor.")
        else:
            how = "checked against the document text" if "text" in grounding.values() else "format-checked (scan)"
            s.passed("DOC-03", f"{cap(label)} read reliably ({how})", subject=label, evidence=ev)


# ---------- stage 4: field validation ----------

def stage_validation(s: RunState) -> None:
    gst_states = s.ctx.ref.state_codes
    for path, label, rule_id, validate in [
        ("gstin", "GSTIN", "TAX-01", lambda v: validate_gstin(v, gst_states)),
        ("pan", "PAN", "TAX-01", validate_pan),
        ("bank.ifsc", "IFSC code", "BANK-01", validate_ifsc),
        ("bank.account_number", "bank account number", "BANK-01", validate_account_number),
    ]:
        if path in s.form_blockers:
            s.blocked(rule_id, s.form_blockers[path], subject=label)
            continue
        value = s.form(path)
        v = validate(value)
        ev = {"field": path, "value": value}
        if v.valid:
            s.passed(rule_id, f"{cap(label)} format is valid", subject=label, evidence=ev)
        else:
            s.form_blockers[path] = rule_id
            s.failed(
                rule_id, f"{cap(label)} is invalid", subject=label, detail=v.reason, evidence=ev,
                vendor_text=f"The {label} you entered ({value}) isn't valid: {v.reason}. Please check and correct it.",
            )


# ---------- stage 5: cross-checks ----------

def _anchor(s: RunState) -> tuple[str | None, str | None]:
    """GST certificate Legal Name (anchor) and Trade Name."""
    gst = s.usable_doc("gst_certificate")
    if gst is None:
        return None, None
    return gst.value("legal_name"), gst.value("trade_name")


def stage_cross_check(s: RunState) -> None:
    gst, pan_card, bank_doc = s.usable_doc("gst_certificate"), s.usable_doc("pan_card"), s.usable_doc("bank_proof")
    form_gstin, form_pan = clean_id(s.form("gstin")), clean_id(s.form("pan"))

    # TAX-02: IDs on documents match the form
    for subject, field_path, slot, doc_field in [
        ("GSTIN on GST certificate", "gstin", "gst_certificate", "gstin"),
        ("PAN on PAN card", "pan", "pan_card", "pan"),
    ]:
        by = s.form_blocker(field_path) or s.doc_blocker(slot)
        if by:
            s.blocked("TAX-02", by, subject=subject)
            continue
        doc = s.usable_doc(slot)
        assert doc is not None
        form_v, doc_v = clean_id(s.form(field_path)), clean_id(doc.value(doc_field))
        ev = {"form_value": form_v, "doc_value": doc_v, "source_doc": slot,
              "quote": doc.fields[doc_field].quote, "page": doc.fields[doc_field].page}
        if form_v == doc_v:
            s.passed("TAX-02", f"{subject} matches the form", subject=subject, evidence=ev)
        else:
            s.failed("TAX-02", f"{subject} doesn't match the form", subject=subject, evidence=ev,
                     detail=f"Form says {form_v}; document says {doc_v}.")

    # TAX-03: PAN embedded in GSTIN matches the submitted PAN
    by = s.form_blocker("gstin")
    if by:
        s.blocked("TAX-03", by)
    else:
        embedded = form_gstin[2:12]
        comparisons: list[tuple[str, str | None, str | None]] = [
            ("PAN on form", form_pan if not s.form_blocker("pan") else None, s.form_blocker("pan")),
            ("PAN on PAN card", clean_id(pan_card.value("pan")) if pan_card else None, s.doc_blocker("pan_card")),
        ]
        for subject, pan_value, blocker in comparisons:
            if blocker:
                s.blocked("TAX-03", blocker, subject=subject)
                continue
            ev = {"gstin": form_gstin, "pan_in_gstin": embedded, "pan": pan_value}
            if pan_value == embedded:
                s.passed("TAX-03", f"GSTIN belongs to the same PAN ({subject})", subject=subject, evidence=ev)
            else:
                s.failed(
                    "TAX-03", "GSTIN belongs to a different PAN than the one submitted", subject=subject,
                    evidence=ev,
                    detail=(f"GSTIN {form_gstin} contains PAN {embedded}, but the {subject} is {pan_value}. "
                            f"The GSTIN's check digit is valid, so this is not a typo — it is the "
                            f"registration of a different legal entity."),
                )

    # TAX-04: GSTIN state code matches address state
    by = s.form_blocker("gstin", "address.state")
    if by:
        s.blocked("TAX-04", by)
    else:
        code = form_gstin[:2]
        gst_state = s.ctx.ref.state_name(code) or code
        addr_state = s.form("address.state") or ""
        ev = {"gstin_state_code": code, "gstin_state": gst_state, "address_state": addr_state}
        if gst_state.casefold() == addr_state.casefold():
            s.passed("TAX-04", f"GSTIN is registered in {gst_state}, matching the address", evidence=ev)
        else:
            s.failed(
                "TAX-04", f"GSTIN is registered in {gst_state}, but the address is in {addr_state}", evidence=ev,
                detail="A business has one GSTIN per state; this looks like another state's registration.",
                vendor_text=(f"The GSTIN you provided ({form_gstin}) is registered in {gst_state}, but your "
                             f"business address is in {addr_state}. Please provide the GSTIN and GST "
                             f"registration certificate for your {addr_state} registration."),
            )

    # TAX-05: PAN holder type matches declared entity type
    by = s.form_blocker("pan", "entity_type")
    if by:
        s.blocked("TAX-05", by)
    else:
        entity = s.form("entity_type") or ""
        expected, actual = ENTITY_PAN_CHAR.get(entity), form_pan[3]
        ev = {"entity_type": entity, "pan": form_pan, "pan_holder_char": actual,
              "pan_holder_type": PAN_HOLDER_TYPES.get(actual)}
        if actual == expected:
            s.passed("TAX-05", f"PAN type ({PAN_HOLDER_TYPES[actual]}) matches business type", evidence=ev)
        else:
            s.failed("TAX-05", "PAN type doesn't match the business type", evidence=ev,
                     detail=(f"PAN {form_pan} is issued to a {PAN_HOLDER_TYPES.get(actual, 'unknown')} "
                             f"(4th character '{actual}'), but the business type is '{entity}'."))

    # ID-01: names are consistent with the GST certificate legal name
    anchor, trade = _anchor(s)
    name_subjects = [
        ("Legal name on form", s.form("legal_name"), s.form_blocker("legal_name"), "form", None),
        ("Name on PAN card", pan_card.value("name") if pan_card else None, s.doc_blocker("pan_card"), "pan_card", "name"),
        ("Account holder on bank proof", bank_doc.value("account_holder_name") if bank_doc else None,
         s.doc_blocker("bank_proof"), "bank_proof", "account_holder_name"),
        ("Account holder name on form", s.form("bank.account_holder_name"),
         s.form_blocker("bank.account_holder_name"), "form", None),
    ]
    for subject, candidate, blocker, source, doc_field in name_subjects:
        by = s.doc_blocker("gst_certificate") or blocker
        if by:
            s.blocked("ID-01", by, subject=subject)
            continue
        assert anchor is not None and candidate is not None
        m = match_names(candidate, anchor, trade)
        ev = {**m.as_evidence(), "source": source}
        if doc_field and source != "form":
            src = s.usable_doc(source)
            if src:
                ev.update(quote=src.fields[doc_field].quote, page=src.fields[doc_field].page)
        if m.matched:
            note = " (via registered trade name)" if m.tier == NameTier.TRADE_NAME else ""
            s.passed("ID-01", f"{subject} matches the GST certificate{note}", subject=subject, evidence=ev)
        else:
            s.failed("ID-01", f"{subject} doesn't match the GST certificate", subject=subject, evidence=ev,
                     detail=f"'{candidate}' vs GST legal name '{anchor}'.")

    # BANK-02: bank proof matches the bank details on the form
    for subject, path, doc_field, clean in [
        ("Account number", "bank.account_number", "account_number", clean_account),
        ("IFSC code", "bank.ifsc", "ifsc", clean_id),
    ]:
        by = s.doc_blocker("bank_proof") or s.form_blocker(path)
        if by:
            s.blocked("BANK-02", by, subject=subject)
            continue
        assert bank_doc is not None
        form_v, doc_v = clean(s.form(path)), clean(bank_doc.value(doc_field))
        ev = {"form_value": form_v, "doc_value": doc_v, "source_doc": "bank_proof",
              "quote": bank_doc.fields[doc_field].quote, "page": bank_doc.fields[doc_field].page}
        shown = (mask(form_v), mask(doc_v)) if doc_field == "account_number" else (form_v, doc_v)
        if form_v == doc_v:
            s.passed("BANK-02", f"{subject} on bank proof matches the form", subject=subject, evidence=ev)
        else:
            s.failed("BANK-02", f"{subject} on bank proof doesn't match the form", subject=subject, evidence=ev,
                     detail=f"Form: {shown[0]}; bank proof: {shown[1]}.")


# ---------- stage 6: external verification ----------

def stage_external_verify(s: RunState) -> None:
    # TAX-06: GST registry
    by = s.form_blocker("gstin")
    if by:
        s.blocked("TAX-06", by)
    else:
        gstin = clean_id(s.form("gstin"))
        try:
            rec = s.ctx.registry.lookup(gstin)
        except Exception as e:  # provider failure -> fail closed
            s.errored("TAX-06", "Couldn't reach the GST registry", f"{type(e).__name__}: {e}")
        else:
            ev = {"adapter_response": rec.model_dump()}
            if rec.status == "active":
                s.passed("TAX-06", "GST registration is active", evidence=ev)
            else:
                label = "not found" if rec.status == "not_found" else rec.status
                s.failed("TAX-06", f"GST registration is {label}", evidence=ev,
                         detail=f"GST registry reports {gstin} as {label}.")

    # BANK-04 / BANK-03: penny drop
    by = s.form_blocker("bank.account_number", "bank.ifsc")
    if by:
        s.blocked("BANK-04", by)
        s.blocked("BANK-03", by)
        return
    acct, ifsc = s.form("bank.account_number") or "", s.form("bank.ifsc") or ""
    try:
        bv: BankVerification = s.ctx.bank.verify(acct, ifsc, submitted_holder=s.form("bank.account_holder_name"))
    except Exception as e:
        detail = f"{type(e).__name__}: {e}"
        s.errored("BANK-04", "Couldn't reach the bank verification service", detail)
        s.errored("BANK-03", "Couldn't confirm the bank account holder", detail)
        return

    ev = {"adapter_response": bv.model_dump()}
    if bv.status != "verified":
        s.failed(
            "BANK-04", f"Bank account {mask(acct)} couldn't be verified ({bv.status.replace('_', ' ')})",
            evidence=ev,
            vendor_text=(f"We couldn't verify the bank account ending {clean_account(acct)[-4:]} "
                         f"(IFSC {clean_id(ifsc)}). Please confirm your account number and IFSC code."),
        )
        s.blocked("BANK-03", "BANK-04")
        return
    s.passed("BANK-04", f"Bank account {mask(acct)} exists", evidence=ev)

    anchor, trade = _anchor(s)
    if anchor is None:
        s.blocked("BANK-03", s.doc_blocker("gst_certificate") or "DOC-02")
        return
    if not bv.holder_name:
        s.errored("BANK-03", "Bank didn't return an account holder name",
                  "Verification succeeded but no holder name was returned.", evidence=ev)
        return
    m = match_names(bv.holder_name, anchor, trade)
    ev.update(m.as_evidence())
    if m.matched:
        note = " (via registered trade name)" if m.tier == NameTier.TRADE_NAME else ""
        s.passed("BANK-03", f"Bank account holder matches the company{note}", evidence=ev)
    else:
        # Deliberately no vendor_text: disclosing this teaches a fraudster what to fix.
        s.failed("BANK-03", "Bank account holder doesn't match the company name", evidence=ev,
                 detail=f"Bank reports the account holder as '{bv.holder_name}'; GST legal name is '{anchor}'.")


# ---------- stage 7: risk ----------

def stage_risk(s: RunState) -> None:
    ref = s.ctx.ref

    # RISK-01: PAN on debarred list (form PAN, PAN inside GSTIN, PAN card PAN)
    pans: set[str] = set()
    if not s.form_blocker("pan"):
        pans.add(clean_id(s.form("pan")))
    if not s.form_blocker("gstin"):
        pans.add(clean_id(s.form("gstin"))[2:12])
    pan_card = s.usable_doc("pan_card")
    if pan_card and validate_pan(pan_card.value("pan")).valid:
        pans.add(clean_id(pan_card.value("pan")))
    pan_hits = ref.debarred_by_pan(pans) if pans else []
    if not pans:
        s.blocked("RISK-01", s.form_blocker("pan") or "TAX-01")
    elif pan_hits:
        hit = pan_hits[0]
        # No vendor_text: the vendor gets a generic message that never names the list.
        s.failed("RISK-01", "Entity is on the debarred list",
                 evidence={"checked_pans": sorted(pans), "matches": [h.__dict__ for h in pan_hits]},
                 detail=f"PAN {hit.pan} matches '{hit.entity_name}' on {hit.list_source} "
                        f"(listed {hit.listed_on}: {hit.reason}).")
    else:
        s.passed("RISK-01", "Not on the debarred list", evidence={"checked_pans": sorted(pans)})

    # RISK-02: name-only match on debarred list
    anchor, _ = _anchor(s)
    names = {n for n in (s.form("legal_name"), anchor) if n}
    if not names:
        s.blocked("RISK-02", "COMP-01")
    else:
        hit_pans = {h.pan for h in pan_hits}
        name_hits = [d for d in ref.debarred_by_name(names) if d.pan not in hit_pans]
        if name_hits:
            hit = name_hits[0]
            s.failed("RISK-02", "Company name matches an entry on the debarred list",
                     evidence={"checked_names": sorted(names), "matches": [h.__dict__ for h in name_hits]},
                     detail=(f"Name matches '{hit.entity_name}' on {hit.list_source}, but the PAN differs "
                             f"({hit.pan}). Likely a different entity — confirm before proceeding."))
        else:
            s.passed("RISK-02", "No name match on the debarred list", evidence={"checked_names": sorted(names)})

    # DUP-01: already in vendor master
    pan, gstin = s.form("pan"), s.form("gstin")
    if not pan and not gstin:
        s.blocked("DUP-01", "COMP-01")
    else:
        existing = ref.master_by_pan_or_gstin(pan, gstin)
        if existing:
            v = existing[0]
            sub_acct, sub_ifsc = clean_account(s.form("bank.account_number")), clean_id(s.form("bank.ifsc"))
            bank_changed = (v.bank_account_number, v.ifsc) != (sub_acct, sub_ifsc)
            detail = f"Already registered as vendor {v.vendor_id} ({v.legal_name}, status: {v.status})."
            if bank_changed:
                detail += (f" Bank on file: {mask(v.bank_account_number)} / {v.ifsc}; "
                           f"submitted: {mask(sub_acct)} / {sub_ifsc} — bank details differ.")
            s.failed("DUP-01", f"Already registered as vendor {v.vendor_id}"
                     + (" with different bank details" if bank_changed else ""),
                     evidence={"matches": [m.__dict__ for m in existing], "bank_changed": bank_changed},
                     detail=detail)
        else:
            s.passed("DUP-01", "Not already a registered vendor")

    # DUP-02: bank account used by a different vendor
    by = s.form_blocker("bank.account_number", "bank.ifsc")
    if by:
        s.blocked("DUP-02", by)
    else:
        own_pan = clean_id(pan)
        others = [v for v in ref.master_by_bank(s.form("bank.account_number") or "", s.form("bank.ifsc") or "")
                  if v.pan != own_pan]
        if others:
            v = others[0]
            s.failed("DUP-02", "Bank account is already used by another vendor",
                     evidence={"matches": [m.__dict__ for m in others]},
                     detail=f"Account {mask(v.bank_account_number)} / {v.ifsc} belongs to vendor "
                            f"{v.vendor_id} ({v.legal_name}).")
        else:
            s.passed("DUP-02", "Bank account not used by another vendor")


# ---------- stage registry ----------

Stage = tuple[str, str, Callable[[RunState], None]]

STAGES: list[Stage] = [
    ("completeness", "Completeness", stage_completeness),
    ("doc_processing", "Document processing", stage_doc_processing),
    ("extraction", "Extraction", stage_extraction),
    ("validation", "Field validation", stage_validation),
    ("cross_check", "Cross-checks", stage_cross_check),
    ("external_verify", "External verification", stage_external_verify),
    ("risk", "Risk checks", stage_risk),
]

__all__ = ["EvaluationContext", "RunState", "STAGES", "OutcomeClass"]
