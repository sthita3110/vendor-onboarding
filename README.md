# Vendor Onboarding

AI-assisted vendor onboarding for Indian vendors: a submission (form + GST certificate, PAN card, bank proof) goes in; **Approved / Pending (awaiting vendor · internal review) / Rejected** comes out, with every check and its evidence visible.

Design docs: [ARCHITECTURE.md](ARCHITECTURE.md) · [RULES.md](RULES.md) · [ASSUMPTIONS.md](ASSUMPTIONS.md)

## Status

| Phase | State |
|---|---|
| 1 — Decision core (validators, name matching, cross-checks, mock adapters, risk, decision engine, golden tests) | ✅ |
| 2 — Documents + AI extraction | — |
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

Regenerate reference data and sample packets (deterministic):

```bash
cd backend && .venv/bin/python -m scripts.generate_data
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
