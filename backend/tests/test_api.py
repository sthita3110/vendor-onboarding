from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import load_sample

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
