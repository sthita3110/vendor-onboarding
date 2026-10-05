# Vendor Onboarding — Assumptions & Limitations

The brief asks candidates to treat ambiguity as part of the exercise: make an assumption, note it, move on. This is that note.

## Scope assumptions

| # | Assumption | Rationale |
|---|---|---|
| A1 | **Edge cases are self-defined.** The brief supplies none for PS-2; H1 and E1–E4 are my design (see [RULES.md](RULES.md) §5). | Brief: "Design and build 2–4 edge cases of your own." |
| A2 | **India only.** All vendors are Indian entities paid in INR to Indian bank accounts. | Depth over breadth. GSTIN embeds the PAN and a state code, and the PAN encodes holder type — rich, deterministic cross-field checks within one coherent regulatory context. Multi-country support is an adapter/validator extension, not a redesign. |
| A3 | **"Pending" has two sub-states** — Awaiting vendor and Internal review — under the brief's three statuses. | Different owner, clock, and message. |
| A4 | **Clean vendors are auto-approved.** | All checks are deterministic and logged. In production I would start in *shadow mode* (system recommends, human approves) to measure agreement before enabling auto-approval. |
| A5 | **"Communicate back what's needed" is reason-dependent.** Internal-review and rejected cases receive a neutral or generic message. | Disclosing a fraud signal ("bank name doesn't match", "you're on a list") teaches bad actors what to fix. |
| A6 | **No expiry checks in the MVP.** None of the mandatory Indian documents (GST certificate, PAN card, cancelled cheque) carries an expiry date. If optional dated documents are added (e.g. Section 197 lower-TDS certificate), the rule is "expired as of today", no buffer. | Avoids inventing a validity policy; a buffer would be a client-config decision. |
| A7 | **Rejection only on exact PAN match against the debarred list** (PAN extracted from GSTIN counts). Name-only matches go to review. | Rejection is the hardest decision to reverse; names collide frequently. PAN is entity-level, so it catches every state GSTIN of the same entity. |
| A8 | **Duplicates are never auto-rejected.** | Usually legitimate (re-registration, new entity, bank change) — but bank change on an existing vendor is a top fraud vector, so a human decides. |
| A9 | **REJECT outcomes are not overridable in the MVP.** | Prevents one-click approval of a debarred entity; in production a compliance role would own overrides. |
| A10 | **Vendor submission is a web form + document uploads.** Ops can also submit on a vendor's behalf. | Brief: "You decide what the submission looks like." |

## Simulated components (stated openly)

| Component | MVP | Production equivalent |
|---|---|---|
| Tax registry lookup | Mock adapter over `registry_fixtures.json` | GST portal / GSP API |
| Bank account verification | Mock adapter over `bank_fixtures.json`, returns holder name | Penny drop via Razorpay / Cashfree / bank API |
| Debarred / sanctions list | Seeded `debarred.csv`, keyed on PAN | OFAC SDN, World Bank debarment, internal blocklist; screening provider |
| Vendor master | Seeded `vendor_master.csv` | ERP vendor master (NetSuite, SAP, Oracle) |
| Email | In-app Outbox, status "sent (simulated)" | Transactional email provider + vendor portal |

Adapters implement the same interface a real integration would; swapping a mock for a real provider is a change confined to `adapters/`.

**Simulated latency.** Mock providers wait `MOCK_LATENCY_MS` (default 400 ms) per call, like a provider sandbox round-trip, so the verification stage is visible in the live run view. Every response carries `simulated: true` and the UI labels it "Simulated provider" — nothing is presented as a real external call. Tests run with 0 ms.

**Sandbox defaults for unknown identifiers.** Fixtures cover every demo case. For identifiers not in the fixtures (e.g. a vendor typed live during the interview), the mocks behave like a provider sandbox: the GST registry returns `active`, and penny drop returns `verified`, echoing the submitted account holder name. Both responses carry `fixture: false`, which is visible in the evidence and audit trail. Without this, every ad-hoc submission would go to review for reasons unrelated to its data.

## Known limitations

- **Static vendor master.** In production, approving a vendor would write it to the ERP vendor master, so a later submission of the same vendor would trigger DUP-01. Here the vendor master is a fixed reference file and approvals do not feed back into it, so demo cases stay repeatable (running H1 in rehearsal doesn't turn the live H1 run into a duplicate).
- **Seeded demo history.** On an empty database the app pre-populates 6 demo cases (H1, E1–E5) labelled "Seeded sample". Their check results are produced by the deterministic rules over each sample's known document data (no model call, no pipeline run) and must match the sample's expected outcome or seeding stops. Their stored run is marked "not executed" and excluded from timing metrics. Replay executes the real pipeline on any case.
- **One open case per legal entity.** A new submission for an entity that already has a case (matched by PAN or GSTIN) is blocked; the user continues via Replay (rerun), Resubmit (correct a pending application) or, after a rejection, Reapply (a new linked case). A reapplication is always reviewed by a person (PRIOR-01) — no cooling-off period is imposed, since any number of days would be invented policy. Concurrent identical submissions are not locked against each other (acceptable at demo scale; production would use a unique constraint on the entity key).
- **Simulated delivery.** Vendor messages are recorded in an in-app outbox with status "sent (simulated)"; nothing is emailed. Real delivery is a provider swap (e.g. a transactional email service).
- **Reviewer free text is sent as written.** A reviewer's Request-info message goes into the vendor checklist verbatim; it isn't run through the AI-output filter (the reviewer is accountable for it, and it's audited). AI-drafted wording always is.
- **Demo reset.** A demo-only action wipes every table (including the append-only audit log) and uploaded files, then re-seeds the samples — the same effect as redeploying onto a fresh database, which the free tier does on every wake. It is passcode-protected, refused while a run is in progress, and disabled with `DEMO_RESET=off`; a real deployment would turn it off.
- **Lightweight schema upgrade.** On startup, new nullable columns are added to an existing SQLite database (forward-only). Anything beyond that is Alembic's job in production.
- **Disposable database.** SQLite, tables created at startup, no migrations; on the free hosting tier the database is reset on restart and re-seeded with demo cases. Production: Postgres + Alembic migrations.

- **Name matching** sends legitimate-but-unattested variations (bank-truncated names, unregistered trade names, form typos) to review. Accepted under the false-approval vs false-hold cost asymmetry.
- **No document tamper / forgery detection.** Extraction trusts the document's visible content; grounding only verifies the value exists in the text layer.
- **Image-only documents** can't be grounded against a text layer; their values are marked `source: image`.
- **LLM dependency:** extraction requires the OpenAI API. Mitigated by caching by file hash and fail-closed behavior (outage → review, never approval).
- **No real auth or roles.** Single access passcode for the demo; reviewer identity is a display name.
- **Single-process, SQLite.** Appropriate for demo scale (tens of vendors), not for concurrent multi-team use.
- **Sample data is fictitious**, generated to be realistic in structure (correct GSTIN checksums, valid PAN structure, valid IFSC format, plausible documents).

## Open questions I would ask a real client

1. Who may override a review decision, and do approvals above some vendor-spend level need a second approver?
2. Which sanctions/debarment lists are mandatory for your industry and geographies?
3. Is a bank account in a registered trade name acceptable policy, or must it be the legal name?
4. What is the expected SLA for vendor responses, and when should an unresponsive case auto-close?
5. Which ERP is the vendor master, and should approval write back to it?
