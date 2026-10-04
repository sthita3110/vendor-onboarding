import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app, get_reader
from app.reference.data import SAMPLES_DIR
from tests.conftest import load_sample
from tests.test_extract import FakeReader, raw_from_truth

client = TestClient(app)


def test_health():
    assert client.get("/api/health").json()["status"] == "ok"


def test_samples_hide_expected_outcome():
    ids = [s["id"] for s in client.get("/api/samples").json()]
    assert {"H1", "E1", "E2", "E3", "E4"} <= set(ids)
    assert "expected" not in client.get("/api/samples/H1").json()


def test_evaluate_round_trip():
    body = client.post("/api/evaluate", json=load_sample("E3")["case"]).json()
    assert body["decision"]["status"] == "PENDING"
    assert body["decision"]["sub_state"] == "AWAITING_VENDOR"


def test_evaluate_sample_endpoint():
    assert client.post("/api/samples/E4/evaluate").json()["decision"]["status"] == "REJECTED"


def test_unknown_sample_404():
    assert client.get("/api/samples/NOPE").status_code == 404


# ---------- step 2d: upload endpoint (fake reader, no network) ----------

@pytest.fixture
def fake_reader():
    sample = load_sample("H1")
    reader = FakeReader({d["filename"]: raw_from_truth(d) for d in sample["case"]["documents"].values()})
    app.dependency_overrides[get_reader] = lambda: reader
    yield reader
    app.dependency_overrides.clear()


def h1_upload(skip: str | None = None, replace: dict | None = None):
    sample = load_sample("H1")
    files = {}
    for slot, doc in sample["case"]["documents"].items():
        if slot == skip:
            continue
        data = (replace or {}).get(slot) or (SAMPLES_DIR / "H1" / doc["filename"]).read_bytes()
        files[slot] = (doc["filename"], data, "application/pdf")
    return {"submission": json.dumps(sample["case"]["submission"])}, files


def test_upload_happy_path(fake_reader, monkeypatch):
    monkeypatch.setenv("EXTRACTION_CACHE", "off")
    data, files = h1_upload()
    body = client.post("/api/evaluate-upload", data=data, files=files).json()
    assert body["decision"]["status"] == "APPROVED"
    assert body["extractions"]["pan_card"]["fields"]["pan"]["grounded"] == "image"


def test_upload_missing_file_is_comp02(fake_reader, monkeypatch):
    monkeypatch.setenv("EXTRACTION_CACHE", "off")
    data, files = h1_upload(skip="pan_card")
    assert client.post("/api/evaluate-upload", data=data, files=files).json()["decision"]["failing_rules"] == ["COMP-02"]


def test_upload_unsupported_file_is_file01(fake_reader, monkeypatch):
    monkeypatch.setenv("EXTRACTION_CACHE", "off")
    data, files = h1_upload(replace={"bank_proof": b"PK\x03\x04 docx"})
    d = client.post("/api/evaluate-upload", data=data, files=files).json()["decision"]
    assert d["sub_state"] == "AWAITING_VENDOR" and d["failing_rules"] == ["FILE-01"]


def test_upload_bad_submission_json(fake_reader):
    _, files = h1_upload()
    assert client.post("/api/evaluate-upload", data={"submission": "{not json"}, files=files).status_code == 422


def test_upload_requires_passcode_when_configured(fake_reader, monkeypatch):
    monkeypatch.setenv("APP_PASSCODE", "s3cret")
    monkeypatch.setenv("EXTRACTION_CACHE", "off")
    data, files = h1_upload()
    assert client.post("/api/evaluate-upload", data=data, files=files).status_code == 401
    ok = client.post("/api/evaluate-upload", data=data, files=files, headers={"X-App-Passcode": "s3cret"})
    assert ok.status_code == 200


def test_upload_without_api_key_is_503(monkeypatch):
    no_key = Settings(openai_api_key=None, openai_model="m", openai_timeout_s=1, openai_reasoning_effort=None)
    monkeypatch.setattr("app.llm.client.get_settings", lambda: no_key)
    data, files = h1_upload()
    assert client.post("/api/evaluate-upload", data=data, files=files).status_code == 503
