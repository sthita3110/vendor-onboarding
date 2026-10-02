# Vendor Onboarding — Architecture

AI-assisted vendor onboarding for a procurement / vendor-ops team. A vendor submission (form + documents) goes in; a status comes out — **Approved**, **Pending** (awaiting vendor / internal review), or **Rejected** — with every check, its evidence, and the reasoning visible. Anything not approved produces a communication back to the vendor.

Companion docs: [RULES.md](RULES.md) (rule catalog, name matching, golden cases) · [ASSUMPTIONS.md](ASSUMPTIONS.md) (scope, assumptions, known limitations).

---

## 1. Problem framing

| | Frequent, annoying | Rare, catastrophic |
|---|---|---|
| What | Incomplete forms, wrong documents, typos, expired certificates | Bank-detail fraud, sanctioned/debarred entity, duplicate vendor used to redirect payments |
| Cost | Analyst time, email ping-pong, weeks of cycle time | Unrecoverable payments, compliance exposure |
| System's job | Chase the vendor automatically with a precise, one-round fix list | Never approve without positive evidence; route judgment to a human with the evidence assembled |

**Users:** procurement/vendor-ops analyst (primary), reviewer (finance controller / compliance), vendor (submitter), auditor (downstream).

**Success metrics:** straight-through approval rate on clean vendors, rounds-per-pending-vendor, time to decision, **zero false approvals**, complete audit trail.

**Governing principle:** the cost of a false approval far exceeds the cost of a false hold. Therefore:
1. **Approve only on positive evidence** — every required check ran *and* passed.
2. **Fail closed** — a check that could not run never results in approval.
3. **Reject rarely** — only on deterministic, non-curable conditions.

---

## 2. Status model

| Status | Sub-state | Owner | Meaning |
|---|---|---|---|
| **Approved** | — | — | All required checks ran and passed |
| **Pending** | **Awaiting vendor** | Vendor | Vendor-fixable issue(s) |
| **Pending** | **Internal review** | Reviewer | Needs judgment, or potential fraud |
| **Rejected** | — | — | Hard, non-curable rule |

**Precedence:** `REJECT > REVIEW > VENDOR_ACTION > APPROVE`.
When a case is in internal review but also has vendor-fixable items, the vendor is still sent the fix list (no wasted round-trip).

**Communication policy differs by reason** — this is deliberate:

| Outcome | Vendor receives | Reviewer receives |
|---|---|---|
| Approved | Welcome / confirmation | — |
| Awaiting vendor | Specific list of what to fix or upload | Visible in dashboard |
| Internal review | Neutral "your application is under review" (+ any vendor-fixable items) — **never the fraud signal** | Full findings + evidence + AI note |
| Rejected | Generic "unable to proceed", contact point — **never names the list** | Full findings + evidence |

---

## 3. AI vs deterministic responsibilities

**Rule of thumb: the LLM produces facts and prose. Code produces decisions.**

| Layer | Owner | Responsibilities |
|---|---|---|
| Document understanding | LLM | Classify document type; extract fields into a strict JSON schema with a **verbatim evidence quote + page** per field |
| Human-facing explanation | LLM | Plain-English case summary; mismatch hypotheses for reviewers (labeled "AI note"); prose of vendor emails |
| Validation | Code | Required fields, format/checksum (GSTIN, PAN, IFSC, account number), date parsing |
| Cross-checks | Code | Name normalization & tiered matching, ID equality, GSTIN↔PAN, GSTIN state↔address, bank doc↔form |
| External / reference | Code (adapters) | Tax registry lookup, bank account verification, debarred list, vendor master |
| Business rules | Code | Versioned rule catalog → outcome class |
| Final decision | Code + human | Precedence engine; reviewer for internal-review cases |

**LLM guardrails**
1. **Blind extraction** — the model never sees form values while extracting (prevents anchoring / "confirming" expected values). Comparison happens in code.
2. **Grounding check** — for PDFs with a text layer, each extracted value must appear (normalized) in the document text; otherwise it is flagged unverified. Image-only documents are marked `source: image`.
3. **No self-reported confidence scores** — they are not calibrated. Evidence quotes + grounding replace them.
4. **Constrained vendor emails** — LLM sees only vendor-safe findings; the required-items checklist is rendered deterministically under the LLM prose; a forbidden-term filter (debarred, sanction, fraud, holder name returned, etc.) blocks unsafe drafts; template fallback on any failure.
5. **Reproducibility** — temperature 0; model id, prompt version, and rule-catalog version stored on every run.

---

## 4. Pipeline

```
Vendor submission (form + documents)
  │
  ├─ 0  Intake ............. create Case + Submission + Run; store files with sha256          [code]
  ├─ 1  Completeness ....... required fields + required documents                             [code]
  ├─ 2  Doc processing ..... file type, page count, text layer; classify document type        [code + LLM]
  ├─ 3  Extraction ......... per document, blind, schema + evidence; parallel; cached by hash  [LLM]
  ├─ 4  Field validation ... format / checksum / dates on form AND extracted values           [code]
  ├─ 5  Cross-checks ....... form ↔ docs ↔ docs: names, IDs, GSTIN↔PAN, state, bank           [code]
  ├─ 6  External verify .... TaxRegistryAdapter, BankVerificationAdapter (mock, real iface)   [code]
  ├─ 7  Risk checks ........ debarred list, vendor-master duplicates, bank-account reuse      [code]
  ├─ 8  Decision ........... check results → precedence → status + reasoning                  [code]
  ├─ 9  Communication ...... vendor message → outbox; case → review queue if needed          [LLM + code]
  └─ 10 Audit .............. append-only events for every stage, check, and human action      [code]
```

### Stage notes
- **0 Intake** — submissions are versioned; a resubmission creates a new `Submission` + `Run` on the same `Case`.
- **2 Doc processing** — classification answers "is the file in the bank-proof slot actually a bank proof?" Mismatch → `DOC-01`.
- **3 Extraction** — one call per document with a doc-type-specific schema. Results cached by `(file_sha256, prompt_version, model)`. Timeout + one retry; failure → check status `error`.
- **6 External verify** — adapters return realistic payloads from fixture files with small realistic latency. Interface is what a real integration (GST portal / GSP API, penny-drop via Razorpay/Cashfree) would implement.
- **8 Decision** — see §5.
- **9 Communication** — no real email in MVP; messages land in an in-app **Outbox** with status `sent (simulated)`.

### Core objects

**CheckResult** — every stage emits these; the decision engine reads only these; the UI renders only these.

```
CheckResult {
  rule_id          e.g. "BANK-03"
  stage            e.g. "external_verify"
  status           pass | fail | blocked | error
  outcome_class    VENDOR_ACTION | REVIEW | REJECT | INFO   (meaningful when status = fail)
  title            business-language one-liner ("Bank account holder doesn't match company name")
  evidence         { form_value, doc_value, source_doc, page, quote, adapter_response }
  reviewer_text    detail for internal users
  vendor_text      optional; only for VENDOR_ACTION findings
  blocked_by       rule_id that prevented this check from running (status = blocked)
}
```

- `blocked` — check could not run because an input is missing for a reason already captured as a vendor finding (e.g. bank-proof cross-check blocked by `DOC-01`). Prevents approval but does not escalate to review.
- `error` — check could not run for a system reason (LLM timeout, adapter failure). Emits `SYS-01` → **REVIEW** (fail closed).

---

## 5. Decision engine

```
fails   = results where status == fail
errors  = results where status == error
blocked = results where status == blocked

if any fail.outcome_class == REJECT            → REJECTED
elif errors or any fail.outcome_class == REVIEW → PENDING / INTERNAL_REVIEW
elif any fail.outcome_class == VENDOR_ACTION    → PENDING / AWAITING_VENDOR
elif blocked                                    → PENDING / INTERNAL_REVIEW   (defensive: should not occur)
elif every required check status == pass        → APPROVED
else                                            → PENDING / INTERNAL_REVIEW   (defensive)
```

Output: `{status, sub_state, reasons[] (rule_ids ordered by severity), summary (LLM, plain English), rule_catalog_version}`.

**Human-in-the-loop actions** (internal review cases):
- **Approve** — reason required
- **Request info** — reviewer writes / edits a vendor message → outbox → case moves to Awaiting vendor
- **Reject** — reason required

`REJECT`-class outcomes (RISK-01) are **not overridable in MVP**. Every action is an audit event (actor, timestamp, reason, prior/new status).

---

## 6. Key decisions (Choice → Why → Alternative → Trade-off)

| Decision | Choice | Why | Alternative | Trade-off |
|---|---|---|---|---|
| Status model | 3 top-level statuses, Pending split into 2 sub-states | Keeps brief's vocabulary; different owners, clocks, messages | Single "Pending" | Single bucket mixes "waiting on them" with "waiting on us" |
| Decision maker | Deterministic rule engine + human | Explainable, testable, auditable | LLM decides | LLM decisions are non-reproducible and hard to defend |
| Name matching | Tiered deterministic normalization, anchored on tax doc | No arbitrary threshold; each match explainable | Fuzzy score / LLM judge | Some legitimate variations go to review (see RULES.md §2) |
| Document reading | OpenAI model with native PDF/image input + strict JSON-schema structured output | Handles text PDFs and scans without an OCR pipeline; schema-enforced output | Tesseract OCR + text LLM | Single-vendor dependency, mitigated by caching; provider is swappable because the LLM only fills `DocumentInput` |
| Orchestration | Plain Python pipeline in a background thread, state in SQLite | Simple, debuggable, one process | Celery/Redis, Temporal, n8n | No distributed retries — irrelevant at this scale |
| Live updates | Frontend polls run status every ~1s | Most robust through hosting proxies | SSE / WebSocket | ~1s latency; fine for 10 stages |
| Rules | Python functions with IDs + JSON policy config | Explainable, unit-testable, versioned | Rules engine / DSL | Rule changes need a deploy |
| External checks | Adapter interface + fixture mocks | Real APIs need KYC / contracts | Real GST / OFAC / penny-drop APIs | Must be stated clearly as mocks |
| Email | In-app simulated Outbox | Demoable, no deliverability risk | Resend / SendGrid | Less "real" (real send is a SHOULD) |
| Scope | India only | GSTIN embeds PAN + state code and PAN encodes holder type → rich, deterministic cross-field checks; one coherent document set and regulatory context | Multi-country (IN + US) | Narrower demo surface, but deeper checks and half the validators, fixtures, and sample docs to build |
| Deploy | Single service (FastAPI serves built React) on an always-on tier with a persistent volume | One URL, no CORS, no cold start, SQLite survives restarts | Separate FE/BE hosts; free tier | Small hosting cost |

---

## 7. Tech stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy/SQLModel, SQLite, Pydantic schemas
- **AI:** OpenAI API — vision-capable model for classification/extraction (configurable via `OPENAI_MODEL`), strict JSON-schema structured outputs, temperature 0 where the model supports it
- **PDF:** `pypdf` (text layer for grounding), `reportlab` (test document generation), Pillow (rasterized "scanned" test doc)
- **Frontend:** React + Vite + TypeScript + Tailwind + shadcn/ui
- **Tests:** pytest — unit tests for validators/normalization, golden end-to-end tests per demo case
- **Hosting:** Railway (or Render paid tier) — always-on instance + persistent volume; reference data re-seeded on boot

### Proposed repo layout

```
PS2/
  backend/
    app/
      main.py              FastAPI app, serves frontend build
      api/                 routes: submissions, runs, cases, review, outbox, audit, samples
      domain/              Pydantic models: submission, documents, CheckResult, Decision
      rules/               validators, names (normalization), catalog, checks (per stage), engine, evaluate
      adapters/            interfaces + fixture-backed mocks (GST registry, penny drop)
      reference/           reference-data loaders
      pipeline/            orchestrator + stage events                (Phase 3)
      llm/                 client, prompts (versioned), schemas, cache (Phase 2)
      db/                  persistence models                         (Phase 3)
    data/
      reference/           vendor_master.csv, debarred.csv, bank_fixtures.json, registry_fixtures.json
      samples/             demo case packets for H1, E1–E5, E3R (+ PDFs from Phase 2)
    scripts/               generate_data.py — reference data + samples (computes GSTIN check digits)
    tests/
  frontend/                                                         (Phase 4)
  Dockerfile
  ARCHITECTURE.md  RULES.md  ASSUMPTIONS.md  README.md
```

### Data model

| Table | Purpose |
|---|---|
| `cases` | One per vendor onboarding attempt; current status/sub-state |
| `submissions` | Versioned form payloads per case |
| `documents` | Uploaded files: slot, sha256, mime, path, classified type |
| `extractions` | Per-document LLM output, evidence, grounding results, prompt/model version, cached flag |
| `runs` | One pipeline execution per submission; timings |
| `stage_events` | Per-stage start/end/status for the live run view |
| `check_results` | All CheckResults (see §4) |
| `decisions` | Status, reasons, summary, rule catalog version |
| `communications` | Outbox: recipient, subject, body, type, status |
| `review_actions` | Reviewer actions with reason |
| `audit_events` | Append-only log of everything above |
| `vendor_master`, `debarred`, `bank_fixtures`, `registry_fixtures` | Reference data |

### API sketch

```
GET  /api/samples                     demo presets (H1, E1–E4)
POST /api/cases                       create case + submission (multipart: form JSON + files) → starts run
POST /api/cases/{id}/resubmit         new submission version → new run
GET  /api/runs/{id}                   run status + stage events (polled by live view)
GET  /api/cases                       dashboard list (filters: status, sub_state, reason)
GET  /api/cases/{id}                  case detail: decision, check results, evidence, comms
GET  /api/review-queue                internal-review cases
POST /api/cases/{id}/review           {action: approve|request_info|reject, reason, message?}
GET  /api/cases/{id}/audit            timeline
GET  /api/outbox                      simulated sent messages
GET  /api/metrics                     KPI tiles
```

---

## 8. UI

Procurement language throughout ("Bank account holder doesn't match company name", never `BANK-03 FAIL`). Raw JSON only behind a "Technical details" toggle.

1. **New vendor** — sections: Company · Tax · Bank · Contact · Documents (GST certificate, PAN card, bank proof). "Load sample" preset picker for the demo.
2. **Live run** — vertical stepper of the 10 stages: status chip, duration, one-line human result; failing steps expand to evidence; decision banner appears at the end. *(Explicitly graded.)*
3. **Case result** — status banner + plain-English summary; "What we checked" grouped into Identity · Tax · Bank · Risk · Documents with ✓ / ⚠ / ✗; evidence panel (form value vs document value + quote); tabs: Vendor message · Audit.
4. **Dashboard** — KPI tiles (total, approved, awaiting vendor, in review, rejected, straight-through %); cases table with status, reason chips, age, filters.
5. **Review queue** — internal-review cases by age with reason chips → case result + action panel (Approve / Request info / Reject, reason required).
6. **Audit history** — per-case timeline of system and human events with actor, timestamp, rule/prompt version.

---

## 9. MVP scope

**MUST**
- Submission form + uploads + "Load sample" presets
- 10-stage pipeline with persisted stage events
- LLM classify + extract with schema, evidence, grounding, cache
- India validators, cross-checks, both mock adapters, debarred + duplicate checks
- Decision engine with rule catalog + precedence + fail-closed
- Screens: live run, case result, dashboard, review queue + actions, audit timeline
- Vendor communications to Outbox (LLM + template fallback + forbidden-term filter)
- Seeded reference data + realistic sample PDFs (incl. one image-only "scan")
- Golden pytest per demo case
- Deployed; access passcode; upload limits

**SHOULD**
- Resubmission loop (E3 → fix → Approved)
- Side-by-side document viewer with extracted vs form values
- Dashboard KPIs: straight-through %, median time to decision, reasons breakdown
- Reviewer edits vendor message before send; real email send
- Optional documents: MSME/Udyam certificate, Section 197 lower-TDS certificate (validity-period check)

**NICE**
- Additional countries (US: EIN/W-9/ABA; UK/EU: VAT/IBAN), real sanctions list ingestion, real penny-drop sandbox
- Roles/auth, SLA reminders / auto-chasers, tamper detection, batch import, shadow mode

---

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| LLM latency / timeout / rate limit in live demo | Parallel per-doc extraction; timeout + 1 retry; cache by file hash with visible "cached" badge; spend headroom on the key |
| Non-deterministic extraction flips an outcome | Temperature 0, strict schema, golden tests run ~10× before the interview |
| Host cold start / ephemeral disk wipes SQLite | Always-on tier + persistent volume; re-seed reference data on boot; warm the app before the call |
| Name normalization surprise | Unit test every demo name pair; few, explicit rules |
| Stages too fast to see on cache hits | Show real per-stage timestamps; no fake backend delays |
| Public URL abuse / API cost | Passcode, upload limits (PDF/PNG/JPG, <10 MB), basic rate limit |
| Network / host failure on interview day | Local instance as hot backup; recorded video |
| Scope creep | MUST list frozen; nothing new after day 5 |

---

## 11. Build order

| Phase | When | Deliverable |
|---|---|---|
| 0 Paper design | ½ day | These docs; reference-data plan; demo case specs |
| 1 Decision core | Day 1–2 | Models, validators, normalization, cross-checks, mock adapters, risk checks, decision engine — fed by JSON with pre-filled "extracted" values. **Golden tests pass for H1, E1–E4.** Hello-world deployed. |
| 2 Documents + AI | Day 2–3 | Sample PDF generator (incl. scan); classification + extraction + grounding + cache; extraction replaces hand-written JSON; golden tests still pass |
| 3 Orchestration + API | Day 3–4 | Background pipeline, stage events, check-result persistence, endpoints |
| 4 Frontend | Day 4–5 | Live run + case result first, then submission, dashboard, review queue, audit |
| 5 Comms + HITL | Day 5–6 | Vendor messages + outbox, reviewer actions, resubmission loop (SHOULD), final deploy |
| 6 Hardening + demo | Day 6–7 | Repeated golden runs, failure drill (revoke API key → fails closed to review), README, rehearsal, 5-min video (H1 → E3 + resubmit → E2 → E4) |
