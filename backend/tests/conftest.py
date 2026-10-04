import copy
import json
import os

import pytest

os.environ.setdefault("MOCK_LATENCY_MS", "0")  # simulated provider delay is for the live UI, not tests

from app.domain.models import CaseInput
from app.reference.data import SAMPLES_DIR
from app.rules.evaluate import default_context

SAMPLE_IDS = ["H1", "E1", "E2", "E3", "E3R", "E4", "E5"]


def load_sample(cid: str) -> dict:
    return json.loads((SAMPLES_DIR / f"{cid}.json").read_text())


@pytest.fixture(scope="session")
def ctx():
    return default_context()


@pytest.fixture
def h1() -> dict:
    """Mutable copy of the clean case payload (submission + documents)."""
    return copy.deepcopy(load_sample("H1")["case"])


def as_case(payload: dict) -> CaseInput:
    return CaseInput.model_validate(payload)
