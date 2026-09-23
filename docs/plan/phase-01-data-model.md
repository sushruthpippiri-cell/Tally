# Phase 1 — Data model & migrations

**Size:** M · **Depends on:** P0 · **SRS:** 5 (all), 6.6, SEC-1.13, SEC-1.15
**Requirements:** DR-4.1–4.6, DR-ML-1, DR-UDF-2 (storage), ACC-DATA-1 (storage), RTE-1.4
**Decisions:** D-001, D-003, D-004, D-010, D-020, D-022, D-024, D-025

## Goal
Every table in SRS Section 5, plus the additions in `docs/decisions.md`, exists as a typed SQLAlchemy model and one hand-reviewed Alembic migration. Constraints and triggers make the key invariants impossible to violate at the database level.

## Read first
SRS Section 5 (all subsections) and 6.6 · `docs/decisions.md` entries listed above

## Tasks

### P1.1 Model conventions — `app/models/base.py`, `app/models/enums.py`
- Constraint naming convention so autogenerate output is deterministic.
- Types: `Money = Numeric(20, 4)`, `Quantity = Numeric(20, 6)`, `Rate = Numeric(20, 6)`; timestamps `timestamptz` (UTC); `voucher_date` and all business dates `date`.
- Status and enum columns: `text` + CHECK constraint generated from a Python StrEnum defined once in `enums.py`.
- Mixin `TallySynced`: `company_id`, `tally_guid text not null`, `alter_id bigint not null`, `status`, `last_synced_at`, `UNIQUE(company_id, tally_guid)` (DR-4.6).
- Keys per D-010.

### P1.2 Company and access (5.3)
`companies`, `users`, `roles` (seed OWNER, ACCOUNTANT, ADMIN in the migration), `user_roles`. `companies.tally_guid` is UNIQUE and nullable until the first Agent registers.

### P1.3 Agents, commands, schedules (5.4)
- `agents`: every SRS column plus `credential_salt`, `last_tally_status`, `tally_status_since` (D-025). `UNIQUE(company_id, agent_name)`. Status CHECK: REGISTERING, ACTIVE, OFFLINE, INCOMPATIBLE, REVOKED.
- `agent_commands`: `agent_id NOT NULL`; a trigger rejects any UPDATE that changes `agent_id` or `company_id` (RTE-1.4). Status CHECK with the 7 SRS states. Indexes `(agent_id, status)` and `(status, created_at)` for the expiry job.
- `agent_registration_tokens`, `sync_schedules` as specified.

### P1.4 Masters (5.5 + D-001)
- `groups`: SRS columns plus `predefined_group_id` (nearest predefined ancestor, including self; nullable), `classification_group_id` (the D-001 anchor: `predefined_group_id`, else the chain's top-level group; nullable only for a broken chain), `nature` (from the primary group, or from Tally's own field for a user top-level group, G14), `is_predefined bool`, `reserved_name text null`, `resolution_status` (RESOLVED | UNRESOLVED_GROUP), `parent_tally_guid text null` (raw parent reference kept until resolved).
- `ledgers`: SRS columns plus cached `classification_group_id` and `predefined_group_id`, `is_bill_wise bool null`, `parent_group_tally_guid text`.
- `voucher_types`: SRS columns plus `resolution_status`, `reserved_name`, `parent_tally_guid`; `base_voucher_type` CHECK (SALES, PURCHASE, RECEIPT, PAYMENT, CONTRA, JOURNAL, CREDIT_NOTE, DEBIT_NOTE, OTHER).
- `stock_items`, `cost_centres` as specified.
- Master status CHECK: ACTIVE, MISSING_IN_TALLY, INACTIVE.
- No closing-balance column on `ledgers` (5.5 note).

### P1.5 Opening balances and snapshots (5.6 + D-022)
`ledger_opening_balances`, `stock_opening_balances`, `stock_snapshots` with the SRS primary keys; `opening_bill_allocations` per D-022.

### P1.6 Vouchers and children (5.7 + D-003, D-004)
- `vouchers`: SRS columns, `voucher_date date`, status CHECK (ACTIVE, CANCELLED, MISSING_IN_TALLY); SRS indexes plus `(company_id, voucher_type_id, voucher_date)`.
- `voucher_entries`: plus `company_id`. CHECKs: `amount_absolute >= 0`; direction in (DEBIT, CREDIT); `amount_signed = CASE WHEN accounting_direction='DEBIT' THEN amount_absolute ELSE -amount_absolute END`; `is_debit = (accounting_direction = 'DEBIT')`. Indexes `voucher_id`, `(company_id, ledger_id)`.
- `bill_allocations`: plus `company_id`, `ledger_id`, `allocation_type_raw`, `allocation_type` CHECK (NEW_REF, AGST_REF, ADVANCE, ON_ACCOUNT, UNSUPPORTED), `accounting_direction`; indexes `(company_id, ledger_id, reference_name)`, `due_date`.
- `cost_centre_allocations`, `voucher_items`: plus `company_id`.
- Child FKs use `ON DELETE CASCADE` (used only by child replacement, 6.9).
- A trigger raises on `DELETE` from `vouchers` and from every master table (5.1-5, DR-ML-1). Tests clean up with `TRUNCATE`, which row triggers do not block.

### P1.7 Sync control (5.9 + D-024)
`sync_watermarks` (PK company_id + collection_type; CHECK on the 7 SRS collection types), `sync_runs`, `sync_errors`, `reconciliation_results`, and `sync_batches` (batch_id uuid PK, sync_run_id, collection_type, batch_seq, committed_at, accepted, rejected_stale, error_count).

### P1.8 Configuration, audit, anomaly (5.10, 5.11)
- `feature_config` (enabled boolean only), `company_settings` (`setting_value jsonb`, `data_type`), `custom_field_mappings`.
- `audit_logs`: JSONB `before_value`/`after_value`; trigger raising on UPDATE/DELETE; `tally_app` granted INSERT and SELECT only (SEC-1.13).
- `anomaly_flags` with `UNIQUE(voucher_id, rule_triggered)`; `ai_tool_log`.

### P1.9 Migration
One initial migration, hand-reviewed. Grants for `tally_app`. `alembic upgrade head` and `alembic downgrade base` both succeed on an empty database.

### P1.10 Test factories — `backend/tests/factories.py`
Builders every later phase uses (amounts passed as strings, converted to Decimal):
- `make_company(fy_start=date(2024, 4, 1), tz="Asia/Kolkata")`
- `make_predefined_groups(company)` → Tally's 28 predefined groups with correct parents (list in `phase-06-lifecycle-hierarchy.md`)
- `make_group(company, name, parent)`, `make_ledger(company, name, group, opening=None)`
- `make_voucher_type(company, name, base=None, parent=None)`
- `make_voucher(company, vtype, date, entries=[("Customer A", "DEBIT", "10000"), ("Sales", "CREDIT", "10000")], items=[...], bills=[...], status="ACTIVE")`, which fills the normalized fields and refuses unbalanced input.

## Tests
- Upgrade/downgrade on an empty database.
- For each synced table: duplicate `(company_id, tally_guid)` rejected; the same GUID or voucher number in two companies accepted (DR-4.4, DR-4.6).
- CHECK constraints reject negative `amount_absolute`, inconsistent `amount_signed`/`is_debit`, unknown status values.
- DELETE on vouchers or masters raises; UPDATE/DELETE on `audit_logs` raises; changing `agent_commands.agent_id` raises.
- Connected as `tally_app`, `CREATE TABLE` fails (SEC-1.15).

## Definition of done
All tests pass; `docs/schema.md` contains a Mermaid ER diagram of the schema; any schema choice not covered by an existing decision is recorded as a new D-entry.

## Out of scope
Business logic, endpoints, sync behaviour.

## Kickoff prompt
~~~text
Read CLAUDE.md, docs/plan/phase-01-data-model.md, docs/decisions.md and SRS Section 5 (grep docs/srs/SRS_v7_3.md). In plan mode, list every table and column you will create, marking which come from a D-entry rather than the SRS, plus the triggers, constraints and the factory API. Wait for approval, then implement P1.1–P1.10 with tests first, commit per task, and update docs/progress.md.
~~~
