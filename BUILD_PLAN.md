# Build Plan — Phases 2–6 in detail

Phase 1 (decision core) is done — see [ARCHITECTURE.md](ARCHITECTURE.md), [RULES.md](RULES.md), and the Phase 1 walkthrough in chat. This document is the detailed plan for everything that remains: what each piece is, how it works internally, why it is built that way, what can go wrong, how it shows up in the demo, and what you need to be able to explain.

Decisions you may be asked about are marked **INTERVIEW DECISION**. Open choices that need your input are marked **YOUR CALL**.

---

## How the pieces fit after all phases

```
Browser (React)
  │  New vendor form + 3 PDF uploads
  ▼
FastAPI  POST /api/cases ──► saves files, creates Case + Submission + Run ──► returns run_id immediately
  │                                   │
  │                                   ▼ background thread
  │                            Pipeline runner
  │                              stage 0  intake
  │                              stage 1  completeness            (Phase 1 code)
  │                              stage 2  read documents          (Phase 2: OpenAI call per doc)
  │                              stage 3  extraction checks       (Phase 1 code + grounding)
  │                              stage 4–7 validation … risk      (Phase 1 code)
  │                              stage 8  decision                (Phase 1 engine)
  │                              stage 9  communication           (Phase 5: message + outbox)
  │                              stage 10 audit                   (written throughout)
  │                                   │ each stage writes a stage_event row to SQLite
  ▼                                   ▼
Browser polls GET /api/runs/{id} every second ──► live stepper fills in stage by stage
```

The one rule that never changes: **OpenAI fills `DocumentInput.fields`; deterministic code does everything after that.**

---

## Phase 2 — Documents and AI extraction

Goal: real PDFs go in; OpenAI reads them into exactly the `DocumentInput` shape Phase 1 already consumes; the golden cases still produce the same outcomes.

### Step 2a — Generate realistic sample documents

**What.** A script that renders, for every demo case, the three documents a vendor would upload:

| Document | Contents (modelled on the real thing) |
|---|---|
| GST registration certificate | "Form GST REG-06 — Registration Certificate" layout: Registration Number (GSTIN), Legal Name, Trade Name, Constitution of Business, Address of Principal Place of Business, Date of Liability, Type of Registration |
| PAN card | Card-sized layout: Name, Permanent Account Number, date of incorporation |
| Cancelled cheque | Bank name, branch, IFSC, account number, "For <ACCOUNT HOLDER>" / Authorised Signatory, diagonal "CANCELLED" |
| Invoice (E3 only) | A plausible tax invoice — the wrong document in the bank-proof slot |

Plus one **image-only "scan"**: a document rendered, rasterized to an image, slightly rotated with light noise, and re-wrapped as a PDF with **no text layer**. This proves the system reads scans, not just digital PDFs.

**How.**
- `reportlab` draws the PDFs (pure Python, no system dependencies).
- `PyMuPDF` rasterizes the page for the scan; `Pillow` adds rotation/noise. (Avoids needing poppler/ghostscript on the server.)
- The values come from the same `generate_data.py` definitions, so PDFs and expected data can never drift apart.
- Every document carries a visible **"SPECIMEN — FICTITIOUS DATA"** watermark and no government emblems or bank logos.

**INTERVIEW DECISION — specimen watermark.** These look like government and bank documents. Watermarking them and using fictitious entities makes it unambiguous they are test fixtures, not forgeries. It does not affect extraction.

**INTERVIEW DECISION — the hand-built JSON becomes ground truth.** Phase 1's sample JSON `documents` blocks are exactly what a perfect extractor should return. In Phase 2 they become **labels**: we can measure field-level extraction accuracy (did OpenAI read the GSTIN exactly right?) instead of eyeballing it. Very few candidates will be able to say "I measured my extraction accuracy against labelled data."

**YOUR CALL — which document is the scan.** Recommendation: **H1's PAN card**. It has only two key fields, large clear text, and it shows the happy path handles a scan. Risk: if the scan is misread on the happy path, H1 fails live. Mitigation: render at high resolution with mild noise, and run H1 10× in Phase 6. Alternative: put the scan on E2's cheque (lower stakes, since E2 is already a review case) — safer, but less impressive.

**Files.** `backend/scripts/render_documents.py` (new), `backend/data/samples/<ID>/*.pdf` (generated), `requirements-dev.txt` (+ reportlab, pymupdf, pillow).

**Run / test.** `python -m scripts.render_documents` → open the PDFs and look at them. A test asserts every sample has its 3 PDFs and that the scan has no text layer.

**Understand before moving on.** Why a text-layer PDF and an image-only PDF are different problems; why the ground truth matters.

---

### Step 2b — OpenAI extraction

**What.** One function: `read_document(file_bytes, mime) -> RawExtraction`, which sends one document to OpenAI and gets back strictly structured JSON.

**How it works.**
1. **Input.** The file is sent directly to a vision-capable OpenAI model (PDF as a file input, PNG/JPG as an image input). For PDFs, the API gives the model both the text layer and page images, so it can read scans too. **No form values are sent** — only the document.
2. **Output schema (strict JSON schema / structured outputs).** The model must return:
   ```
   doc_type:  gst_certificate | pan_card | bank_proof | invoice | other
   readable:  true | false
   fields:    { legal_name, trade_name, gstin, constitution_of_business, principal_address, state,
                name, pan,
                account_holder_name, account_number, ifsc, bank_name,
                invoice_number, invoice_date, total_amount }
              each field = { value: string|null, quote: string|null, page: int|null }
   ```
   Strict mode means the API guarantees the response matches the schema — no "the model returned prose instead of JSON" failures.
3. **Prompt rules.** Extract only what is printed; never infer, complete, or correct values; return `null` when a field is not on the document; `quote` must be copied verbatim from the document; set `readable: false` if the document is too blurry or cut off to read reliably.
4. **Mapping.** Code converts `RawExtraction` into `DocumentInput`: the upload slot comes from where the user uploaded it, `classified_type` from `doc_type`, and only the fields relevant to that type are kept.
5. **Settings.** Model name from `OPENAI_MODEL` (env), API key from `OPENAI_API_KEY`. Temperature 0 where the chosen model supports it. 30-second timeout, one retry on transient errors (timeouts, 429, 5xx). The three documents are read **in parallel**, so a case takes roughly as long as its slowest document.
6. **Failure.** Any failure after the retry sets `extraction_error` on that document → Phase 1 turns it into an `error` → SYS-01 → internal review. Never approval.

**INTERVIEW DECISION — one call per document does classification and extraction together.** Alternative: a classification call, then a type-specific extraction call. One call halves latency and failure points in a live demo; the schema is a superset and code discards irrelevant fields. Trade-off: the prompt is slightly more general.

**INTERVIEW DECISION — blind extraction.** If the model saw the form, it would tend to "find" the expected value (anchoring), hiding exactly the mismatches we are trying to catch (E1, E2). Comparison is done by code.

**INTERVIEW DECISION — no confidence scores.** We do not ask the model "how sure are you?" — self-reported confidence is not calibrated. We use verbatim quotes + grounding (2c) + ground-truth accuracy measurement instead.

**INTERVIEW DECISION — model choice.** Use a capable vision model for extraction; the model is a config value, not code. Pick the specific model at implementation time from what the account has access to, then measure accuracy on the samples. If a cheaper model hits the same accuracy, use it.

**Files.** `backend/app/llm/client.py` (OpenAI wrapper, timeout/retry), `backend/app/llm/extract.py` (prompt, schema, mapping), `backend/app/llm/prompts.py` (versioned prompt text, `PROMPT_VERSION = "extract-v1"`), `requirements.txt` (+ openai).

**Run / test.**
- Unit tests use a **fake client** returning canned JSON — they test mapping, field filtering, and failure handling without network or cost.
- `python -m scripts.try_extract data/samples/H1/gst_certificate.pdf` prints what OpenAI read (manual check).

**Understand before moving on.** What strict structured output guarantees (shape) and what it does not (correctness of values) — that gap is why 2c exists.

---

### Step 2c — Grounding check and extraction cache

**Grounding — what.** After extraction, for PDFs with a text layer, code checks that each extracted value actually appears in the document's text.

**How.**
- `pypdf` extracts the text layer.
- Both sides are normalized (uppercase, whitespace collapsed; for IDs and account numbers, all spaces removed) and compared as a substring.
- Each field gets `grounded = "text"` (found), `"unverified"` (text layer exists but value not found), or `"image"` (no text layer — can't check).

**INTERVIEW DECISION / YOUR CALL — what happens when a key field is unverified.** Options:
- (a) Show it to the reviewer only (INFO) — no effect on the decision.
- (b) New rule **DOC-03 "Extracted value not found in document text" → REVIEW** for key fields (GSTIN, PAN, legal name, account number, IFSC).
- (c) Treat as DOC-02 and ask the vendor to re-upload.

Recommendation: **(b)**. An unverified key field in a digital PDF means the model produced something not printed on the page — a hallucination or a misread. That should never silently drive a decision, and asking the vendor (c) would be asking them to fix our problem. Trade-off: a formatting quirk could cause a false review; normalization minimizes that, and the golden runs will show if it happens.

**Cache — what.** Extraction results are stored under a key of `sha256(file bytes) + PROMPT_VERSION + model`. Same file again → cached result, no API call.

**Why.**
- Demo reliability: sample documents can be replayed instantly if the API is slow or down.
- Cost and speed during development.
- Correctness: changing the prompt or model changes the key, so stale results are never reused.

**How it shows in the product.** A "cached" badge on the document in the run view. For the live demo, run **uncached** by default (proves it's real); if the API misbehaves, flip `EXTRACTION_CACHE=prefer` and re-run.

**INTERVIEW DECISION — cache is by content hash, not filename.** Renaming a file doesn't fool it; changing one byte of the file does invalidate it.

**Files.** `backend/app/llm/grounding.py`, `backend/app/llm/cache.py` (JSON files on disk in Phase 2; moves to a SQLite table in Phase 3), `catalog.py` + `checks.py` (DOC-03 if chosen), `RULES.md`.

**Run / test.** Unit tests: grounded value, unverified value, image-only doc, cache hit/miss, cache invalidation on prompt-version change.

---

### Step 2d — Wire it together and measure

**What.**
- `extract_case(submission, files) -> CaseInput`: reads all uploaded documents (parallel, cached, grounded) and builds the `CaseInput` Phase 1 already evaluates.
- A temporary endpoint `POST /api/evaluate-upload` (multipart form + files) so the whole flow can be exercised before Phase 3 exists.
- An **integration test** (skipped unless `OPENAI_API_KEY` is set) that runs every sample's real PDFs through real extraction and asserts:
  1. the golden outcome (status, sub-state, failing rules) is unchanged;
  2. field-level accuracy against ground truth (report per field; key fields must be 100%).

**Run / test.** `pytest -m integration` with the key set. Expect ~20 OpenAI calls per full run (7 cases × 3 docs).

**Understand before moving on.** Phase 2 is done when the integration test passes repeatedly — that is the evidence the AI layer doesn't change decisions on known inputs.

---

## Phase 3 — Orchestration, persistence, API

Goal: a submission becomes a stored case with a run that executes in the background and reports progress stage by stage.

### 3a — Database

**What.** SQLite via SQLAlchemy. Tables (from ARCHITECTURE §7): `cases`, `submissions`, `documents`, `extractions`, `runs`, `stage_events`, `check_results`, `decisions`, `communications`, `review_actions`, `audit_events`.

**Key relationships.**
- A **case** is one vendor onboarding attempt. It has a current status.
- A case has one or more **submissions** (versions). Resubmission adds version 2, 3, ….
- Each submission has one **run** (a pipeline execution) with its **stage_events**, **check_results**, and **decision**.
- Uploaded files are stored on disk under `data/uploads/<case_id>/<sha256>.<ext>`; the `documents` table stores the path and hash.

**INTERVIEW DECISION — SQLite.** One file, zero setup, plenty for tens of cases. Enable WAL mode so the UI can read while a run writes. Alternative: Postgres — needed for multiple app instances or real concurrency, not for this. Using SQLAlchemy keeps the switch to Postgres a connection-string change.

**INTERVIEW DECISION — audit is append-only.** `audit_events` rows are only ever inserted, never updated or deleted, through one helper `audit(case_id, actor, event, data)`. Every stage, decision, message, and reviewer action writes one. That is what makes "who decided what, when, and on what evidence" answerable.

### 3b — Pipeline runner

**What.** `run_pipeline(run_id)` executes stages 0–10 in a background thread; each stage writes a `stage_event` (`pending → running → done | failed`, start/end time, one-line human summary).

**How stages map to the UI** (the live stepper shows these 10 rows; a separate "Recorded" row was dropped during implementation because audit events are written throughout, not as a final step):

| # | UI label | What runs |
|---|---|---|
| 0 | Submission received | Files saved, hashes computed |
| 1 | Checking completeness | COMP-01, COMP-02 |
| 2 | Reading documents | OpenAI call per document (parallel) |
| 3 | Checking what we read | DOC-01, DOC-02, grounding / DOC-03 |
| 4 | Validating details | TAX-01, BANK-01 |
| 5 | Cross-checking | TAX-02…05, ID-01, BANK-02 |
| 6 | Verifying with GST registry and bank | TAX-06, BANK-04, BANK-03 |
| 7 | Risk screening | RISK-01, RISK-02, DUP-01, DUP-02 |
| 8 | Deciding | Decision engine |
| 9 | Notifying | Vendor message → outbox; review queue |

Note: classification and extraction happen in **one** OpenAI call (2b), so stage 2 does the AI work and stage 3 shows the deterministic checks on what was read.

**INTERVIEW DECISION — background thread, not a job queue.** FastAPI returns the run id immediately; a thread runs the pipeline; state lives in SQLite. Alternative: Celery + Redis or a workflow engine — real retries and distribution, but two more services to deploy and debug. At demo scale a thread is enough, and every stage is persisted, so nothing is invisible.

**INTERVIEW DECISION — interrupted runs fail closed.** If the server restarts mid-run, that run would be stuck "running" forever. On startup, any run still marked running is set to `interrupted` and its case goes to internal review with SYS-01.

**INTERVIEW DECISION — polling, not WebSockets.** The browser asks `GET /api/runs/{id}` every second while a run is active. Alternative: Server-Sent Events / WebSockets — lower latency, but more fragile through hosting proxies. A 10-stage run that takes ~10–20 seconds doesn't need sub-second updates.

### 3c — API

```
GET  /api/samples                 demo presets (form values + links to sample PDFs)
POST /api/cases                   multipart: form JSON + 3 files → {case_id, run_id}
GET  /api/runs/{id}               run status + stage events + (when done) decision
GET  /api/cases                   dashboard list; filters: status, sub_state, rule
GET  /api/cases/{id}              case detail: latest decision, check results, evidence, messages, versions
GET  /api/cases/{id}/documents/{doc_id}   the file itself (for the document viewer)
POST /api/cases/{id}/resubmit     new submission version (changed files only) → new run
GET  /api/review-queue            internal-review cases, oldest first
POST /api/cases/{id}/review       {action, reason, message?}
GET  /api/cases/{id}/audit        timeline
GET  /api/outbox                  simulated sent messages
GET  /api/metrics                 dashboard tiles
```

Upload rules: PDF/PNG/JPG only, ≤ 10 MB per file, checked server-side (file type from content, not just extension).

### 3d — Seed data on startup

**What.** On boot, if the database is empty: load reference data and create cases for the samples so the dashboard is never empty.

**How.** Seeded cases use the stored ground-truth extraction (no OpenAI call on every boot) and are labelled **"seeded sample"** in the UI and audit trail.

**INTERVIEW DECISION.** Honest labelling — seeded history is clearly marked, and live runs are visibly different. It also protects against free-tier disk resets (see deployment).

**Run / test.** API tests for each endpoint; a test that a submitted case reaches a decision; a test that a run interrupted mid-way ends in review.

---

## Phase 4 — Frontend

Goal: a product a procurement user would recognise, centered on the live run view (graded explicitly).

### Stack
React + Vite + TypeScript + Tailwind + shadcn/ui; React Router for pages; TanStack Query for data fetching and polling (`refetchInterval: 1000` while running, off when done). The production build is served by FastAPI, so there is **one URL and no CORS**. The Dockerfile becomes multi-stage: Node builds the frontend, the Python image serves it.

**INTERVIEW DECISION — component library.** shadcn/ui gives accessible, consistent components (tables, badges, dialogs) so time goes into the workflow, not CSS.

### Screens

**1. New vendor** (`/new`)
- Sections: Company (legal name, trade name, business type, address) · Tax (GSTIN, PAN) · Bank (holder, account, IFSC, bank name) · Contact · Documents (three labelled upload slots).
- **Load sample** dropdown at the top: fills the form *and attaches the sample PDFs*, so a demo case is one click + Submit.
- Light client-side hints (e.g. "GSTIN is 15 characters"), but **no blocking client-side validation** — the server is the authority, and a bad submission must be able to reach the pipeline so the system can respond to it.
- Submit → redirect to the live run.

**2. Live run** (`/runs/:id`) — the centerpiece
- Vertical stepper, 10 rows. Each row: icon (waiting / spinner / ✓ / ⚠ / ✗), label, duration, one-line result ("Read 3 documents · 1 scanned", "GSTIN belongs to a different PAN than the one submitted").
- Rows with findings expand to show evidence: form value vs document value, the quote from the document, the match tier.
- When stage 8 completes, a decision banner appears: green Approved / amber Awaiting vendor / orange Internal review / red Rejected, with the summary and a link to the case.

**3. Case** (`/cases/:id`)
- Header: vendor name, status banner, summary, submitted/decided times, version selector if resubmitted.
- **What we checked** — grouped Documents · Tax · Identity · Bank · Risk; each rule shows ✓ / ⚠ / ✗ / "not checked (because …)".
- **Evidence panel** — click a finding to see the document page beside the form value.
- Tabs: **Vendor message** (exactly what the vendor was sent) · **Audit**.
- If awaiting vendor: **Resubmit on vendor's behalf** (opens the form pre-filled; replace only the files that changed).

**4. Dashboard** (`/`)
- Tiles: Total · Approved · Awaiting vendor · In review · Rejected · Straight-through rate (approved on first run with no human touch).
- Table: vendor, status badge, reason chips (business labels, not rule IDs), submitted, age, version. Filters by status and reason.

**5. Review queue** (`/review`)
- Internal-review cases, oldest first, with reason chips and age.
- Opening one shows the Case page plus an action panel (Phase 5).

**6. Audit** — per-case timeline (tab on the Case page): time, actor (System / reviewer name), event, details.

### Language rules
Business wording everywhere ("Bank account holder doesn't match company name"). Rule IDs appear only in a small grey tag and in a "Technical details" toggle. Masked account numbers (••••8912) except in the evidence panel.

### Access passcode
The public URL triggers paid OpenAI calls, so mutating endpoints require a shared passcode (`APP_PASSCODE` env var); the frontend asks for it once and stores it in the browser session.

**Run / test.** `npm run dev` with the API proxied; click through every sample. A small set of Playwright-style smoke checks is optional; manual click-through of every demo case is mandatory.

---

## Phase 5 — Vendor communication and human review

### 5a — Vendor messages

**What.** At stage 9, generate the message the vendor receives and put it in the outbox.

**How.**
| Status | Message |
|---|---|
| Approved | Short confirmation |
| Awaiting vendor | Polite intro (LLM) + **checklist rendered by code from `vendor_actions`** + closing |
| Internal review | Neutral "your application is under review" + any vendor-fixable checklist items |
| Rejected | Generic "unable to proceed", contact point — never the reason or the list |

- The LLM only sees vendor-safe information: vendor name, status, and the `vendor_actions` text.
- A **forbidden-term filter** rejects any draft containing internal signals (debarred, sanction, blocklist, fraud, the penny-drop holder name, etc.). Rejected draft → fixed template.
- Any LLM failure → fixed template. The message never blocks the pipeline.

**INTERVIEW DECISION — the checklist is code, the tone is AI.** If the LLM wrote the whole email, it could drop or reword a required item. Rendering the checklist from structured data guarantees completeness; the LLM only makes it read well. Defense in depth: the model never receives the fraud signal, and the filter catches anything that slips through.

**INTERVIEW DECISION — simulated outbox.** No real email in the demo: zero deliverability risk, and the interviewer sees the exact message in the UI. Real sending is a provider swap.

### 5b — Reviewer actions

| Action | Effect | Requires |
|---|---|---|
| Approve | Case → Approved; the rules that fired are recorded as **overridden** | Reason |
| Request info | Reviewer writes/edits a vendor message → outbox; case → Awaiting vendor | Message |
| Reject | Case → Rejected; generic vendor message | Reason |

- REJECT outcomes (RISK-01) cannot be approved in the MVP.
- Every action writes `review_actions` + `audit_events` with reviewer name, time, reason, previous and new status.

**INTERVIEW DECISION — mandatory reason.** An override without a reason is unauditable. This is the single most important control in human-in-the-loop design.

### 5c — Resubmission

**What.** From a pending case, upload corrected documents and/or fields → new submission version → new run on the same case.

**Demo.** E3 → Awaiting vendor with two items → resubmit with the Tamil Nadu GST certificate + cancelled cheque (E3R files) → Approved. The case page shows version 1 and version 2 side by side.

### 5d — AI explanations for reviewers (SHOULD)

- Plain-English case summary written from the findings (labelled "AI summary"; the deterministic summary stays alongside it).
- On name mismatches, a short hypothesis ("bank holder appears to be an individual's name, not a company") labelled "AI note".
- Neither can change a status.

---

## Phase 6 — Hardening, deployment, and demo

### 6a — Reliability
- Run the integration suite **10 times**; any variance in a golden outcome is a bug to fix before the demo.
- Failure drills, each must end in internal review (never approval) and look sensible in the UI:
  - invalid OpenAI key · network timeout · corrupt PDF · 30 MB file · `.docx` upload · server restart mid-run.
- Check spend limit / balance on the OpenAI account.

### 6b — Deployment (final)
See the deployment comparison in chat; the final setup is decided before Day 7. Checklist: production env vars set (`OPENAI_API_KEY`, `OPENAI_MODEL`, `APP_PASSCODE`), health check green, seeded dashboard visible, one live run end-to-end on the deployed URL.

### 6c — Demo script (rehearsed)
| Order | Case | Point to make |
|---|---|---|
| 1 | H1 | Full pipeline live; documents read (incl. a scan); bank name passes by normalization, not fuzzy luck |
| 2 | E3 → resubmit | Vendor-fixable issues → specific checklist → resubmission → approved |
| 3 | E2 | Fraud pattern → review; show the vendor message deliberately says nothing |
| 4 | E4 | Hard rule → reject; generic message |
| 5 | Review queue | Reviewer approves E5 with a reason → audit trail |
| (spare) | E1 | If asked about "subtle inconsistencies" |

### 6d — Submission package
- README: what it does, architecture diagram, how to run, assumptions, limitations, what I'd build next.
- 5-minute video following the demo script.

### 6e — Interview-day checklist
Open the deployed app 5–10 minutes early · sample PDFs on the desktop · local copy running as backup · OpenAI balance checked · cache toggle known · browser zoom set for screen sharing.

---

## Schedule

| Day | Work |
|---|---|
| 2 | 2a documents, 2b extraction |
| 3 | 2c grounding + cache, 2d integration; 3a database |
| 4 | 3b runner, 3c API, 3d seeding; deploy |
| 5 | Phase 4 frontend: live run + case first, then form, dashboard, queue |
| 6 | Phase 5: messages, reviewer actions, resubmission; final deploy |
| 7 | Phase 6: drills, rehearsal, README, video |

Rule: nothing new after Day 5 except fixes.

---

## Open decisions (YOUR CALL)

| # | Decision | Recommendation |
|---|---|---|
| 1 | Which document is the scanned one | H1 PAN card |
| 2 | Unverified key field after grounding | New rule DOC-03 → REVIEW |
| 3 | Live demo uncached or cached | Uncached by default; cache as fallback switch |
| 4 | Final hosting for submission week | Always-on paid tier with a disk (see deployment comparison) |
