"""Step 3c: HTTP API — submit, poll, case detail, resubmission, queue, audit, metrics, passcode."""

import json

import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_pipeline_deps
from app.db.engine import get_engine, init_db
from app.main import app
from app.pipeline.runner import PipelineDeps
from app.reference.data import SAMPLES_DIR
from tests.conftest import TruthReader, load_sample

client = TestClient(app)


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch, ctx):
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("APP_PASSCODE", raising=False)
    init_db(f"sqlite:///{tmp_path / 'api.db'}")
    reader = TruthReader()
    app.dependency_overrides[get_pipeline_deps] = lambda: PipelineDeps(
        reader_factory=lambda: reader, cache=None, ctx=ctx, background=False)
    yield
    app.dependency_overrides.clear()
    get_engine().dispose()


def files_for(cid: str, only: set[str] | None = None, replace: dict | None = None) -> dict:
    out = {}
    for slot, doc in load_sample(cid)["case"]["documents"].items():
        if only and slot not in only:
            continue
        data = (replace or {}).get(slot) or (SAMPLES_DIR / cid / doc["filename"]).read_bytes()
        out[slot] = (doc["filename"], data, "application/pdf")
    return out


def submit(cid: str, **kw) -> dict:
    form = {"submission": json.dumps(load_sample(cid)["case"]["submission"]), "sample_id": cid}
    r = client.post("/api/cases", data=form, files=files_for(cid, **kw))
    assert r.status_code == 201, r.text
    return r.json()


# ---------- access ----------

def test_health_is_open_but_api_needs_passcode(monkeypatch):
    monkeypatch.setenv("APP_PASSCODE", "s3cret")
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/cases").status_code == 401
    assert client.get("/api/cases", headers={"X-App-Passcode": "wrong"}).status_code == 401
    assert client.get("/api/cases", headers={"X-App-Passcode": "s3cret"}).status_code == 200


# ---------- samples ----------

def test_sample_listing_and_detail_hide_expected_outcome():
    assert {"H1", "E1", "E2", "E3", "E3R", "E4", "E5"} <= {s["id"] for s in client.get("/api/samples").json()}
    body = client.get("/api/samples/E3").json()
    assert "expected" not in body and "documents" not in json.dumps(body["submission"])
    assert {f["slot"] for f in body["files"]} == {"gst_certificate", "pan_card", "bank_proof"}


def test_sample_file_download_and_whitelist():
    f = client.get("/api/samples/E3").json()["files"][0]
    r = client.get(f["url"])
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert client.get("/api/samples/E3/files/..%2F..%2FE3.json").status_code == 404
    assert client.get("/api/samples/NOPE/files/x.pdf").status_code == 404


# ---------- submit + live run ----------

def test_submit_and_poll_run():
    created = submit("H1")
    assert created["reference"] == f"VO-{created['case_id']:04d}"
    run = client.get(f"/api/runs/{created['run_id']}").json()
    assert run["status"] == "completed" and not run["active"]
    assert [st["key"] for st in run["stages"]][:3] == ["intake", "completeness", "read_documents"]
    assert all(st["status"] == "done" and st["duration_ms"] is not None for st in run["stages"])
    assert run["decision"]["display_status"] == "APPROVED"


def test_case_detail_groups_checks_with_business_labels():
    case_id = submit("E2")["case_id"]
    c = client.get(f"/api/cases/{case_id}").json()
    assert c["display_status"] == "INTERNAL_REVIEW" and c["reasons"] == [{"rule_id": "BANK-03", "issue": "Bank holder mismatch"}]
    groups = {g["group"]: g for g in c["checks"]}
    assert list(groups) == ["Documents", "Tax", "Identity", "Bank", "Risk"]
    bank03 = next(r for r in groups["Bank"]["rules"] if r["rule_id"] == "BANK-03")
    assert bank03["status"] == "fail" and bank03["name"] == "Bank account belongs to the company"
    assert bank03["results"][0]["evidence"]["adapter_response"]["simulated"] is True
    assert c["extractions"]["pan_card"]["classified_type"] == "pan_card"
    assert c["can_resubmit"] is True


def test_document_download_returns_original_and_is_scoped_to_case():
    a, b = submit("H1")["case_id"], submit("E2")["case_id"]
    doc = client.get(f"/api/cases/{a}").json()["documents"][0]
    r = client.get(doc["url"])
    assert r.status_code == 200 and r.content == files_for("H1")[doc["slot"]][1]
    assert client.get(f"/api/cases/{b}/documents/{doc['id']}").status_code == 404  # other case's document


def test_unsupported_upload_becomes_vendor_action():
    case_id = submit("H1", replace={"bank_proof": b"PK\x03\x04 a docx"})["case_id"]
    c = client.get(f"/api/cases/{case_id}").json()
    assert c["display_status"] == "AWAITING_VENDOR" and c["reasons"][0]["rule_id"] == "FILE-01"


def test_bad_submission_json_is_422():
    r = client.post("/api/cases", data={"submission": "{nope"}, files=files_for("H1"))
    assert r.status_code == 422


# ---------- lists, queue, filters ----------

def test_dashboard_filters_and_review_queue():
    h1, e2, e3 = submit("H1")["case_id"], submit("E2")["case_id"], submit("E3")["case_id"]
    assert [c["id"] for c in client.get("/api/cases").json()] == [e3, e2, h1]  # newest first
    assert [c["id"] for c in client.get("/api/cases?status=INTERNAL_REVIEW").json()] == [e2]
    assert [c["id"] for c in client.get("/api/cases?rule=TAX-04").json()] == [e3]
    assert [c["id"] for c in client.get("/api/cases?q=kaveri").json()] == [e3]
    assert [c["id"] for c in client.get("/api/review-queue").json()] == [e2]
    assert client.get("/api/cases?status=AWAITING_VENDOR").json()[0]["vendor_actions"] == 2


# ---------- resubmission and history ----------

def test_resubmission_creates_version_and_keeps_history():
    case_id = submit("E3")["case_id"]
    form = {"submission": json.dumps(load_sample("E3R")["case"]["submission"])}
    r = client.post(f"/api/cases/{case_id}/resubmit", data=form,
                    files=files_for("E3R", only={"gst_certificate", "bank_proof"}))
    assert r.status_code == 201 and r.json()["version"] == 2
    c = client.get(f"/api/cases/{case_id}").json()
    assert c["display_status"] == "APPROVED" and c["selected_version"] == 2
    assert [v["run"]["decision"]["display_status"] for v in c["versions_detail"]] == ["AWAITING_VENDOR", "APPROVED"]
    assert {d["slot"]: d["carried_over"] for d in c["documents"]}["pan_card"] is True
    v1 = client.get(f"/api/cases/{case_id}?version=1").json()
    assert v1["run"]["decision"]["display_status"] == "AWAITING_VENDOR"
    # approved cases can't be resubmitted
    assert client.post(f"/api/cases/{case_id}/resubmit", data=form, files=files_for("E3R")).status_code == 409


def test_audit_trail_is_ordered():
    case_id = submit("E4")["case_id"]
    events = [e["event"] for e in client.get(f"/api/cases/{case_id}/audit").json()]
    assert events[:3] == ["case.created", "submission.received", "run.created"]
    assert events[-3:] == ["decision.made", "status.changed", "run.completed"]


# ---------- metrics ----------

def test_metrics():
    for cid in ("H1", "E2", "E3", "E4"):
        submit(cid)
    mtr = client.get("/api/metrics").json()
    assert mtr["total"] == 4
    assert mtr["by_status"] == {"APPROVED": 1, "AWAITING_VENDOR": 1, "INTERNAL_REVIEW": 1, "REJECTED": 1, "IN_PROGRESS": 0}
    assert mtr["straight_through_rate"] == 0.25
    assert {r["rule_id"] for r in mtr["top_reasons"]} == {"BANK-03", "DOC-01", "TAX-04", "RISK-01"}


# ---------- 404s and dev tool ----------

def test_not_found():
    assert client.get("/api/cases/999").status_code == 404
    assert client.get("/api/runs/999").status_code == 404
    case_id = submit("H1")["case_id"]
    assert client.get(f"/api/cases/{case_id}?version=7").status_code == 404


def test_rules_only_evaluate_still_available():
    body = client.post("/api/evaluate", json=load_sample("E4")["case"]).json()
    assert body["decision"]["status"] == "REJECTED"


# ---------- frontend serving ----------

def test_spa_routes_serve_index_and_api_404_stays_json():
    from app.config import get_settings
    if not (get_settings().frontend_dist / "index.html").is_file():
        pytest.skip("frontend not built")
    for path in ("/", "/cases/3", "/runs/7", "/review"):
        r = client.get(path)
        assert r.status_code == 200 and "<div id=\"root\">" in r.text
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")
    assert client.get("/../backend/.env").status_code in (200, 404) and "OPENAI" not in client.get("/../backend/.env").text


def test_states_for_address_dropdown():
    states = client.get("/api/reference/states").json()
    assert "Karnataka" in states and "Tamil Nadu" in states and states == sorted(states)
    assert states.count("Andhra Pradesh") == 1  # two GST codes, one state
