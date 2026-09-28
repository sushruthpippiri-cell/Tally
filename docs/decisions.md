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

### D-002 Voucher lines reference masters by GUID — ACCEPTED (product owner, 2026-09-25; gate G30)
The voucher TDL emits the referenced master's GUID for every ledger entry, inventory entry and cost-centre allocation (in addition to the name); every record reference therefore carries both `*_guid` (optional) and `*_name`. Ingest resolves by GUID. If G30 fails, the fallback resolves **names against the masters synced in the same run**; an unknown name is logged as a sync error (`UNKNOWN_MASTER_REFERENCE`) and is never guessed.

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

### D-007 Deletion-detection safety guard — ACCEPTED (product owner, 2026-09-27, as amended by D-041 #3)
If a key list is empty while local records exist in its scope, or would mark more than `max(5, sync.keylist_max_missing_ratio × records in scope)` (default ratio 0.2) as missing in one run, nothing is changed; `key_list_suspicious` is logged and shown in Data Quality. An Owner/Admin confirmation lets the next key list apply (D-041 #3); P10's full reconciliation is the other route. The floor was 50; the owner lowered it to 5 so small collections are protected too.

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

### D-014 Unknown master reference fails the chunk — SUPERSEDED by D-039 #7
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

### D-027 Uploads when another Agent holds the lease — SUPERSEDED by D-039 #1
A batch upload is accepted if the caller holds the collection lease or no unexpired lease is held (it is then re-acquired). If another Agent holds it, the upload gets 409 `SYNC_LOCKED` and stays in the local queue. Stale-record protection handles ordering (SYNC-4.4).

### D-028 Browser token storage — PROPOSED (review in P16)
Access token in memory; refresh token in `sessionStorage`; bearer headers only (so CSRF does not apply, SEC-1.5).

### D-029 Incremental sync before gates pass — ACCEPTED
With gate rows NOT_TESTED, incremental sync is allowed when `ALLOW_UNVERIFIED_INCREMENTAL=true` (default in dev/test) and forced to full-pull in prod (VAL-1.1). Any FAILED row forces full-pull everywhere (VAL-1.2).

### D-030 Error codes added beyond SRS v7.3 — ACCEPTED
The SRS defines 15 error codes (`TALLY_SERVER_DISABLED`, `TDL_NOT_LOADED`, `COMPANY_NOT_LOADED`, `COMPANY_MISMATCH`, `TALLY_EXPORT_TIMEOUT`, `QUEUE_FULL`, `SYNC_LOCKED`, `STALE_ALTERID`, `CREDENTIAL_INVALID`, `AGENT_REVOKED`, `UDF_NOT_FOUND`, `UNRESOLVED_GROUP`, `UNSUPPORTED_ALLOCATION_TYPE`, `UNLINKED_CREDIT_NOTE`, `UNLINKED_DEBIT_NOTE`). The 18 below are **additions not in SRS v7.3** (checked by searching the SRS text; none appear). They live in `tally_contract.errors.ErrorCode` marked `# not in SRS v7.3`.

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
| `HTTPS_REQUIRED` | Plain-HTTP request rejected in prod (400, SEC-1.3, D-033 #6) | P2 |
| `CHUNK_FAILED` | An upload chunk that could not be written; it holds the watermark (D-040 #5) | P5 |
| `AGENT_LOST` | A sync run closed because its command's lease lapsed (D-040 #3) | P5 |


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
| 3 | Rate limits (SEC-1.9) are an in-process fixed-window counter, not slowapi. Key = user id for a valid access token (1,000/min), else client IP (100/min); 429 with `Retry-After` | About 30 lines; no new dependency. Ceiling: per process, so N replicas allow N× the limit; move the counters to Postgres or Redis before running more than one replica — required task P16.11. |
| 4 | **Refresh-token reuse** revokes every open refresh token of that user, is audited (`REFRESH_TOKEN_REUSE`, FAILURE) and returns 401 | A reused token was probably stolen, so both copies must stop working. |
| 5 | **Client IP**: `X-Forwarded-For` is honoured only when the direct peer is in `TRUSTED_PROXIES` (env, CIDR list, empty by default); the client is the rightmost address that is not itself a trusted proxy. Otherwise the peer address is used | Anyone can send `X-Forwarded-For`; trusting it blindly lets a client pick its own rate-limit bucket, and ignoring it puts every user behind a load balancer in one bucket. |
| 6 | **HTTPS** (SEC-1.3): the effective scheme is `X-Forwarded-Proto` only from a trusted proxy, else the connection's own scheme. In prod a non-https effective scheme gets 400; HSTS is sent in prod | Same reasoning as item 5: a spoofed header from an untrusted peer must not pass as https. |
| 7 | **Per-email login throttle**: 10 failed logins for one email in 15 minutes → 429 for that email until the window passes. The email is normalized (`strip().lower()`) for both lookup and throttle. The count is taken from `audit_logs` (`LOGIN`/`FAILURE` rows); throttled attempts are audited as `THROTTLED` and do not count, so the block always lapses 15 minutes after the 10th failure. The same answer is given for existing and unknown emails | Limits password guessing per account without letting an attacker lock an Owner out for good, and without revealing which emails exist. Counting audit rows needs no extra state and works across replicas. |
| 8 | **Adding a user whose email already exists** attaches that account to the company with the requested roles; the initial password is ignored | Roles are per company (RBAC-1.2); an accountant can serve several companies with one login. Anyone allowed to add users learns that the email is registered. |
| 9 | **Deactivating from a company** removes the user's roles in that company only; `users.is_active` is never changed by it (it stays a platform-level block). Roles are read from `user_roles` on every request, never from the JWT, so removal applies on the next request. A company always keeps at least one Owner: removing or downgrading the last Owner (including oneself) → 409. Every role change is audited | An Owner of company A must not be able to lock a user out of company B. |
| 10 | Settings `sync.incremental_interval` and `sync.full_reconciliation_interval` are stored as minutes (60, 1440); `sync.key_list_interval` as "every N incremental runs" (1) | SRS 18.2 gives "Hourly", "Daily" and "Every incremental run" as prose; numbers can be validated (> 0) and scheduled. |
| 11 | `GET /companies/{id}/settings` returns `{settings: {key: {value, is_default}}, feature_flags: {name: {enabled, is_default}}}`; `PUT` takes a partial `{settings?, feature_flags?}`, validates everything before writing anything, and rejects unknown keys (422). Cross-key rules: `stock.dead_stock_days > stock.slow_threshold_days` | SRS 19.2 has one "Settings and flags" endpoint. D-009 needs slow < dead. |
| 12 | A `COMPANY_GROUP` allow-list entry that names a predefined group is rejected (use the `PREDEFINED` form) | One stored form per group, so a rename or G32 fallback never gives two answers. |

### D-034 Financial year starts on day 1–28 of a month — ACCEPTED (product owner, 2026-09-25)
`financial_year_start` must fall on day 1–28 of a month; other days get 422. Every month has those
days, so financial-year and quarter boundaries (`app/core/periods.py`) always exist; a start of
31 January would otherwise give quarters starting "31 April". Indian companies use 1 April, so
this should never bite. Revisit if a real Tally company uses a later start day.

### D-035 Phase 3 choices: command lifecycle, registration, lease timing — ACCEPTED (product owner, 2026-09-25)
Approved with the Phase 3 plan, including the owner's additions (items 11–14).

| # | Choice | Why |
|---|---|---|
| 1 | `agent_commands.error_code` (migration 0003) | The result call carries an error code (P3.8); FAILED_AGENT_LOST and EXPIRED record theirs. |
| 2 | Every Agent-side transition (progress, result) needs an unexpired lease; a lapsed lease is final even before the lost-Agent job runs | AGT-1.8 says the command becomes FAILED_AGENT_LOST once the deadline passes; the job and a late call can never both win. |
| 3 | Claim rejects a PENDING command already past the claim timeout | AGT-1.10, even before the expiry job has run. |
| 4 | COMPLETED only from RUNNING; FAILED from CLAIMED or RUNNING | An Agent can fail right after claiming (e.g. COMPANY_MISMATCH) but cannot complete work it never started. |
| 5 | A Tally GUID already bound to another platform company → 409 `COMPANY_MISMATCH` | `companies.tally_guid` is unique; one Tally company belongs to one account. |
| 6 | Commands are delivered only to ACTIVE Agents | REGISTERING has not confirmed its GUID; INCOMPATIBLE receives none (VER-1.2). |
| 7 | D-023 default schedules: `0 * * * *` INCREMENTAL and `0 2 * * *` RECONCILIATION, in `company_timezone`, inactive until the first FULL sync | Concrete values for D-023. |
| 8 | APScheduler 3.x runs the jobs and parses cron | One dependency for interval jobs and cron evaluation (P3.10). |
| 9 | Registration and heartbeat return one `config` object (poll interval, progress interval, command lease, batch size, Tally host/port/company, expected TDL version, per-collection sync mode) | SRS 4.2 step 8; settings changes reach the Agent on its next heartbeat. |
| 10 | `GET /companies/{id}/commands/{command_id}` | AGT-1.6: command status visible as it changes. |
| 11 | **Lease vs long Tally exports**: default command lease `agent.command_lease_seconds` = 300 s; the Agent sends progress every 60 s (`progress_interval_seconds`); the lease setting must be ≥ 180 s. The Agent (P7) sends progress **on its own timer, independent of any Tally request in flight** (`docs/agent-protocol.md`) | One Tally request can take 10 minutes and is retried once (AGT-4.3); progress tied to request completion would turn a healthy sync into FAILED_AGENT_LOST. |
| 12 | A progress call also updates `last_heartbeat_at` | An Agent busy with a long sync is never marked OFFLINE. |
| 13 | **One command per Agent at a time**: a heartbeat never hands out a command while that Agent has one CLAIMED or RUNNING, and the database enforces it with a partial unique index `agent_commands(agent_id) WHERE status IN ('CLAIMED','RUNNING')`; a claim that hits it → 409 `INVALID_COMMAND_STATE` | A `NOT EXISTS` check in the claim is not race-proof: two claims of different rows can both pass under READ COMMITTED. |
| 14 | The committing test fixture refuses to TRUNCATE unless the database name ends in `_test` (same guard as the phase report) | Concurrency tests really commit; the cleanup must never reach the dev database. |

### D-036 Deterministic command order, schedule firing, routing and Agent replacement — ACCEPTED (product owner, 2026-09-25)
Prompted by a flaky P3.6 test: "oldest PENDING command" was not deterministic when two commands
shared a `created_at`. Fixed in the product, not only the test.

| # | Choice | Why |
|---|---|---|
| 1 | `agent_commands.created_at` is set from the app clock (the one-clock rule); a new `seq BIGINT GENERATED ALWAYS AS IDENTITY` breaks ties. "Oldest" is always `ORDER BY created_at, seq` (migration 0004) | `now()` in SQL is the transaction start, so two commands in one transaction tied and the order fell to a random UUID. |
| 2 | Schedules carry `next_fire_at`; the job fires every active schedule with `next_fire_at <= now` once, then sets the next occurrence in `company_timezone`. Missed runs during downtime coalesce into one command | One indexed query per tick; no burst of stale commands after an outage. |
| 3 | When several schedules fire at the same moment for the same Agent, commands are created in the order INCREMENTAL, FULL, DATE_RANGE, RECONCILIATION (same `created_at`, increasing `seq`) | At 02:00 the hourly INCREMENTAL and the daily RECONCILIATION both fire; reconciliation must compare against the latest data. |
| 4 | Schedules of REVOKED or INCOMPATIBLE Agents advance without creating a command (logged); OFFLINE Agents still get PENDING commands (RTE-1.6) | D-012: such Agents cannot receive commands. |
| 5 | **One-Agent companies**: "eligible" = not REVOKED or INCOMPATIBLE. With exactly one eligible Agent, "Sync Now" without `agent_id` targets it even when OFFLINE or REGISTERING; the command waits with "Waiting — Agent offline since …" or "Waiting — Agent has not connected yet". With several eligible Agents: exactly one ACTIVE → it, else 422 `AGENT_SELECTION_REQUIRED` (RTE-1.1/1.2). None eligible → 422 `AGENT_SELECTION_REQUIRED` "No Agent can take commands; register one" | Asking an Owner to choose from a list of one is confusing; RTE-1.6 already covers a waiting command. |
| 6 | **Replacing an Agent keeps scheduled syncs working**: revoking an Agent deactivates its schedules in the same transaction (audited `SCHEDULE_DEACTIVATED`); registration creates the D-023 default schedules whenever the company has no schedule belonging to a non-revoked Agent (not only for the first Agent), so a replacement gets them and a standby beside a working Agent does not; the Agents view warns `NO_ACTIVE_SCHEDULE` when an ACTIVE Agent exists but no schedule is active. P5 activates a new Agent's default schedules after its first FULL sync (`docs/plan/phase-05-sync-engine.md`) | Replacing an Agent must not silently stop scheduled syncs. |

### D-037 GST analytics are out of scope for v1 — ACCEPTED (product owner, 2026-09-25)
Confirms the SRS 8.15 default (and D-016) before the voucher TDL Collection is finalised, as 8.15
requires. The voucher Collection emits no tax detail (no rate, HSN/SAC or CGST/SGST/IGST split);
tax ledgers arrive as ordinary ledger entries and are classified through
`classification.tax_groups`. Revenue and purchases are reported at taxable value. Bringing GST
into scope later needs a `tax_details` table, TDL extensions and new requirements (SRS 8.15).

### D-038 Live-Tally capture kit and two more gates — ACCEPTED (product owner, 2026-09-25)
| # | Choice | Why |
|---|---|---|
| 1 | Live captures are taken with a **PowerShell-only capture kit** (`tools/capture_kit/`, built by `make capture-kit`), run inside a Windows 11 ARM VM with TallyPrime using only built-in Windows tools. It replaces the Python `tally_probe` of gate-track step G-A; analysis happens on the Mac (step G-E) | The capture machine must need nothing installed. |
| 2 | The kit saves raw response bytes, a `meta.json` per request, and a zip of each run into one folder that can be shared with the Mac; its first step (`check`) only verifies that Tally's XML server is reachable, the company is open and the project TDL is loaded | Captures must be exact evidence (VAL-1.3), and setup problems must show up before anything else. |
| 3 | A minimal TDL (`tdl/TA_Minimal.tdl`, only `TallyAnalyticsInfo`) is loaded first, then the full one; the README says where TallyPrime reports TDL errors and exactly what to copy back. A failing report during capture is saved and the run continues | The TDL has never been loaded into a real Tally, so the first load may fail. |
| 4 | Reference evidence (TEST-4.1): the kit captures TallyPrime's built-in reports (Trial Balance, Day Book, Stock Summary, List of Accounts); an optional section runs tally-database-loader with file output so only Node.js is needed | Nothing to install for the main kit; TEST-4.1 can still be met as worded. |
| 5 | Captures come from a **dedicated test company only**, never a real business's books | Captured responses are committed to the repository. |
| 6 | New gates (not in SRS v7.3): **G34** the voucher Collection excludes order and inventory-only vouchers (SRS 1.3); **G35** Tally's error-response text (unknown report, company not loaded), response encoding and invalid XML characters | Both are Tally facts the parser and TDL rely on; rule 15 requires them to be gated. |
| 7 | Windows CI jobs run only when files they depend on change (path filters, separate workflow); the Linux `check` job runs on every push | Windows runners cost twice the Linux rate on a private repo; running out of minutes would stop CI and block every phase. |

### D-039 Sync engine: batch acceptance, watermarks, failed records, openings — ACCEPTED (product owner, 2026-09-27)
| # | Choice | Why |
|---|---|---|
| 1 | **A batch is accepted only while its command is RUNNING and the caller holds an unexpired lease on the collection** (no implicit re-acquire), its run belongs to that command and is IN_PROGRESS. Re-verified inside every chunk transaction: the chunk locks the watermark row `FOR UPDATE` and the command row `FOR SHARE`, so the lost-Agent job or a takeover waits for the chunk in flight and every later chunk sees it and stops. Supersedes D-027 | A lost Agent must never write alongside the Agent that took over; a late batch from a lost command changes nothing. |
| 2 | **Watermarks** move only where no record can be skipped: an ALTERID-windowed batch (ascending, D-013/D-026) advances per committed chunk to `GREATEST(watermark, chunk max)`; a DATE_RANGE run never moves it (its records are still upserted); a FULL pull paged by date moves it once, when the Agent reports the collection complete, to the collection's max ALTERID **as read before the pull started** — and not at all if that pre-pull max is unavailable (G33 not passed) | Departs from SRS 6.1's wording for date ranges: moving to the highest ALTERID a date-range run saw would skip changes outside its dates, and a record edited during a long date-paged pull gets an ALTERID below the end-of-pull max. |
| 3 | A command `progress` call also renews every sync lease the Agent holds, with TTL `agent.command_lease_seconds`; a command `result` releases them | One timer (D-035 #11): an Agent that stops sending progress loses its command and its leases together. |
| 4 | Until P6's resolver runs, new groups are stored `UNRESOLVED_GROUP` and new voucher types `OTHER` / `UNRESOLVED`; parents by GUID, IDs filled when the parent is present | The resolver needs the whole chain; P6 re-resolves after every sync. |
| 5 | **Opening balances (ledger and stock openings, opening bills) are stored as at the company's books-beginning date** (`companies.books_from`, taken from the COMPANY batch; tagged GATE-G16). LEDGER and STOCK_ITEM batches are refused until it is known. The `financial_year_start` column of the opening tables holds that date. **For P8:** a balance-sheet ledger's balance on any date D = its books-beginning opening + all ACTIVE movements from `books_from` to D | The opening on a Tally ledger master is as at books beginning, not the current year; a company holding several years of books then gets correct balances without a separate opening per year, instead of "opening balance unavailable" (ACC-9.6) after the first year. |
| 6 | A COMPANY batch whose GUID is not `companies.tally_guid` is refused with `COMPANY_MISMATCH` | Defence in depth for AGT-3.2. |
| 7 | **A record that fails never stalls its chunk and never lets the watermark pass it.** A failing record (an unknown master reference after GUID-then-exact-name resolution, a failed balance re-check, a database error on that record, or an Agent-side parse error) is skipped; the other records are stored; `sync_errors` gets its GUID and ALTERID; the run is PARTIAL; the watermark stays **below the lowest failed ALTERID** (`watermark_hold` = ALTERID − 1), or at its pre-batch value when the failing record's ALTERID is unknown, so the next run retries it. Data Quality shows "sync held back by N failing records" (errors whose hold is at or above the current watermark). Supersedes D-014 | Rolling back a whole chunk for one bad reference contradicts SYNC-6.5 and can stall a collection; skipping a record and moving past it would lose it silently. |
| 8 | Audit rows `VOUCHER_MODIFIED` (header fields, voucher total, entry summary before/after) and `VOUCHER_CANCELLED` | LOG-1.1 (system changes to vouchers); AC-02. |

### D-040 Sync runs: how they end, first FULL sync, full-only collections, snapshots — ACCEPTED (product owner, 2026-09-27)
| # | Choice | Why |
|---|---|---|
| 1 | **One `close_run` decides how a run ends**, for `finish`, the command `result` and the lost-Agent job. Agent reports COMPLETED → PARTIAL if the run has any sync error classified **NOT_STORED**, else COMPLETED. Agent reports FAILED → PARTIAL if anything was committed (`records_fetched > 0`), else FAILED. Every code that can be written to `sync_errors` is classified explicitly as NOT_STORED (data not stored or a collection not synced) or INFO (`SYNC_ERROR_KIND` in `app/sync/context.py`); an unclassified code cannot be written, and a test fails if one appears | SYNC-6.4 / AC-05: a run that fails part-way is PARTIAL. Owner: PARTIAL means data was not stored or a collection was not synced; `UDF_NOT_FOUND` on every run (DR-UDF-3) must not make every run PARTIAL. |
| 2 | `finish` takes `problems: [{collection_type, code, message}]` for a collection skipped with `SYNC_LOCKED`, a segment that hit `TALLY_EXPORT_TIMEOUT`, or `TALLY_UNREACHABLE`; each becomes a `sync_errors` row without a watermark hold | Every PARTIAL reason is queryable in `/sync/errors`. |
| 3 | **`on_command_lost`**, in the lost job's transaction: closes the command's open runs through `close_run` as FAILED (so PARTIAL when chunks had committed), writes an `AGENT_LOST` sync error, releases every lease the Agent holds | Owner-approved deviation from "fail the run": AC-05 records a run that failed part-way as PARTIAL. |
| 4 | The command `result` also closes the command's open runs | A missed `finish` never leaves a run IN_PROGRESS. |
| 5 | A chunk that fails with an exception writes `CHUNK_FAILED` with `watermark_hold` = the watermark before that chunk | Its records are known only as a range; a later batch in the same run must not move the watermark past them (D-039 #7). |
| 6 | **First FULL sync (owner rule).** An Agent's inactive default schedules (`created_by IS NULL`) are activated, audited `SCHEDULE_ACTIVATED`, when its first FULL run ends COMPLETED **or PARTIAL** (no earlier FULL run of that Agent with either status). A FAILED first FULL leaves them off. `INITIAL_SYNC_INCOMPLETE` shows in sync status and the Agents view while the company has a finished run but none COMPLETED | After a PARTIAL full, incremental runs pull never-synced collections in full, resume from watermarks and retry held records, so scheduling is safe. A FAILED full stored nothing and usually needs the Owner (Tally unreachable, TDL not loaded, wrong company). Either way the company is never left with no automatic sync and no warning. |
| 7 | **Full-only collections (owner rule, VAL-1.2, AC-12).** The plan always asks for a full pull; batches with a `DATE` window or none are accepted in any run, including a scheduled INCREMENTAL. Only an `ALTER_ID`-windowed batch for a FULL_ONLY collection is refused (409 `GATE_NOT_PASSED`, nothing written). `release(complete)` never advances a FULL_ONLY collection's watermark | Its ALTERIDs are unverified; the watermark stays NEVER_SYNCED, so once the gate passes the first run is a full pull. A scheduled sync must not fail every hour. |
| 8 | **Stock snapshots** come in a batch with `collection_type = null`, need a RUNNING command and the Agent's live `STOCK_ITEM` lease (checked per chunk), and are upserted on `(stock_item_id, as_of_date)` with `sync_run_id`. An unknown item → `UNKNOWN_MASTER_REFERENCE`, no hold. They are not recorded in `sync_batches`; a replay repeats the same upsert. Closing balances and reconciliation totals → 422 until P10 | FR-STK-15; snapshots have no watermark. |

### D-041 Deletion detection, reappearance, hierarchy resolution — ACCEPTED (product owner, 2026-09-27)
| # | Choice | Why |
|---|---|---|
| 1 | **Key lists** come as `KeyListChunk`s (`POST /agent/commands/{id}/key-lists`): `list_id`, `chunk_seq`, `is_final`, up to 10,000 `(GUID, ALTERID)` keys, and a `window` (a DATE window, VOUCHER only; null = the whole collection). Accepted under the batch rule (RUNNING command, live lease on the collection, D-039 #1). Chunks are staged idempotently (`sync_key_list_keys`) and the list is evaluated in one transaction once chunks 0..final are in; its keys are then deleted and the `sync_key_lists` row stays as history. A run that closes first abandons its unfinished lists | Lists can be large; staging makes chunks replay-safe and evaluation atomic. |
| 2 | **One definition (owner).** A key list is requested with `requests.collection(keys_only=True)`: the same company, date variables and (always 0/0) ALTERID window as the data request, only the report differs, and every `*Keys` Part repeats the data report's own Collection, so filters such as G34's are shared, never copied. A windowed key request is refused | A key list and the pull it is compared with must agree on what is included, or records outside one filter would be marked missing. |
| 3 | **Evaluation.** Candidates are ACTIVE local records of that collection **inside the window** (vouchers by `voucher_date`; masters all); those without a key → MISSING_IN_TALLY, audited. Records outside the window are never touched. **Guard (D-007):** an empty list with candidates, or more than `max(5, ratio × candidates)` missing → nothing marked, the list is SUSPICIOUS, logged, in Data Quality. `POST /companies/{id}/sync/key-lists/{list_id}/confirm` (MANAGE_SETTINGS, audited) waives the guard once, for the **next** list of that collection (a fresh one, never the stale list) | Owner: a truncated key list must never mark records missing; small collections need the ratio too; a real bulk deletion needs one confirm. |
| 4 | **Reappearance does not depend on ALTERID (owner).** A MISSING_IN_TALLY record present in a key list (anywhere, even when the guard fires) or in a pulled chunk (higher, equal or lower ALTERID) → ACTIVE, audited `REAPPEARED` | Stale protection treats an equal ALTERID as "no change", so a record wrongly marked missing would otherwise stay missing forever. |
| 5 | **Missed changes.** Keys whose ALTERID is above the stored one (or unknown locally) yet at or below the watermark mean a change was skipped: for an INCREMENTAL collection the watermark is lowered to the lowest such ALTERID − 1 so the next run re-pulls them; logged `key_list_missed_change` | Lowering a watermark only costs a re-pull (equal ALTERIDs are no-ops); a skipped change would otherwise be lost. |
| 6 | **Frequency (SYNC-5.4)** keeps D-033's meaning: `sync.key_list_interval` = every N incremental runs (default 1). The run plan's `key_list_due` is true when the collection has no evaluated list yet, or N−1 INCREMENTAL runs of the company started after its last evaluated list | One meaning, as D-033 and the settings registry already define it. |
| 7 | **GATE-G32:** a record's `reserved_name` is used only when G32 PASSED; before that the 28 group names and the 8 accounting voucher-type names are matched by exact name. **GATE-G14:** a group's own nature comes from its flags (`IsRevenue` + `IsDeemedPositive` → EXPENSE; `IsRevenue` only → INCOME; `IsDeemedPositive` only → ASSET; neither → LIABILITY) into `groups.own_nature`; a user top-level group without them stays UNRESOLVED_GROUP (a RESOLVED group needs a nature) | Rule 15: unverified Tally facts switch behaviour through gates with a safe default; a guessed nature would put balances on the wrong side. |
| 8 | **Hierarchy** is recomputed in each GROUP, LEDGER and VOUCHER_TYPE chunk's own transaction (per-company advisory lock): parent IDs from parent GUIDs (a reparent updates them), the group forest walked with cycle detection and stopping at predefined primary groups, ledger caches refreshed in one statement. Voucher-type walks stop at the first predefined type. A change to a group or voucher type that was already RESOLVED is audited with before/after; a new placeholder's first resolution is not | No committed chunk leaves a stale parent or anchor (ACC-7.5); walks never read a predefined record's own parent, which Tally may report oddly (G12, G15). |
| 9 | Data Quality is a registry of checks (`app/services/data_quality.py`), each one SQL query giving count and items, so later phases register theirs. The two "possibly renamed" checks (groups; the 8 accounting voucher types used by ACTIVE vouchers) run only while G32 is not PASSED | A renamed predefined group or "Sales" type would otherwise silently drop figures to zero. |
| 10 | Not in P6: DR-ML-5 (INACTIVE) waits for G29; SYNC-5.3 is P10's reconciliation | No Tally fact yet. |

**Review against the reference implementation (SYNC-5.5, 2026-09-27).** The reference is tally-database-loader (github.com/dhananjay1405/tally-database-loader, MIT, SRS 1.5), reviewed from its public source at commit `6aae17d` (2026-08-02): `src/tally.mts` (`importData`, incremental branch), `tally-export-config-incremental.yaml`, `docs/incremental-sync.md`. It is guidance only (SRS 1.5): nothing below is treated as confirmed Tally behaviour. No code was copied.

What it does:
- **Deletions are detected only in its optional "incremental" mode.** Its default "full" mode truncates and reloads every table, so deleted records simply do not come back. Its own documentation calls incremental sync less safe and recommends full sync.
- **The check runs only when the company-level AlterIDs changed.** Each run first reads the company's `$AltMstId` / `$AltVchId`. If neither differs from the stored values it stops, deletion check included.
- **The key list comes from the same definition as the data pull.** For each "Primary" table (groups, ledgers, voucher types, stock items, cost centres, vouchers and others) it pulls a key list (`_diff`: GUID, AlterID) of the whole collection, using the same Collection and the same filter list as the data pull (vouchers: `NOT $IsCancelled`, `NOT $IsOptional`), with no AlterID filter and no date window beyond the company's period.
- **Absent rows are hard-deleted.** Local rows whose GUID is absent go to `_delete` and are deleted, with their child tables (`cascade_delete`). Rows whose AlterID differs are deleted too and re-imported by the following AlterID-filtered pull.
- **There is no safety guard, no soft status and no reappearance handling.** We found none in the source: an empty or truncated key list is applied as it is. A record deleted locally by mistake returns only when its AlterID next changes, or on a full reload.

How ours compares:
- **Same definition.** Both take the key list from the same Collection and filter as the pull, never AlterID-windowed. Ours pins this with tests (#2).
- **Stronger on the points below**, each a deliberate difference, not a gap:
  - **Trigger.** Ours runs every N incremental runs (#6) whether or not the company AlterIDs moved, so it does not depend on a deletion raising `$AltVchId` (G11, unverified).
  - **Guard.** Ours never applies an empty or implausibly short list (D-007, #3); the reference would delete everything a truncated list omits.
  - **Soft status.** Ours marks records MISSING_IN_TALLY, audited, and keeps them (DR-ML-1/2); the reference hard-deletes, which would also drop masters that past vouchers use.
  - **Reappearance.** Ours restores any listed or pulled record whatever its ALTERID (#4); the reference's mistaken deletions persist until the AlterID changes or a full reload.
  - **Scope.** Ours may limit a voucher list to a date window and then touches only records inside it (#3); the reference always lists the whole collection.
- **Equivalent on missed modifications.** The reference deletes and re-imports on any AlterID difference; ours lowers the watermark so the next pull re-fetches (#5).
- **Different on cancellation, by design.** The reference excludes cancelled vouchers from both pull and key list, so a cancelled voucher is deleted locally. Ours keeps it as CANCELLED (SRS 6.7, G9), and our voucher Collection excludes only optional and non-accounting vouchers (G34).
- **Broader master coverage there.** The reference also lists units, godowns, stock groups and cost categories. We do not sync those masters (SRS 1.3), so there is nothing to detect.
- **Conclusion.** No gap found in our mechanism; nothing changed. The reference's reliance on company AlterIDs to trigger the check is a design to avoid unless G11 shows that deletions raise `$AltVchId`.

### D-042 Tally Sync Agent design — ACCEPTED (product owner, 2026-09-27)
| # | Choice | Why |
|---|---|---|
| 1 | **Threads, not asyncio.** A main loop thread, an uploader thread draining the queue, and a **progress thread** per running command that calls `/progress` every `progress_interval_seconds` and never waits on Tally or the parser; a progress 409 sets an abort event the executor checks between steps. Tally calls use a synchronous httpx client with the 10-minute timeout | Owner: progress runs on its own timer, independent of any Tally request in flight (agent-protocol.md); a slow export or a CPU-bound parse must not starve it. Threads fit a pywin32 service. |
| 2 | **Streaming, bounded memory.** The parser gains a streaming form (`parse()` stays a list wrapper). The executor writes upload envelopes of `upload_batch_records` (default 500) to the SQLite queue inside the window's transaction and commits the window only once the whole document parsed, so a malformed document leaves nothing behind. Records are staged on disk and read back in ALTERID order (D-026), and the parser feeds the XML in 64 KB slices (no second full copy): a 5,000-voucher window peaks at about 1.3× its XML. Full pulls without ALTERID windows go by date pages, a month at a time, halved when a page returns more than `extraction_batch_size` records or times out | Owner: never accumulate a large Tally response's records (P4 measured about 19 KB per parsed voucher); P4's "never half a response" rule is kept. |
| 3 | **Secrets.** The Agent credential (and optional proxy credentials) is stored only with **Windows DPAPI in machine scope** (`CRYPTPROTECT_LOCAL_MACHINE`) with Agent-specific entropy, in `<data_dir>\credential.bin`; never in `agent.toml`. Confidentiality comes from the `data_dir` ACL: the service account (`NT SERVICE\TallyAgent`, a virtual account, not LocalSystem), SYSTEM and Administrators, inheritance off. The Agent sets it on creation and checks it at start; the installer does the same with `icacls`. Off Windows (development, CI) a `0600` file, refused if anyone else can read it. `set-credential` reads a hidden prompt, never an argument. **Required P7.9 real-machine check:** encrypt as the installing user, decrypt as the service account | Owner: `register` and `set-credential` run in the installing person's account while the service runs as its own account, so DPAPI user scope would pass CI (same account both ways) and fail on every real install. Administrators are in the ACL because the elevated CLI must write the file and an administrator can take ownership of any file anyway; no other local user can read it (AGT-2.6). **Confirmed by the owner 2026-09-28: Administrators stay in the ACL.** |
| 4 | **Customer networks.** TLS verification uses certifi's roots plus an optional `ca_bundle` (PEM, additive, never replacing), TLS ≥ 1.2 (SEC-2.0), and an optional `proxy_url` (HTTP CONNECT; basic credentials stored with DPAPI via `set-proxy-credentials`). `agent.toml` is a strict model, so no key can turn verification off, and a source test forbids `verify=False`, `CERT_NONE` and `check_hostname = False`. `backend_url` must be `https://` (plain HTTP only for a loopback host). The Tally client never uses a proxy. NTLM/Kerberos proxies are not supported | Owner: office antivirus and firewalls intercept HTTPS; supporting their CA and proxy must never mean switching checks off. |
| 5 | **Dates come from the backend.** The run plan carries `as_of` (today in `company_timezone`) and the start of date-paged full pulls (`books_from`); the Agent uses them for the stock snapshot date and every date window. The PC's clock is used only locally (timers, backoff, queue age), and ages are reported as durations. The backend refuses a stock snapshot dated after its own today | Owner: the PC's clock isn't trusted for anything the backend compares. |
| 6 | **Queue under D-039.** Batches upload strictly in order per (run, collection), so the watermark never passes a gap. A batch dead-lettered after 20 failures (AGT-2.5) takes the rest of that run and collection with it into `deadletter.jsonl`: reported, never dropped, and re-pulled next run from the backend's watermark. A 409 saying the command is no longer running makes that run's remaining batches obsolete: removed with a log entry and a count, and re-pulled next run. A refusal that can never succeed (a 4xx other than 401 and 409) is dead-lettered at once instead of retried 20 times, which would hold the whole queue for hours. The queue therefore bridges outages shorter than the command lease; longer ones cost a re-pull, never data | D-039 accepts a batch only while its command is RUNNING; uploading out of order could move the watermark past a failed batch. |
| 7 | **TDL version.** The TDL version Tally reports must equal the version bundled with this Agent build (`tally_constants.TDL_VERSION`); otherwise `TDL_NOT_LOADED`, naming both. The backend keeps enforcing only a minimum (VER-1.2) | Owner: the Agent and its TDL ship together; comparing with the backend's minimum breaks as soon as a newer TDL is released. |
| 8 | **Code signing** of the Agent build and its installer is a required Phase 16 task (P16.8a) | Owner: unsigned PyInstaller executables are often blocked by SmartScreen and antivirus. |

### D-043 Agent rate limits, 429 handling, the Windows service — ACCEPTED (product owner, 2026-09-28)
| # | Choice | Why |
|---|---|---|
| 1 | **Each Agent has its own rate-limit bucket**, `agent:<agent_id>`, at 1,000 requests per window (the authenticated-user limit of SEC-1.9). The bucket is granted only to a credential that has verified: `current_agent` records `sha256(credential) → agent_id` in a process-local cache (10-minute TTL, bounded), and the middleware looks the bearer up there. An unknown or forged `agt_…` token, or the very first request of a new or rotated credential, stays in its IP's bucket (100/min). The limit and the window length are settings (`agent_rate_limit`, `rate_limit_window_seconds`) so tests can shrink them. Same per-process ceiling as D-033 #3 (P16.11) | Owner: an Agent credential is not a user JWT, so every Agent request fell into its office IP's anonymous bucket; after an outage the uploader would hit 429 at once and starve everything else behind that IP. Keying on the unverified id would let forged tokens mint fresh buckets. |
| 2 | **A 429 is never a failure.** The Agent's client raises `RateLimited(retry_after)`; the uploader defers the item until `Retry-After` (with jitter) without counting an attempt, so a rate-limited batch is never dead-lettered; the progress thread and the heartbeat treat a 429 as a temporary outage; the executor's other calls wait `Retry-After` and retry, up to 5 times | Owner: a 429 means "slow down", not "never". |
| 3 | **Windows service:** pywin32 `ServiceFramework` (`tally_agent.winservice`), NSSM documented as the fallback. A PyInstaller one-folder x64 build with `tally-agent.exe` (CLI) and `tally-agent-service.exe`, built only by the manual `agent-build` workflow; installed by `Install-TallyAgent.ps1` as `NT SERVICE\TallyAgent`, delayed-automatic start, restart on failure. **IMPLEMENTATION TEST — pending** the owner's real-machine checklist (`docs/agent-windows-checklist.md`), and to be repeated on a real x64 PC before launch (P16) | The service, its virtual account and DPAPI across accounts can only be proven on Windows itself. |
| 4 | Uninstalling or retiring a PC: the Agent must be **revoked in the dashboard**; the uninstaller leaves the data directory (queue for inspection, the encrypted credential) and says so | The credential file stays on disk; revocation is what makes it useless. |
