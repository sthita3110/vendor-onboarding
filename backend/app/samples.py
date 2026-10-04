"""Demo sample packets: form JSON + the rendered PDFs, as the app would receive them."""

from __future__ import annotations

import json

from app.domain.models import Submission
from app.llm.extract import UploadedFile
from app.reference.data import SAMPLES_DIR


def sample_ids() -> list[str]:
    return [p.stem for p in sorted(SAMPLES_DIR.glob("*.json"))]


def load_sample(cid: str) -> dict:
    return json.loads((SAMPLES_DIR / f"{cid}.json").read_text())


def sample_submission(sample: dict) -> Submission:
    return Submission.model_validate(sample["case"]["submission"])


def sample_uploads(sample: dict) -> list[UploadedFile]:
    """The sample's PDFs, placed in the slots a vendor would have used."""
    return [
        UploadedFile(slot, doc["filename"], (SAMPLES_DIR / sample["id"] / doc["filename"]).read_bytes())
        for slot, doc in sample["case"]["documents"].items()
    ]
