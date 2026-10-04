# Vendor Onboarding

AI-assisted vendor onboarding for Indian vendors: a submission (form + GST certificate, PAN card, bank proof) goes in; **Approved / Pending (awaiting vendor · internal review) / Rejected** comes out, with every check and its evidence visible.

Design docs: [ARCHITECTURE.md](ARCHITECTURE.md) · [RULES.md](RULES.md) · [ASSUMPTIONS.md](ASSUMPTIONS.md)

## Status

| Phase | State |
|---|---|
| 1 — Decision core (validators, name matching, cross-checks, mock adapters, risk, decision engine, golden tests) | ✅ |
| 2 — Documents + AI extraction (sample PDFs, OpenAI extraction, file checks, grounding, cache, live golden tests) | ✅ |
| 3 — Orchestration + persistence + API | 3a database ✅ · 3b runner ✅ · 3c API ✅ · 3d seeding — |
| 4 — Frontend | — |
| 5 — Communications + human review | — |
| 6 — Hardening + demo | — |

## Run locally

```bash
cd backend
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m pytest -q                  # validators, names, rule mutations, golden cases, API
.venv/bin/uvicorn app.main:app --reload        # http://localhost:8000/docs
```

Regenerate reference data, sample packets, and sample PDFs (all deterministic):

```bash
cd backend && .venv/bin/python -m scripts.generate_data && .venv/bin/python -m scripts.render_documents
```

Sample documents live in `backend/data/samples/<ID>/` (H1's PAN card is an image-only scan).

AI extraction needs `backend/.env` with `OPENAI_API_KEY=...` (git-ignored). Optional: `OPENAI_MODEL` (default `gpt-4.1`).

```bash
cd backend
.venv/bin/python -m scripts.try_extract data/samples/H1/pan_card_scan.pdf --slot pan_card
.venv/bin/python -m scripts.benchmark_extraction --models gpt-4.1,gpt-4.1-mini   # accuracy vs ground truth
.venv/bin/python -m pytest -m live                    # all 7 cases, real model: outcomes + key-field accuracy
.venv/bin/python -m scripts.run_golden_live --runs 3  # stability across repeated live runs
```

## API

All routes except `/api/health` require the `X-App-Passcode` header when `APP_PASSCODE` is set.
Interactive docs: `/docs`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness (open) |
| GET | `/api/samples` · `/api/samples/{id}` · `/api/samples/{id}/files/{name}` | Demo presets: form values + sample PDFs |
| POST | `/api/cases` | Multipart `submission` (JSON) + `gst_certificate`, `pan_card`, `bank_proof` → `{case_id, reference, run_id}`; pipeline runs in the background |
| GET | `/api/runs/{id}` | Live run: 10 stages (status, outcome, summary, timings) + decision when done |
| GET | `/api/cases?status=&rule=&q=` | Dashboard list |
| GET | `/api/cases/{id}?version=` | Case detail: versions, form, documents, grouped checks with evidence, extractions |
| GET | `/api/cases/{id}/documents/{doc_id}` | Original uploaded file |
| POST | `/api/cases/{id}/resubmit` | New version (changed files only; others carry over) → new run |
| GET | `/api/review-queue` | Internal-review cases, oldest first |
| GET | `/api/cases/{id}/audit` | Audit timeline |
| GET | `/api/metrics` | Counts by status, straight-through rate, median time to decision, top reasons |
| GET | `/api/rules` | Rule catalog |
| POST | `/api/evaluate` | Developer tool: rules only on a JSON case (no AI, nothing stored) |

## Deploy

Single container from the repo-root `Dockerfile`; the host injects `$PORT`. Use an always-on tier (no cold starts). A persistent volume is needed from Phase 3, when SQLite is added.
