# Reliability — stability runs and failure drills

Measured on 2026-10-05 against the real OpenAI model (`gpt-4.1`), real PDFs, no extraction cache.
Re-run before the interview with `python -m scripts.run_golden_live --runs 10` (from `backend/`).

## Stability: same input, same decision

| Run | Cases × runs | Correct outcome | Key-field misreads |
|---|---|---|---|
| 10× each, 4 cases in parallel | 7 × 10 = 70 | **70 / 70** | **0** |
| 3× each, one case at a time (like a live demo) | 7 × 3 = 21 | **21 / 21** | **0** |
| 3× each, one at a time, with hedging | 7 × 3 = 21 | **21 / 21** | **0** |

## Latency: time to read a case's three documents

| Setting | Typical (p50) | Worst |
|---|---|---|
| 4 cases in parallel | 6–10 s | 40 s |
| One case at a time (demo pattern) | 6–9 s | 34.6 s |
| One case at a time **+ hedged requests** | 5.5–9.7 s | **17.6 s** |

The long tail comes from the AI provider, not our load: even one case at a time, roughly 1 run in 20 had a document
read stall for 20–35 s. **Fix: hedged requests** — if a read hasn't answered in 10 s (a single read normally takes
5–7 s), one identical backup is sent and whichever answers first is used. Backups were needed for 3 of 63 reads
(~5% extra cost, only on slow reads). Configurable with `OPENAI_HEDGE_AFTER_S` (0 = off).

## Failure drills (real server)

| Drill | How | Result |
|---|---|---|
| Invalid OpenAI key | Server started with a wrong key; replay H1 | Run completes; "Reading documents" ✗ *"The AI service rejected our credentials"*; **internal review (SYS-01)**; vendor gets a neutral template message |
| Model timeout | `OPENAI_TIMEOUT_S=0.01`; replay H1 | *"The AI service timed out"*; **internal review (SYS-01)** |
| Server killed mid-run | `kill -9` while reading documents; restart | Run **interrupted** with a plain reason; that stage marked failed; case **internal review (SYS-01)**; no duplicate seeding on restart |
| Damaged PDF | Resubmit E3 with a broken PDF as bank proof | **Awaiting vendor (FILE-01)**: *"the PDF is damaged and can't be opened"*; no AI call |
| `.docx` upload | Same, with a Word file | FILE-01: *"this file type isn't supported — please upload a PDF, PNG or JPG"* |
| Password-protected PDF | Same, with an encrypted PDF (like an e-PAN) | FILE-01: *"the PDF is password-protected — please upload a copy without a password"* |
| 11 MB file | Same, with an oversized file | FILE-01: *"the file is larger than 10 MB"* |

In every drill the system **failed closed**: no path led to an approval.

## Bugs the drills found (all fixed, each with a regression test)

1. **A reviewer could approve a case whose run was interrupted.** The "can't approve unchecked evidence" rule looked
   for blocked/errored checks — but an interrupted run has *no* results at all, so it found none. Approve now requires
   the latest run to have completed with a decision, and is always refused while SYS-01 is open.
2. **Raw provider errors reached the UI, audit trail and database**, including a masked fragment of the API key
   (`Incorrect API key provided: sk-inval***`). Errors are now reduced to a plain category; full detail goes only to
   the server log.
3. **Message-summary wording was lower-cased and truncated** ("template (ai unavailable: authen…").

## Document-type verification (added after the first runs)

The one AI output previously trusted unchecked was the document type: a valid cheque misread as an invoice would have
been sent back to the vendor, and the same file would likely fail again. Now the model quotes its evidence for the type
and that quote must be on the page; a re-sent identical file that we flagged is never sent back twice (see RULES.md).

| Check | Result |
|---|---|
| Live golden tests, new prompt | **8 / 8** |
| Live stability, 5 runs each, one case at a time | **40 / 40** correct — E3's real invoice still goes to the vendor every time (its evidence "TAX INVOICE" is grounded) |
| Same document, old vs new prompt, interleaved | median **9.3 s vs 9.4 s** — no latency cost (the old prompt also had a 55 s stall: provider-side) |

One earlier 3-run batch had a single transient read failure on E3R's GST certificate; the case **failed closed to
internal review (SYS-01)**, and six immediate retries plus the 40-run batch were clean. Read failures are now printed
by `run_golden_live`. Latency varies with the provider's load during the day (p50 ~6–9 s earlier, ~9–13 s later);
hedged requests absorb the tail.
