# Live demo — script, checklist, fallbacks

After **Reset demo**, the seeded cases are always: **VO-0001** H1 (approved) · **VO-0002** E1 (in review) ·
**VO-0003** E2 (in review) · **VO-0004** E3 (awaiting vendor) · **VO-0005** E4 (rejected) · **VO-0006** E5 (in review).
H2 is not seeded; submitting it creates **VO-0007**.

## Before the interview

**The day before**
- [ ] `cd backend && .venv/bin/python -m scripts.run_golden_live --runs 10 --workers 1` → must print **ALL STABLE** (~$1–2).
- [ ] OpenAI account has credit, and a spend limit that won't cut off mid-demo.
- [ ] Render: latest commit is **Live** (Events tab); `APP_PASSCODE` and `OPENAI_API_KEY` set.
- [ ] Rehearse the script below twice, end to end, with a timer.

**30 minutes before**
- [ ] Open the Render URL (wakes the free tier — first load can take ~1 minute), enter the passcode.
- [ ] Dashboard → **Reset demo** → confirm. Check: 6 cases, review queue badge 3.
- [ ] Start the **local backup**: `cd backend && .venv/bin/uvicorn app.main:app` → http://localhost:8000 in a second tab.
- [ ] Browser zoom ~110%, notifications off, close other tabs. Have [RELIABILITY.md](RELIABILITY.md) open in a tab.

**5 minutes before:** open the Render URL again (keeps it awake) and leave it on the dashboard.

## The script (~12 minutes)

Expect each live run to take **12–18 s** end to end: ~5–10 s reading documents, ~1 s simulated providers, ~2–4 s
writing the vendor message. Rehearsed in this order on 2026-10-05: H2 approved · E3 v2 approved · E2 request info ·
E4 duplicate → reapply → rejected again.

### 1. The problem and the dashboard — 1 min
*Show:* Dashboard.
*Say:* "Before a company pays a vendor it must know they're legitimate. The expensive failure is paying a fraudster;
the common one is chasing vendors for documents. This system reads the documents with AI, decides with fixed rules,
and sends a person only what needs judgement. Six cases are seeded samples so the dashboard has history — labelled,
not live. Everything I run now is live."

Point at: status tiles · straight-through rate (approved first time, no human touch) · "why cases aren't approved".

### 2. Happy path, from the form — 2½ min
*Do:* **New vendor → Load sample → H2** → scroll through the filled form and the three attached PDFs → **Submit for checks**.
*Say while it runs:*
- **Reading documents (5–10 s):** "This is the only AI step. Each document is identified and its fields extracted with
  the exact quote they came from — and the model never sees the form, so it can't just confirm what it expects."
- **Checking what we read:** "Every value is checked against the PDF's own text and for a valid format — so a misread
  can't slip through as a 'mismatch'."
- **Cross-checking:** "The PAN inside the GSTIN, the GSTIN's state code against the address, names standardised —
  'Private Limited' equals 'Pvt Ltd' — but no fuzzy matching: a near-match in payments is a red flag."
- **Verifying (labelled simulated):** "GST registry and a penny drop — simulated providers behind real interfaces."
- **Decision:** "Approved — all 22 required checks passed. The rules decided, not the model."

*Do:* **Open case** → expand one check to show evidence → **Documents** tab (quotes, "Found in document text") →
**Vendor messages** (AI wording, checklist from the rules).

### 3. Vendor-fixable problems and the vendor loop — 2½ min (E3)
*Do:* Open **VO-0004** (Kaveri Packaging, awaiting vendor).
*Say:* "The vendor uploaded an invoice as their cancelled cheque — and the invoice even prints bank details. A field
check would accept it; the system recognised what the document *is*. And the GSTIN is valid but it's their Karnataka
registration for a Tamil Nadu address — one GSTIN per state, an honest mistake."
*Show:* the two vendor asks → **Vendor messages** tab (exact checklist).
*Do:* **Resubmit for vendor → Load sample → E3R** → point at the PAN card "Kept from version 1" → **Submit version 2**.
*Say:* "Only the changed documents are re-sent. Same case, new version." → Approved → back on the case: History shows
**v1 awaiting vendor → v2 approved**.

### 4. A fraud pattern and the human decision — 2½ min (E2)
*Do:* Open **VO-0003** (Northwind, in review) → expand **Bank account belongs to the company**.
*Say:* "Everything on paper matches. But the bank says the account belongs to an individual, Rakesh K Sharma — who is
also the vendor's contact person. That's the classic payment-diversion pattern. It isn't auto-rejected — a sole
proprietor's account is a legitimate explanation — so a person decides."
*Show:* **Vendor messages** → "your application is under review" — no reason given. "Telling a fraudster *why* teaches
them what to fix."
*Do:* Review panel → **Request info** → message "Please send a letter on bank letterhead confirming the account holder"
→ reason → your name → Confirm.
*Say:* "Reason is mandatory; it's in the audit trail with my name. Approve would be disabled if any check hadn't run —
a reviewer can overrule a judgement, not missing evidence." → **Audit trail** tab.

### 5. The hard rule and reapplication — 1½ min (E4)
*Do:* Open **VO-0005** (Apex, rejected) → show "Debarred" → **Vendor messages**: generic, no list named.
*Do:* **New vendor → Load sample → E4 → Submit** → the duplicate panel appears.
*Say:* "One open case per vendor. Replay reruns the same data, Resubmit corrects a pending application, Reapply starts a
new application after a rejection." → **Reapply as a new application** → Submit → **Rejected again** (Debarred +
Previously rejected). "A rejected vendor can reapply — but it's a new case, linked to the old one, always reviewed by a
person, and the debarred list is checked again."

### 6. Close — 1 min
*Say:* "It's measured, not assumed: 70 out of 70 live runs reach the same decision, and every failure drill — bad API
key, timeout, killing the server mid-run, damaged or password-protected files — fails closed. I found the AI's slow tail
and halved it with hedged requests." Show [RELIABILITY.md](RELIABILITY.md) if asked.

**Spares if there's time or a question invites it:** E1 (VO-0002 — valid GSTIN carrying another entity's PAN) ·
E5 (VO-0006 — existing vendor, new bank) · Outbox page · H1's scanned PAN card (Documents tab: "Scan · format-checked").

## Fallbacks

| If… | Do |
|---|---|
| Render is asleep / slow to load | Wait — up to ~1 min on first load. Or switch to the local tab. |
| "Reading documents" is slow (> 15 s) | Narrate: "This is the AI provider's tail latency — after 10 s the system sends a backup request and takes whichever answers first." It will finish. |
| A run ends in **internal review with SYS-01** | Use it: "The AI service failed, and the system failed *closed* — it never approves on checks that didn't run." Then **Replay**. |
| H2 says "already has an onboarding case" | You didn't reset after a rehearsal. Either use the panel's **Replay existing case** (still a live run) or Reset demo. |
| Anything else is broken on Render | Switch to the local backup tab — same build, same script. |
| Internet is down | Local backup still runs the rules; document reading needs OpenAI → you'll see SYS-01 fail closed (see above). |

## Questions to expect

| Question | Short answer |
|---|---|
| Why not let the AI decide? | Decisions must be reproducible and auditable. The model returns facts with quotes; versioned rules decide; humans decide the rest. |
| How do you know the AI read correctly? | Blind extraction, then each value checked against the PDF text and its format; measured 0 key-field misreads in 112 live runs against labelled data. |
| What if OpenAI is down? | Every path fails closed to internal review (drilled). Approve is disabled until the checks actually run. |
| Why no fuzzy name matching? | "Lumen Analytics India Pvt Ltd" vs "Lumen Analytics Pvt Ltd" are different legal entities that score ~0.9. Explicit tiers are explainable. |
| Why doesn't E2 get rejected? | A proprietor's personal account is a legitimate explanation. Rejection is reserved for non-curable hard rules. |
| Why tell the vendor nothing for E2? | Disclosing the fraud signal teaches the fraudster what to fix. |
| Why is E3 not sent to review? | Nothing suspicious — wrong upload and the other state's GSTIN are honest, vendor-fixable mistakes. |
| What would change for production? | Real GST/penny-drop providers, Postgres + job queue, user roles, ERP write-back, real email, benchmark on real documents. See README → What I'd build next. |
| What's simulated? | GST registry, bank verification (labelled in the UI), vendor master, message delivery. All behind real interfaces. |
| What would you measure in production? | Straight-through rate, time to decision, vendor rounds per case, reviewer overrides by rule, false approvals (target 0). |
