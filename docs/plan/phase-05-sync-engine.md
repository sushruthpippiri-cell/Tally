# Phase 5 — Sync engine core (backend ingest)

**Size:** L (split: P5.1–P5.5, then P5.6–P5.10) · **Depends on:** P3, P4
**SRS:** 6.1–6.6, 6.9, 5.9, 16 (sync rows), 19.2 (sync status rows)
**Requirements:** SYNC-1.1–1.3, SYNC-3.1–3.5, SYNC-4.1–4.4, SYNC-6.1–6.6, DR-4.1–4.6, DR-VE-2–4, VAL-1.1–1.2, NFR-REL-2
**Acceptance:** AC-01, AC-02, AC-05, AC-06, AC-07, AC-08, AC-09, AC-12 · **Decisions:** D-006, D-014, D-024, D-026, D-027, D-029

## Goal
The backend accepts uploaded batches and stores them exactly once, never partially, never older-over-newer, with independent per-collection watermarks and a lease that prevents two Agents writing the same collection.

## Tasks

### P5.1 Agent sync API (D-006)
- `POST /agent/commands/{id}/runs` → creates `sync_runs` row (IN_PROGRESS) and returns `sync_run_id` plus a plan: for each collection `{mode: INCREMENTAL|FULL_ONLY (from gates.py), watermark}`.
- `POST /agent/leases/acquire {collection_type, sync_run_id}` — compare-and-set on the watermark row (insert the row first if missing):
  ```sql
  UPDATE sync_watermarks
     SET locked_by_agent_id = :agent, lock_acquired_at = now(), lock_expires_at = now() + :ttl
   WHERE company_id = :company AND collection_type = :type
     AND (locked_by_agent_id IS NULL OR lock_expires_at < now() OR locked_by_agent_id = :agent)
  RETURNING last_alter_id, lock_expires_at;
  ```
  No row → 409 `SYNC_LOCKED` with the holder's Agent name (SYNC-4.2).
- `POST /agent/leases/renew`, `POST /agent/leases/release`; expired leases are reclaimable automatically (SYNC-4.3).
- `POST /agent/commands/{id}/batches` (SRS 19.2) accepts a `BatchEnvelope`; lease rule per D-027.
- `POST /agent/commands/{id}/runs/{run_id}/finish {status, notes}`.

### P5.2 Ingest pipeline — `app/sync/ingest.py`
- Validate `contract_version` compatibility and collection type; replayed `batch_id` → return the stored result from `sync_batches` (D-024).
- Split records into chunks of `sync.db_commit_batch` (500); each chunk is one transaction (SYNC-6.1). Process chunks in ALTERID order and **stop at the first failed chunk** (D-026).
- Record `parse_errors` from the envelope into `sync_errors`.
- Counters into `sync_runs.records_fetched` / `records_failed`.

### P5.3 Master upserts with stale protection (SYNC-3.x)
- For each chunk, pre-read stored alter_ids: `SELECT tally_guid, alter_id … WHERE company_id = :c AND tally_guid = ANY(:guids)`. Classify: new, higher (apply), equal (skip, SYNC-3.3), lower (reject, `STALE_ALTERID` to `sync_errors`, SYNC-3.2).
- Write with `INSERT … ON CONFLICT (company_id, tally_guid) DO UPDATE … WHERE <table>.alter_id < EXCLUDED.alter_id` so the database enforces the rule even under races.
- Resolve references after upsert within the chunk (group `parent_tally_guid` → `parent_group_id`; ledger → group; voucher type → parent). Unresolved parents stay NULL for P6's resolver.
- Opening balances (ledger, stock, opening bills) upserted by their primary keys in the same transaction as their master.

### P5.4 Voucher writer — `app/sync/vouchers.py`
- Each voucher inside a SAVEPOINT (SYNC-6.2, DR-VE-4).
- Resolve `ledger_guid`, `stock_item_guid`, `cost_centre_guid`, `voucher_type_guid`. Missing → `UNKNOWN_MASTER_REFERENCE`; the whole chunk rolls back (D-014).
- Re-check balance (defence in depth, D-005) → `DEBIT_CREDIT_IMBALANCE`: voucher not written, error logged, chunk continues.
- New GUID → insert header + children, status ACTIVE (or CANCELLED if `is_cancelled`).
- Higher ALTERID → child replacement in the SRS 6.9 order: update header; delete bill and cost-centre allocations of its entries; delete entries; delete items; insert current children. If gate G24 passed, use per-line update by `stable_line_id` instead (DR-VE-2) — implement behind a strategy switch, default replacement.
- Modified voucher → `audit.record(system, "VOUCHER_MODIFIED", before, after)` with header fields, voucher total (Σ debit `amount_absolute`) and an entry summary (ledger, direction, amount), so AC-02's ₹10,000 → ₹15,000 is visible.
- Bulk inserts for children (`insert().values([...])` or asyncpg `copy_records_to_table`); target ingest ≥ 500 vouchers/s on the benchmark hardware (PERF-1.2 budget).

### P5.5 Watermarks (SYNC-1.x)
- In the same transaction as each committed chunk: `last_alter_id = GREATEST(last_alter_id, :max_alter_id_of_chunk)`, `last_successful_sync_at = now()` (SYNC-1.2).
- DATE_RANGE runs move the watermark only for records beyond it (SRS 6.1).
- Watermarks are per `(company_id, collection_type)` (SYNC-1.1, AC-07).

### P5.6 Stock snapshots
Upsert `stock_snapshots` by `(stock_item_id, as_of_date)` with `sync_run_id` (FR-STK-15 data path; analytics in P12).

### P5.7 Run bookkeeping and recovery
- Finish → COMPLETED, PARTIAL (any chunk failed, any segment timed out, any collection skipped with SYNC_LOCKED) or FAILED (SYNC-6.4).
- Implement P3's `on_command_lost` hook: run → FAILED, leases held by that Agent released.
- Tally unreachable reported by the Agent → run FAILED, no data changed (SYNC-6.6).
- **REQUIRED (D-036 #6): activate a new Agent's default schedules after its first FULL sync.** When a FULL run completes (COMPLETED) for an Agent that has no earlier COMPLETED FULL run, call `app.services.schedules.activate()` on that Agent's **inactive, system-created** schedules (`created_by IS NULL`), in the same transaction, and audit each as `SCHEDULE_ACTIVATED` (system actor, reason "first full sync"). Only on the first FULL run, so a schedule an Owner deactivated on purpose is never switched back on. P3 already creates the defaults for a company's first Agent and for a replacement after a revoke, deactivates a revoked Agent's schedules, and warns `NO_ACTIVE_SCHEDULE` in the Agents view; without this item a new company or a replaced Agent never syncs on a timer.

### P5.8 Sync status APIs
- `GET /companies/{id}/sync/status`: per collection watermark, last success, mode (`INCREMENTAL` or `FULL_ONLY`, shown as "Full sync only", AC-12), lease holder.
- `GET /companies/{id}/sync/runs` (paginated), `GET /companies/{id}/sync/errors` (VIEW_LOGS; filter by run, code), `GET /companies/{id}/sync/lease-status`.
- `GET /companies/{id}/settings/custom-fields/tdl` (P4.6 generator) and `GET/PUT /companies/{id}/settings/custom-fields` (MANAGE_CUSTOM_FIELDS, audited).

### P5.9 Full-pull-only enforcement (VAL-1.1, VAL-1.2)
Plans for FULL_ONLY collections always request a full pull; batches claiming an incremental window for such a collection are rejected with `GATE_NOT_PASSED`.

### P5.10 Tests
- AC-01: full sync of the synthetic dataset twice → identical row counts, keyed by `(company_id, GUID)`.
- AC-02: voucher at ₹10,000 then ALTERID+1 at ₹15,000 → local ₹15,000; audit has old and new.
- AC-05: failure injected at chunk 100 of 200 → PARTIAL, watermark = last committed chunk's max, rerun completes with no duplicates.
- AC-06: stored ALTERID 108, incoming 106 → unchanged, `STALE_ALTERID` logged; equal → no change, no error.
- AC-07: voucher watermark 500, ledger watermark 50 → each plan uses its own; a ledger change is not skipped.
- AC-08: modified voucher → no orphaned or duplicate child rows (count and FK checks).
- AC-09 / TEST-3.1: two Agents acquire the same lease concurrently → exactly one succeeds, the other gets SYNC_LOCKED.
- AC-12: gate row FAILED → plan FULL_ONLY and status shows "Full sync only".
- TEST-3.3: exception injected between entry insert and bill-allocation insert → voucher entirely absent (new) or entirely previous version (modified).
- SYNC-6.3: same batch posted twice → identical database state.
- DR-4.4: same voucher number in two companies and across two financial years → no collision.
- D-036 #6 replacement path: Agent A scheduled → revoke A → register B → B's first FULL sync completes → B's default schedules are active and `fire_schedules` creates B's command; a second FULL run does not re-activate a schedule the Owner turned off.

## Definition of done
All listed tests pass; `docs/sync-engine.md` explains chunking, stale protection, watermarks, leases and child replacement in a page, for P6/P7 sessions.

## Kickoff prompt
~~~text
Read CLAUDE.md, docs/plan/phase-05-sync-engine.md, docs/agent-protocol.md, docs/decisions.md (D-006, D-014, D-024, D-026, D-027, D-029, D-036) and SRS Sections 5.9, 6.1–6.6, 6.9. In plan mode, propose the ingest pipeline, the exact SQL for lease CAS, stale-protected upserts and watermark updates, and the tests for AC-01, 02, 05–09, 12. Implement P5.1–P5.5, stop and update docs/progress.md; P5.6–P5.10 in the next session. Tests first, commit per task.
~~~
