"""Deterministic, tiered legal-name matching (RULES.md §2).

No fuzzy similarity scores: near-matches in payments are risk signals, so anything that
is not equal after explicit normalization (or via a GST-registered trade name) is a MISMATCH.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum


class NameTier(str, Enum):
    EXACT = "EXACT"
    NORMALIZED = "NORMALIZED"
    TRADE_NAME = "TRADE_NAME"
    MISMATCH = "MISMATCH"


_PREFIXES = ("MESSRS", "THE")  # "M/S" is stripped by regex before punctuation handling

# Applied in order, as whole-word replacements. Suffixes are canonicalized, never removed:
# "… PVT LTD" vs "… LLP" must stay different entities.
_SUFFIX_RULES: list[tuple[str, str]] = [
    (r"\bLIMITED LIABILITY PARTNERSHIP\b", "LLP"),
    (r"\bPRIVATE LIMITED\b", "PVT LTD"),
    (r"\bPVT LIMITED\b", "PVT LTD"),
    (r"\bPRIVATE LTD\b", "PVT LTD"),
    (r"\bP LTD\b", "PVT LTD"),
    (r"\bLIMITED\b", "LTD"),
]


def normalize_name(name: str | None) -> str:
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = s.upper()
    # "M/S" must be handled before "/" is treated as punctuation.
    s = re.sub(r"^\s*M\s*/\s*S\.?\s+", "", s)
    s = s.replace("&", " AND ")
    s = re.sub(r"[.,'\"()\-/]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    tokens = s.split(" ")
    while tokens and tokens[0] in _PREFIXES and len(tokens) > 1:
        tokens = tokens[1:]
    s = " ".join(tokens)
    for pattern, repl in _SUFFIX_RULES:
        s = re.sub(pattern, repl, s)
    return s


def _casefold_ws(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().casefold()


@dataclass
class NameMatch:
    tier: NameTier
    candidate: str
    anchor: str
    candidate_normalized: str
    anchor_normalized: str
    only_in_candidate: list[str] = field(default_factory=list)
    only_in_anchor: list[str] = field(default_factory=list)

    @property
    def matched(self) -> bool:
        return self.tier != NameTier.MISMATCH

    def as_evidence(self) -> dict:
        ev = {
            "match_tier": self.tier.value,
            "candidate": self.candidate,
            "anchor": self.anchor,
            "candidate_normalized": self.candidate_normalized,
            "anchor_normalized": self.anchor_normalized,
        }
        if self.tier == NameTier.MISMATCH:
            ev["only_in_candidate"] = self.only_in_candidate
            ev["only_in_anchor"] = self.only_in_anchor
        return ev


def match_names(candidate: str, anchor: str, trade_name: str | None = None) -> NameMatch:
    """Compare `candidate` to the anchor legal name (GST certificate Legal Name)."""
    cand_n, anchor_n = normalize_name(candidate), normalize_name(anchor)

    def result(tier: NameTier) -> NameMatch:
        m = NameMatch(tier, candidate, anchor, cand_n, anchor_n)
        if tier == NameTier.MISMATCH:
            ct, at = cand_n.split(), anchor_n.split()
            m.only_in_candidate = [t for t in ct if t not in at]
            m.only_in_anchor = [t for t in at if t not in ct]
        return m

    if _casefold_ws(candidate) == _casefold_ws(anchor):
        return result(NameTier.EXACT)
    if cand_n and cand_n == anchor_n:
        return result(NameTier.NORMALIZED)
    if trade_name and cand_n and cand_n == normalize_name(trade_name):
        return result(NameTier.TRADE_NAME)
    return result(NameTier.MISMATCH)
