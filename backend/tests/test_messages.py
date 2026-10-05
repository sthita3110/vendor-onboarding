"""Step 5b: vendor messages — template, AI wording with a code-built checklist, safety filter, outbox."""

import json

import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_pipeline_deps
from app.db.engine import get_engine, init_db
from app.main import app
from app.messages.compose import Draft, MessageContext, compose, private_terms_from, unsafe_reason
from app.pipeline.runner import PipelineDeps
from app.pipeline.seed import seed_demo_cases
from tests.conftest import TruthReader

client = TestClient(app)

E3_ASKS = ["Please upload your cancelled cheque or bank letter.", "Please provide the GSTIN for Tamil Nadu."]


class FakeWriter:
    model = "fake-llm"

    def __init__(self, draft: Draft | None = None, fail: Exception | None = None):
        self.draft, self.fail, self.seen = draft, fail, []

    def write(self, facts):
        self.seen.append(facts)
        if self.fail:
            raise self.fail
        return self.draft or Draft("Your application with us", f"Thank you for the application for {facts['vendor_company']}; please send the following:",
                                   "Thanks so much for your help.")


def ctx(kind="action_needed", items=None):
    return MessageContext(kind=kind, company="Kaveri Packaging Private Limited", contact_name="Meena Krishnan",
                          reference="VO-0004", items=E3_ASKS if items is None else items)


# ---------- composition ----------

@pytest.mark.parametrize("kind", ["approved", "action_needed", "under_review", "rejected"])
def test_template_for_every_kind(kind):
    msg = compose(ctx(kind, items=[] if kind in ("approved", "rejected") else E3_ASKS), writer=None)
    assert msg.generated_by == "template" and "VO-0004" in msg.subject and "Dear Meena Krishnan," in msg.body
    assert msg.body.rstrip().endswith("Reference: VO-0004")


def test_checklist_is_rendered_by_code_exactly():
    msg = compose(ctx(), FakeWriter())
    assert msg.generated_by == "llm:fake-llm"
    assert "  1. Please upload your cancelled cheque or bank letter." in msg.body
    assert "  2. Please provide the GSTIN for Tamil Nadu." in msg.body
    assert msg.items == E3_ASKS


def test_writer_sees_only_vendor_safe_facts():
    writer = FakeWriter()
    compose(ctx(), writer)
    assert writer.seen == [{"kind": "action_needed", "vendor_company": "Kaveri Packaging Private Limited",
                            "contact_name": "Meena Krishnan", "reference": "VO-0004", "item_count": 2}]


def test_rejection_message_gives_no_reason():
    body = compose(ctx("rejected", items=[]), writer=None).body.lower()
    assert "unable to proceed" in body and "debar" not in body and "because" not in body


# ---------- safety filter ----------

@pytest.mark.parametrize("text,why", [
    ("Your bank account failed our penny drop", "penny"),
    ("We found you on a debarment list", "debar"),
    ("Check BANK-03 failed", "rule identifier"),
    ("Possible fraud detected", "fraud"),
])
def test_internal_terms_block_the_ai_draft(text, why):
    msg = compose(ctx(), FakeWriter(Draft("Update", text, "Thanks.")))
    assert msg.generated_by.startswith("template (AI draft blocked") and why in msg.generated_by
    assert text not in msg.body


def test_private_case_values_block_the_ai_draft():
    private = private_terms_from([{"adapter_response": {"holder_name": "RAKESH K SHARMA", "status": "verified"}}])
    msg = compose(ctx("under_review", []), FakeWriter(Draft("Update", "The account belongs to Rakesh K Sharma.", "Thanks.")),
                  private)
    assert "private case value" in msg.generated_by and "rakesh" not in msg.body.lower()


def test_vendors_own_name_is_not_private():
    """Regression: the GST registry echoes the vendor's own legal name; that must not block a greeting by name."""
    ev = [{"adapter_response": {"status": "active", "legal_name": "KAVERI PACKAGING PRIVATE LIMITED"}},
          {"adapter_response": {"status": "verified", "holder_name": "KAVERI PACKAGING PVT LTD"}}]
    msg = compose(ctx(), FakeWriter(Draft("Update", "Thank you, Kaveri Packaging Private Limited.", "Thanks.")),
                  private_terms_from(ev))
    assert msg.generated_by == "llm:fake-llm"


def test_model_greeting_is_not_duplicated():
    msg = compose(ctx("approved", []), FakeWriter(Draft("Approved", "Dear Meena Krishnan, we are pleased to confirm.", "Thanks.")))
    assert msg.body.count("Dear Meena Krishnan") == 1 and "\n\nWe are pleased to confirm." in msg.body


def test_ai_failure_falls_back_to_template():
    msg = compose(ctx(), FakeWriter(fail=TimeoutError("slow")))
    assert msg.generated_by == "template (AI unavailable: TimeoutError)" and "  1. " in msg.body


def test_oversized_or_empty_drafts_are_rejected():
    assert unsafe_reason(Draft("x" * 200, "ok", "ok"), set()) == "too long"
    assert unsafe_reason(Draft("Subject", " ", "ok"), set()) == "empty section"


# ---------- end to end ----------

@pytest.fixture
def api(tmp_path, monkeypatch, ctx):
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("APP_PASSCODE", raising=False)
    init_db(f"sqlite:///{tmp_path / 'msg.db'}")
    reader, writer = TruthReader(), FakeWriter()
    app.dependency_overrides[get_pipeline_deps] = lambda: PipelineDeps(
        reader_factory=lambda: reader, cache=None, ctx=ctx, background=False, message_writer_factory=lambda: writer)
    seed_demo_cases()
    yield writer
    app.dependency_overrides.clear()
    get_engine().dispose()


def cid(sample_id):
    return next(c for c in client.get("/api/cases").json() if c["sample_id"] == sample_id)["id"]


def test_seeded_cases_have_template_messages(api):
    out = client.get("/api/outbox").json()
    assert len(out) == 6 and all(x["generated_by"] == "template" and x["status"] == "sent (simulated)" for x in out)
    kinds = {x["reference"]: x["kind"] for x in out}
    assert sorted(kinds.values()) == ["action_needed", "approved", "rejected", "under_review", "under_review", "under_review"]


def test_e2_message_never_reveals_the_bank_holder(api):
    e2 = cid("E2")
    msg = client.get(f"/api/cases/{e2}").json()["messages"][0]
    assert msg["kind"] == "under_review" and msg["items"] == []
    # The contact on the form *is* Rakesh Sharma, so greeting him is right; what must never appear is what the
    # bank reported ("RAKESH K SHARMA") or anything about the bank check.
    assert msg["body"].startswith("Dear Rakesh Sharma,")
    assert "RAKESH K SHARMA" not in msg["body"].upper() and "bank" not in msg["body"].lower()


def test_replay_with_unchanged_outcome_sends_nothing(api):
    e3 = cid("E3")
    run = client.get(f"/api/runs/{client.post(f'/api/cases/{e3}/replay').json()['run_id']}").json()
    notify = next(s for s in run["stages"] if s["key"] == "notify")
    assert "no new message sent" in notify["summary"]
    assert len(client.get(f"/api/cases/{e3}").json()["messages"]) == 1  # still just the seeded one


def test_new_outcome_sends_an_ai_worded_message(api):
    e2 = cid("E2")
    client.post(f"/api/cases/{e2}/review", json={"action": "approve", "reviewer": "Priya", "reason": "verified"})
    msgs = client.get(f"/api/cases/{e2}").json()["messages"]
    assert msgs[0]["kind"] == "approved" and msgs[0]["source"] == "review" and msgs[0]["ai_drafted"] is True


def test_request_info_puts_the_reviewers_words_in_the_checklist(api):
    e5 = cid("E5")
    ask = "Please send a letter on bank letterhead confirming the new account."
    client.post(f"/api/cases/{e5}/review", json={"action": "request_info", "reviewer": "Priya",
                                                  "reason": "bank change", "message": ask})
    msg = client.get(f"/api/cases/{e5}").json()["messages"][0]
    assert msg["kind"] == "action_needed" and msg["items"] == [ask] and f"  1. {ask}" in msg["body"]


def test_reviewer_rejection_sends_generic_notice(api):
    e1 = cid("E1")
    client.post(f"/api/cases/{e1}/review", json={"action": "reject", "reviewer": "Priya",
                                                  "reason": "GSTIN belongs to another entity"})
    msg = client.get(f"/api/cases/{e1}").json()["messages"][0]
    assert msg["kind"] == "rejected" and "GSTIN" not in msg["body"] and "another entity" not in msg["body"]


def test_message_audited(api):
    e2 = cid("E2")
    client.post(f"/api/cases/{e2}/review", json={"action": "reject", "reviewer": "Priya", "reason": "no"})
    events = [e for e in client.get(f"/api/cases/{e2}/audit").json() if e["event"] == "message.sent"]
    assert events[-1]["data"]["kind"] == "rejected" and events[-1]["data"]["source"] == "review"
    assert json.dumps(events[-1]["data"])  # serialisable record of what was sent
