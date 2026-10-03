"""Sample PDFs (step 2a): present, consistent with ground truth, scans have no text, and reproducible."""

import io
import re

import pytest
from pypdf import PdfReader

from app.reference.data import SAMPLES_DIR
from app.rules.checks import KEY_FIELDS
from scripts.render_documents import render_sample
from tests.conftest import SAMPLE_IDS, load_sample


def pdf_text(data: bytes) -> str:
    return "".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)


def squash(text: str) -> str:
    return re.sub(r"\s+", "", text).upper()


def documents(cid: str):
    sample = load_sample(cid)
    for slot, doc in sample["case"]["documents"].items():
        yield sample, slot, doc, (SAMPLES_DIR / cid / doc["filename"])


ALL_DOCS = [(cid, slot) for cid in SAMPLE_IDS for _, slot, _, _ in documents(cid)]


@pytest.mark.parametrize("cid,slot", ALL_DOCS)
def test_document_exists(cid, slot):
    path = next(p for _, s, _, p in documents(cid) if s == slot)
    assert path.is_file() and path.read_bytes().startswith(b"%PDF")


@pytest.mark.parametrize("cid,slot", ALL_DOCS)
def test_text_layer_matches_ground_truth(cid, slot):
    """Every key value in the ground truth is printed on the document (the bar the AI will be held to)."""
    sample, _, doc, path = next(d for d in documents(cid) if d[1] == slot)
    if slot in sample["scanned_slots"]:
        pytest.skip("scanned document has no text layer")
    text = squash(pdf_text(path.read_bytes()))
    kind = doc["classified_type"]
    names = [n for n, _ in KEY_FIELDS[kind]] if kind in KEY_FIELDS else list(doc["fields"])
    for name in names:
        assert squash(doc["fields"][name]["value"]) in text, f"{name} not printed on {path.name}"


def test_scan_has_no_text_layer():
    sample = load_sample("H1")
    assert sample["scanned_slots"] == ["pan_card"]
    path = SAMPLES_DIR / "H1" / sample["case"]["documents"]["pan_card"]["filename"]
    assert pdf_text(path.read_bytes()).strip() == ""


def test_invoice_contains_bank_details_but_is_an_invoice():
    """The E3 trap: an invoice prints account number and IFSC, yet is not proof of bank ownership."""
    sample = load_sample("E3")
    doc = sample["case"]["documents"]["bank_proof"]
    text = squash(pdf_text((SAMPLES_DIR / "E3" / doc["filename"]).read_bytes()))
    assert doc["classified_type"] == "invoice"
    assert squash(sample["case"]["submission"]["bank"]["account_number"]) in text


@pytest.mark.parametrize("cid", SAMPLE_IDS)
def test_rendering_is_deterministic_and_committed_files_are_current(cid, tmp_path):
    """Same input -> same bytes. Keeps extraction-cache keys stable and catches stale committed PDFs."""
    sample = load_sample(cid)
    first = {p.name: p.read_bytes() for p in render_sample(sample, tmp_path / "a")}
    second = {p.name: p.read_bytes() for p in render_sample(sample, tmp_path / "b")}
    assert first == second
    committed = {name: (SAMPLES_DIR / cid / name).read_bytes() for name in first}
    assert first == committed, "committed PDFs are stale; run: python -m scripts.render_documents"
