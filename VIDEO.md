# 5-minute demo video — script

**The brief:** *"Record yourself walking through your process. Show the happy path running live, then run at least one
edge case. Narrate what's happening and why — what the process is doing at each step, the decisions it's making, and
anything interesting about how you built it. Five minutes max. No editing needed, no slides."*

How this script meets it:

| Brief asks for | Where |
|---|---|
| Record yourself | Loom (or similar) with the **camera bubble on** — your face in the corner the whole time |
| Happy path **running live** | 0:20 — H2 submitted through the form, all 10 stages live |
| **Run** at least one edge case | 1:35 — **E3 replayed live** (vendor-fixable) · 2:35 — **E2 replayed live** (fraud pattern → human review) |
| What it's doing and the decisions it makes | Narration on every stage and outcome |
| How you built it | 4:05 — blind extraction + grounding, model chosen by benchmark, hedged requests, measured reliability |
| ≤ 5 min, no slides, no editing | One take; only the app on screen |

**Before recording:** Reset demo (6 cases, review badge 3) · open the app 5 minutes early so the free tier is awake ·
browser ~110% zoom · notifications off · camera bubble on · one practice run. Each live run takes **12–18 s** — keep
talking through it (the script is written for that).

| Time | Screen | Say (roughly — keep it natural) |
|---|---|---|
| **0:00–0:20** | Dashboard | "This is a vendor onboarding process for Indian vendors. Before a company pays a vendor, it has to know they're legitimate. My design rule: AI reads the documents, fixed rules make every decision, and a person decides only what the rules can't. These six cases are labelled seeded samples so there's history — everything I run now is live." |
| **0:20–0:35** | New vendor → Load sample **H2** → scroll to documents → **Submit for checks** | "A new vendor: company, tax IDs, bank account, and three documents — GST certificate, PAN card, cancelled cheque." |
| **0:35–1:25** | Live run view | As stages turn green: "Completeness. Now the AI reads each document — it says what the document is and extracts the fields with the exact quote they came from, without seeing the form, so it can't just confirm what it expects. Next, each value it read is checked against the PDF's own text and its format. Then the rules: GSTIN check digit, the PAN inside the GSTIN, the GSTIN's state against the address, names across every document — standardised, never fuzzy-matched. GST registry and bank — simulated providers. Risk screening. Approved: all twenty-two checks passed — the rules decided, not the model." |
| **1:25–1:35** | Open case → expand one check | "Every check keeps its evidence: what the form said, what the document said, and the quote." |
| **1:35–2:35** | Open **VO-0004** (Kaveri, awaiting vendor) → **Replay** → live run → decision panel | **Edge case 1, live.** "This vendor uploaded an invoice as their cancelled cheque — and the invoice even prints bank details, so a simple field check would accept it." *(Reading documents: point at "identified as Invoice — not what this slot needs")* "The AI identified what the document *is*. And the GSTIN is valid but it's their Karnataka registration for a Tamil Nadu address — one GSTIN per state. Both are honest mistakes, so it goes back to the vendor with exactly two requests — the AI writes the polite wording, the checklist comes from the rules. And because the outcome didn't change, the vendor isn't emailed twice." |
| **2:35–3:35** | Open **VO-0003** (Northwind, in review) → **Replay** → live run → open case → expand *Bank account belongs to the company* → Vendor messages tab | **Edge case 2, live.** "Here everything on paper matches. Watch the bank verification…" *(stage turns amber)* "…the bank says the account belongs to an individual — who is also the vendor's own contact person. Classic payment diversion. It's not auto-rejected — a proprietor's account is a legitimate explanation — so it goes to a person. And the vendor's message just says 'under review'. Telling a fraudster *why* teaches them what to fix." |
| **3:35–4:05** | Review panel → **Request info** (message + reason + name) → Confirm | "The reviewer asks for a bank letter. A reason is required and audited with their name — and Approve is disabled whenever a check didn't actually run: a person can overrule a judgement, not missing evidence." |
| **4:05–4:45** | Stay on the case (or open RELIABILITY.md) | **How I built it.** "A few things I'm glad I did. The extraction model was picked by benchmark against labelled documents, not by reputation. Every AI-read value has to be printed on the page or pass a format check — that caught a real misread of a scanned PAN during development. I ran every case seventy times live: same decision every time. And when I measured, the AI provider occasionally stalled for 35 seconds, so slow reads now send a backup request — that halved the worst case. Every failure I could throw at it — bad key, timeout, killing the server mid-run, damaged or password-protected files — fails safe." |
| **4:45–5:00** | Dashboard | "AI reads, rules decide, people judge — and nothing gets approved on evidence that isn't there. Thanks for watching." |

**If running long:** cut 1:25–1:35 and shorten 4:05–4:45 to two sentences. Never cut the two live edge-case runs —
that's the brief.

**If a run hits SYS-01 on camera** (AI service failure): keep it — "the AI service failed and the system failed closed;
it never approves on checks that didn't run" — then Replay once more.

**If Replay is disabled on a case:** you didn't Reset after a rehearsal (a reviewer has decided it). Reset demo first.
