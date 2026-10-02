import pytest

from app.reference.data import load_reference
from app.rules.validators import (
    gstin_check_char,
    validate_account_number,
    validate_gstin,
    validate_ifsc,
    validate_pan,
)

STATES = load_reference().state_codes


def test_gstin_checksum_matches_published_example():
    # Widely published real GSTIN used as a format example.
    assert gstin_check_char("27AAPFU0939F1Z") == "V"
    assert validate_gstin("27AAPFU0939F1ZV", STATES).valid


@pytest.mark.parametrize("value,reason_part", [
    ("27AAPFU0939F1ZX", "check digit"),        # one-character typo
    ("27AAPFU0939F1Z", "15 characters"),
    ("00AAPFU0939F1ZV", "state code"),
    ("27AAPXU0939F1ZV", "embedded"),           # 4th PAN char X is not a holder type
    ("27AAPFU0939F1YV", "structure"),          # 14th char must be Z
])
def test_gstin_invalid(value, reason_part):
    v = validate_gstin(value, STATES)
    assert not v.valid and reason_part in v.reason


def test_gstin_tolerates_case_and_spaces():
    assert validate_gstin(" 27aapfu0939f1zv ", STATES).valid


@pytest.mark.parametrize("pan,valid", [
    ("AAACL4821K", True), ("AXRPP4412K", True), ("aaacl4821k", True),
    ("AAAXL4821K", False), ("AAACL482K", False), ("1AACL4821K", False), ("", False), (None, False),
])
def test_pan(pan, valid):
    assert validate_pan(pan).valid is valid


@pytest.mark.parametrize("ifsc,valid", [
    ("HDFC0000075", True), ("SBIN0001789", True), ("HDFC1000075", False), ("HDF0000075", False),
])
def test_ifsc(ifsc, valid):
    assert validate_ifsc(ifsc).valid is valid


@pytest.mark.parametrize("acct,valid", [
    ("50200074561238", True), ("5020 0074 5612 38", True), ("12345678", False), ("1234567890123456789", False),
    ("50200A74561238", False),
])
def test_account_number(acct, valid):
    assert validate_account_number(acct).valid is valid
