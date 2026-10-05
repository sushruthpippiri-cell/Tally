# Phase 15 — Optional anomaly detection (rules + MCP + Claude explanation)

**Size:** M · **Depends on:** P8, P14 · **Can be skipped for v1 without affecting anything else.**
**SRS:** 12 (all), 19.3, 14.1 (review permission), 15 (AI tool log)
**Requirements:** FR-3.1–3.9, SEC-1.12, SEC-1.14, NFR-REL-1, PERF-1.4, LOG-1.1
**Acceptance:** AC-55, AC-56, AC-57, AC-58 · **Decisions:** D-015 (amended), D-055

## Goal
Deterministic rules find unusual and possibly duplicate transactions and store numeric evidence. Only when the feature flag is on, Claude may write a plain-language explanation of one anomaly's stored evidence. Nothing in the core system depends on this phase.

## Tasks

### P15.1 Feature-flag gating (FR-3.1, SRS 12.1)
`anomaly_enabled(session, company_id)` = `settings.get_flag(..., "FEATURE_ANOMALY_DETECTION")`. Flag off: no rule job runs, no rows created, no MCP or Claude calls, `anthropic`/`mcp` not even imported, API returns the section as disabled, UI hides it.

The rule job **follows a cursor rather than hooking the sync path** (D-055 #4): `app/jobs/anomaly.py` every 60 s under `LOCK_ANOMALY_RULES`, scanning each enabled company's newly stored vouchers. `app.sync` may not import `app.anomaly`, and running rules inside `close_run` would hold the Agent's request transaction.

The cursor is **`Voucher.last_synced_at` with a 5-minute overlap**, in `anomaly_scan_state.synced_through` — **never Tally's ALTERID** (D-055 #9): a record held back by D-039 #7 or recovered by a D-041 key-list check arrives later with a *lower* ALTERID and an ALTERID cursor would skip it forever.

First enable scans only `voucher_date >= today − anomaly.initial_scan_days` (default 30, D-055 #11).

### P15.2 Rules engine — `app/anomaly/rules.py` (deterministic SQL/Python)
- Transaction amount = the party ledger's entry `amount_absolute` on an ACTIVE voucher (party = Sundry Debtors or Sundry Creditors class).
- **Unusually large (FR-3.2, amended by D-015 / D-055 #1):** history = the same party's ACTIVE transactions in the `anomaly.history_window_days` before the voucher date, excluding the voucher itself; requires ≥ `anomaly.min_prior_transactions` priors (default 5); flag when amount > mean + `anomaly.deviation_sd` × sample SD **and** amount >= `anomaly.min_average_multiple` × mean (default 2). **The second condition is a stated departure from FR-3.2**: without it a flat ₹70,000 history (SD = 0) flags a ₹70,001 invoice, and a near-flat one flags ₹70,050. Second rule only when `anomaly.max_multiplier` is set: amount > previous maximum × multiplier.
- **Possible duplicate (FR-3.3, amended by D-055 #2):** same party ledger, same amount, voucher dates within `anomaly.duplicate_window_days`, different GUIDs, **and the same `base_voucher_type`** → flag the later voucher with `duplicate_of_voucher_id`. Without the base-type condition the rule flags an invoice followed by its payment of the same amount — the most ordinary pattern there is.
- Evidence stored (FR-3.4): transaction amount, historical average, historical maximum, deviation percent = (amount − mean) ÷ mean × 100, rule triggered. `UNIQUE(voucher_id, rule_triggered)` keeps runs idempotent; only vouchers stored or re-stored since the cursor are evaluated.
- **A flag follows its voucher (D-055 #10):** a re-evaluated voucher gets fresh evidence and its explanation dropped back to `PENDING`; a rule that no longer triggers sets `cleared_at` rather than deleting the row, so a reviewed flag survives for the audit trail and a re-trigger un-clears it. A flag whose voucher becomes CANCELLED or MISSING_IN_TALLY stays in the table and leaves the list.
- Anomaly evidence is never read by any accounting metric (ACC-4.6; import-linter already enforces the direction).

### P15.3 MCP server — `app/anomaly/mcp_server.py` (FR-3.5, SEC-1.12, SRS 19.3)
Python `mcp` SDK exposing exactly one read-only tool, `get_anomaly_evidence(anomaly_id)`, returning only that anomaly's stored evidence fields (no narration text, no bulk data, no SQL). The company is bound server-side by the explainer's session, not supplied by the model; an ID from another company returns "not found". Uses a read-only database role. Every call is written to `ai_tool_log` (FR-3.9).

### P15.4 Explainer — `app/anomaly/explainer.py`
- An MCP client session to the server plus an Anthropic SDK tool-use loop in which the only tool offered is `get_anomaly_evidence`. Model from `ANOMALY_EXPLAINER_MODEL`; API key from `ANTHROPIC_API_KEY` (SEC-1.14).
- Only placeholders and numbers are ever sent (SEC-1.12, D-055 #6): parties and vouchers appear as `Party A`, `Voucher A`, `Voucher B` — **letters, never digits**, so our own labels cannot trip the number check (D-055 #8). Never sent: real names, voucher numbers, voucher type names, narration, dates, GUIDs. One `redact()` decides this; names are restored locally for display.
- System prompt: explain the evidence for a non-technical business owner in at most ~120 words, in digits; use only numbers present in the evidence; never calculate new figures (FR-3.6).
- `tool_choice` is **`auto`** plus an instruction naming the tool — forced tool use returns 400 on the current models. Effort `low`; `thinking` omitted; no prefill. `stop_reason` is checked before the content is read.
- At most `anomaly.max_explanations_per_day` attempts per company per day, newest first (D-055 #11).
- Post-check: every number in the explanation must appear in the evidence (after normalizing formats); otherwise discard it and mark UNAVAILABLE.
- Timeout (20 s) and any error → `explanation_status = UNAVAILABLE`; detection is never blocked (NFR-REL-1, AC-58). PENDING while running. A retry job re-attempts UNAVAILABLE explanations later ("automatic when restored", SRS 16).

### P15.5 API and review
- `GET /companies/{id}/anomalies` (filters: rule, reviewed, date).
- `POST /companies/{id}/anomalies/{anomaly_id}/review {action: reviewed | not_an_issue}` — REVIEW_ANOMALIES (Owner and Accountant; Admin gets 403 from the existing matrix), audited (FR-3.8).
- `GET /companies/{id}/anomalies/disclosure` — MANAGE_SETTINGS: the real system prompt, the field list and a worked example from the real `redact()`, shown before the flag can be turned on (D-055 #7).
- `GET /companies/{id}/anomalies/explanation-health` — VIEW_LOGS: discarded-explanation counts by reason (D-055 #3).

### P15.6 UI
Anomalies section visible only when enabled; evidence panel and explanation panel clearly separated and labelled (FR-3.7); "Explanation unavailable" state; review buttons by role; link to the voucher detail.

### P15.7 Tests
- AC-55: flag off → after syncs, zero anomaly rows and zero MCP/Claude calls (mocks assert not called).
- AC-56: amount above mean + 3 SD → record with amount, average, maximum, deviation, rule. Check the SRS example: ₹4,50,000 vs average ₹70,000 → deviation ≈ +543 %.
- AC-57: same party, same amount within 3 days → duplicate referencing both.
- AC-58: Claude unreachable → anomalies created and shown with evidence; explanation UNAVAILABLE.
- MCP tool refuses another company's anomaly (proven against the RLS policy, not just a WHERE); post-check discards an explanation containing an invented number **and lets a realistic good one through** — a duplicate explanation naming both Voucher A and Voucher B; PERF-1.4 evidence tool ≤ 2 s; Admin review → 403.
- D-055 #6/#8: nothing human-typed leaves, asserted over a dataset whose party name is itself an injection attempt; no placeholder constant contains a digit.
- D-055 #9: a held-back voucher stored a run later with a *lower* ALTERID is still scanned.
- D-055 #10: a modified flagged voucher is re-evaluated; one that stops triggering is cleared but kept when reviewed; a CANCELLED voucher's flag leaves the list.
- D-055 #11: first enable scans only the initial window, and the daily cap defers the rest newest-first.

## Definition of done
Tests pass; with the flag off, the full test suite of P0–P14 shows no behavioural change.

## Kickoff prompt
~~~text
Read CLAUDE.md, docs/plan/phase-15-anomaly-optional.md, docs/decisions.md (D-015) and SRS Sections 12 and 19.3. In plan mode, propose the rule SQL, the MCP server and the explainer loop, including exactly what data leaves the system. Wait for approval, implement P15.1–P15.7 with tests first, commit per task, update docs/progress.md.
~~~
