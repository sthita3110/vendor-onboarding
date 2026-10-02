"""Single-rule mutations of the clean case H1: each change should trigger exactly the intended rule(s)."""

from app.adapters.mock import MockGstRegistry, MockPennyDrop, UnavailableAdapter
from app.domain.models import CheckResult, Status, SubState
from app.rules.checks import EvaluationContext
from app.rules.engine import decide
from app.rules.evaluate import evaluate
from app.rules.validators import gstin_check_char
from tests.conftest import as_case, load_sample


def run(payload, ctx):
    return evaluate(as_case(payload), ctx)


def failing(payload, ctx) -> set[str]:
    return set(run(payload, ctx).decision.failing_rules)


def with_adapters(ctx, registry=None, bank=None) -> EvaluationContext:
    return EvaluationContext(ref=ctx.ref, registry=registry or ctx.registry, bank=bank or ctx.bank)


def set_all_names(payload, name):
    payload["submission"]["legal_name"] = name
    payload["submission"]["bank"]["account_holder_name"] = name
    d = payload["documents"]
    d["gst_certificate"]["fields"]["legal_name"]["value"] = name
    d["pan_card"]["fields"]["name"]["value"] = name
    d["bank_proof"]["fields"]["account_holder_name"]["value"] = name


# ---------- completeness / documents ----------

def test_missing_field_asks_vendor(h1, ctx):
    h1["submission"]["pan"] = "  "
    d = run(h1, ctx).decision
    assert d.failing_rules == ["COMP-01"] and d.sub_state == SubState.AWAITING_VENDOR
    assert d.vendor_actions == ["Please provide your PAN."]


def test_missing_document_asks_vendor(h1, ctx):
    del h1["documents"]["pan_card"]
    assert failing(h1, ctx) == {"COMP-02"}


def test_unreadable_document_asks_for_clearer_copy(h1, ctx):
    h1["documents"]["bank_proof"]["readable"] = False
    d = run(h1, ctx).decision
    assert d.failing_rules == ["DOC-02"] and "clear, complete copy" in d.vendor_actions[0]


def test_key_field_not_found(h1, ctx):
    h1["documents"]["pan_card"]["fields"]["pan"]["value"] = None
    assert failing(h1, ctx) == {"DOC-02"}


# ---------- tax ----------

def test_gstin_typo_is_vendor_fix_not_review(h1, ctx):
    g = h1["submission"]["gstin"]
    h1["submission"]["gstin"] = g[:-1] + ("A" if g[-1] != "A" else "B")
    d = run(h1, ctx).decision
    assert d.failing_rules == ["TAX-01"] and d.sub_state == SubState.AWAITING_VENDOR


def test_gstin_on_certificate_differs(h1, ctx):
    other = "29AAACL4821K2Z"
    h1["documents"]["gst_certificate"]["fields"]["gstin"]["value"] = other + gstin_check_char(other)
    assert failing(h1, ctx) == {"TAX-02"}


def test_pan_type_vs_entity_type(h1, ctx):
    h1["submission"]["entity_type"] = "llp"  # LLP PAN should have 'F' as 4th char; H1 has 'C'
    assert failing(h1, ctx) == {"TAX-05"}


def test_cancelled_gst_registration(h1, ctx):
    g = h1["submission"]["gstin"]
    registry = MockGstRegistry({g: {"status": "cancelled", "legal_name": "X"}})
    assert failing(h1, with_adapters(ctx, registry=registry)) == {"TAX-06"}


# ---------- identity ----------

def test_pan_card_name_mismatch(h1, ctx):
    h1["documents"]["pan_card"]["fields"]["name"]["value"] = "LUMEN ANALYTICS INDIA PRIVATE LIMITED"
    ev = run(h1, ctx)
    assert set(ev.decision.failing_rules) == {"ID-01"}
    assert ev.decision.reasons[0].evidence["only_in_candidate"] == ["INDIA"]


def test_proprietorship_passes_via_registered_trade_name(ctx):
    pan = "AXRPM5521K"  # 'P' = individual
    first14 = f"29{pan}1Z"
    gstin = first14 + gstin_check_char(first14)
    payload = load_sample("H1")["case"]
    sub = payload["submission"]
    sub.update(legal_name="Lumen Analytics", entity_type="proprietorship", pan=pan, gstin=gstin)
    sub["bank"]["account_holder_name"] = "Lumen Analytics"
    docs = payload["documents"]
    docs["gst_certificate"]["fields"]["legal_name"]["value"] = "LALITA MENON"
    docs["gst_certificate"]["fields"]["trade_name"]["value"] = "LUMEN ANALYTICS"
    docs["gst_certificate"]["fields"]["gstin"]["value"] = gstin
    docs["pan_card"]["fields"].update(name={"value": "LALITA MENON"}, pan={"value": pan})
    docs["bank_proof"]["fields"]["account_holder_name"]["value"] = "LUMEN ANALYTICS"

    ev = run(payload, with_adapters(ctx, bank=MockPennyDrop({})))  # sandbox echoes submitted holder
    assert ev.decision.status == Status.APPROVED
    tiers = {r.subject: r.evidence["match_tier"] for r in ev.results if r.rule_id == "ID-01"}
    assert tiers["Legal name on form"] == "TRADE_NAME" and tiers["Name on PAN card"] == "EXACT"


# ---------- bank ----------

def test_bank_proof_account_differs(h1, ctx):
    h1["documents"]["bank_proof"]["fields"]["account_number"]["value"] = "50200074561299"
    assert failing(h1, ctx) == {"BANK-02"}


def test_invalid_ifsc_blocks_penny_drop(h1, ctx):
    h1["submission"]["bank"]["ifsc"] = "HDFC1000075"
    ev = run(h1, ctx)
    assert ev.decision.failing_rules == ["BANK-01"]
    assert {r.rule_id for r in ev.results if r.blocked_by == "BANK-01"} >= {"BANK-03", "BANK-04", "BANK-02"}


def test_closed_account_asks_vendor(h1, ctx):
    s = h1["submission"]["bank"]
    bank = MockPennyDrop({f"{s['account_number']}|{s['ifsc']}": {"status": "closed", "holder_name": None}})
    d = run(h1, with_adapters(ctx, bank=bank)).decision
    assert d.failing_rules == ["BANK-04"] and d.sub_state == SubState.AWAITING_VENDOR


# ---------- risk ----------

def test_debarred_name_only_goes_to_review_not_reject(h1, ctx):
    set_all_names(h1, "SUNRISE INFRA PROJECTS PRIVATE LIMITED")  # on list, but with a different PAN
    d = run(h1, with_adapters(ctx, bank=MockPennyDrop({}))).decision
    assert d.failing_rules == ["RISK-02"] and d.status == Status.PENDING


def test_bank_account_reused_by_another_vendor(h1, ctx):
    master = ctx.ref.vendor_master[0]
    h1["submission"]["bank"].update(account_number=master.bank_account_number, ifsc=master.ifsc)
    h1["documents"]["bank_proof"]["fields"]["account_number"]["value"] = master.bank_account_number
    h1["documents"]["bank_proof"]["fields"]["ifsc"]["value"] = master.ifsc
    # The fixture returns the other vendor's name, so BANK-03 fires too — both are review signals.
    assert failing(h1, ctx) == {"DUP-02", "BANK-03"}


# ---------- precedence ----------

def test_reject_outranks_everything_and_suppresses_vendor_asks(ctx):
    payload = load_sample("E4")["case"]
    del payload["documents"]["pan_card"]
    d = run(payload, ctx).decision
    assert d.status == Status.REJECTED and d.failing_rules[0] == "RISK-01" and d.vendor_actions == []


def test_review_still_sends_vendor_fixable_items(ctx):
    payload = load_sample("E2")["case"]
    payload["submission"]["contact_email"] = None
    d = run(payload, ctx).decision
    assert d.sub_state == SubState.INTERNAL_REVIEW
    assert d.failing_rules == ["BANK-03", "COMP-01"]
    assert d.vendor_actions == ["Please provide your contact email."]


# ---------- fail closed ----------

def test_provider_outage_fails_closed(h1, ctx):
    down = UnavailableAdapter()
    d = run(h1, with_adapters(ctx, registry=down, bank=down)).decision
    assert d.status == Status.PENDING and d.sub_state == SubState.INTERNAL_REVIEW
    assert d.failing_rules == ["SYS-01"]


def test_extraction_failure_fails_closed(h1, ctx):
    h1["documents"]["gst_certificate"]["extraction_error"] = "LLM timeout"
    d = run(h1, ctx).decision
    assert d.sub_state == SubState.INTERNAL_REVIEW and d.failing_rules == ["SYS-01"]


def test_classification_failure_fails_closed(h1, ctx):
    h1["documents"]["pan_card"]["classified_type"] = None
    assert failing(h1, ctx) == {"SYS-01"}


def test_no_results_is_never_approved():
    d = decide([])
    assert d.status == Status.PENDING and d.failing_rules == ["SYS-01"]


def test_partial_results_are_never_approved():
    only_pass = [CheckResult(rule_id="COMP-01", stage="completeness", status="pass", title="ok")]
    assert decide(only_pass).status != Status.APPROVED
