# Decisions and spec clarifications

Status values: **ACCEPTED** (binding), **PROPOSED** (use this default until the product owner changes it), **OPEN** (needs a business answer; default applies meanwhile), **SUPERSEDED**.
Claude Code: add new entries at the bottom with the next number and status PROPOSED. Never delete entries; mark them SUPERSEDED.

---

### D-001 Classification anchor is the nearest predefined group, or the ledger's own top-level group — ACCEPTED (confirmed by the product owner, 2026-09-23)

**The problem.** ACC-7.1–7.6 say to classify a ledger by its "primary group", and the default
allow-lists name Sundry Debtors, Sundry Creditors, Cash-in-Hand, Bank Accounts and Duties & Taxes.
In TallyPrime those are predefined *sub-groups*, not primary groups: Sundry Debtors sits under
Current Assets, Duties & Taxes under Current Liabilities, Bank OD A/c under Loans (Liability).
Taken literally, every customer would classify as "Current Assets" and no rule would ever match.

**The rule, in plain language.** Walk up the group chain from the ledger until you reach one of
Tally's 28 predefined groups. That group is the ledger's **classification anchor**, and it is what
every allow-list, metric and customer/supplier test uses. If the chain never meets a predefined
group — because the user built their own top-level group under Primary — the anchor is that
top-level group itself. The anchor is never the immediate parent unless the immediate parent
happens to be the anchor, and nested user groups always roll up.

A group is only `UNRESOLVED_GROUP` when the chain is *broken*: a parent that is not in the
company's groups, or a loop. "I do not recognise this group" is not the same as "this group is
broken", and only the second one hides a ledger from analytics.

**Columns on `groups`** (cached onto `ledgers`):

| Column | Meaning | Null when |
|---|---|---|
| `predefined_group_id` | nearest predefined ancestor, including the group itself | the chain has no predefined group |
| `classification_group_id` | the anchor: `predefined_group_id`, else the top-level group of the chain | the chain is broken (case 4) |
| `primary_group_id` | the top-level *predefined* primary group | the chain has no predefined group |
| `nature` | ASSET / LIABILITY / INCOME / EXPENSE | never for a resolved group (see below) |

A group is recognised as predefined by its **reserved name** (gate G32), never by its display name,
so renaming one in Tally changes nothing. `nature` comes from the primary group when there is one,
otherwise from the nature Tally itself stores on the group (gate G14) — TallyPrime requires a
nature to be chosen when a group is created directly under Primary, so it is always available.

**Allow-lists** (`company_settings`) may therefore contain any of the 28 predefined groups **or**
any of the company's own top-level groups. An Owner or Admin adds one when a real classification is
missing.

**Allow-list entries are never stored by display name**, because renaming a group in TallyPrime
would silently drop it from the list and the figures would change with no error. Each entry is one
of two tagged forms in the `setting_value` JSONB:

| Entry | Stored as | Why |
|---|---|---|
| A predefined group | `{"type": "PREDEFINED", "reserved_name": "Sundry Debtors"}` | The reserved name is Tally's own identifier and survives a rename (G32). |
| One of the company's own top-level groups | `{"type": "COMPANY_GROUP", "tally_guid": "<guid>"}` | A user group has no reserved name, and identity is `(company_id, tally_guid)` (DR-4.2). |

The UI and every export show the group's **current display name**, resolved at read time; only the
identifier is persisted. Validation accepts a `COMPANY_GROUP` entry only for a group that can
actually be an anchor — one of the company's top-level groups — because a nested user group can
never be an anchor and adding one would silently do nothing. An entry whose GUID no longer matches
a live group (the group was deleted in Tally) is reported in Data Quality as a stale allow-list
entry rather than being dropped.

The 28 reserved names equal the predefined groups' default display names, so the same stored string
resolves correctly both after G32 passes (matched on the exported reserved name) and before it does
(matched on the display name by the fallback).

Defaults are unchanged, and are stored in the `PREDEFINED` form: Sales = Sales Accounts;
Purchase = Purchase Accounts; Expense = Direct Expenses, Indirect Expenses;
Cash/Bank = Cash-in-Hand, Bank Accounts; Tax = Duties & Taxes.

**Worked examples**

| # | Situation | Anchor | Nature | Status | What the user sees |
|---|---|---|---|---|---|
| 1 | Ledger `Amazon Sales` under `Sales - Online - Marketplace` under `Sales - Online` under **Sales Accounts** | Sales Accounts | Income | RESOLVED | Counts as sales revenue, because Sales Accounts is in the Sales allow-list. Two levels of user groups roll up (ACC-7.1). |
| 2 | Ledger `Sharma Traders` under `Retail Customers` under **Sundry Debtors** (under Current Assets) | **Sundry Debtors**, not Current Assets | Asset | RESOLVED | A customer (ACC-7.6), and part of receivables. This is the case the literal SRS reading breaks. |
| 3 | Ledger `Solar Subsidy Receivable` under `Government Schemes`, a group the user created **directly under Primary** with nature Assets | `Government Schemes` itself | Asset (from Tally's own field, G14) | **RESOLVED** | In no allow-list, so it is in no sales/purchase/expense/cash/tax metric and is not a customer or supplier. Its balance still appears. Data Quality lists it under **"Groups not in any classification list"**, and an Owner/Admin can add `Government Schemes` to an allow-list. |
| 4 | Group `Project X` whose parent GUID is not among the company's groups, or a loop `A -> B -> A` | none | unknown | **UNRESOLVED_GROUP** | The group and every descendant are excluded from all classified metrics (ACC-7.4) and listed in Data Quality under "Unresolved groups". It re-resolves by itself on the next sync once the missing parent arrives (ACC-7.5). |
| 5 | The user renamed the predefined group `Sundry Debtors` to `Customers` | Sundry Debtors | Asset | RESOLVED | Unchanged behaviour: the reserved name identifies it (G32), so its ledgers stay customers. The dashboard shows the user's name, `Customers`. |

**Case 5 before G32 passes.** The fallback matches the 28 predefined groups by exact name, so a
renamed one would not be recognised and its ledgers would silently anchor one level up
(`Customers` under Current Assets would anchor to Current Assets, and those customers would
disappear from receivables). To make that visible rather than silent, Data Quality gains a
**"Predefined group possibly renamed"** check: any of the 28 names absent from the company's
groups while an unrecognised group sits directly under the matching parent. This check retires
when G32 passes.

**Where this departs from the SRS** (all three were unworkable as written):
- **ACC-7.1, 7.2, 7.6** say "primary group"; the anchor is the nearest *predefined* group instead.
- **ACC-7.3** says allow-lists hold primary groups only; they also hold predefined sub-groups, and
  now a company's own top-level groups.
- **ACC-7.4** marks a chain that "does not reach a primary group" as UNRESOLVED; that is narrowed
  to a *broken* chain (missing parent or loop), so case 3 stays usable instead of vanishing.

**Verify with:** G13 (every chain reaches a predefined group), G14 (nature on a user top-level
group), G32 (reserved name survives a rename).

### D-002 Voucher lines reference masters by GUID — PROPOSED (gate G30)
The voucher TDL emits the referenced master's GUID for every ledger entry, inventory entry and cost-centre allocation (in addition to the name). Ingest resolves by GUID. If G30 fails: resolve by exact name among the company's masters and log `UNKNOWN_MASTER_REFERENCE` on a miss.

### D-003 `company_id` on every child table — ACCEPTED
Follows SRS Principle 5.1-1. `voucher_entries`, `bill_allocations`, `cost_centre_allocations`, `voucher_items` carry `company_id` with composite indexes.

### D-004 Bill allocation shape — PROPOSED (gates G25, G31)
Bill identity is `(company_id, ledger_id, reference_name)`. `bill_allocations` adds `ledger_id` (denormalized from the entry), `allocation_type_raw`, normalized `allocation_type` (NEW_REF, AGST_REF, ADVANCE, ON_ACCOUNT, UNSUPPORTED) and `accounting_direction`. Index `(company_id, ledger_id, reference_name)`.

### D-005 Agent upload contract — ACCEPTED
The Agent parses Tally XML using the shared `tally_contract` package (SRS 21: "shares parsing code with the backend") and uploads normalized JSON records validated by Pydantic, versioned by `CONTRACT_VERSION`. The backend re-validates everything and never trusts the Agent's arithmetic (it re-checks voucher balance and sign consistency).

### D-006 API additions beyond SRS 19.2 — ACCEPTED
- `POST /companies`, `GET /companies`, `GET/PUT /companies/{id}`; CLI `python -m app.cli create-owner` to bootstrap the first user; `POST /auth/change-password`.
- `POST /companies/{id}/sync` with optional `agent_id` (auto-routes per RTE-1.1; otherwise 422 `AGENT_SELECTION_REQUIRED`). The per-agent path from 19.2 remains.
- Agent side: `POST /agent/commands/{id}/runs`, `POST /agent/leases/acquire|renew|release`, `POST /agent/commands/{id}/keylists`, `POST /agent/commands/{id}/reconciliation`, `POST /agent/commands/{id}/runs/{run_id}/finish`.
- `GET /companies/{id}/settings/custom-fields/tdl` (download generated UDF TDL include).

### D-007 Deletion-detection safety guard — PROPOSED
If a key list is empty while local records exist in its scope, or would mark more than `max(50, sync.keylist_max_missing_ratio × records in scope)` (default ratio 0.2) as missing in one run, nothing is changed; `KEY_LIST_SUSPICIOUS` is logged and shown in Data Quality. The next full reconciliation (or an Owner/Admin confirmation) applies it.

### D-008 Reconciliation compares like-for-like bases — PROPOSED
Each reconciliation metric has an explicit definition computed identically on both sides (documented in `docs/reconciliation-basis.md`, created in P10). Example: `SALES_CREDITS` = credits on Sales-class ledgers in non-cancelled Sales-base vouchers for the period, with no return adjustment, compared with the same local aggregation (not the Total Sales Revenue metric). Stock quantity reconciliation checks the stored snapshot against a fresh Tally closing quantity, because local data cannot recompute stock without inventory-only vouchers.

### D-009 Stock classification precedence — PROPOSED
Evaluate in this order; first match wins: (1) Not classified: stock ≤ 0 and no sale in period; (2) Never sold: no sale ever and stock > 0; (3) Fast; (4) Normal; (5) Dead: last sale ≥ `dead_stock_days` ago and stock > 0; (6) Slow: last sale > `slow_threshold_days` and < `dead_stock_days` ago; (7) gap case (stock > 0, last sale outside the period but within `slow_threshold_days`) → **Normal**, with `note = "no sale in selected period"`. Percentile = PostgreSQL `percentile_cont` over items with sales quantity > 0 in the period.

### D-010 Keys and numeric types — ACCEPTED
UUID primary keys for companies, users, agents, commands, schedules, masters, vouchers. BIGINT identity for voucher child rows, sync_errors, audit_logs, ai_tool_log, reconciliation_results. Money `NUMERIC(20,4)`; quantity and rate `NUMERIC(20,6)`.

### D-011 Agent credential format and hashing — ACCEPTED
Credential = `agt_<agent_id>.<secret>` where secret is 48 random bytes (url-safe). Stored as SHA-256(salt ‖ secret) with a per-agent random salt; verified with constant-time compare. bcrypt is not used here because the secret is high-entropy and verified every 30 s. Satisfies SEC-2.0a/b.

### D-012 Commands for REVOKED or INCOMPATIBLE Agents — ACCEPTED
Rejected at creation with 409 (`AGENT_REVOKED` / `AGENT_INCOMPATIBLE`). OFFLINE Agents still receive PENDING commands (RTE-1.6).

### D-013 Voucher paging by ALTERID windows — PROPOSED (IMPLEMENTATION TEST, gate G33)
The Agent pages vouchers by ALTERID window `(from, from + extraction_batch_size]`, which bounds a request to at most N changed objects. Fallback if G33 fails: page by voucher-date windows.

### D-014 Unknown master reference fails the chunk — ACCEPTED
A voucher referencing a master GUID not yet stored rolls back its commit chunk, the watermark does not advance, and the run is PARTIAL. The Agent always syncs masters before vouchers, so the next run resolves it. The error names the missing GUID.

### D-015 Anomaly minimum sample — PROPOSED (IMPLEMENTATION TEST)
The large-transaction rule needs at least 5 prior transactions for the party in the window; sample standard deviation is used.

### D-016 Defaults for OPEN business decisions — ACCEPTED as defaults
GST analytics out of v1 (taxable-value mode on). Journal entries excluded from cash flow (`cashflow.include_journal=false`). Fast-moving ranked by quantity with new setting `stock.fast_ranking_basis` (`quantity` | `value`). Godown/batch stock and profitability out of v1. Backup RPO ≤ 24 h / RTO ≤ 4 h as proposed values.

### D-017 Single scheduler firing — ACCEPTED
Scheduled jobs take a PostgreSQL advisory lock so multiple backend replicas never create duplicate commands.

### D-018 Frontend stack additions — ACCEPTED
TypeScript (strict), Vite, React Router, TanStack Query, openapi-typescript, Vitest + Testing Library, Playwright. (SRS 21 fixes React, Tailwind, Recharts.)

### D-019 Returns follow their own party and items — PROPOSED
A linked Sales Return is attributed to the customer on the credit note (same one-customer rule as ACC-6.1) and its inventory lines reduce product revenue and quantity. Keeps ACC-6.4 and FR-STK-6 consistent.

### D-020 Voucher dates are DATEs — ACCEPTED
Tally vouchers carry a date, not a time. `voucher_date` is `DATE`; TZ-1.x applies to "today", timestamps (sync times, exports, audit) and schedules. AC-62 is tested with a timestamp-based view (e.g. sync time and "today") and by confirming voucher dates are never shifted by the server time zone.

### D-021 Cash flow scope — OPEN
As specified, inflow/outflow count only Receipt/Payment vouchers (ACC-1.6/1.7). Cash or bank legs of Sales/Purchase vouchers (common for POS/cash sales) are not counted. Implemented as specified; ask the business whether a setting to include them is wanted.

### D-022 Opening bill allocations — PROPOSED (gate G31)
Add table `opening_bill_allocations` (company_id, ledger_id, reference_name, bill_date, due_date, amount_absolute, accounting_direction, financial_year_start) for bills outstanding at books-beginning, which Tally stores on the ledger master. Aging treats them as New References.

### D-023 Default schedules — PROPOSED
When a company's first Agent registers, create an hourly INCREMENTAL schedule and a daily RECONCILIATION schedule bound to it, inactive until the first FULL sync completes.

### D-024 Batch dedupe table — ACCEPTED
`sync_batches(batch_id PK, …)` records committed upload batches so a replayed batch returns the original result without reprocessing (upserts already make replays safe, SYNC-6.3).

### D-025 Agent Tally status columns — ACCEPTED
`agents.last_tally_status` and `agents.tally_status_since` store the Agent-reported Tally state (OK, TALLY_UNREACHABLE, TALLY_SERVER_DISABLED, TDL_NOT_LOADED, COMPANY_NOT_LOADED, COMPANY_MISMATCH) for the Agents view and failure messages.

### D-026 Chunk ordering — ACCEPTED
Records in an upload are sorted by ALTERID ascending; the backend commits chunks in order and stops at the first failed chunk, so the watermark never skips an uncommitted record.

### D-027 Uploads when another Agent holds the lease — ACCEPTED
A batch upload is accepted if the caller holds the collection lease or no unexpired lease is held (it is then re-acquired). If another Agent holds it, the upload gets 409 `SYNC_LOCKED` and stays in the local queue. Stale-record protection handles ordering (SYNC-4.4).

### D-028 Browser token storage — PROPOSED (review in P16)
Access token in memory; refresh token in `sessionStorage`; bearer headers only (so CSRF does not apply, SEC-1.5).

### D-029 Incremental sync before gates pass — ACCEPTED
With gate rows NOT_TESTED, incremental sync is allowed when `ALLOW_UNVERIFIED_INCREMENTAL=true` (default in dev/test) and forced to full-pull in prod (VAL-1.1). Any FAILED row forces full-pull everywhere (VAL-1.2).

### D-030 Error codes added beyond SRS v7.3 — ACCEPTED
The SRS defines 15 error codes (`TALLY_SERVER_DISABLED`, `TDL_NOT_LOADED`, `COMPANY_NOT_LOADED`, `COMPANY_MISMATCH`, `TALLY_EXPORT_TIMEOUT`, `QUEUE_FULL`, `SYNC_LOCKED`, `STALE_ALTERID`, `CREDENTIAL_INVALID`, `AGENT_REVOKED`, `UDF_NOT_FOUND`, `UNRESOLVED_GROUP`, `UNSUPPORTED_ALLOCATION_TYPE`, `UNLINKED_CREDIT_NOTE`, `UNLINKED_DEBIT_NOTE`). The 14 below are **additions not in SRS v7.3** (checked by searching the SRS text; none appear). They live in `tally_contract.errors.ErrorCode` marked `# not in SRS v7.3`.

| Code | Used for | Introduced in |
|---|---|---|
| `TALLY_UNREACHABLE` | Tally process not running / not reachable (distinct from `TALLY_SERVER_DISABLED`) | P7 |
| `DEBIT_CREDIT_IMBALANCE` | Voucher whose signed entries do not sum to zero | P4, P5 |
| `UNKNOWN_MASTER_REFERENCE` | Voucher line references a master not stored (D-002, D-014) | P5 |
| `PARSE_ERROR` | Per-record XML parse failure (SYNC-6.5) | P4 |
| `AGENT_SELECTION_REQUIRED` | More than one ACTIVE Agent and none chosen (D-006) | P3 |
| `AGENT_INCOMPATIBLE` | Agent below `MIN_AGENT_VERSION` / `MIN_TDL_VERSION` (D-012) | P3 |
| `INVALID_COMMAND_STATE` | Illegal command state transition or lost claim race | P3 |
| `KEY_LIST_SUSPICIOUS` | Deletion-detection safety guard (D-007) | P6 |
| `GATE_NOT_PASSED` | Batch claims an incremental window for a FULL_ONLY collection | P5 |
| `VALIDATION_ERROR` | Request body failed Pydantic validation (422) | P0 |
| `NOT_AUTHENTICATED` | Missing or invalid user token (401) | P0 |
| `FORBIDDEN` | Authenticated but not permitted (403) | P0 |
| `NOT_FOUND` | Resource does not exist (404) | P0 |
| `CONFLICT` | Generic 409 | P0 |

