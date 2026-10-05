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
    assert events[-2:] == ["review.approve", "status.changed"]


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
