"""Golden cases (RULES.md §5): each demo case must produce exactly its expected outcome."""

import pytest

from app.rules.evaluate import evaluate
from tests.conftest import SAMPLE_IDS, as_case, load_sample


@pytest.mark.parametrize("cid", SAMPLE_IDS)
def test_golden(cid, ctx):
    sample = load_sample(cid)
    exp = sample["expected"]
    ev = evaluate(as_case(sample["case"]), ctx)
    d = ev.decision
    assert d.status.value == exp["status"]
    assert (d.sub_state.value if d.sub_state else None) == exp["sub_state"]
    assert set(d.failing_rules) == set(exp["failing_rules"])
    assert not [r for r in ev.results if r.status == "error"], "golden cases must not hit system errors"


def test_h1_bank_name_passes_by_normalization_not_exact(ctx):
    ev = evaluate(as_case(load_sample("H1")["case"]), ctx)
    bank03 = next(r for r in ev.results if r.rule_id == "BANK-03")
    assert bank03.status == "pass" and bank03.evidence["match_tier"] == "NORMALIZED"


@pytest.mark.parametrize("cid", ["E2", "E4"])
def test_fraud_signals_are_not_disclosed_to_vendor(cid, ctx):
    d = evaluate(as_case(load_sample(cid)["case"]), ctx).decision
    assert d.vendor_actions == []


def test_e3_vendor_asks_are_specific(ctx):
    d = evaluate(as_case(load_sample("E3")["case"]), ctx).decision
    assert len(d.vendor_actions) == 2
    joined = " ".join(d.vendor_actions)
    assert "appears to be an invoice" in joined and "Tamil Nadu registration" in joined


def test_e3_bank_crosscheck_is_blocked_not_errored(ctx):
    ev = evaluate(as_case(load_sample("E3")["case"]), ctx)
    bank02 = [r for r in ev.results if r.rule_id == "BANK-02"]
    assert bank02 and all(r.status == "blocked" and r.blocked_by == "DOC-01" for r in bank02)


def test_e5_shows_bank_change(ctx):
    d = evaluate(as_case(load_sample("E5")["case"]), ctx).decision
    assert d.reasons[0].evidence["bank_changed"] is True
