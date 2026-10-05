# 5-minute demo video — script

The brief: *show the happy path running live, then at least one edge case; narrate what's happening and why.* Five
minutes maximum, no slides, no editing needed. This script shows the happy path, two edge cases, and the human step.

**Before recording:** Reset demo (6 cases) · browser at ~110% zoom · notifications off · cursor visible · one practice
run · record in one take; if a stage is slow, keep talking (the tail is real and handled — see 2:30).

| Time | Screen | Say (roughly — keep it natural) |
|---|---|---|
| **0:00–0:25** | Dashboard | "This is a vendor onboarding process for Indian vendors. Before a company pays a vendor it has to know they're legitimate. The costly failure is paying a fraudster; the common one is chasing vendors for documents. My design rule: AI reads the documents, fixed rules make every decision, and a person decides only what the rules can't. These six cases are seeded samples so there's history — everything I'm about to run is live." |
| **0:25–0:45** | New vendor → Load sample **H2** → scroll to the documents | "A new vendor: company details, tax IDs, bank account, and three documents — GST certificate, PAN card, cancelled cheque. I'll submit it." → **Submit for checks** |
| **0:45–1:40** | Live run view | Narrate the stages as they turn green: "Completeness. Now the AI reads each document — it identifies the document and extracts the fields with the exact quote they came from, without ever seeing the form, so it can't just confirm what it expects. Next, every value it read is checked against the PDF's own text and its format. Then the rules: the GSTIN's check digit, the PAN inside the GSTIN, the GSTIN's state against the address, names across every document — standardised, not fuzzy-matched. Then the GST registry and a penny drop to the bank — simulated providers. Risk: debarred list, existing vendors. Approved — all twenty-two checks passed." |
| **1:40–2:00** | Open case → expand a check → Documents tab | "Every decision shows its evidence: what the form said, what the document said, and the quote it was read from." |
| **2:00–2:50** | Open **VO-0004** (Kaveri, awaiting vendor) → Vendor messages tab | "Edge case one. This vendor uploaded an invoice as their cancelled cheque — and the invoice even lists bank details, so a field check would accept it. The system recognised what the document *is*. Their GSTIN is valid but it's the Karnataka registration for a Tamil Nadu address. Both are honest mistakes, so this goes straight back to the vendor with exactly two requests — the AI writes the polite wording, but the checklist comes from the rules." |
| **2:50–3:20** | Resubmit → Load sample **E3R** → point at "Kept from version 1" → Submit → approved | "The vendor resubmits only what changed. Same case, version two — approved. The history keeps both versions." |
| **3:20–4:15** | Open **VO-0003** (Northwind, in review) → expand *Bank account belongs to the company* → Vendor messages tab | "Edge case two. Everything on paper matches — but the bank says the account belongs to an individual, who is also the vendor's own contact person. That's the classic payment-diversion pattern. It isn't auto-rejected, because a proprietor's account is a legitimate explanation, so it goes to a person. And look at the vendor's message: under review — no reason. Telling a fraudster why teaches them what to fix." |
| **4:15–4:40** | Review panel → **Request info** with a message + reason + name → Confirm → Audit trail | "The reviewer asks for a bank letter. A reason is required, it's audited with their name — and Approve would be disabled if any check hadn't actually run." |
| **4:40–5:00** | Dashboard (or RELIABILITY.md) | "It's measured: seventy out of seventy live runs reach the same decision, and every failure — a bad API key, a timeout, the server killed mid-run, a damaged or password-protected file — fails safe. AI reads, rules decide, people judge. Thanks for watching." |

**If running long,** cut 1:40–2:00 (evidence) and the resubmission (2:50–3:20) — the brief requires the happy path and
one edge case; E3 alone qualifies.

**If a run hits SYS-01 on camera** (AI service failure): keep it — "the AI service failed and the system failed
closed; it will never approve on checks that didn't run" — then Replay.
