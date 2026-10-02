"""Format and checksum validators for Indian identifiers. Pure functions, no I/O."""

from __future__ import annotations

import re
from dataclasses import dataclass

_ALNUM36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
ACCOUNT_RE = re.compile(r"^[0-9]{9,18}$")

# 4th character of a PAN encodes the holder type.
PAN_HOLDER_TYPES = {
    "C": "company",
    "P": "individual",
    "F": "firm / LLP",
    "H": "Hindu undivided family",
    "A": "association of persons",
    "T": "trust",
    "B": "body of individuals",
    "L": "local authority",
    "J": "artificial juridical person",
    "G": "government",
}

# Declared entity type -> expected PAN 4th character (TAX-05).
ENTITY_PAN_CHAR = {
    "company": "C",
    "llp": "F",
    "partnership": "F",
    "proprietorship": "P",
}


@dataclass(frozen=True)
class Validation:
    valid: bool
    reason: str | None = None


def clean_id(value: str | None) -> str:
    """Uppercase and strip whitespace — how IDs are compared everywhere."""
    return re.sub(r"\s+", "", value or "").upper()


def clean_account(value: str | None) -> str:
    return re.sub(r"[\s-]+", "", value or "")


def gstin_check_char(first14: str) -> str:
    """GSTIN check character: base-36 weighted sum with alternating factors 1, 2."""
    total = 0
    for i, ch in enumerate(first14):
        product = _ALNUM36.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return _ALNUM36[(36 - total % 36) % 36]


def validate_pan(value: str | None) -> Validation:
    pan = clean_id(value)
    if not PAN_RE.match(pan):
        return Validation(False, "PAN must be 5 letters, 4 digits, 1 letter (e.g. AAACL4821K)")
    if pan[3] not in PAN_HOLDER_TYPES:
        return Validation(False, f"PAN 4th character '{pan[3]}' is not a valid holder type")
    return Validation(True)


def validate_gstin(value: str | None, state_codes: dict[str, str]) -> Validation:
    gstin = clean_id(value)
    if len(gstin) != 15:
        return Validation(False, f"GSTIN must be 15 characters (got {len(gstin)})")
    if not GSTIN_RE.match(gstin):
        return Validation(False, "GSTIN structure is invalid (state code + PAN + entity no. + 'Z' + check digit)")
    if gstin[:2] not in state_codes:
        return Validation(False, f"GSTIN state code '{gstin[:2]}' does not exist")
    pan_check = validate_pan(gstin[2:12])
    if not pan_check.valid:
        return Validation(False, f"PAN embedded in GSTIN is invalid: {pan_check.reason}")
    expected = gstin_check_char(gstin[:14])
    if gstin[14] != expected:
        return Validation(False, "GSTIN check digit doesn't match — likely a typo")
    return Validation(True)


def validate_ifsc(value: str | None) -> Validation:
    if not IFSC_RE.match(clean_id(value)):
        return Validation(False, "IFSC must be 4 letters, '0', then 6 letters/digits (e.g. HDFC0001234)")
    return Validation(True)


def validate_account_number(value: str | None) -> Validation:
    if not ACCOUNT_RE.match(clean_account(value)):
        return Validation(False, "Account number must be 9–18 digits")
    return Validation(True)
