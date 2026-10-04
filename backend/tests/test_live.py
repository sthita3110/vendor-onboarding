"""Live golden test: real PDFs -> real OpenAI extraction -> rules. Opt-in: `pytest -m live`.

Proves the AI layer doesn't change decisions on known inputs: every case must reach its expected
outcome, every document must be classified correctly, and every key field must be read exactly.
No cache — each run makes fresh model calls (about 21 calls, a few cents).
"""

import pytest

from app.config import get_settings
from app.llm.client import make_reader
from app.llm.extract import extract_case
from app.llm.scoring import score_document
from app.rules.evaluate import evaluate
from app.samples import load_sample, sample_ids, sample_submission, sample_uploads

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not get_settings().openai_api_key, reason="OPENAI_API_KEY not set"),
]


@pytest.fixture(scope="module")
def reader():
    return make_reader()


@pytest.mark.parametrize("cid", sample_ids())
def test_live_golden(cid, reader, ctx):
    sample = load_sample(cid)
    case, extractions = extract_case(sample_submission(sample), sample_uploads(sample), reader, cache=None)

    for slot, ex in extractions.items():
        assert not ex.document.extraction_error, f"{slot}: {ex.document.extraction_error}"
        score = score_document(sample["case"]["documents"][slot], ex.document)
        assert score.type_ok, f"{slot}: classified as {score.got_type}, expected {score.want_type}"
        assert not score.key_mismatches, f"{slot}: " + "; ".join(map(str, score.key_mismatches))

    d = evaluate(case, ctx).decision
    exp = sample["expected"]
    assert d.status.value == exp["status"]
    assert (d.sub_state.value if d.sub_state else None) == exp["sub_state"]
    assert set(d.failing_rules) == set(exp["failing_rules"])
