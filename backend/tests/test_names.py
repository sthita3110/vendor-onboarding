import pytest

from app.rules.names import NameTier, match_names, normalize_name


@pytest.mark.parametrize("raw,expected", [
    ("Lumen Analytics Private Limited", "LUMEN ANALYTICS PVT LTD"),
    ("LUMEN ANALYTICS PVT. LTD.", "LUMEN ANALYTICS PVT LTD"),
    ("Lumen Analytics (P) Ltd", "LUMEN ANALYTICS PVT LTD"),
    ("M/s. Lumen Analytics Pvt Ltd", "LUMEN ANALYTICS PVT LTD"),
    ("The Lumen Analytics Pvt Ltd", "LUMEN ANALYTICS PVT LTD"),
    ("Konkan Logistics Limited Liability Partnership", "KONKAN LOGISTICS LLP"),
    ("Gupta & Sons Limited", "GUPTA AND SONS LTD"),
    ("Café Bistro Pvt Ltd", "CAFE BISTRO PVT LTD"),
])
def test_normalize(raw, expected):
    assert normalize_name(raw) == expected


def test_exact():
    assert match_names("Lumen Analytics Pvt Ltd", "lumen analytics  pvt ltd").tier == NameTier.EXACT


def test_normalized_bank_abbreviation():
    m = match_names("LUMEN ANALYTICS PVT LTD", "LUMEN ANALYTICS PRIVATE LIMITED")
    assert m.tier == NameTier.NORMALIZED and m.matched


def test_trade_name_tier_only_via_registered_trade_name():
    assert match_names("Shree Ganesh Caterers", "SURESH PATIL", "SHREE GANESH CATERERS").tier == NameTier.TRADE_NAME
    assert match_names("Shree Ganesh Caterers", "SURESH PATIL", None).tier == NameTier.MISMATCH


@pytest.mark.parametrize("candidate,anchor", [
    ("Lumen Analytics India Pvt Ltd", "Lumen Analytics Pvt Ltd"),   # subsidiary vs parent
    ("Lumen Analytics LLP", "Lumen Analytics Pvt Ltd"),             # different entity type
    ("ABD Traders Pvt Ltd", "ABC Traders Pvt Ltd"),                  # impersonation pattern
    ("RAKESH K SHARMA", "NORTHWIND SUPPLIES PRIVATE LIMITED"),
])
def test_near_matches_are_mismatches(candidate, anchor):
    """Fuzzy scoring would pass most of these; deterministic tiers must not."""
    assert match_names(candidate, anchor).tier == NameTier.MISMATCH


def test_mismatch_carries_token_diff():
    m = match_names("Lumen Analytics India Pvt Ltd", "Lumen Analytics Pvt Ltd")
    assert m.only_in_candidate == ["INDIA"] and m.only_in_anchor == []
