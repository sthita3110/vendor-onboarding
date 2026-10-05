"""Reapply: a genuinely new application after rejection = a new case linked to the rejected one, always reviewed
by a person (PRIOR-01). Resubmit = correction of the same application; Replay = rerun the same data."""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.routes import get_pipeline_deps
from app.db import models as m
from app.db.engine import get_engine, init_db, session_scope
from app.db.repository import set_case_status
from app.domain.models import CaseInput, PriorRejection, Status, SubState
from app.main import app
from app.pipeline.runner import PipelineDeps
from app.pipeline.seed import seed_demo_cases
from app.reference.data import SAMPLES_DIR
from app.rules.evaluate import evaluate
from tests.conftest import TruthReader, load_sample

client = TestClient(app)


@pytest.fixture
def db(tmp_path, monkeypatch, ctx):
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("APP_PASSCODE", raising=False)
    init_db(f"sqlite:///{tmp_path / 'reapply.db'}")
    reader = TruthReader()
    app.dependency_overrides[get_pipeline_deps] = lambda: PipelineDeps(
        reader_factory=lambda: reader, cache=None, ctx=ctx, background=False)
    seed_demo_cases()
    yield
    app.dependency_overrides.clear()
    get_engine().dispose()


def sample_files(cid: str) -> dict:
    sample = load_sample(cid)
    return {slot: (d["filename"], (SAMPLES_DIR / cid / d["filename"]).read_bytes(), "application/pdf")
            for slot, d in sample["case"]["documents"].items()}


def form_data(cid: str, **override) -> dict:
    return {"submission": json.dumps({**load_sample(cid)["case"]["submission"], **override})}


def case_id_of(sample_id: str) -> int:
    return next(c for c in client.get("/api/cases").json() if c["sample_id"] == sample_id)["id"]


def reject(case_id: int) -> None:
    """A reviewer's rejection. H1 is approved, so first replay it into review with a misread, then reject."""
    with session_scope() as s:  # put the approved sample back into review, as a fresh finding would
        set_case_status(s, s.get(m.Case, case_id), "PENDING", "INTERNAL_REVIEW", ["ID-01"], actor="system",
                        reason="test: finding raised")
    r = client.post(f"/api/cases/{case_id}/review",
                    json={"action": "reject", "reviewer": "Priya (AP)", "reason": "identity not established"})
    assert r.status_code == 200, r.text


# ---------- PRIOR-01 as a rule ----------

def test_prior01_passes_on_a_first_application(ctx):
    ev = evaluate(CaseInput.model_validate(load_sample("H1")["case"]), ctx)
    assert next(r for r in ev.results if r.rule_id == "PRIOR-01").status == "pass"
    assert ev.decision.status == Status.APPROVED


def test_prior01_sends_clean_reapplication_to_review(ctx):
    case = CaseInput.model_validate(load_sample("H1")["case"])
    case.prior_rejections = [PriorRejection(case_id=1, reference="VO-0001", rejected_at="2026-10-05T10:00:00Z",
                                            failing_rules=["ID-01"])]
    d = evaluate(case, ctx).decision
    assert d.sub_state == SubState.INTERNAL_REVIEW and d.failing_rules == ["PRIOR-01"]
    assert d.vendor_actions == []  # the vendor isn't told about internal history


# ---------- duplicate check now knows about rejection ----------

def test_rejected_case_offers_reapply_not_resubmit(db):
    r = client.post("/api/cases", data=form_data("E4"), files=sample_files("E4"))
    assert r.status_code == 409
    match = r.json()["detail"]["matches"][0]
    assert match["display_status"] == "REJECTED"
    assert match["can_reapply"] is True and match["can_resubmit"] is False


def test_pending_or_approved_cases_do_not_offer_reapply(db):
    for cid in ("H1", "E3"):
        match = client.post("/api/cases", data=form_data(cid), files=sample_files(cid)).json()["detail"]["matches"][0]
        assert match["can_reapply"] is False


# ---------- reapply ----------

def test_reapply_debarred_entity_is_rejected_again_and_linked(db):
    e4 = case_id_of("E4")
    r = client.post(f"/api/cases/{e4}/reapply", data=form_data("E4"), files=sample_files("E4"))
    assert r.status_code == 201
    new = client.get(f"/api/cases/{r.json()['case_id']}").json()
    assert new["previous_case"]["id"] == e4 and new["run"]["trigger"] == "reapplication"
    # Still debarred: RISK-01 (reject) outranks PRIOR-01 (review)
    assert new["display_status"] == "REJECTED"
    assert {x["rule_id"] for x in new["reasons"]} == {"RISK-01", "PRIOR-01"}
    old = client.get(f"/api/cases/{e4}").json()
    assert old["display_status"] == "REJECTED" and [x["id"] for x in old["superseded_by"]] == [new["id"]]
    assert "case.reapplied" in [e["event"] for e in client.get(f"/api/cases/{e4}/audit").json()]


def test_reapply_after_reviewer_rejection_goes_to_review_never_auto_approve(db):
    h1 = case_id_of("H1")
    reject(h1)
    r = client.post(f"/api/cases/{h1}/reapply", data=form_data("H1"), files=sample_files("H1"))
    new = client.get(f"/api/cases/{r.json()['case_id']}").json()
    assert new["display_status"] == "INTERNAL_REVIEW"  # clean documents, but a person must sign off
    assert [x["rule_id"] for x in new["reasons"]] == ["PRIOR-01"]
    prior01 = next(rule for g in new["checks"] for rule in g["rules"] if rule["rule_id"] == "PRIOR-01")
    assert "VO-0001 was rejected" in prior01["results"][0]["detail"] and "Name mismatch" in prior01["results"][0]["detail"]


def test_one_open_case_rule_still_holds_after_reapplying(db):
    h1 = case_id_of("H1")
    reject(h1)
    new_id = client.post(f"/api/cases/{h1}/reapply", data=form_data("H1"), files=sample_files("H1")).json()["case_id"]
    # A new upload now matches the open reapplication; the old rejected case no longer offers reapply
    matches = {mt["id"]: mt for mt in client.post("/api/cases", data=form_data("H1"),
                                                  files=sample_files("H1")).json()["detail"]["matches"]}
    assert matches[new_id]["display_status"] == "INTERNAL_REVIEW" and matches[new_id]["can_resubmit"] is True
    assert matches[h1]["can_reapply"] is False
    # Reapplying again while the reapplication is open is refused
    assert client.post(f"/api/cases/{h1}/reapply", data=form_data("H1"), files=sample_files("H1")).status_code == 409


def test_only_the_latest_rejected_application_offers_reapply(db):
    """After VO-0005 -> reapplication (rejected again, still debarred), only the newest case can be reapplied from."""
    e4 = case_id_of("E4")
    new_id = client.post(f"/api/cases/{e4}/reapply", data=form_data("E4"), files=sample_files("E4")).json()["case_id"]
    assert client.get(f"/api/cases/{e4}").json()["can_reapply"] is False  # superseded
    assert client.get(f"/api/cases/{new_id}").json()["can_reapply"] is True  # latest in the chain
    r = client.post(f"/api/cases/{e4}/reapply", data=form_data("E4"), files=sample_files("E4"))
    assert r.status_code == 409 and "already followed by" in r.json()["detail"]
    matches = {mt["id"]: mt["can_reapply"] for mt in
               client.post("/api/cases", data=form_data("E4"), files=sample_files("E4")).json()["detail"]["matches"]}
    assert matches == {e4: False, new_id: True}


def test_reapply_only_from_rejected_cases(db):
    e3 = case_id_of("E3")  # pending
    assert client.post(f"/api/cases/{e3}/reapply", data=form_data("E3"), files=sample_files("E3")).status_code == 409
    assert client.post("/api/cases/999/reapply", data=form_data("E3"), files=sample_files("E3")).status_code == 404


def test_reapply_must_be_the_same_entity(db):
    e4 = case_id_of("E4")
    r = client.post(f"/api/cases/{e4}/reapply", data=form_data("E2"), files=sample_files("E2"))
    assert r.status_code == 422 and "new vendor" in r.json()["detail"]
    with session_scope() as s:
        assert s.scalar(select(func.count(m.Case.id))) == 6  # nothing created


def test_replay_of_a_rejected_case_is_a_rerun_not_a_reapplication(db):
    e4 = case_id_of("E4")
    run_id = client.post(f"/api/cases/{e4}/replay").json()["run_id"]
    run = client.get(f"/api/runs/{run_id}").json()
    assert run["case_id"] == e4 and run["trigger"] == "replay"
    # The case's own rejection is not "prior": replaying it doesn't add PRIOR-01
    assert [x["rule_id"] for x in run["decision"]["reasons"]] == ["RISK-01"]


# ---------- schema upgrade for existing databases ----------

def test_existing_database_gains_new_nullable_column(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)  # a cases table from before previous_case_id existed
    con.execute("CREATE TABLE cases (id INTEGER PRIMARY KEY, vendor_name VARCHAR(300), gstin VARCHAR(20), "
                "pan VARCHAR(10), status VARCHAR(20), sub_state VARCHAR(20), failing_rules JSON, source VARCHAR(20), "
                "sample_id VARCHAR(10), created_at DATETIME, updated_at DATETIME, decided_at DATETIME)")
    con.commit()
    con.close()
    init_db(f"sqlite:///{path}")
    cols = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(cases)")}
    assert "previous_case_id" in cols
    get_engine().dispose()
