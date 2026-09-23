# Gate track — Live TallyPrime validation (runs in parallel from P4 onward)

**Who:** you (on a Windows machine with TallyPrime) + Claude Code (tooling and analysis)
**SRS:** 7, TEST-2.2, TEST-4.1, VAL-1.1–1.3, VER-1.3
**Why it matters:** Claude Code cannot reach TallyPrime. Everything it writes about Tally's XML is a draft until real output is captured. This track captures that output, turns it into fixtures and tests, and flips the gate switches that unlock features.

## Step G-A — Build the probe tool (Claude Code, after P4.3 exists)
`tools/tally_probe/` — a small Python CLI that runs on Windows (no backend needed), reusing `tally_contract` request builders:
- `probe list` — every gate test G1–G33 with the requests it sends.
- `probe run G7 --company "Test Co"` — sends the requests and saves request + raw response under `fixtures/xml/live/G7/<timestamp>/` with a `meta.json` (TallyPrime version/build if obtainable, Windows version, date).
- `probe run-all --company "Test Co"`.
- `probe scenario G8` — guided, interactive tests that need you to change something in Tally between captures: capture → "edit voucher 1001 in Tally, then press Enter" → capture → diff ALTERIDs and print the observed result. Scenarios for G8 (edit), G9 (cancel), G11 (delete), G29 (make a master inactive), AGT-5.4 (rename company), ACC-7.5 (move a group).
- `probe summarize` — prints a proposed Status/Evidence line per gate for `docs/validation-gate.md`, which a human confirms.

Kickoff prompt:
~~~text
Read CLAUDE.md, docs/plan/gate-track.md, docs/validation-gate.md and shared/tally_contract. Build tools/tally_probe as specified in Step G-A, runnable on Windows with only the shared package and its dependencies, with unit tests using the mock Tally server. Also write docs/gate-track-howto.md: install steps for the Windows machine and the exact commands I will run. Commit per task.
~~~

## Step G-B — Create the test company in TallyPrime (you)
Use a dedicated test company, never a client's real books. Financial year from 1 April. Load a second company at the same time (needed for G20 / AC-23). Enter:

**Groups:** Sales Accounts → "Sales – Online" → "Sales – Online – Marketplace" (three-level chain); a custom group under Sundry Debtors ("Retail Customers"); a custom group under Bank Accounts.

**Ledgers:** three customers with bill-wise details on (one inside "Retail Customers"), one customer with bill-wise off; two suppliers; two sales ledgers (one in the nested group); a purchase ledger; one Direct and one Indirect expense ledger; Cash; two bank ledgers; a Bank OD ledger; GST output and input ledgers under Duties & Taxes. Opening balances on several ledgers (both debit and credit), and at least one customer with **opening bills** (bill-wise opening balance).

**Voucher types:** "POS Invoice" derived from Sales; a custom Receipt type.

**Stock items:** five items, one with an alternate unit (e.g. box of 12 / pieces); opening stock on some.

**Cost centres:** two.

**Vouchers:**
- Sales with one customer and stock items; a cash sale; a sale with stock items plus a service/freight ledger line (G28, AC-32); a POS Invoice.
- Purchase; expense payment with a cost-centre allocation; journal touching a bank ledger; contra (cash → bank).
- Receipts settling a bill in two parts (Against Reference); a receipt as Advance; a payment On Account.
- Credit note against a specific sales bill (G26); a credit note with no bill reference; a debit note.
- A voucher using a user-defined field (G22, if you have a TDL customisation for one).
- Then, via the probe scenarios: edit a voucher (G8), cancel one (G9), delete one (G11), make a master inactive (G29), rename the company (AGT-5.4), move a group to a new parent (ACC-7.5).

## Step G-C — Reference capture with tally-database-loader (you, TEST-4.1)
Run tally-database-loader (github.com/dhananjay1405/tally-database-loader) against the test company and keep its output (database dump or CSVs) under `fixtures/reference/tdl-loader/<date>/`. This is comparison evidence, not truth.

## Step G-D — Load the project TDL and capture (you)
Load the files from `tdl/` into TallyPrime, confirm `tally-agent test-tally` works, then run `probe run-all` and the scenarios. Commit `fixtures/xml/live/` (test-company data only).

## Step G-E — Analyse and update (Claude Code)
Kickoff prompt:
~~~text
Read CLAUDE.md, docs/plan/gate-track.md, docs/validation-gate.md and every capture under fixtures/xml/live/ and fixtures/reference/. For each gate, compare observed output with the expected result and propose PASSED/FAILED with evidence paths. Do not change gate_status.yaml until I confirm. After confirmation: update docs/validation-gate.md and gate_status.yaml, fix the GATE-tagged constants in tally_contract and tdl/, add the live captures to the contract test harness with expected JSON, and list every behaviour that changes because a gate flipped. Commit per gate group.
~~~

## Step G-F — Keep it current (VER-1.3)
Re-run `probe run-all` on each new TallyPrime release you intend to support; record certified releases in a compatibility table in `docs/validation-gate.md`. Never assume version numbers in advance.

## What flips when a gate passes

| Gate(s) | When PASSED | While NOT TESTED / FAILED |
|---|---|---|
| G1–G7, G10 (per collection) | Incremental sync for that collection | Full pull in prod; FAILED = full pull everywhere (VAL-1.2) |
| G8, G9 | AC-02 / AC-03 verified on real data | Behaviour implemented on draft constants |
| G12–G15, G32 | Hierarchy/voucher-type resolution uses verified fields | Name-based fallback for predefined groups |
| G16, G19 | Balances and ledger reconciliation verified | Balances shown, flagged unverified |
| G18 | Stock snapshot and stock reconciliation verified | Stock view flagged unverified |
| G20 | AGT-5.5 mechanism confirmed | Draft mechanism |
| G21, G11 | Deletion detection confirmed | Key lists on draft request |
| G22 | Custom fields | UDF mappings disabled in prod |
| G23 | Parser sign mapping verified — **blocks production use of every figure** | Draft rule |
| G24 | Per-line child updates | Full child replacement (safe default) |
| G25, G31 | Payment behaviour shown; aging verified | Payment behaviour hidden; aging flagged unverified |
| G26 | Linked returns subtracted | All notes unlinked |
| G27 | Unit conversion | Multi-unit limitation banner |
| G28 | "Unattributed / Non-product Sales Revenue" label | "Product Attribution Difference" label |
| G29 | INACTIVE master status | Not recorded |
| G30 | GUID-based line resolution | Exact-name fallback |
| G33 | ALTERID window paging | Date-window paging |
