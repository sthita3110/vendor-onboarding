"""Step 2c: file intake (FILE-01), grounding + format reliability (DOC-03), extraction cache."""

import io

import pytest
from pypdf import PdfWriter

from app.documents.grounding import apply_grounding
from app.documents.inspect import MAX_PDF_PAGES, inspect_file
from app.domain.models import CaseInput, Status, SubState, Submission
from app.llm.cache import ExtractionCache, cache_key
from app.llm.extract import UploadedFile, read_document, read_documents, to_document
from app.reference.data import SAMPLES_DIR
from app.rules.evaluate import evaluate
from tests.conftest import load_sample
from tests.test_extract import FakeReader, raw_from_truth

H1 = load_sample("H1")
H1_DOCS = H1["case"]["documents"]


def sample_bytes(cid: str, slot: str) -> bytes:
    return (SAMPLES_DIR / cid / load_sample(cid)["case"]["documents"][slot]["filename"]).read_bytes()


def blank_pdf(pages: int = 1, user_password: str | None = None, owner_password: str | None = None) -> bytes:
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=200, height=200)
    if user_password is not None:
        w.encrypt(user_password=user_password, owner_password=owner_password)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def evaluate_h1_with(ctx, replace: dict[str, bytes] | None = None, raw_override: dict[str, dict] | None = None,
                     cache=None):
    """Run H1 through extraction (fake model returning ground truth unless overridden) and the rules."""
    replace, raw_override = replace or {}, raw_override or {}
    by_filename = {d["filename"]: raw_override.get(slot, raw_from_truth(d)) for slot, d in H1_DOCS.items()}
    uploads = [UploadedFile(slot, d["filename"], replace.get(slot, sample_bytes("H1", slot)))
               for slot, d in H1_DOCS.items()]
    extracted = read_documents(FakeReader(by_filename), uploads, cache)
    case = CaseInput(submission=Submission.model_validate(H1["case"]["submission"]),
                     documents={slot: ex.document for slot, ex in extracted.items()})
    return evaluate(case, ctx)


# ---------- FILE-01: inspect_file ----------

@pytest.mark.parametrize("data,expect", [
    (b"", "empty"),
    (b"PK\x03\x04 a docx is a zip", "isn't supported"),
    (b"%PDF-1.7 this is not really a pdf", "damaged"),
    (blank_pdf(user_password="15081985"), "password-protected"),
    (blank_pdf(pages=MAX_PDF_PAGES + 1), "pages"),
])
def test_unusable_files(data, expect):
    result = inspect_file(data)
    assert result.problem and expect in result.problem


def test_too_large(monkeypatch):
    monkeypatch.setattr("app.documents.inspect.MAX_BYTES", 10)
    assert "larger than" in inspect_file(blank_pdf()).problem


def test_restriction_only_encryption_is_fine():
    """No user password (only print/copy restrictions): opens in any viewer, so it must be accepted."""
    assert inspect_file(blank_pdf(user_password="", owner_password="owner")).problem is None


def test_type_comes_from_content_not_extension():
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    assert inspect_file(png).mime == "image/png"
    up = UploadedFile("pan_card", "looks_like.pdf", b"PK\x03\x04", "application/pdf")
    assert read_document(FakeReader(), up).document.file_problem  # renamed zip is still rejected


def test_unusable_file_never_reaches_the_model():
    ex = read_document(FakeReader(fail=AssertionError("model must not be called")),
                       UploadedFile("pan_card", "e-pan.pdf", blank_pdf(user_password="15081985")))
    assert ex.document.file_problem and not ex.document.extraction_error


def test_password_protected_pan_asks_vendor(ctx):
    d = evaluate_h1_with(ctx, replace={"pan_card": blank_pdf(user_password="15081985")}).decision
    assert d.sub_state == SubState.AWAITING_VENDOR and d.failing_rules == ["FILE-01"]
    assert "password" in d.vendor_actions[0] and "pan_card_scan.pdf" in d.vendor_actions[0]


# ---------- grounding ----------

def test_digital_pdf_values_are_grounded_and_scan_is_image():
    gst = apply_grounding(to_document("gst_certificate", "g.pdf", raw_from_truth(H1_DOCS["gst_certificate"])),
                          sample_bytes("H1", "gst_certificate"), "application/pdf")
    assert {f.grounded for f in gst.fields.values()} == {"text"}
    pan = apply_grounding(to_document("pan_card", "p.pdf", raw_from_truth(H1_DOCS["pan_card"])),
                          sample_bytes("H1", "pan_card"), "application/pdf")
    assert {f.grounded for f in pan.fields.values()} == {"image"}


def test_grounding_tolerates_punctuation_but_not_different_content():
    raw = raw_from_truth(H1_DOCS["bank_proof"])
    raw["fields"]["account_holder_name"]["value"] = "Lumen Analytics Pvt Ltd"  # printed: "LUMEN ANALYTICS PVT. LTD."
    raw["fields"]["account_number"]["value"] = "50200074561239"  # one digit off
    doc = apply_grounding(to_document("bank_proof", "c.pdf", raw), sample_bytes("H1", "bank_proof"), "application/pdf")
    assert doc.fields["account_holder_name"].grounded == "text"
    assert doc.fields["account_number"].grounded == "unverified"


def test_images_are_never_text_grounded():
    doc = apply_grounding(to_document("pan_card", "p.png", raw_from_truth(H1_DOCS["pan_card"])), b"", "image/png")
    assert {f.grounded for f in doc.fields.values()} == {"image"}


# ---------- DOC-03 end to end ----------

def test_value_not_on_page_goes_to_review_not_mismatch(ctx):
    """Model 'reads' a name that isn't printed: DOC-03 review, and no misleading ID-01/TAX mismatch."""
    raw = raw_from_truth(H1_DOCS["gst_certificate"])
    raw["fields"]["legal_name"]["value"] = "LUMEN ANALYTICS INDIA PRIVATE LIMITED"
    ev = evaluate_h1_with(ctx, raw_override={"gst_certificate": raw})
    assert ev.decision.sub_state == SubState.INTERNAL_REVIEW and ev.decision.failing_rules == ["DOC-03"]
    assert ev.decision.vendor_actions == []  # our misread, not the vendor's problem
    blocked = {r.rule_id for r in ev.results if r.blocked_by == "DOC-03"}
    assert {"ID-01", "TAX-02", "BANK-03"} <= blocked


def test_scan_misread_caught_by_format_check(ctx):
    """The real failure seen in step 2b: 'AACL4821K' (9 chars) from the scanned PAN card."""
    raw = raw_from_truth(H1_DOCS["pan_card"])
    raw["fields"]["pan"]["value"] = "AACL4821K"
    ev = evaluate_h1_with(ctx, raw_override={"pan_card": raw})
    assert ev.decision.failing_rules == ["DOC-03"]
    doc03 = next(r for r in ev.results if r.rule_id == "DOC-03" and r.status == "fail")
    assert "AACL4821K" in doc03.detail and doc03.evidence["grounding"]["pan"] == "image"


def test_perfect_read_of_real_pdfs_approves_h1(ctx):
    assert evaluate_h1_with(ctx).decision.status == Status.APPROVED


# ---------- cache ----------

def test_cache_hit_skips_the_model(tmp_path, ctx):
    cache = ExtractionCache(tmp_path)
    evaluate_h1_with(ctx, cache=cache)  # populate
    assert len(list(tmp_path.glob("*.json"))) == 3
    up = UploadedFile("gst_certificate", "renamed.pdf", sample_bytes("H1", "gst_certificate"))
    ex = read_document(FakeReader(fail=AssertionError("should be cached")), up, cache)
    assert ex.meta["cached"] is True and ex.document.classified_type == "gst_certificate"
    assert ex.document.fields["gstin"].grounded == "text"  # grounding recomputed, not cached


def test_cache_key_depends_on_content_and_model():
    data = sample_bytes("H1", "gst_certificate")
    assert cache_key(data, "gpt-4.1") == cache_key(data, "gpt-4.1")
    assert cache_key(data, "gpt-4.1") != cache_key(data, "gpt-4.1-mini")
    assert cache_key(data, "gpt-4.1") != cache_key(data + b" ", "gpt-4.1")


def test_failures_are_not_cached(tmp_path):
    cache = ExtractionCache(tmp_path)
    read_document(FakeReader(fail=TimeoutError()), UploadedFile("pan_card", "p.pdf", blank_pdf()), cache)
    assert not list(tmp_path.glob("*.json"))


def test_corrupt_cache_entry_is_a_miss(tmp_path):
    data = sample_bytes("H1", "gst_certificate")
    cache = ExtractionCache(tmp_path)
    (tmp_path / f"{cache_key(data, 'fake-model')}.json").write_text("{not json")
    raw = raw_from_truth(H1_DOCS["gst_certificate"])
    ex = read_document(FakeReader({"g.pdf": raw}), UploadedFile("gst_certificate", "g.pdf", data), cache)
    assert ex.meta["cached"] is False and ex.document.classified_type == "gst_certificate"
