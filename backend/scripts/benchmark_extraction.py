"""Compare models on the 21 sample documents against ground truth.

Scores per model: document-type accuracy, key-field accuracy (fields the rules depend on),
all-field accuracy, failures, latency, tokens. Prints every mismatch so errors can be inspected.

Run from backend/ (costs a few cents per model):
  python -m scripts.benchmark_extraction --models gpt-4.1,gpt-4.1-mini
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from app.config import get_settings
from app.llm.client import OpenAIReader
from app.llm.extract import MIME_BY_EXT, UploadedFile, read_document
from app.llm.schema import FIELDS_BY_TYPE
from app.reference.data import SAMPLES_DIR
from app.rules.checks import KEY_FIELDS
from app.rules.validators import clean_account, clean_id


def norm(name: str, value: str | None) -> str:
    """Compare what was *read*, tolerant only of whitespace/case/formatting — not of different content."""
    v = value or ""
    if name in ("gstin", "pan", "ifsc"):
        return clean_id(v)
    if name == "account_number":
        return clean_account(v)
    if name == "total_amount":
        return re.sub(r"[^\d.]", "", v)
    return re.sub(r"\s+", " ", v).strip().upper()


def load_cases() -> list[tuple[str, str, dict, UploadedFile]]:
    items = []
    for path in sorted(SAMPLES_DIR.glob("*.json")):
        sample = json.loads(path.read_text())
        for slot, doc in sample["case"]["documents"].items():
            f = SAMPLES_DIR / sample["id"] / doc["filename"]
            items.append((sample["id"], slot, doc,
                          UploadedFile(slot, f.name, f.read_bytes(), MIME_BY_EXT[f.suffix.lower()])))
    return items


def run_model(model: str, effort: str | None, items) -> dict:
    settings = replace(get_settings(), openai_model=model, openai_reasoning_effort=effort)
    reader = OpenAIReader(settings)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda it: read_document(reader, it[3]), items))

    type_ok = key_ok = key_n = all_ok = all_n = failures = 0
    latencies, tokens, mismatches = [], 0, []
    for (cid, slot, truth, upload), ex in zip(items, results):
        label = f"{cid}/{upload.filename}"
        if ex.document.extraction_error:
            failures += 1
            mismatches.append(f"{label}: FAILED {ex.document.extraction_error}")
            continue
        latencies.append(ex.meta["latency_ms"])
        tokens += (ex.meta.get("input_tokens") or 0) + (ex.meta.get("output_tokens") or 0)
        expected_type = truth["classified_type"]
        if ex.document.classified_type == expected_type:
            type_ok += 1
        else:
            mismatches.append(f"{label}: doc_type {ex.document.classified_type!r} != {expected_type!r}")
            continue
        key_names = {n for n, _ in KEY_FIELDS.get(expected_type, [])}
        for name in FIELDS_BY_TYPE[expected_type]:
            want = truth["fields"].get(name, {}).get("value")
            if want is None:
                continue
            got = ex.document.value(name)
            ok = norm(name, got) == norm(name, want)
            all_n += 1
            all_ok += ok
            if name in key_names:
                key_n += 1
                key_ok += ok
            if not ok:
                mismatches.append(f"{label}: {name}{' (KEY)' if name in key_names else ''} "
                                  f"got {got!r} want {want!r}")
    return {
        "model": model + (f" [{effort}]" if effort else ""),
        "doc_type": f"{type_ok}/{len(items)}",
        "key_fields": f"{key_ok}/{key_n}",
        "all_fields": f"{all_ok}/{all_n}",
        "failures": failures,
        "p50_ms": int(statistics.median(latencies)) if latencies else None,
        "max_ms": max(latencies) if latencies else None,
        "tokens": tokens,
        "mismatches": mismatches,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="gpt-4.1,gpt-4.1-mini")
    ap.add_argument("--effort", help="reasoning effort for reasoning models (e.g. low)")
    args = ap.parse_args()
    items = load_cases()
    reports = [run_model(m.strip(), args.effort, items) for m in args.models.split(",")]

    cols = ["model", "doc_type", "key_fields", "all_fields", "failures", "p50_ms", "max_ms", "tokens"]
    print(" | ".join(f"{c:>14}" for c in cols))
    for r in reports:
        print(" | ".join(f"{str(r[c]):>14}" for c in cols))
    for r in reports:
        if r["mismatches"]:
            print(f"\n{r['model']} mismatches:")
            for m in r["mismatches"]:
                print("  " + m)


if __name__ == "__main__":
    main()
