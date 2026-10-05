"""Duplicate-case check at submission: one onboarding case per legal entity (PAN or GSTIN)."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.routes import get_pipeline_deps
from app.db import models as m
from app.db.engine import get_engine, init_db, session_scope
from app.db.storage import uploads_root
from app.main import app
from app.pipeline.runner import PipelineDeps
from app.pipeline.seed import seed_demo_cases
from app.reference.data import SAMPLES_DIR
from app.rules.validators import gstin_check_char
from tests.conftest import TruthReader, load_sample

client = TestClient(app)


class CountingReader(TruthReader):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def read(self, *args):
        self.calls += 1
        return super().read(*args)


@pytest.fixture
def reader(tmp_path, monkeypatch, ctx):
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("APP_PASSCODE", raising=False)
    init_db(f"sqlite:///{tmp_path / 'dup.db'}")
    r = CountingReader()
    app.dependency_overrides[get_pipeline_deps] = lambda: PipelineDeps(
        reader_factory=lambda: r, cache=None, ctx=ctx, background=False)
    yield r
    app.dependency_overrides.clear()
    get_engine().dispose()


def post(cid: str, submission: dict | None = None):
    sample = load_sample(cid)
    files = {slot: (d["filename"], (SAMPLES_DIR / cid / d["filename"]).read_bytes(), "application/pdf")
             for slot, d in sample["case"]["documents"].items()}
    return client.post("/api/cases", files=files,
                       data={"submission": json.dumps(submission or sample["case"]["submission"]), "sample_id": cid})


def count(model) -> int:
    with session_scope() as s:
        return s.scalar(select(func.count(model.id)))


def test_same_sample_twice_is_blocked_and_creates_nothing(reader):
    first = post("H1")
    assert first.status_code == 201 and reader.calls == 3
    files_before = sorted(p.name for p in uploads_root().rglob("*.pdf"))
    second = post("H1")
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["code"] == "duplicate_case"
    assert [mt["id"] for mt in detail["matches"]] == [first.json()["case_id"]]
    assert reader.calls == 3  # no model call for the blocked attempt
    assert count(m.Case) == 1 and count(m.Run) == 1  # no case, no run
    assert sorted(p.name for p in uploads_root().rglob("*.pdf")) == files_before  # no files stored


def test_blocked_attempt_is_audited_on_existing_case(reader):
    case_id = post("H1").json()["case_id"]
    post("H1")
    events = [e["event"] for e in client.get(f"/api/cases/{case_id}/audit").json()]
    assert events.count("duplicate_submission.blocked") == 1


def test_match_offers_the_right_actions(reader):
    seed_demo_cases()
    approved = post("H1").json()["detail"]["matches"][0]  # seeded H1 is approved: final
    assert approved["display_status"] == "APPROVED"
    assert approved["can_replay"] is True and approved["can_resubmit"] is False
    pending = post("E3").json()["detail"]["matches"][0]  # seeded E3 is awaiting vendor
    assert pending["can_resubmit"] is True and pending["can_replay"] is True
    assert pending["selected_version"] == 1


def test_resubmission_sample_is_recognised_as_same_entity(reader):
    """E3R is E3's correction: same PAN, different (Tamil Nadu) GSTIN -> must go to E3's case."""
    seed_demo_cases()
    r = post("E3R")
    assert r.status_code == 409 and r.json()["detail"]["matches"][0]["sample_id"] == "E3"


def test_match_by_gstin_embedded_pan(reader):
    """Same company, PAN left blank, GSTIN from another state: its embedded PAN still identifies the entity."""
    post("H1")
    sub = load_sample("H1")["case"]["submission"]
    first14 = "27" + sub["pan"] + "1Z"
    other_state = {**sub, "pan": None, "gstin": first14 + gstin_check_char(first14)}
    assert post("H1", other_state).status_code == 409


def test_match_by_gstin_alone(reader):
    post("H1")
    sub = load_sample("H1")["case"]["submission"]
    assert post("H1", {**sub, "pan": "ZZZPZ9999Z"}).status_code == 409


def test_different_entity_creates_a_new_case(reader):
    post("H1")
    assert post("E2").status_code == 201
    assert count(m.Case) == 2


def test_no_identifiers_cannot_match(reader):
    """Without PAN or GSTIN there is nothing to match on; the case is created and COMP-01 asks for them."""
    sub = {**load_sample("H1")["case"]["submission"], "pan": None, "gstin": None}
    r = post("H1", sub)
    assert r.status_code == 201
    case = client.get(f"/api/cases/{r.json()['case_id']}").json()
    assert {x["rule_id"] for x in case["reasons"]} == {"COMP-01"}


def test_replay_and_resubmit_stay_on_the_existing_case(reader):
    """The supported paths: reprocessing = new run, correcting = new version; never a new case."""
    seed_demo_cases()
    e3 = next(c for c in client.get("/api/cases").json() if c["sample_id"] == "E3")["id"]
    client.post(f"/api/cases/{e3}/replay")
    e3r = load_sample("E3R")
    files = {slot: (d["filename"], (SAMPLES_DIR / "E3R" / d["filename"]).read_bytes(), "application/pdf")
             for slot, d in e3r["case"]["documents"].items() if slot != "pan_card"}
    client.post(f"/api/cases/{e3}/resubmit", data={"submission": json.dumps(e3r["case"]["submission"])}, files=files)
    c = client.get(f"/api/cases/{e3}").json()
    assert [r["trigger"] for r in c["runs_detail"]] == ["seed", "replay", "resubmission"]
    assert [v["version"] for v in c["versions_detail"]] == [1, 2]
    assert count(m.Case) == 6  # still only the seeded cases
