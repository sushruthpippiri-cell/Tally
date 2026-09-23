# Phase 15 — Optional anomaly detection (rules + MCP + Claude explanation)

**Size:** M · **Depends on:** P8, P14 · **Can be skipped for v1 without affecting anything else.**
**SRS:** 12 (all), 19.3, 14.1 (review permission), 15 (AI tool log)
**Requirements:** FR-3.1–3.9, SEC-1.12, SEC-1.14, NFR-REL-1, PERF-1.4, LOG-1.1
**Acceptance:** AC-55, AC-56, AC-57, AC-58 · **Decisions:** D-015

## Goal
Deterministic rules find unusual and possibly duplicate transactions and store numeric evidence. Only when the feature flag is on, Claude may write a plain-language explanation of one anomaly's stored evidence. Nothing in the core system depends on this phase.

## Tasks

### P15.1 Feature-flag gating (FR-3.1, SRS 12.1)
One function `anomaly_enabled(company_id)`. Flag off: no rule job runs, no rows created, no MCP or Claude calls, API returns the section as disabled, UI hides it. The rule job is triggered after a sync run completes, only when enabled.

### P15.2 Rules engine — `app/anomaly/rules.py` (deterministic SQL/Python)
- Transaction amount = the party ledger's entry `amount_absolute` on an ACTIVE voucher (party = Sundry Debtors or Sundry Creditors class).
- **Unusually large (FR-3.2):** history = the same party's transactions in the `anomaly.history_window_days` before the voucher date, excluding the voucher itself; requires ≥ 5 prior transactions (D-015); flag when amount > mean + `anomaly.deviation_sd` × sample SD. Second rule only when `anomaly.max_multiplier` is set: amount > previous maximum × multiplier.
- **Possible duplicate (FR-3.3):** same party ledger, same amount, voucher dates within `anomaly.duplicate_window_days`, different GUIDs → flag the later voucher with `duplicate_of_voucher_id`.
- Evidence stored (FR-3.4): transaction amount, historical average, historical maximum, deviation percent = (amount − mean) ÷ mean × 100, rule triggered. `UNIQUE(voucher_id, rule_triggered)` keeps runs idempotent; only vouchers inserted or modified since the last run are evaluated.
- Anomaly evidence is never read by any accounting metric (ACC-4.6; import-linter already enforces the direction).

### P15.3 MCP server — `app/anomaly/mcp_server.py` (FR-3.5, SEC-1.12, SRS 19.3)
Python `mcp` SDK exposing exactly one read-only tool, `get_anomaly_evidence(anomaly_id)`, returning only that anomaly's stored evidence fields (no narration text, no bulk data, no SQL). The company is bound server-side by the explainer's session, not supplied by the model; an ID from another company returns "not found". Uses a read-only database role. Every call is written to `ai_tool_log` (FR-3.9).

### P15.4 Explainer — `app/anomaly/explainer.py`
- An MCP client session to the server plus an Anthropic SDK tool-use loop in which the only tool offered is `get_anomaly_evidence`. Model from `ANOMALY_EXPLAINER_MODEL`; API key from `ANTHROPIC_API_KEY` (SEC-1.14).
- System prompt: explain the evidence for a non-technical business owner in at most ~120 words; use only numbers present in the evidence; never calculate new figures (FR-3.6).
- Post-check: every number in the explanation must appear in the evidence (after normalizing formats); otherwise discard it and mark UNAVAILABLE.
- Timeout (20 s) and any error → `explanation_status = UNAVAILABLE`; detection is never blocked (NFR-REL-1, AC-58). PENDING while running. A retry job re-attempts UNAVAILABLE explanations later ("automatic when restored", SRS 16).

### P15.5 API and review
- `GET /companies/{id}/anomalies` (filters: rule, reviewed, date).
- `POST /companies/{id}/anomalies/{anomaly_id}/review {action: reviewed | not_an_issue}` — REVIEW_ANOMALIES (Owner and Accountant; Admin gets 403), audited (FR-3.8).

### P15.6 UI
Anomalies section visible only when enabled; evidence panel and explanation panel clearly separated and labelled (FR-3.7); "Explanation unavailable" state; review buttons by role; link to the voucher detail.

### P15.7 Tests
- AC-55: flag off → after syncs, zero anomaly rows and zero MCP/Claude calls (mocks assert not called).
- AC-56: amount above mean + 3 SD → record with amount, average, maximum, deviation, rule. Check the SRS example: ₹4,50,000 vs average ₹70,000 → deviation ≈ +543 %.
- AC-57: same party, same amount within 3 days → duplicate referencing both.
- AC-58: Claude unreachable → anomalies created and shown with evidence; explanation UNAVAILABLE.
- MCP tool refuses another company's anomaly; post-check discards an explanation containing an invented number; PERF-1.4 evidence tool ≤ 2 s; Admin review → 403.

## Definition of done
Tests pass; with the flag off, the full test suite of P0–P14 shows no behavioural change.

## Kickoff prompt
~~~text
Read CLAUDE.md, docs/plan/phase-15-anomaly-optional.md, docs/decisions.md (D-015) and SRS Sections 12 and 19.3. In plan mode, propose the rule SQL, the MCP server and the explainer loop, including exactly what data leaves the system. Wait for approval, implement P15.1–P15.7 with tests first, commit per task, update docs/progress.md.
~~~
