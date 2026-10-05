"""Demo reset: wipe everything and re-seed, so rehearsals start from a known state."""

import json

import pytest
from fastapi.testclient import TestClient

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


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch, ctx):
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("APP_PASSCODE", raising=False)
    monkeypatch.delenv("DEMO_RESET", raising=False)
    init_db(f"sqlite:///{tmp_path / 'reset.db'}")
    reader = TruthReader()
    app.dependency_overrides[get_pipeline_deps] = lambda: PipelineDeps(
        reader_factory=lambda: reader, cache=None, ctx=ctx, background=False)
    seed_demo_cases()
    yield
    app.dependency_overrides.clear()
    get_engine().dispose()


def cid(sample_id: str) -> int:
    return next(c for c in client.get("/api/cases").json() if c["sample_id"] == sample_id)["id"]


def make_history():
    """A human approval (Replay now blocked), a replay, and a genuinely new vendor."""
    client.post(f"/api/cases/{cid('E2')}/review", json={"action": "approve", "reviewer": "Priya", "reason": "ok"})
    client.post(f"/api/cases/{cid('H1')}/replay")
    sample = load_sample("H1")
    first14 = "29AAACN7777Q1Z"
    sub = {**sample["case"]["submission"], "legal_name": "Nova Instruments Private Limited",
           "pan": "AAACN7777Q", "gstin": first14 + gstin_check_char(first14)}
    files = {slot: (d["filename"], (SAMPLES_DIR / "H1" / d["filename"]).read_bytes(), "application/pdf")
             for slot, d in sample["case"]["documents"].items()}
    assert client.post("/api/cases", data={"submission": json.dumps(sub)}, files=files).status_code == 201


def test_reset_restores_the_seeded_state():
    make_history()
    assert len(client.get("/api/cases").json()) == 7
    assert client.get(f"/api/cases/{cid('E2')}").json()["can_replay"] is False
    r = client.post("/api/admin/reset-demo")
    assert r.status_code == 200 and r.json() == {"reset": True, "seeded_cases": 6}
    cases = client.get("/api/cases").json()
    assert sorted(c["reference"] for c in cases) == [f"VO-000{i}" for i in range(1, 7)]  # numbering restarts
    assert all(c["source"] == "seed" for c in cases)
    e2 = client.get(f"/api/cases/{cid('E2')}").json()
    assert e2["display_status"] == "INTERNAL_REVIEW" and e2["can_review"] and e2["can_replay"]  # usable again
    assert len(client.get(f"/api/cases/{cid('H1')}").json()["runs_detail"]) == 1  # replay history gone


def test_reset_clears_reviews_audit_and_uploads():
    make_history()
    client.post("/api/admin/reset-demo")
    with session_scope() as s:
        assert s.query(m.ReviewAction).count() == 0
        assert {e.event for e in s.query(m.AuditEvent)} == {
            "case.created", "submission.received", "run.created", "decision.made", "status.changed", "message.sent",
            "seed.loaded"}
    assert len([p for p in uploads_root().rglob("*") if p.is_file()]) == 18  # only the seeded PDFs remain (6 cases x 3)


def test_reset_refused_while_a_run_is_in_progress():
    with session_scope() as s:
        s.query(m.Run).first().status = "running"
    r = client.post("/api/admin/reset-demo")
    assert r.status_code == 409 and len(client.get("/api/cases").json()) == 6


def test_reset_can_be_disabled(monkeypatch):
    monkeypatch.setenv("DEMO_RESET", "off")
    assert client.post("/api/admin/reset-demo").status_code == 403


def test_reset_needs_the_passcode_when_set(monkeypatch):
    monkeypatch.setenv("APP_PASSCODE", "s3cret")
    assert client.post("/api/admin/reset-demo").status_code == 401
    assert client.post("/api/admin/reset-demo", headers={"X-App-Passcode": "s3cret"}).status_code == 200
