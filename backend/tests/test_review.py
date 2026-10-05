"""Step 5a: reviewer actions — Approve / Request info / Reject — and what a human may not override."""

import json

import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_pipeline_deps
from app.db.engine import get_engine, init_db
from app.main import app
from app.pipeline.runner import PipelineDeps
from app.pipeline.seed import seed_demo_cases
from tests.conftest import TruthReader, load_sample

client = TestClient(app)


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch, ctx):
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("APP_PASSCODE", raising=False)
    init_db(f"sqlite:///{tmp_path / 'review.db'}")
    reader = TruthReader()
    app.dependency_overrides[get_pipeline_deps] = lambda: PipelineDeps(
        reader_factory=lambda: reader, cache=None, ctx=ctx, background=False)
    seed_demo_cases()
    yield
    app.dependency_overrides.clear()
    get_engine().dispose()


def cid(sample_id: str) -> int:
    return next(c for c in client.get("/api/cases").json() if c["sample_id"] == sample_id)["id"]


def review(case_id: int, action: str, reason: str = "checked the documents", reviewer: str = "Priya (AP)", **kw):
    return client.post(f"/api/cases/{case_id}/review",
                       json={"action": action, "reviewer": reviewer, "reason": reason, **kw})


def case(case_id: int) -> dict:
    return client.get(f"/api/cases/{case_id}").json()


# ---------- the three actions ----------

def test_approve_records_override_and_leaves_queue():
    e2 = cid("E2")
    assert case(e2)["can_review"] and case(e2)["can_approve"]
    r = review(e2, "approve", reason="Sole proprietor's personal account; matches GST trade name on file")
    assert r.status_code == 200
    c = case(e2)
    assert c["display_status"] == "APPROVED" and c["reasons"] == []
    hd = c["human_decision"]
    assert hd["action"] == "approve" and hd["actor"] == "Priya (AP)"
    assert [x["rule_id"] for x in hd["overridden_rules"]] == ["BANK-03"]
    assert e2 not in [x["id"] for x in client.get("/api/review-queue").json()]
    events = [e["event"] for e in client.get(f"/api/cases/{e2}/audit").json()]
    assert events[-3:] == ["review.approve", "status.changed", "message.sent"]


def test_reject_keeps_findings_as_the_reason():
    e1 = cid("E1")
    review(e1, "reject", reason="GSTIN belongs to a different legal entity")
    c = case(e1)
    assert c["display_status"] == "REJECTED" and [x["rule_id"] for x in c["reasons"]] == ["TAX-03"]
    assert c["can_reapply"] is True  # a new application is possible, and PRIOR-01 will apply


def test_request_info_moves_case_to_vendor():
    e5 = cid("E5")
    r = review(e5, "request_info", reason="confirm the bank change",
               message="Please send a letter on bank letterhead confirming the new account.")
    assert r.status_code == 200
    c = case(e5)
    assert c["display_status"] == "AWAITING_VENDOR" and c["can_resubmit"] is True
    assert c["human_decision"]["message"].startswith("Please send a letter")


# ---------- required inputs ----------

@pytest.mark.parametrize("body", [
    {"action": "approve", "reviewer": "Priya", "reason": "   "},
    {"action": "approve", "reviewer": "", "reason": "fine"},
    {"action": "request_info", "reviewer": "Priya", "reason": "need proof"},  # no vendor message
])
def test_reason_reviewer_and_message_are_required(body):
    assert client.post(f"/api/cases/{cid('E2')}/review", json=body).status_code == 422
    assert case(cid("E2"))["display_status"] == "INTERNAL_REVIEW"  # unchanged


def test_unknown_action_is_rejected_by_schema():
    assert client.post(f"/api/cases/{cid('E2')}/review",
                       json={"action": "escalate", "reviewer": "P", "reason": "x"}).status_code == 422


# ---------- only review cases, only once ----------

@pytest.mark.parametrize("sample_id", ["H1", "E3", "E4"])  # approved, awaiting vendor, rejected
def test_only_internal_review_cases_can_be_reviewed(sample_id):
    assert review(cid(sample_id), "approve").status_code == 409


def test_a_decided_case_cannot_be_reviewed_again():
    e2 = cid("E2")
    review(e2, "reject", reason="not satisfied")
    assert review(e2, "approve", reason="changed my mind").status_code == 409


# ---------- what a human may not override ----------

def test_cannot_approve_when_checks_did_not_run(ctx):
    """A misread GST certificate (DOC-03) blocks the cross-checks: a case can't be approved unchecked."""
    class MisreadingReader(TruthReader):
        def read(self, data, filename, mime):
            result = super().read(data, filename, mime)
            if result.data["doc_type"] == "gst_certificate":  # a value that isn't printed on the page
                result.data["fields"]["legal_name"]["value"] = "LUMEN ANALYTICS INDIA PRIVATE LIMITED"
            return result

    reader = MisreadingReader()
    app.dependency_overrides[get_pipeline_deps] = lambda: PipelineDeps(
        reader_factory=lambda: reader, cache=None, ctx=ctx, background=False)
    h1 = cid("H1")
    client.post(f"/api/cases/{h1}/replay")
    c = case(h1)
    assert c["display_status"] == "INTERNAL_REVIEW" and [x["rule_id"] for x in c["reasons"]] == ["DOC-03"]
    assert c["can_review"] is True and c["can_approve"] is False
    assert "didn't run" in c["approve_blocked_reason"]
    assert review(h1, "approve").status_code == 409
    # The reviewer's real options remain: ask for a clearer copy, or reject
    assert review(h1, "request_info", reason="unclear certificate",
                  message="Please upload a clearer copy of your GST certificate.").status_code == 200


def test_cannot_approve_while_vendor_still_owes_items():
    """Mixed case: BANK-03 review + a missing contact email. Approve waits for the complete application."""
    sample = load_sample("E2")
    e2 = cid("E2")
    client.post(f"/api/cases/{e2}/replay")  # make sure E2 has an executed run first
    sub = {**sample["case"]["submission"], "contact_email": None}
    client.post(f"/api/cases/{e2}/resubmit", data={"submission": json.dumps(sub)}, files={})
    c = case(e2)
    assert c["display_status"] == "INTERNAL_REVIEW" and c["can_review"] is True
    assert c["can_approve"] is False and "owes 1 item" in c["approve_blocked_reason"]
    assert review(e2, "approve").status_code == 409
    # Request info is the right move, and works
    assert review(e2, "request_info", reason="need contact", message="Please share a contact email.").status_code == 200


# ---------- replay after a human decision ----------

def test_replay_is_blocked_after_a_human_decision():
    e2 = cid("E2")
    review(e2, "approve", reason="verified with the vendor by phone")
    assert case(e2)["can_replay"] is False
    r = client.post(f"/api/cases/{e2}/replay")
    assert r.status_code == 409 and "override" in r.json()["detail"]


def test_resubmission_after_request_info_unblocks_and_runs_again():
    e5 = cid("E5")
    review(e5, "request_info", reason="bank change", message="Please confirm the new bank account.")
    assert case(e5)["can_replay"] is False  # the reviewer is waiting on the vendor, not on a rerun
    sample = load_sample("E5")
    r = client.post(f"/api/cases/{e5}/resubmit", data={"submission": json.dumps(sample["case"]["submission"])}, files={})
    assert r.status_code == 201
    c = case(e5)
    # Same facts -> DUP-01 fires again -> back to review for a fresh human decision
    assert c["display_status"] == "INTERNAL_REVIEW" and c["can_review"] is True and c["human_decision"] is None


def test_cannot_approve_an_interrupted_run():
    """Regression (found in the restart drill): an interrupted run has no results at all — not 'nothing failed'."""
    from app.db import models as m
    from app.db.engine import session_scope
    from app.pipeline.runner import recover_interrupted_runs

    h1 = cid("H1")
    with session_scope() as s:  # a replay cut off mid-way by a restart
        run = s.get(m.Case, h1).runs[-1]
        run.status = "running"
    recover_interrupted_runs()
    c = case(h1)
    assert c["display_status"] == "INTERNAL_REVIEW" and [x["rule_id"] for x in c["reasons"]] == ["SYS-01"]
    assert c["can_review"] is True and c["can_approve"] is False and "didn't complete" in c["approve_blocked_reason"]
    assert review(h1, "approve").status_code == 409
    assert c["can_replay"] is True  # the way forward


def test_request_and_response_are_carried_through_the_loop():
    """Gap A: the reviewer sees what they asked for and exactly what the vendor sent back."""
    from app.reference.data import SAMPLES_DIR

    e2 = cid("E2")
    ask = "Please send a letter on bank letterhead confirming the account holder."
    review(e2, "request_info", reason="confirm account holder", message=ask)

    waiting = case(e2)["request_context"]
    assert waiting["state"] == "waiting" and waiting["request"]["message"] == ask
    assert waiting["requested_on_version"] == 1 and waiting["response_version"] is None

    # The vendor responds: a new bank document and a corrected bank name; GST certificate and PAN card unchanged.
    sample = load_sample("E2")
    sub = {**sample["case"]["submission"], "bank": {**sample["case"]["submission"]["bank"], "bank_name": "ICICI Bank Ltd"}}
    cheque = sample["case"]["documents"]["bank_proof"]
    letter = (SAMPLES_DIR / "E2" / cheque["filename"]).read_bytes()
    r = client.post(f"/api/cases/{e2}/resubmit", data={"submission": json.dumps(sub)},
                    files={"bank_proof": ("bank_letter.pdf", letter, "application/pdf")})
    assert r.status_code == 201

    c = case(e2)
    ctx = c["request_context"]
    assert ctx["state"] == "responded" and ctx["response_version"] == 2 and ctx["responded_at"]
    assert ctx["replaced_documents"] == [{"slot": "bank_proof", "label": "Cheque / bank letter", "filename": "bank_letter.pdf"}]
    assert ctx["changed_fields"] == [{"field": "Bank name", "before": "ICICI Bank", "after": "ICICI Bank Ltd"}]
    # Same bank facts -> BANK-03 again -> back to a person, who now sees the request and the response
    assert c["display_status"] == "INTERNAL_REVIEW" and c["can_review"] is True
    row = next(x for x in client.get("/api/review-queue").json() if x["id"] == e2)
    assert row["vendor_responded"] is True


def test_request_context_clears_once_the_reviewer_decides():
    e5 = cid("E5")
    review(e5, "request_info", reason="bank change", message="Please confirm the new account.")
    sample = load_sample("E5")
    client.post(f"/api/cases/{e5}/resubmit", data={"submission": json.dumps(sample["case"]["submission"])}, files={})
    assert case(e5)["request_context"]["state"] == "responded"
    review(e5, "approve", reason="Confirmed with the vendor's bank")
    assert case(e5)["request_context"] is None and case(e5)["vendor_responded"] is False


def test_no_request_no_context():
    assert case(cid("E1"))["request_context"] is None
    assert all(x["vendor_responded"] is False for x in client.get("/api/review-queue").json())
