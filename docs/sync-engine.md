# Sync engine (P5)

How the backend stores what the Agent uploads. Decisions: D-024, D-026, D-039, D-040. The Agent's side of the protocol is in `docs/agent-protocol.md`.

## A batch, step by step (`app/sync/ingest.py`)
1. **Contract and replay.** The contract's major version must match. A `batch_id` already committed returns its stored result and writes nothing (SYNC-6.3).
2. **Refusals that write nothing.**
   - an `ALTER_ID` window for a full-only collection → `GATE_NOT_PASSED`
   - a parse-error code that isn't classified → 422
   - a run that is not this command's → 404
3. **Guard** (D-039 #1). The command must be RUNNING, the run IN_PROGRESS, and the Agent must hold a live lease on the collection. Snapshots use the `STOCK_ITEM` lease.
4. **Chunks** of `sync.db_commit_batch` records (default 500), one transaction each (SYNC-6.1). Each chunk:
   1. re-runs the guard under row locks: the command `FOR SHARE`, the watermark row `FOR UPDATE`
   2. writes the records
   3. records stale rows and failures in `sync_errors`
   4. updates the run's counters
   5. moves the watermark (below)

   So a lost command or a takeover waits for the chunk in flight, and every later chunk is refused.
5. **A chunk that raises** is rolled back and the batch stops (D-026). `CHUNK_FAILED` is written with a watermark hold at the pre-chunk watermark (D-040 #5).
6. `sync_batches` is written only when every chunk committed.

## Records
- **Stale protection** (SYNC-3.x). A pre-read of the stored ALTERIDs decides what to log: lower → `STALE_ALTERID`, equal → nothing, higher → write. `INSERT … ON CONFLICT (company_id, tally_guid) DO UPDATE … WHERE stored.alter_id < excluded.alter_id` enforces the rule even under races.
- **One SAVEPOINT per record.** A failing record never takes its chunk with it (D-039 #7). The failures:
  - an unknown master reference: GUID first, then exact name (D-002)
  - an unbalanced voucher
  - a database error on that record
  - an Agent parse error

  Each is skipped and recorded with its GUID and ALTERID.
- **Vouchers** (`app/sync/vouchers.py`, SRS 6.9). A higher ALTERID updates the header, then replaces the children in one transaction:
  1. bill and cost-centre allocations
  2. entries
  3. items
  4. bulk insert of the current children

  Per-line updates (DR-VE-2) wait for GATE-G24. Audit rows: `VOUCHER_MODIFIED` (before/after totals and entries), `VOUCHER_CANCELLED`.
- **Masters** (`app/sync/masters.py`).
  - Parents are stored by GUID and linked when present.
  - Groups and voucher types stay UNRESOLVED until P6.
  - Openings (ledger, stock, opening bills) are stored as at `companies.books_from` (GATE-G16), so LEDGER and STOCK_ITEM batches wait for the COMPANY batch.
  - A COMPANY GUID that isn't this company's → `COMPANY_MISMATCH`.
- **Snapshots** (`app/sync/snapshots.py`). Upserted on `(stock_item_id, as_of_date)`. No watermark.

## Watermarks (`sync_watermarks`, one row per company and collection)
- **Independent per collection** (SYNC-1.1).
- **`ALTER_ID`-windowed batches** move the watermark per committed chunk, in that chunk's transaction, to `max(watermark, chunk max)` (SYNC-1.2).
- **`DATE` windows never move it.**
- **A FULL pull paged by date** moves it only on `release(complete, start_max_alter_id)`, to the max ALTERID read *before* the pull. Without that value (G33 not passed), and for full-only collections, it doesn't move.
- **Holds** (`app/sync/holds.py`).
  - Each failure stores `watermark_hold`: the failed record's ALTERID − 1, the pre-batch watermark when the ALTERID is unknown, or the pre-chunk watermark for a failed chunk.
  - Within a run, the lowest hold caps every watermark move for that collection. The next run therefore starts below the failure and retries it; a permanent failure never lets the watermark pass.
  - `held_back()` feeds "sync held back by N failing records" (P6.6, P13.9).

## Leases (`app/sync/leases.py`)
- **Acquire** is a compare-and-set UPDATE on the watermark row: free, expired, or already mine → take it; otherwise `SYNC_LOCKED`, naming the holder (SYNC-4.1/4.2).
- **TTL** is `agent.command_lease_seconds`. Command progress renews every lease the Agent holds; the command result, `finish` and the lost-Agent job release them (SYNC-4.3).
- **Leases and stale protection are both needed** (SYNC-4.4). The lease keeps a second writer out; stale protection keeps old data out when a writer takes over later.

## How a run ends (`app/services/sync_runs.py:close_run`, D-040)
- **Classification.** Every code that can reach `sync_errors` is classified in `SYNC_ERROR_KIND` (`app/sync/context.py`) as NOT_STORED or INFO. `error_row` refuses an unclassified code, and `tests/sync/test_error_kinds.py` finds every code the source can write.
- **Reported COMPLETED** → PARTIAL if the run has a NOT_STORED error, else COMPLETED.
- **Reported FAILED** → PARTIAL if anything was committed (SYNC-6.4, AC-05), else FAILED (SYNC-6.6: nothing changed).
- **Callers.** `finish`, the command `result` and `on_command_lost` all use this rule. The lost-Agent job also records `AGENT_LOST` and releases the Agent's leases.
- **First FULL sync.** An Agent's first FULL run ending COMPLETED or PARTIAL activates its inactive default schedules, audited `SCHEDULE_ACTIVATED`; a later one never does. `INITIAL_SYNC_INCOMPLETE` shows while no run has COMPLETED.

## Status APIs (`/companies/{id}/sync/…`)
- `status`: per collection, the mode ("Full sync only", AC-12), watermark, last success, live lease holder and held-back count, plus the last run and warnings.
- `runs`: newest first, paged by `before`.
- `errors`: VIEW_LOGS, filtered by run and code.
- `lease-status`.
- Custom-field mappings and their generated TDL: `/settings/custom-fields[/tdl]`, MANAGE_CUSTOM_FIELDS.
