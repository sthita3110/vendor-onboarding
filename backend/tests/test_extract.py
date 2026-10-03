"""Extraction layer (step 2b) with a fake reader — no network, no cost."""

import time

import httpx
import pytest
from openai import BadRequestError

from app.config import Settings
from app.domain.models import CaseInput, Status, SubState, Submission
from app.llm.client import OpenAIReader, ReadResult, _content_part
from app.llm.extract import UploadedFile, read_document, read_documents, to_document
from app.llm.schema import ALL_FIELDS, EXTRACTION_SCHEMA
from app.reference.data import SAMPLES_DIR
from app.rules.evaluate import evaluate
from tests.conftest import SAMPLE_IDS, load_sample

VALID_PDF = (SAMPLES_DIR / "H1" / "gst_certificate.pdf").read_bytes()


def raw_from_truth(doc: dict) -> dict:
    """What a perfect model would return for a ground-truth document."""
    fields = {name: {"value": None, "quote": None, "page": None} for name in ALL_FIELDS}
    for name, f in doc["fields"].items():
        fields[name] = {"value": f["value"], "quote": f["quote"], "page": f["page"]}
    return {"doc_type": doc["classified_type"], "readable": doc.get("readable", True), "fields": fields}


class FakeReader:
    model = "fake-model"

    def __init__(self, by_filename: dict[str, dict] | None = None, fail: Exception | None = None, delay: float = 0):
        self.by_filename, self.fail, self.delay = by_filename or {}, fail, delay

    def read(self, data: bytes, filename: str, mime: str) -> ReadResult:
        time.sleep(self.delay)
        if self.fail:
            raise self.fail
        return ReadResult(data=self.by_filename[filename], model=self.model, latency_ms=1)


def upload(slot="bank_proof", filename="f.pdf", cid: str | None = None) -> UploadedFile:
    """A real PDF: the sample file when `cid` is given, otherwise any valid PDF."""
    data = (SAMPLES_DIR / cid / filename).read_bytes() if cid else VALID_PDF
    return UploadedFile(slot, filename, data, "application/pdf")


# ---------- schema ----------

def _walk(schema):
    if schema.get("type") == "object":
        yield schema
        for sub in schema["properties"].values():
            yield from _walk(sub)


def test_schema_meets_strict_mode_rules():
    for obj in _walk(EXTRACTION_SCHEMA):
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])


# ---------- mapping ----------

def test_only_fields_of_identified_type_are_kept():
    """E3's invoice prints bank details; once typed as invoice, bank fields must not leak through."""
    raw = raw_from_truth(load_sample("E3")["case"]["documents"]["bank_proof"])
    raw["fields"]["account_number"] = {"value": "20031045678912", "quote": "A/c No. 20031045678912", "page": 1}
    doc = to_document("bank_proof", "INV.pdf", raw)
    assert doc.classified_type == "invoice"
    assert "account_number" not in doc.fields and doc.value("invoice_number") == "INV-2026-0418"


def test_blank_values_are_dropped():
    raw = raw_from_truth(load_sample("H1")["case"]["documents"]["gst_certificate"])
    raw["fields"]["trade_name"]["value"] = "   "
    assert "trade_name" not in to_document("gst_certificate", "g.pdf", raw).fields


def test_unreadable_flag_is_preserved():
    raw = raw_from_truth(load_sample("H1")["case"]["documents"]["bank_proof"])
    raw["readable"] = False
    assert to_document("bank_proof", "c.pdf", raw).readable is False


# ---------- failure handling ----------

def test_reader_failure_becomes_extraction_error():
    ex = read_document(FakeReader(fail=TimeoutError("timed out")), upload())
    assert ex.document.extraction_error and ex.document.classified_type is None
    assert "TimeoutError" in ex.meta["error"]


def test_malformed_output_becomes_extraction_error():
    ex = read_document(FakeReader({"f.pdf": {"unexpected": True}}), upload())
    assert ex.document.extraction_error.startswith("Unexpected extraction shape")


def test_extraction_failure_fails_closed_end_to_end(ctx):
    sample = load_sample("H1")
    docs = sample["case"]["documents"]
    reader = FakeReader({d["filename"]: raw_from_truth(d) for d in docs.values()})
    uploads = [upload(slot, d["filename"], "H1") for slot, d in docs.items()]
    extracted = {slot: ex.document for slot, ex in read_documents(reader, uploads).items()}
    extracted["gst_certificate"] = read_document(FakeReader(fail=ConnectionError("down")),
                                                 upload("gst_certificate", "gst_certificate.pdf")).document
    case = CaseInput(submission=Submission.model_validate(sample["case"]["submission"]), documents=extracted)
    d = evaluate(case, ctx).decision
    assert d.status == Status.PENDING and d.sub_state == SubState.INTERNAL_REVIEW and d.failing_rules == ["SYS-01"]


# ---------- parallelism and compatibility with the rules ----------

def test_documents_are_read_in_parallel():
    raw = raw_from_truth(load_sample("H1")["case"]["documents"]["pan_card"])
    reader = FakeReader({"a.pdf": raw, "b.pdf": raw, "c.pdf": raw}, delay=0.3)
    start = time.monotonic()
    out = read_documents(reader, [upload("gst_certificate", "a.pdf"), upload("pan_card", "b.pdf"),
                                  upload("bank_proof", "c.pdf")])
    assert time.monotonic() - start < 0.8  # sequential would be >= 0.9s
    assert set(out) == {"gst_certificate", "pan_card", "bank_proof"}


@pytest.mark.parametrize("cid", SAMPLE_IDS)
def test_perfect_extraction_reproduces_golden_outcome(cid, ctx):
    """Perfect model output + the real PDFs (so grounding runs) reproduces every golden outcome."""
    sample = load_sample(cid)
    docs = sample["case"]["documents"]
    reader = FakeReader({d["filename"]: raw_from_truth(d) for d in docs.values()})
    extracted = read_documents(reader, [upload(slot, d["filename"], cid) for slot, d in docs.items()])
    case = CaseInput(submission=Submission.model_validate(sample["case"]["submission"]),
                     documents={slot: ex.document for slot, ex in extracted.items()})
    d = evaluate(case, ctx).decision
    assert d.status.value == sample["expected"]["status"]
    assert set(d.failing_rules) == set(sample["expected"]["failing_rules"])


# ---------- client request building ----------

def test_content_parts():
    assert _content_part(b"x", "a.pdf", "application/pdf")["detail"] == "high"
    assert _content_part(b"x", "a.png", "image/png")["type"] == "input_image"
    with pytest.raises(ValueError):
        _content_part(b"x", "a.docx", "application/msword")


class _FakeResponses:
    def __init__(self, reject_temperature: bool):
        self.calls, self.reject = [], reject_temperature

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.reject and "temperature" in kwargs:
            req = httpx.Request("POST", "https://api.openai.com/v1/responses")
            raise BadRequestError("Unsupported parameter: 'temperature'", response=httpx.Response(400, request=req),
                                  body=None)
        raw = raw_from_truth(load_sample("H1")["case"]["documents"]["pan_card"])
        return type("R", (), {"output_text": __import__("json").dumps(raw), "usage": None})()


class _FakeOpenAI:
    def __init__(self, reject_temperature=False):
        self.responses = _FakeResponses(reject_temperature)


SETTINGS = Settings(openai_api_key="test", openai_model="m", openai_timeout_s=5, openai_reasoning_effort=None)


def test_request_uses_strict_schema_and_temperature_zero():
    fake = _FakeOpenAI()
    OpenAIReader(SETTINGS, client=fake).read(b"%PDF", "p.pdf", "application/pdf")
    call = fake.responses.calls[0]
    assert call["text"]["format"]["strict"] is True and call["temperature"] == 0
    assert "form" not in str(call["input"]).lower()  # blind: no submission data is sent


def test_temperature_dropped_for_models_that_reject_it():
    fake = _FakeOpenAI(reject_temperature=True)
    reader = OpenAIReader(SETTINGS, client=fake)
    reader.read(b"%PDF", "p.pdf", "application/pdf")
    reader.read(b"%PDF", "p.pdf", "application/pdf")
    assert [("temperature" in c) for c in fake.responses.calls] == [True, False, False]
