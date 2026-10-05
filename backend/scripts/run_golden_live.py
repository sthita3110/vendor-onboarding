"""Run every demo case end to end with the real model, N times, and report stability.

For each case: expected outcome, the outcome of every run, key-field misreads, and read time.
Any run whose outcome differs from the expected one is a bug to fix before the demo.

Run from backend/:
  python -m scripts.run_golden_live              # 1 run, no cache (fresh model calls)
  python -m scripts.run_golden_live --runs 10    # stability check before the interview
  python -m scripts.run_golden_live --cache      # replay cached extractions (fast, free)
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from app.config import get_settings
from app.llm.cache import ExtractionCache
from app.llm.client import make_reader
from app.llm.extract import extract_case
from app.llm.scoring import score_document
from app.rules.evaluate import default_context, evaluate
from app.samples import load_sample, sample_ids, sample_submission, sample_uploads


def outcome(d) -> str:
    return d.status.value + (f"/{d.sub_state.value}" if d.sub_state else "") + f" {sorted(d.failing_rules)}"


def run_once(cid: str, reader, cache, ctx) -> dict:
    sample = load_sample(cid)
    start = time.monotonic()
    case, extractions = extract_case(sample_submission(sample), sample_uploads(sample), reader, cache)
    read_s = time.monotonic() - start
    d = evaluate(case, ctx).decision
    misreads = []
    for slot, ex in extractions.items():
        score = score_document(sample["case"]["documents"][slot], ex.document)
        if not score.type_ok:
            misreads.append(f"{slot}: type {score.got_type}")
        misreads += [f"{slot}: {m}" for m in score.key_mismatches]
    hedged = sum(bool(ex.meta.get("hedged")) for ex in extractions.values())
    return {"outcome": outcome(d), "misreads": misreads, "read_s": read_s, "hedged": hedged}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--cache", action="store_true", help="use the extraction cache")
    ap.add_argument("--workers", type=int, default=4, help="cases run in parallel (1 = like a live demo)")
    args = ap.parse_args()

    settings = get_settings()
    reader = make_reader(settings)
    cache = ExtractionCache(settings.extraction_cache_dir) if args.cache else None
    ctx = default_context()
    ids = sample_ids()
    jobs = [(cid, i) for cid in ids for i in range(args.runs)]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda job: run_once(job[0], reader, cache, ctx), jobs))

    unstable = 0
    print(f"model={reader.model} runs={args.runs} workers={args.workers} cache={'on' if cache else 'off'}\n")
    for cid in ids:
        sample = load_sample(cid)
        exp = sample["expected"]
        expected = exp["status"] + (f"/{exp['sub_state']}" if exp["sub_state"] else "") + f" {sorted(exp['failing_rules'])}"
        runs = [r for (c, _), r in zip(jobs, results) if c == cid]
        ok = sum(r["outcome"] == expected for r in runs)
        unstable += ok != len(runs)
        times = [r["read_s"] for r in runs]
        print(f"{cid:4} {'OK ' if ok == len(runs) else 'BAD'} {ok}/{len(runs)} expected {expected}  "
              f"read p50 {statistics.median(times):.1f}s max {max(times):.1f}s")
        for r in runs:
            if r["outcome"] != expected:
                print(f"       got {r['outcome']}")
            for m in r["misreads"]:
                print(f"       misread {m}")
    print(f"\nbackup requests sent (hedged slow reads): {sum(r['hedged'] for r in results)} of {len(results) * 3} reads")
    print(f"\n{'ALL STABLE' if not unstable else f'{unstable} case(s) unstable'}")
    sys.exit(1 if unstable else 0)


if __name__ == "__main__":
    main()
