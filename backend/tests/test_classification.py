"""Is "wrong document" a bad document or an AI mistake?

Layer 1 — the model quotes the text that shows the document type; on a text PDF the quote must be on the page.
           Grounded -> genuinely the wrong document -> vendor (DOC-01). Not grounded -> unreliable -> person (DOC-03).
Layer 2 — the vendor re-sends the identical file we flagged as the wrong document -> person, never asked again.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_pipeline_deps
from app.db.engine import get_engine, init_db
from app.domain.models import CaseInput, ExtractedField, Status, SubState
from app.main import app
from app.pipeline.runner import PipelineDeps
from app.pipeline.seed import seed_demo_cases
from app.reference.data import SAMPLES_DIR
from app.rules.evaluate import evaluate
from tests.conftest import TruthReader, load_sample

client = TestClient(app)


def h1_with_bank_proof_typed_as_invoice(evidence: ExtractedField | None) -> CaseInput:
    """H1's valid cancelled cheque, but the model says 'invoice' (the scenario in question)."""
    case = CaseInput.model_validate(load_sample("H1")["case"])
    doc = case.documents["bank_proof"]
    doc.classified_type = "invoice"
    doc.type_evidence = evidence
    return case


# ---------- layer 1 (rules) ----------

def test_ai_mistake_with_ungrounded_evidence_goes_to_a_person_not_the_vendor(ctx):
    ev = ExtractedField(value="TAX INVOICE", quote="TAX INVOICE", page=1, grounded="unverified")  # not on the cheque
    d = evaluate(h1_with_bank_proof_typed_as_invoice(ev), ctx).decision
    assert d.status == Status.PENDING and d.sub_state == SubState.INTERNAL_REVIEW
    assert d.failing_rules == ["DOC-03"]
    assert d.vendor_actions == []  # the vendor is NOT asked to replace a valid cheque
    assert "isn't printed on the document" in d.reasons[0].detail


def test_missing_evidence_on_a_readable_document_is_not_trusted(ctx):
    d = evaluate(h1_with_bank_proof_typed_as_invoice(None), ctx).decision
    assert d.failing_rules == ["DOC-03"] and d.vendor_actions == []


def test_genuine_wrong_document_still_goes_to_the_vendor(ctx):
    """E3's real invoice: the model's evidence 'TAX INVOICE' is printed on it -> vendor fixes it (unchanged)."""
    d = evaluate(CaseInput.model_validate(load_sample("E3")["case"]), ctx).decision
    assert d.sub_state == SubState.AWAITING_VENDOR and set(d.failing_rules) == {"DOC-01", "TAX-04"}


def test_scan_cannot_be_text_checked_so_keeps_the_vendor_path(ctx):
    ev = ExtractedField(value="TAX INVOICE", quote="TAX INVOICE", page=1, grounded="image")
    d = evaluate(h1_with_bank_proof_typed_as_invoice(ev), ctx).decision
    assert d.failing_rules == ["DOC-01"]  # layer 2 is the backstop for scans


# ---------- end to end (API) ----------

class MisclassifyingReader(TruthReader):
    """Reads everything correctly, except it calls a valid cancelled cheque an 'invoice' and quotes text that
    isn't on the cheque."""

    def read(self, data, filename, mime):
        result = super().read(data, filename, mime)
        if result.data["doc_type"] == "bank_proof":
            result.data["doc_type"] = "invoice"
            result.data["type_evidence"] = {"quote": "TAX INVOICE", "page": 1}
        return result


@pytest.fixture
def api(tmp_path, monkeypatch, ctx):
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("APP_PASSCODE", raising=False)
    init_db(f"sqlite:///{tmp_path / 'cls.db'}")
    seed_demo_cases()
    yield ctx
    app.dependency_overrides.clear()
    get_engine().dispose()


def use(reader, ctx):
    app.dependency_overrides[get_pipeline_deps] = lambda: PipelineDeps(
        reader_factory=lambda: reader, cache=None, ctx=ctx, background=False)


def cid(sample_id):
    return next(c for c in client.get("/api/cases").json() if c["sample_id"] == sample_id)["id"]


def test_valid_cheque_misread_as_invoice_end_to_end(api):
    use(MisclassifyingReader(), api)
    h1 = cid("H1")
    run = client.get(f"/api/runs/{client.post(f'/api/cases/{h1}/replay').json()['run_id']}").json()
    c = client.get(f"/api/cases/{h1}").json()
    assert c["display_status"] == "INTERNAL_REVIEW" and [x["rule_id"] for x in c["reasons"]] == ["DOC-03"]
    assert run["decision"]["vendor_actions"] == []
    assert c["messages"][0]["kind"] == "under_review"  # vendor isn't told to replace their valid cheque
    assert c["can_approve"] is False  # cross-checks on that document didn't run


# ---------- layer 2 (re-sent identical file) ----------

def e3_resubmit(slots: set[str], source: str = "E3"):
    """Resubmit seeded E3 with the Tamil Nadu details fixed, re-uploading the given slots from `source`."""
    sample = load_sample(source)
    files = {slot: (d["filename"], (SAMPLES_DIR / source / d["filename"]).read_bytes(), "application/pdf")
             for slot, d in sample["case"]["documents"].items() if slot in slots}
    form = load_sample("E3R")["case"]["submission"]
    return client.post(f"/api/cases/{cid('E3')}/resubmit", data={"submission": json.dumps(form)}, files=files)


def test_vendor_resending_the_same_flagged_file_goes_to_a_person(api):
    use(TruthReader(), api)
    r = e3_resubmit({"bank_proof"})  # the vendor re-sends the identical invoice we flagged on v1
    assert r.status_code == 201
    c = client.get(f"/api/cases/{cid('E3')}").json()
    assert c["display_status"] == "INTERNAL_REVIEW"
    doc03 = next(rule for g in c["checks"] for rule in g["rules"] if rule["rule_id"] == "DOC-03")
    assert "re-sent the same file we flagged as the wrong document on version 1" in doc03["results"][0]["detail"]
    assert not any("cancelled cheque" in a for a in c["run"]["decision"]["vendor_actions"])  # not asked again


def test_a_carried_over_flagged_file_is_still_the_vendors_to_fix(api):
    """Not re-sent, just left in place: the vendor hasn't responded on that document yet."""
    use(TruthReader(), api)
    e3_resubmit({"gst_certificate"}, source="E3R")  # fixes the GSTIN only; the invoice carries over
    c = client.get(f"/api/cases/{cid('E3')}").json()
    assert c["display_status"] == "AWAITING_VENDOR" and [x["rule_id"] for x in c["reasons"]] == ["DOC-01"]


def test_replay_is_not_a_resend(api):
    """Replay reruns the same version: the invoice is still simply the wrong document."""
    use(TruthReader(), api)
    e3 = cid("E3")
    client.post(f"/api/cases/{e3}/replay")
    c = client.get(f"/api/cases/{e3}").json()
    assert c["display_status"] == "AWAITING_VENDOR" and {x["rule_id"] for x in c["reasons"]} == {"DOC-01", "TAX-04"}
