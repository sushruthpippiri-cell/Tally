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
The SRS defines 15 error codes (`TALLY_SERVER_DISABLED`, `TDL_NOT_LOADED`, `COMPANY_NOT_LOADED`, `COMPANY_MISMATCH`, `TALLY_EXPORT_TIMEOUT`, `QUEUE_FULL`, `SYNC_LOCKED`, `STALE_ALTERID`, `CREDENTIAL_INVALID`, `AGENT_REVOKED`, `UDF_NOT_FOUND`, `UNRESOLVED_GROUP`, `UNSUPPORTED_ALLOCATION_TYPE`, `UNLINKED_CREDIT_NOTE`, `UNLINKED_DEBIT_NOTE`). The 15 below are **additions not in SRS v7.3** (checked by searching the SRS text; none appear). They live in `tally_contract.errors.ErrorCode` marked `# not in SRS v7.3`.

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
| `RATE_LIMITED` | Too many requests (429): SEC-1.9 limits and the per-email login throttle (D-033) | P2 |


### D-031 Phase 1 schema choices not covered by the SRS — ACCEPTED (product owner, 2026-09-23)
Approved with the Phase 1 plan. See `docs/schema.md` for the resulting schema.

| # | Choice | Why |
|---|---|---|
| 1 | Every company-scoped reference is a composite FK `(company_id, x_id) → parent(company_id, x_id)`; referenced tables carry `UNIQUE(company_id, pk)` | A row can never point at another company's master, voucher, Agent or run (SEC-1.7 enforced by the database, not only by code). Child tables reach `companies` through these FKs. |
| 2 | `users`: unique index on `lower(email)` | `Owner@x` and `owner@x` are one account. |
| 3 | `agent_commands`: CHECK that a DATE_RANGE command has `date_from <= date_to`, both set | A malformed command cannot be queued. |
| 4 | `groups`: CHECK that a RESOLVED group has `classification_group_id` and `nature` | Only a broken chain may lack an anchor (D-001). |
| 5 | `ledgers.group_id` nullable (raw parent kept in `parent_group_tally_guid`); index `(company_id, classification_group_id)` | Mirrors groups for an unresolved parent; the anchor is what analytics filter on. |
| 6 | `amount_absolute >= 0` on `ledger_opening_balances` and `bill_allocations` | Same normalization rule as voucher entries (5.8). |
| 7 | `opening_bill_allocations`: `UNIQUE(company_id, ledger_id, financial_year_start, reference_name)` | Bill identity (D-004) per year; needed for idempotent upserts. |
| 8 | `sync_watermarks.status` ∈ NEVER_SYNCED, OK, FAILED (default NEVER_SYNCED); `last_alter_id` defaults to 0 | SRS 5.9 names the column but no values. |
| 9 | `sync_errors` and `sync_batches` carry `company_id` | SRS 5.1-1 (every company-scoped table). |
| 10 | `custom_field_mappings`: `mapping_id uuid` PK and `UNIQUE(company_id, collection_type, field_key)`; `collection_type` uses the 7 collection types | SRS 5.10 names no key. |
| 11 | `sync_errors.error_code` has no CHECK | `ErrorCode` grows by phase (D-030); a CHECK would need a migration each time. |
| 12 | `voucher_entries.amount_raw` is `text` | "Exactly as received" (5.8); only audit/debug views read it. |
| 13 | **Allow-list defaults are not seeded by the migration** (departs from P1.8's wording). They live once in `app/models/defaults.py` as tagged `PREDEFINED` entries; `company_settings` holds overrides only, and the P2 settings registry falls back to the defaults | `company_settings` is keyed by `company_id` and no company exists at migration time. This matches P2's "effective value with `is_default`". |
| 14 | The migration seeds `roles` only (OWNER=1, ACCOUNTANT=2, ADMIN=3) | 5.3. |

### D-032 Smaller schema choices made while implementing Phase 1 — ACCEPTED (product owner, 2026-09-23)
Not in the approved Phase 1 plan. Accepted after checking that none changes a business rule or
drops an SRS requirement: #4 applies SRS 5.8 ("amount_absolute: always non-negative") to two
more tables, and for #6 the SRS 5.4 "index company_id" on `agents` is served by the
`UNIQUE(company_id, agent_name)` index, whose leading column is `company_id`.

| # | Choice | Why |
|---|---|---|
| 1 | `ai_tool_log.status` ∈ SUCCESS, FAILED | SRS 5.10 names the column but no values; P1.1 requires a CHECK on status columns. Revisit in P15. |
| 2 | `agent_registration_tokens.token_hash` UNIQUE | Lookup by hash must find one token. |
| 3 | `agents.queue_status` is JSONB | The Agent reports several queue figures, not one value. |
| 4 | `cost_centre_allocations.amount_absolute >= 0` and `opening_bill_allocations.amount_absolute >= 0` | Same rule as item 6 of D-031. |
| 5 | `audit_logs` index `(company_id, created_at)` | The audit view lists a company's entries by time. |
| 6 | A plain `company_id` index is omitted where a unique/composite index already leads with `company_id` (agents, agent_commands, custom_field_mappings, opening_bill_allocations, reconciliation_results) | Redundant index; the SRS "index company_id" is still satisfied. A convention test enforces it. |
| 7 | The audit REVOKE in the migration names the role `tally_app` | Same role name as `deploy/postgres/grants.sql`; a different production role name would need both changed. |

### D-033 Phase 2 choices: auth, users, rate limits, settings shape — ACCEPTED (product owner, 2026-09-25)
Approved with the Phase 2 plan, including the owner's additions (items 4–9).

| # | Choice | Why |
|---|---|---|
| 1 | Passwords hashed with the `bcrypt` package directly, not passlib | passlib is unmaintained and breaks with current bcrypt releases. Same algorithm (SEC-1.1). |
| 2 | Table `refresh_tokens(jti, user_id, expires_at, used_at)` (migration 0002). A refresh marks its token used and issues a new pair; `change-password` closes all of the user's open tokens | A stateless JWT cannot be rotated: without a record of used tokens an old refresh token keeps working. |
| 3 | Rate limits (SEC-1.9) are an in-process fixed-window counter, not slowapi. Key = user id for a valid access token (1,000/min), else client IP (100/min); 429 with `Retry-After` | About 30 lines; no new dependency. Ceiling: per process, so N replicas allow N× the limit; move the counters to Postgres or Redis before running more than one replica. |
| 4 | **Refresh-token reuse** revokes every open refresh token of that user, is audited (`REFRESH_TOKEN_REUSE`, FAILURE) and returns 401 | A reused token was probably stolen, so both copies must stop working. |
| 5 | **Client IP**: `X-Forwarded-For` is honoured only when the direct peer is in `TRUSTED_PROXIES` (env, CIDR list, empty by default); the client is the rightmost address that is not itself a trusted proxy. Otherwise the peer address is used | Anyone can send `X-Forwarded-For`; trusting it blindly lets a client pick its own rate-limit bucket, and ignoring it puts every user behind a load balancer in one bucket. |
| 6 | **HTTPS** (SEC-1.3): the effective scheme is `X-Forwarded-Proto` only from a trusted proxy, else the connection's own scheme. In prod a non-https effective scheme gets 400; HSTS is sent in prod | Same reasoning as item 5: a spoofed header from an untrusted peer must not pass as https. |
| 7 | **Per-email login throttle**: 10 failed logins for one email in 15 minutes → 429 for that email until the window passes. The email is normalized (`strip().lower()`) for both lookup and throttle. The count is taken from `audit_logs` (`LOGIN`/`FAILURE` rows); throttled attempts are audited as `THROTTLED` and do not count, so the block always lapses 15 minutes after the 10th failure. The same answer is given for existing and unknown emails | Limits password guessing per account without letting an attacker lock an Owner out for good, and without revealing which emails exist. Counting audit rows needs no extra state and works across replicas. |
| 8 | **Adding a user whose email already exists** attaches that account to the company with the requested roles; the initial password is ignored | Roles are per company (RBAC-1.2); an accountant can serve several companies with one login. Anyone allowed to add users learns that the email is registered. |
| 9 | **Deactivating from a company** removes the user's roles in that company only; `users.is_active` is never changed by it (it stays a platform-level block). Roles are read from `user_roles` on every request, never from the JWT, so removal applies on the next request. A company always keeps at least one Owner: removing or downgrading the last Owner (including oneself) → 409. Every role change is audited | An Owner of company A must not be able to lock a user out of company B. |
| 10 | Settings `sync.incremental_interval` and `sync.full_reconciliation_interval` are stored as minutes (60, 1440); `sync.key_list_interval` as "every N incremental runs" (1) | SRS 18.2 gives "Hourly", "Daily" and "Every incremental run" as prose; numbers can be validated (> 0) and scheduled. |
| 11 | `GET /companies/{id}/settings` returns `{settings: {key: {value, is_default}}, feature_flags: {name: {enabled, is_default}}}`; `PUT` takes a partial `{settings?, feature_flags?}`, validates everything before writing anything, and rejects unknown keys (422). Cross-key rules: `stock.dead_stock_days > stock.slow_threshold_days` | SRS 19.2 has one "Settings and flags" endpoint. D-009 needs slow < dead. |
| 12 | A `COMPANY_GROUP` allow-list entry that names a predefined group is rejected (use the `PREDEFINED` form) | One stored form per group, so a rename or G32 fallback never gives two answers. |

### D-034 Financial year starts on day 1–28 of a month — PROPOSED
`financial_year_start` must fall on day 1–28 of a month; other days get 422. Every month has those
days, so financial-year and quarter boundaries (`app/core/periods.py`) always exist; a start of
31 January would otherwise give quarters starting "31 April". Indian companies use 1 April, so
this should never bite. Revisit if a real Tally company uses a later start day.
