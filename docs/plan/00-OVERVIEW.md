# Implementation Plan — Tally Integration & Business Analytics Platform (SRS v7.3)

This folder splits SRS v7.3 into 17 build phases (P0–P16) plus one parallel **live-Tally validation track** (G). Each phase file is written to be handed to Claude Code as-is: what to read, what to build, the requirement and acceptance-criteria IDs to satisfy, the tests to write, a definition of done, and a kickoff prompt.

## How to run this with Claude Code

1. Create an empty git repository. Copy `CLAUDE.md` to its root and the `docs/` folder next to it. Put your original SRS PDF in `docs/srs/`.
2. Open Claude Code in the repository. It reads `CLAUDE.md` automatically at the start of every session.
3. For each phase, in order:
   - Start a fresh session (`/clear`) so earlier phases don't crowd the context.
   - Switch to plan mode, paste the phase's **kickoff prompt**, read the plan it proposes, correct it, approve.
   - Let it implement task by task. Review each commit.
   - Check the phase's **Definition of done** yourself before moving on.
4. Phases marked **L** are best split over 2–3 sessions (the kickoff prompts show where to split).
5. Answer the questions Claude Code writes into `docs/progress.md`, and move decisions from PROPOSED to ACCEPTED in `docs/decisions.md` as you confirm them. That file is how later sessions learn what earlier sessions decided.

## Phase map

| # | Phase | Size | Depends on | Main SRS sections | Acceptance criteria |
|---|---|---|---|---|---|
| 0 | Foundation & guardrails | S | — | 2.3, 2.4, 17.6, 21 | — |
| 1 | Data model & migrations | M | 0 | 5 | (DR-4.6) |
| 2 | Identity, RBAC, tenancy, audit, settings | M | 1 | 14, 15, 17.5, 18 | AC-59, 60, 62, 63 |
| 3 | Agent control plane (backend) | L | 2 | 4.2–4.9, 4.13, 19.2 | AC-13–20, 22, 24 (setting) |
| 4 | Tally contract: TDL, request builder, parser | L | 0 | 5.8, 5.11, 6.11, 23 | AC-34 (parser), 66 |
| 5 | Sync engine core | L | 3, 4 | 6.1–6.6, 6.9 | AC-01, 02, 05–09, 12 |
| 6 | Lifecycle, deletion detection, hierarchy resolution | M | 5 | 6.7, 6.8, 6.10, 8.2, 8.3 | AC-03, 04, 10, 11 |
| 7 | Tally Sync Agent (Windows) | L | 3–6 | 4, 16 | AC-21, 23, 24, 25 + E2E of AC-01/02/04 |
| 8 | Core accounting analytics | L | 6 | 8.1–8.4, 8.7–8.10, 8.14 | AC-26–29, 34–38 |
| 9 | Attribution & rankings | M | 8 | 8.5, 8.6, 8.11–8.13 | AC-30–33 |
| 10 | Reconciliation | M | 7, 8 | 9, ACC-9.5 | AC-38 (match), 40–44 |
| 11 | Aging & payment behaviour | M | 8 | 10 | AC-45–51 |
| 12 | Stock analytics | M | 8 | 11 | AC-52–54 |
| 13 | Frontend foundation & operations views | L | 3 (API), 6 | 13.1, 14, 17.4 | AC-17/18/19 (UI) |
| 14 | Analytics UI, drill-down, exports | L | 9–13 | 13, 17.4 | AC-39, 61, 65 (partial) |
| 15 | Optional anomaly detection (MCP + Claude) | M | 8, 14 | 12, 19.3 | AC-55–58 |
| 16 | Hardening, performance, backup, E2E, acceptance | L | all | 14.2, 15, 16, 17, 22, 23, 25 | AC-59, 60, 64, 65 + full AC run |
| G | Live-Tally validation track (you + Claude Code) | — | starts after P4, runs in parallel | 7, TEST-2.2, TEST-4.1 | G1–G29 (+ proposed G30–G33) |

## Dependency graph

```
P0 ──► P1 ──► P2 ──► P3 ──────────────────┐
 │                    │                    ▼
 └────► P4 ───────────┼──────────────────► P5 ──► P6 ──► P7 (Agent, end-to-end)
         │            │                            │       │
         └──► G (live-Tally gate track, parallel)  ▼       ▼
                      │                            P8 ──► P9
                      │                            ├────► P10 (also needs P7)
                      │                            ├────► P11
                      │                            └────► P12
                      └──► P13 (frontend can start once P3's API exists)
                                    P9–P13 ──► P14 ──► P15 ──► P16
```

Parallel opportunities if you run more than one Claude Code session: P4 can start right after P0; P13 can start after P3; P10, P11 and P12 are independent of each other after P8.

## How the SRS status markers become code

| SRS marker | How it is implemented |
|---|---|
| LIVE TALLY VERIFICATION REQUIRED | Isolated constant/module tagged `# GATE-Gxx`, safe default, behaviour switch via `app/core/gates.py` reading `gate_status.yaml`. Features that stay off until their gate passes: incremental sync per collection (G1–G10), payment behaviour (G25), return linking (G26), unit conversion (G27), the "Unattributed / Non-product" label (G28), per-line updates (G24). |
| OPEN — BUSINESS DECISION | A company setting (or config value) with the SRS default; tracked in `docs/decisions.md` D-016. |
| IMPLEMENTATION TEST | Config value with the SRS default, plus a measurement task in P16. |

## Spec issues found while planning

These were found by reading the SRS against how TallyPrime actually structures data. Each has a PROPOSED decision in `docs/decisions.md` with a safe default, so work is not blocked, but confirm them before the phase shown.

| # | Issue | Impact if ignored | Proposed handling | Decision | Confirm before |
|---|---|---|---|---|---|
| 1 | ACC-7.x classifies by "primary group", but Sundry Debtors, Sundry Creditors, Cash-in-Hand, Bank Accounts and Duties & Taxes are Tally *predefined sub-groups*, not primary groups | Customers, suppliers, cash/bank and tax would match nothing | Classify by nearest predefined ancestor group | D-001 | P1 |
| 2 | Tally voucher lines usually reference ledgers and stock items by name | A rename breaks joins | TDL emits master GUIDs on each line (gate G30) | D-002 | P4 |
| 3 | Bill references are unique per party ledger; bills outstanding at books-beginning live on the ledger master; `bill_allocations` has no direction | Wrong aging, reference collisions | Bill key (ledger, reference); add `opening_bill_allocations`; store direction | D-004, D-022 | P1, P11 |
| 4 | API table (19.2) lacks endpoints the design needs (company creation, lease acquire/release, key lists, reconciliation upload, auto-routed "Sync Now") | — | Additions listed | D-006 | P2, P3, P5 |
| 5 | Reconciliation compares "Sales" etc., but Tally's own totals and the local business metric use different bases | Legitimate differences reported as FAIL | Define a like-for-like basis per metric | D-008 | P10 |
| 6 | Stock classes leave gaps/overlaps for some measurement-period settings | Items with no class or two classes | Explicit precedence and a default for the gap | D-009 | P12 |
| 7 | Cash flow counts only Receipt/Payment vouchers | Cash sales/purchases posted directly in Sales/Purchase vouchers are missed | Implement as specified; ask the business | D-021 | P8 |
| 8 | Deletion detection marks everything missing if a key list is truncated or empty | Data silently vanishes from analytics | Safety guard with thresholds | D-007 | P6 |

## Project-level definition of done
- Every phase's Definition of done is met and committed.
- `docs/traceability.md` maps every SRS requirement ID to at least one test or a documented manual check (SRS Section 25).
- `docs/acceptance-report.md` shows AC-01 to AC-66 with PASS, or "blocked by Gxx" where live-Tally evidence is still missing.
- `docs/validation-gate.md` has evidence for every gate that a shipped feature depends on.
- Per SRS Section 28: implementation-ready ≠ production-ready. Production sign-off additionally needs the gates, the benchmark (PERF-VAL-1) and the business decisions.
