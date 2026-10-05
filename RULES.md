# Vendor Onboarding — Rules

Rule catalog version: **v1**. Scope: **Indian vendors only** (see [ASSUMPTIONS.md](ASSUMPTIONS.md) A2). Every rule is a deterministic Python function emitting a `CheckResult` (see [ARCHITECTURE.md](ARCHITECTURE.md) §4). The LLM never emits a rule outcome.

Outcome classes: `VENDOR_ACTION` (vendor can fix) · `REVIEW` (human judgment) · `REJECT` (hard stop) · `INFO` (shown, non-blocking).
Precedence: `REJECT > REVIEW > VENDOR_ACTION > APPROVE`. Any `error` status → `SYS-01` → `REVIEW`.

---

## 1. Submission requirements

### Form fields

| Field | Required | Notes |
|---|---|---|
| `legal_name` | ✓ | |
| `trade_name` | opt | As registered on GST |
| `entity_type` | ✓ | `company`, `llp`, `partnership`, `proprietorship` |
| `address` (line1, city, state, pin_code) | ✓ | State from fixed list; PIN 6 digits |
| `contact_name`, `contact_email` | ✓ | |
| `gstin` | ✓ | |
| `pan` | ✓ | |
| `bank.account_holder_name` | ✓ | |
| `bank.account_number` | ✓ | |
| `bank.ifsc` | ✓ | |
| `bank.bank_name` | ✓ | |

### Required documents

| Slot | Key extracted fields |
|---|---|
| `gst_certificate` (Form GST REG-06) | legal_name, trade_name, gstin, constitution_of_business, principal_address, state |
| `pan_card` | name, pan |
| `bank_proof` (cancelled cheque or bank letter) | account_holder_name, account_number, ifsc, bank_name |

Every extracted field carries `{value, quote, page, grounded: true|false|image}`.

None of these documents carries an expiry date, so there is no expiry rule in v1.

---

## 2. Name matching (used by ID-01 and BANK-03)

**Anchor:** the **Legal Name on the GST certificate**. The form is a claim; the bank must match the anchor.

**Normalization (applied to both sides, in order):**
1. Uppercase; Unicode → ASCII; strip punctuation (`. , ' " ( ) -`); collapse whitespace
2. Strip leading `M/S`, `MESSRS`, `THE`
3. `&` → `AND`
4. Canonicalize (not remove) entity suffix:
   - `PRIVATE LIMITED`, `PVT LIMITED`, `PRIVATE LTD`, `PVT LTD`, `P LTD` → `PVT LTD`
   - `LIMITED` → `LTD`
   - `LIMITED LIABILITY PARTNERSHIP` → `LLP`
5. **Never** drop meaningful tokens (`INDIA`, `HOLDINGS`, `AND SONS`, …) or the entity type.

**Tiers:**

| Tier | Condition | Result |
|---|---|---|
| `EXACT` | raw strings equal (case-insensitive) | pass |
| `NORMALIZED` | normalized strings equal | pass |
| `TRADE_NAME` | candidate equals (normalized) the **Trade Name printed on the GST certificate** | pass + INFO note "matched via registered trade name" |
| `MISMATCH` | otherwise | fail → REVIEW, with deterministic token diff + LLM "AI note" hypothesis |

**Why no fuzzy score:** high-similarity pairs are often different legal entities (`Lumen Analytics Pvt Ltd` vs `Lumen Analytics India Pvt Ltd`; `… Pvt Ltd` vs `… LLP`; `ABC Traders` vs `ABD Traders`). In payments a near-match is a risk signal, not a rounding error.

**Proprietorships:** GST Legal Name is the proprietor's personal name; the business name is the Trade Name. A form or bank account in the business name passes via the `TRADE_NAME` tier — the link is attested by the government document, not by similarity.

**Accepted costs:** bank-truncated holder names and genuine form typos go to review.

---

## 3. Validators (format / checksum)

| ID type | Rule |
|---|---|
| **PAN** | `^[A-Z]{5}[0-9]{4}[A-Z]$`; 4th char = holder type (C company, P individual, F firm/LLP, H HUF, A AOP, T trust, B BOI, L local authority, J artificial juridical person, G government) |
| **GSTIN** | 15 chars: `SS` state code + 10-char PAN + entity number `[1-9A-Z]` + `Z` + checksum. Checksum: map `0-9A-Z` → 0–35; for i in 0..13, factor = 1 if i even else 2; p = value×factor; sum += p // 36 + p % 36; check = (36 − sum % 36) % 36 → char |
| **GST state code** | Must exist in `data/reference/gst_state_codes.json` |
| **IFSC** | `^[A-Z]{4}0[A-Z0-9]{6}$` |
| **Account number** | digits, 9–18 length |
| **PIN code** | 6 digits, first digit 1–9 |

**Entity type → expected PAN 4th character** (used by TAX-05): `company → C` · `llp → F` · `partnership → F` · `proprietorship → P`.

GST state codes used in samples: `07` Delhi · `27` Maharashtra · `29` Karnataka · `33` Tamil Nadu.

---

## 4. Rule catalog

| ID | Stage | Check | Fail outcome | Vendor told? |
|---|---|---|---|---|
| **COMP-01** | completeness | Required form field missing | VENDOR_ACTION | Yes — which field |
| **COMP-02** | completeness | Required document slot empty | VENDOR_ACTION | Yes — which document |
| **FILE-01** | doc processing | File can't be used: empty, > 10 MB, not PDF/PNG/JPG (by content), damaged, password-protected, > 10 pages. Checked before any AI call | VENDOR_ACTION | Yes — the specific fix (e.g. "upload a copy without a password") |
| **DOC-01** | doc processing | Classified type ≠ slot's expected type | VENDOR_ACTION | Yes — "file in X slot appears to be Y" |
| **DOC-02** | extraction | Document unreadable, or a key field not found | VENDOR_ACTION | Yes — re-upload clearer copy |
| **DOC-03** | extraction | Document couldn't be read reliably: a key value is not in the PDF's text layer (grounding), or an extracted GSTIN / PAN / IFSC / account number fails its format rule (catches misreads on scans too) — **or the AI's "wrong document" verdict can't be trusted** (see below) | REVIEW | Neutral — our misread, not the vendor's problem |
| **TAX-01** | validation | GSTIN or PAN on the form fails format/checksum | VENDOR_ACTION | Yes — likely typo |
| **TAX-02** | cross-check | GSTIN on certificate ≠ form, or PAN on PAN card ≠ form (all valid) | REVIEW | Neutral |
| **TAX-03** | cross-check | PAN embedded in GSTIN (chars 3–12) ≠ submitted PAN / PAN card | REVIEW | Neutral |
| **TAX-04** | cross-check | GSTIN state code ≠ address state | VENDOR_ACTION | Yes — provide GSTIN for the registration in that state |
| **TAX-05** | cross-check | PAN holder-type char inconsistent with declared entity type | REVIEW | Neutral |
| **TAX-06** | external | GST registry: not found / inactive / cancelled | REVIEW | Neutral |
| **ID-01** | cross-check | Form legal name, PAN card name, or bank-proof holder name doesn't match anchor (§2) | REVIEW | Neutral |
| **BANK-01** | validation | IFSC / account number format invalid | VENDOR_ACTION | Yes |
| **BANK-02** | cross-check | Bank proof account number / IFSC ≠ form | REVIEW | Neutral |
| **BANK-03** | external | Penny-drop account holder name doesn't match anchor (§2) | REVIEW | **No — neutral only** |
| **BANK-04** | external | Penny drop: account not found / closed / invalid | VENDOR_ACTION | Yes — confirm bank details |
| **RISK-01** | risk | PAN (form or GSTIN-embedded) exactly matches debarred list | **REJECT** | Generic — list never named |
| **RISK-02** | risk | Normalized name matches debarred list, no PAN match | REVIEW | Neutral |
| **DUP-01** | risk | PAN or GSTIN already in vendor master | REVIEW | Neutral |
| **DUP-02** | risk | Bank account (number + IFSC) already in vendor master under a different vendor | REVIEW | Neutral |
| **PRIOR-01** | risk | The legal entity has an earlier **rejected** application (any case matched by PAN/GSTIN) | REVIEW | Neutral — internal history isn't disclosed |
| **SYS-01** | any | A required check errored (LLM timeout, adapter failure) | REVIEW | Neutral |

### Who owns a "couldn't read it" problem

| Situation | Rule | Outcome | Reasoning |
|---|---|---|---|
| File itself unusable (type, damaged, password, size) | FILE-01 | Awaiting vendor | Vendor can fix it by uploading a different file |
| File opens, content illegible (model: `readable: false`) | DOC-02 | Awaiting vendor | Vendor can fix it with a clearer copy |
| File fine, but what we read is ungrounded or malformed | DOC-03 | Internal review | Our misread — the vendor's document may be perfect; a reviewer can still request a clearer copy |
| Model / provider failure | SYS-01 | Internal review | Our failure — re-uploading the same file would fail the same way |

Test: *can the vendor fix this by doing something different?* If yes → vendor; if no → us.

**Bad document or AI mistake?** When the AI says a file is the wrong type, the verdict is checked before the vendor is
asked to replace it:

| Signal | Outcome |
|---|---|
| The text the model quoted as evidence of the type (e.g. "TAX INVOICE") **is printed on the page** | Genuinely the wrong document → DOC-01, vendor |
| The quoted evidence **isn't on the page**, or no evidence was given for a readable PDF | Identification unreliable → DOC-03, a person checks the document |
| The vendor **re-sent the identical file** (same content hash) we flagged as the wrong document on an earlier version | → DOC-03, a person — never asked twice (the model would read it the same way) |
| Scanned image (no text layer to check) | DOC-01, vendor; the re-send rule is the backstop |

Replaying the same version is not a re-send. A file carried over unchanged is not a re-send.

### Dependencies (→ `blocked` status, not `error`)

| Check | Needs | Blocked by |
|---|---|---|
| DOC-01 (classification) | File usable | COMP-02, FILE-01 |
| Extraction for a slot | Document present + correct type | COMP-02, FILE-01, DOC-01 |
| Any cross-check using a document | Document read reliably | DOC-03 (in addition to COMP-02, FILE-01, DOC-01, DOC-02) |
| TAX-02 | Form ID valid + GST certificate / PAN card extracted | TAX-01, COMP-02, DOC-01, DOC-02 |
| ID-01 | GST certificate extracted (anchor) + the compared name present | COMP-01, COMP-02, DOC-01, DOC-02 |
| BANK-02 | Bank proof extracted | COMP-02, DOC-01, DOC-02 |
| TAX-03, TAX-04, TAX-05, TAX-06 | GSTIN / PAN pass TAX-01 | TAX-01 |
| BANK-04 | Bank details pass BANK-01 | BANK-01 |
| BANK-03 | BANK-04 verified + GST certificate extracted (anchor) | BANK-01, BANK-04, COMP-02, DOC-01, DOC-02 |
| RISK-01 | At least one valid PAN (form, GSTIN-embedded, or PAN card) | COMP-01, TAX-01 |

A blocked check prevents approval but does not on its own escalate to review — the blocking rule already carries the outcome.

Doc-side IDs are not format-validated separately: a malformed GSTIN/PAN on a document surfaces as a TAX-02 mismatch against the (valid) form value, which a human should look at.

### Required checks for approval

COMP-01, COMP-02, FILE-01, DOC-01, DOC-02, DOC-03, PRIOR-01, TAX-01, TAX-02, TAX-03, TAX-04, TAX-05, TAX-06, ID-01, BANK-01, BANK-02, BANK-03, BANK-04, RISK-01, RISK-02, DUP-01, DUP-02.

Approved ⇔ every required check has status `pass`.

---

## 4b. Intake: one case per legal entity

Not a rule in the catalog — it runs before a case exists. `POST /api/cases` first looks for an existing case
(any status) for the same legal entity: same PAN, same GSTIN, or a GSTIN whose embedded PAN matches. If one
exists, nothing is created (no case, no stored files, no model call); the API returns 409 `duplicate_case`
with the matching case(s), and the attempt is recorded on each matching case's audit trail as
`duplicate_submission.blocked`.

| Existing case | Offered |
|---|---|
| Pending, no run in progress | Open · Resubmit (new version, carrying over what was entered) · Replay (new run) |
| Approved (a live vendor) | Open · Replay |
| Rejected, latest in its chain, entity has no open case | Open · **Reapply** (new linked case) · Replay |
| Rejected but already followed by a reapplication | Open · Replay |
| Run in progress | Open |

Three distinct actions, never a duplicate case:

- **Replay** = rerun the same data → new run, same case, same version.
- **Resubmit** = correct the same application → new version, same case (pending cases only).
- **Reapply** = a genuinely new application after rejection → new case linked to the rejected one (`previous_case_id`). The rejected case stays final and unchanged. The new case always fails PRIOR-01 → internal review, so it can't be auto-approved; hard rules still apply (a still-debarred PAN is rejected again by RISK-01, which outranks review). The reapplication must identify the same entity (PAN/GSTIN), otherwise it's a new vendor (422).

There is deliberately no "create anyway". Without a PAN or GSTIN there is nothing to match on; the case is created and COMP-01 asks for them.

## 4c. Human review (internal-review cases)

| Action | Case becomes | Required | Notes |
|---|---|---|---|
| Approve | Approved | reviewer, reason | The findings on the case are recorded as overridden |
| Request info | Awaiting vendor | reviewer, internal reason, message to the vendor | Leaves the review queue; the vendor resubmits |
| Reject | Rejected | reviewer, reason | Findings kept as the rejection reasons; the vendor may later Reapply (PRIOR-01 applies) |

A reviewer can overrule a judgement finding but can't approve past missing evidence. **Approve is refused** when any check
on the latest run was blocked or errored (it never ran — e.g. SYS-01, or a DOC-03 misread that blocked cross-checks), or when
the vendor still owes items (an incomplete application). **Replay is blocked** once a reviewer has acted on the latest run:
it would override a human decision; new information comes in by Resubmit or Reapply.

**Request → response loop.** After Request info the case shows *"Waiting for the vendor — you asked: …"*. When a new
version arrives, every check runs again (a human decision never carries over to new evidence); if the case returns to
review, the reviewer sees what they asked for, which documents were replaced and which form fields changed, and the
queue tags the case *Vendor responded*.

## 4d. Vendor messages

| Outcome (system or reviewer) | Message kind | Checklist | Never included |
|---|---|---|---|
| Approved | approved | — | — |
| Awaiting vendor / reviewer Request info | action_needed | decision's vendor actions (+ the reviewer's message, verbatim) | internal reason |
| Internal review | under_review | vendor-fixable items only, if any | why it's in review |
| Rejected | rejected | — | reason, list names |

Subject, opening and closing may be AI-drafted from vendor-safe facts only (vendor company, contact, reference, item
count); the checklist is rendered by code. AI wording is rejected for internal vocabulary (debar, fraud, penny, risk,
mismatch, …), rule IDs, or this case's private values (bank-reported holder name, other entities' names), and the
fixed template is used — also on any AI failure. A system decision with the same outcome and items as the last
message sends nothing (a replay doesn't re-email the vendor). Every message is audited (`message.sent`).

## 5. Golden cases

All sample values are fictitious. PANs follow real structure (4th char = holder type, 5th char = first letter of the entity name). GSTIN check digits are computed by `backend/scripts/generate_data.py`; values shown as `…` are filled by the generator. Generated packets live in `backend/data/samples/`; tests in `backend/tests/test_golden.py`. Each case asserts: final status, sub-state, and the **exact set** of failing rule IDs.

### H1 — Clean vendor → **Approved**
- Lumen Analytics Private Limited · company · Bengaluru, Karnataka
- PAN `AAACL4821K`; GSTIN `29AAACL4821K1Z…` (state 29 = Karnataka; embedded PAN matches)
- GST certificate legal name "LUMEN ANALYTICS PRIVATE LIMITED"; PAN card matches; cancelled cheque matches form
- Penny drop returns holder **"LUMEN ANALYTICS PVT LTD"** → `NORMALIZED` tier pass (deliberate)
- Not in vendor master; not debarred; registry active
- **Expected:** APPROVED · failing rules: ∅

### E1 — Valid-looking GSTIN, conflicting identity → **Internal review**
- Brightpath Logistics Private Limited · Mumbai, Maharashtra
- PAN (form + PAN card) `AAECB7302M`; GSTIN (form + certificate) `27AAFCB1156Q1Z…` — format + checksum valid, state 27 matches, but embedded PAN `AAFCB1156Q` ≠ `AAECB7302M`
- Names consistent across all documents; bank verified; registry active
- **Expected:** PENDING / INTERNAL_REVIEW · failing rules: {TAX-03}
- **Defense:** a typo would fail the checksum. A valid GSTIN carrying a different PAN is a real registration of another entity — an identity question, not a fixable typo.

### E2 — Bank account belongs to an individual → **Internal review, vendor not told why**
- Northwind Supplies Private Limited · New Delhi, Delhi · PAN `AABCN6419H` · GSTIN `07AABCN6419H1Z…`
- All documents consistent; cancelled cheque printed with company name
- Penny drop returns holder **"RAKESH K SHARMA"** → `MISMATCH`
- **Expected:** PENDING / INTERNAL_REVIEW · failing rules: {BANK-03} · vendor message is neutral "under review"
- **Defense:** classic payment-diversion pattern — the cheque says company, the bank says individual. Not rejected: a legitimate explanation is possible, so a human decides.

### E3 — Wrong document + wrong-state GSTIN → **Awaiting vendor**
- Kaveri Packaging Private Limited · Chennai, Tamil Nadu (state 33) · PAN `AADCK3390P`
- GSTIN `29AADCK3390P1Z…` — valid, embedded PAN matches, registry active, but it is the **Karnataka** registration → TAX-04
- `bank_proof` slot contains an **invoice** → DOC-01 (BANK-02 blocked)
- Penny drop on form bank details passes
- **Expected:** PENDING / AWAITING_VENDOR · failing rules: {DOC-01, TAX-04} · email lists exactly two items
- **Defense:** a company holds one GSTIN per state; supplying the wrong state's registration is a common, legitimate mistake — vendor-fixable, not suspicious. The wrong-document case shows classification catching what a filename check never would.
- **Resubmission (SHOULD):** upload cancelled cheque + Tamil Nadu GST certificate (`33AADCK3390P1Z…`) → APPROVED (sample `E3R`)

### E4 — Debarred entity → **Rejected**
- Apex Industrial Supplies Private Limited · Pune, Maharashtra · PAN `AAGCA5517R` · GSTIN `27AAGCA5517R1Z…`
- Clean, consistent packet; PAN exactly matches a row in `debarred.csv`
- **Expected:** REJECTED · failing rules: {RISK-01} · generic vendor message, list not named
- **Defense:** PAN match = reject; name-only match = review (RISK-02). Matching on PAN (entity-level) catches every state GSTIN of the debarred entity.

### E5 (optional) — Existing vendor, new bank → **Internal review**
- PAN + GSTIN already in vendor master with a different bank account
- **Expected:** PENDING / INTERNAL_REVIEW · failing rules: {DUP-01} · reviewer evidence shows master bank vs submitted bank

### Failure drill (not a demo case)
- Any case run with the LLM unavailable → affected extractions `error` → SYS-01 → PENDING / INTERNAL_REVIEW. **Never approved.**
