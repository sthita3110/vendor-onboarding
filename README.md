# Vendor Onboarding

AI-assisted vendor onboarding for Indian vendors: a submission (form + GST certificate, PAN card, bank proof) goes in; **Approved / Pending (awaiting vendor · internal review) / Rejected** comes out, with every check and its evidence visible.

Design docs: [ARCHITECTURE.md](ARCHITECTURE.md) · [RULES.md](RULES.md) · [ASSUMPTIONS.md](ASSUMPTIONS.md)

## Status

| Phase | State |
|---|---|
| 1 — Decision core (validators, name matching, cross-checks, mock adapters, risk, decision engine, golden tests) | ✅ |
| 2 — Documents + AI extraction | 2a documents ✅ · 2b OpenAI extraction ✅ · 2c file checks, grounding, cache ✅ · 2d — |
| 3 — Orchestration + persistence + API | — |
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
```

## Phase 1 API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness + rule catalog version |
| GET | `/api/rules` | Rule catalog |
| GET | `/api/samples` | Demo cases |
| GET | `/api/samples/{id}` | Demo case payload |
| POST | `/api/samples/{id}/evaluate` | Evaluate a demo case |
| POST | `/api/evaluate` | Evaluate any `CaseInput` JSON |

## Deploy

Single container from the repo-root `Dockerfile`; the host injects `$PORT`. Use an always-on tier (no cold starts). A persistent volume is needed from Phase 3, when SQLite is added.
