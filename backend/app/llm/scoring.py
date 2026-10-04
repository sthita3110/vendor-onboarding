"""Score an extracted document against ground truth (the sample JSON the PDF was rendered from).

Comparison tolerates only formatting (case, whitespace, ID spacing, thousands separators) — never
different content. Used by the live golden test and the model benchmark.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.domain.models import DocumentInput
from app.llm.schema import FIELDS_BY_TYPE
from app.rules.checks import KEY_FIELDS
from app.rules.validators import clean_account, clean_id


def norm(name: str, value: str | None) -> str:
    v = value or ""
    if name in ("gstin", "pan", "ifsc"):
        return clean_id(v)
    if name == "account_number":
        return clean_account(v)
    if name == "total_amount":
        return re.sub(r"[^\d.]", "", v)
    return re.sub(r"\s+", " ", v).strip().upper()


@dataclass
class Mismatch:
    field: str
    got: str | None
    want: str
    key: bool

    def __str__(self) -> str:
        return f"{self.field}{' (KEY)' if self.key else ''}: got {self.got!r}, want {self.want!r}"


@dataclass
class DocScore:
    type_ok: bool
    got_type: str | None
    want_type: str
    fields_checked: int = 0
    key_checked: int = 0
    mismatches: list[Mismatch] = field(default_factory=list)

    @property
    def key_mismatches(self) -> list[Mismatch]:
        return [m for m in self.mismatches if m.key]


def score_document(truth: dict, doc: DocumentInput) -> DocScore:
    want_type = truth["classified_type"]
    score = DocScore(type_ok=doc.classified_type == want_type, got_type=doc.classified_type, want_type=want_type)
    if not score.type_ok:
        return score
    key_names = {n for n, _ in KEY_FIELDS.get(want_type, [])}
    for name in FIELDS_BY_TYPE[want_type]:
        want = (truth["fields"].get(name) or {}).get("value")
        if want is None:
            continue
        got = doc.value(name)
        score.fields_checked += 1
        score.key_checked += name in key_names
        if norm(name, got) != norm(name, want):
            score.mismatches.append(Mismatch(name, got, want, name in key_names))
    return score
