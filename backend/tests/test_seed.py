"""Step 3d: seeded samples (no execution), Replay (real execution), new upload (real execution)."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.routes import get_pipeline_deps
from app.db import models as m
from app.db.engine import get_engine, init_db, session_scope
from app.db.storage import uploads_root
from app.main import app
from app.pipeline import seed as seed_module
from app.pipeline.runner import STAGES, PipelineDeps
from app.pipeline.seed import SEED_IDS, SeedMismatchError, seed_demo_cases
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
    init_db(f"sqlite:///{tmp_path / 'seed.db'}")
    r = CountingReader()
    app.dependency_overrides[get_pipeline_deps] = lambda: PipelineDeps(
        reader_factory=lambda: r, cache=None, ctx=ctx, background=False)
    # Any attempt to build a real OpenAI reader during seeding would fail loudly.
    monkeypatch.setattr("app.llm.client.OpenAIReader.__init__",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("OpenAI must not be called")))
    yield r
    app.dependency_overrides.clear()
    get_engine().dispose()


def case_by_sample(sample_id: str) -> dict:
    return next(c for c in client.get("/api/cases").json() if c["sample_id"] == sample_id)


# ---------- 1. seeded sample: pre-populated, not executed ----------

def test_seed_populates_empty_db_without_running_anything(reader):
    ids = seed_demo_cases()
    assert len(ids) == len(SEED_IDS) == 6
    assert reader.calls == 0  # no model calls
    rows = client.get("/api/cases").json()
    assert {r["sample_id"] for r in rows} == set(SEED_IDS)  # E3R deliberately not seeded
    assert all(r["source"] == "seed" and r["source_label"] == "Seeded sample" for r in rows)


@pytest.mark.parametrize("cid", SEED_IDS)
def test_seeded_case_matches_expected_and_has_full_history(cid, reader):
    seed_demo_cases()
    exp = load_sample(cid)["expected"]
    c = client.get(f"/api/cases/{case_by_sample(cid)['id']}").json()
    assert (c["status"], c["sub_state"]) == (exp["status"], exp["sub_state"])
    assert {r["rule_id"] for r in c["reasons"]} == set(exp["failing_rules"])
    assert [v["version"] for v in c["versions_detail"]] == [1]
    assert len(c["documents"]) == 3
    assert len(list((uploads_root() / str(c["id"])).iterdir())) == 3  # three real files in the store
    run = c["run"]
    assert run["trigger"] == "seed" and run["executed"] is False and run["status"] == "completed"
    assert [st["key"] for st in run["stages"]] == [k for k, _ in STAGES]
    assert all(st["status"] == "done" for st in run["stages"])
    read = next(st for st in run["stages"] if st["key"] == "read_documents")
    assert "Seeded sample" in read["summary"] and "Replay" in read["summary"]
    assert c["checks"] and all(x["meta"]["source"] == "seed" for x in c["extractions"].values())


def test_seeded_documents_are_the_real_pdfs(reader):
    seed_demo_cases()
    doc = client.get(f"/api/cases/{case_by_sample('E3')['id']}").json()["documents"]
    invoice = next(d for d in doc if d["slot"] == "bank_proof")
    assert client.get(invoice["url"]).content == (SAMPLES_DIR / "E3" / "INV-2026-0418.pdf").read_bytes()


def test_seeded_data_feeds_queue_and_metrics(reader):
    seed_demo_cases()
    assert {c["sample_id"] for c in client.get("/api/review-queue").json()} == {"E1", "E2", "E5"}
    mtr = client.get("/api/metrics").json()
    assert mtr["by_status"] == {"APPROVED": 1, "AWAITING_VENDOR": 1, "INTERNAL_REVIEW": 3, "REJECTED": 1,
                                "IN_PROGRESS": 0}
    assert mtr["seeded_cases"] == 6
    assert mtr["median_seconds_to_decision"] is None  # seeded runs have no real duration


def test_seed_audit_says_not_executed(reader):
    seed_demo_cases()
    events = client.get(f"/api/cases/{case_by_sample('H1')['id']}/audit").json()
    seeded = next(e for e in events if e["event"] == "seed.loaded")
    assert seeded["actor"] == "system (seed)" and "not executed" in seeded["data"]["note"]


def test_seed_is_noop_when_db_not_empty(reader):
    assert len(seed_demo_cases()) == 6
    assert seed_demo_cases() == []  # second startup: nothing duplicated or overwritten
    with session_scope() as s:
        assert s.scalar(select(func.count(m.Case.id))) == 6


def test_seed_skips_if_any_real_case_exists(reader):
    sample = load_sample("H1")
    client.post("/api/cases", data={"submission": json.dumps(sample["case"]["submission"])},
                files={slot: (d["filename"], (SAMPLES_DIR / "H1" / d["filename"]).read_bytes(), "application/pdf")
                       for slot, d in sample["case"]["documents"].items()})
    assert seed_demo_cases() == []


def test_seed_refuses_wrong_history(reader, monkeypatch):
    real = seed_module.load_sample

    def tampered(cid):
        s = real(cid)
        if cid == "E2":
            s["expected"]["status"] = "APPROVED"
        return s

    monkeypatch.setattr(seed_module, "load_sample", tampered)
    with pytest.raises(SeedMismatchError):
        seed_demo_cases()
    with session_scope() as s:  # verified before writing: nothing partially seeded
        assert s.scalar(select(func.count(m.Case.id))) == 0


# ---------- 2. replay: real execution on an existing (seeded) case ----------

def test_replay_seeded_case_executes_pipeline(reader):
    seed_demo_cases()
    case_id = case_by_sample("E2")["id"]
    r = client.post(f"/api/cases/{case_id}/replay")
    assert r.status_code == 201
    assert reader.calls == 3  # the model really read all three documents
    run = client.get(f"/api/runs/{r.json()['run_id']}").json()
    assert run["trigger"] == "replay" and run["executed"] is True and run["status"] == "completed"
    read = next(st for st in run["stages"] if st["key"] == "read_documents")
    assert read["summary"].startswith("Read 3 documents")
    c = client.get(f"/api/cases/{case_id}").json()
    assert c["display_status"] == "INTERNAL_REVIEW"  # same outcome as the seeded history
    assert [x["trigger"] for x in c["runs_detail"]] == ["seed", "replay"]
    assert c["run"]["id"] == r.json()["run_id"]  # case page shows the latest run
    assert "run.replayed" in [e["event"] for e in client.get(f"/api/cases/{case_id}/audit").json()]


def test_replay_blocked_while_run_in_progress(reader):
    seed_demo_cases()
    case_id = case_by_sample("H1")["id"]
    with session_scope() as s:
        s.get(m.Case, case_id).runs[-1].status = "running"
    assert client.post(f"/api/cases/{case_id}/replay").status_code == 409
    assert client.post("/api/cases/999/replay").status_code == 404


def test_seeded_e3_can_be_resubmitted_live_with_e3r(reader):
    seed_demo_cases()
    case_id = case_by_sample("E3")["id"]
    e3r = load_sample("E3R")
    files = {slot: (d["filename"], (SAMPLES_DIR / "E3R" / d["filename"]).read_bytes(), "application/pdf")
             for slot, d in e3r["case"]["documents"].items() if slot in ("gst_certificate", "bank_proof")}
    r = client.post(f"/api/cases/{case_id}/resubmit",
                    data={"submission": json.dumps(e3r["case"]["submission"])}, files=files)
    assert r.status_code == 201 and r.json()["version"] == 2
    c = client.get(f"/api/cases/{case_id}").json()
    assert c["display_status"] == "APPROVED" and [x["trigger"] for x in c["runs_detail"]] == ["seed", "resubmission"]


# ---------- 3. new upload: real execution, never seeded ----------

def test_new_upload_runs_pipeline_and_is_not_seeded(reader):
    """A genuinely new entity: real execution, labelled "Uploaded", seeded cases untouched.
    (Re-uploading a seeded sample is blocked as a duplicate — see test_duplicates.py.)"""
    seed_demo_cases()
    sample = load_sample("H1")
    first14 = "29AAACN7777Q1Z"
    new_entity = {**sample["case"]["submission"], "legal_name": "Nova Instruments Private Limited",
                  "pan": "AAACN7777Q", "gstin": first14 + gstin_check_char(first14)}
    files = {slot: (d["filename"], (SAMPLES_DIR / "H1" / d["filename"]).read_bytes(), "application/pdf")
             for slot, d in sample["case"]["documents"].items()}
    r = client.post("/api/cases", data={"submission": json.dumps(new_entity), "sample_id": "H1"}, files=files)
    assert r.status_code == 201 and reader.calls == 3
    c = client.get(f"/api/cases/{r.json()['case_id']}").json()
    assert c["source"] == "form" and c["source_label"] == "Uploaded · from sample H1"
    assert c["run"]["trigger"] == "submission" and c["run"]["executed"] is True
    assert len(client.get("/api/cases").json()) == 7  # a new case, seeded ones untouched


def test_reuploading_a_seeded_sample_is_blocked(reader):
    seed_demo_cases()
    sample = load_sample("H1")
    files = {slot: (d["filename"], (SAMPLES_DIR / "H1" / d["filename"]).read_bytes(), "application/pdf")
             for slot, d in sample["case"]["documents"].items()}
    r = client.post("/api/cases", data={"submission": json.dumps(sample["case"]["submission"])}, files=files)
    assert r.status_code == 409 and reader.calls == 0
    assert len(client.get("/api/cases").json()) == 6
