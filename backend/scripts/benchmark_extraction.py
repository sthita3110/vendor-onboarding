"""Compare models on the 21 sample documents against ground truth.

Scores per model: document-type accuracy, key-field accuracy (fields the rules depend on),
all-field accuracy, failures, latency, tokens. Prints every mismatch so errors can be inspected.
Always calls the model (no cache).

Run from backend/ (costs a few cents per model):
  python -m scripts.benchmark_extraction --models gpt-4.1,gpt-4.1-mini
"""

from __future__ import annotations

import argparse
import statistics
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from app.config import get_settings
from app.llm.client import OpenAIReader
from app.llm.extract import read_document
from app.llm.scoring import score_document
from app.samples import load_sample, sample_ids, sample_uploads


def load_items():
    items = []
    for cid in sample_ids():
        sample = load_sample(cid)
        for upload in sample_uploads(sample):
            items.append((cid, sample["case"]["documents"][upload.slot], upload))
    return items


def run_model(model: str, effort: str | None, items) -> dict:
    reader = OpenAIReader(replace(get_settings(), openai_model=model, openai_reasoning_effort=effort))
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda it: read_document(reader, it[2]), items))

    type_ok = key_ok = key_n = all_ok = all_n = failures = 0
    latencies, tokens, problems = [], 0, []
    for (cid, truth, upload), ex in zip(items, results):
        label = f"{cid}/{upload.filename}"
        if ex.document.extraction_error or ex.document.file_problem:
            failures += 1
            problems.append(f"{label}: FAILED {ex.document.extraction_error or ex.document.file_problem}")
            continue
        latencies.append(ex.meta["latency_ms"])
        tokens += (ex.meta.get("input_tokens") or 0) + (ex.meta.get("output_tokens") or 0)
        score = score_document(truth, ex.document)
        if not score.type_ok:
            problems.append(f"{label}: doc_type {score.got_type!r} != {score.want_type!r}")
            continue
        type_ok += 1
        all_n += score.fields_checked
        all_ok += score.fields_checked - len(score.mismatches)
        key_n += score.key_checked
        key_ok += score.key_checked - len(score.key_mismatches)
        problems += [f"{label}: {m}" for m in score.mismatches]
    return {
        "model": model + (f" [{effort}]" if effort else ""),
        "doc_type": f"{type_ok}/{len(items)}",
        "key_fields": f"{key_ok}/{key_n}",
        "all_fields": f"{all_ok}/{all_n}",
        "failures": failures,
        "p50_ms": int(statistics.median(latencies)) if latencies else None,
        "max_ms": max(latencies) if latencies else None,
        "tokens": tokens,
        "problems": problems,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="gpt-4.1,gpt-4.1-mini")
    ap.add_argument("--effort", help="reasoning effort for reasoning models (e.g. low)")
    args = ap.parse_args()
    items = load_items()
    reports = [run_model(m.strip(), args.effort, items) for m in args.models.split(",")]

    cols = ["model", "doc_type", "key_fields", "all_fields", "failures", "p50_ms", "max_ms", "tokens"]
    print(" | ".join(f"{c:>14}" for c in cols))
    for r in reports:
        print(" | ".join(f"{str(r[c]):>14}" for c in cols))
    for r in reports:
        if r["problems"]:
            print(f"\n{r['model']} problems:")
            for p in r["problems"]:
                print("  " + p)


if __name__ == "__main__":
    main()
