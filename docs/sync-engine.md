# Sync engine (P5, P6)

How the backend stores what the Agent uploads, and what happens to records that leave Tally. Decisions: D-001, D-007, D-024, D-026, D-039, D-040, D-041. The Agent's side of the protocol is in `docs/agent-protocol.md`.

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

## Deletion detection by key list (`app/sync/keylists.py`, P6, D-007, D-041)
- **One definition.** A key list comes from the collection's key-only report, which repeats the same named TDL Collection as the data report: same filter (G34 for vouchers), same company and date variables, never an ALTERID window. Tests pin this (`shared/tests/test_tdl.py`, `test_requests.py`).
- **Staging.** `KeyListChunk`s (≤ 10,000 keys) go to `sync_key_list_keys`, idempotently, under the batch guard (RUNNING command and live lease). Once chunks 0..final are in, the list is evaluated in one transaction; its keys are then deleted and the `sync_key_lists` row stays as history. A run that closes first abandons its unfinished lists.
- **Evaluation.**
  1. **Reappeared:** every MISSING_IN_TALLY record with a key → ACTIVE, audited `REAPPEARED`, whatever its ALTERID and even if the guard fires.
  2. **Candidates:** ACTIVE records of the collection inside the list's window (vouchers by `voucher_date`; masters all). CANCELLED records and anything outside the window are never touched.
  3. **Guard:** an empty list with candidates, or more than `max(5, sync.keylist_max_missing_ratio × candidates)` missing → nothing marked, the list is SUSPICIOUS, `key_list_suspicious` is logged, and Data Quality shows it. An Owner/Admin confirmation (`POST /companies/{id}/sync/key-lists/{list_id}/confirm`) waives the guard once, for the next list of that collection.
  4. **Missing:** otherwise candidates without a key → MISSING_IN_TALLY, audited. Rows are never deleted; vouchers keep their links to missing masters (DR-ML-1/2).
  5. **Missed changes:** keys newer than the stored record but at or below the watermark lower the watermark (INCREMENTAL collections), so the next run re-pulls them.
- **Frequency.** `key_list_due` in the run plan: every `sync.key_list_interval` incremental runs (default 1).
- **Reappearance by a pull.** Every master and voucher chunk first restores the MISSING_IN_TALLY records it contains (`app/sync/lifecycle.py`), whatever their ALTERID: stale protection would otherwise treat an equal ALTERID as "no change" and leave them missing forever.
- **Self-healing.** A voucher whose date moved out of the window between the pull and the key list is marked missing, then restored by the next pull.

## Hierarchy (`app/sync/hierarchy.py`, P6, D-001, D-041 #7-8)
- Recomputed in the transaction of every GROUP, LEDGER and VOUCHER_TYPE chunk, under a per-company advisory lock.
- **Groups:** parent IDs come from parent GUIDs, so a reparent updates them. Each walk goes up to a predefined primary group (never reading its own parent) or to a group under Primary, with cycle detection. The anchor is the nearest predefined group, else the top-level group. Nature comes from the primary group, else from the top-level group's own Tally flags (G14; without them the group stays UNRESOLVED_GROUP). Only a broken chain (missing parent, loop) is UNRESOLVED_GROUP, and so is everything beneath it. Ledger caches refresh in one statement.
- **Voucher types:** the walk stops at the first predefined type. The 8 accounting types give their base type; other predefined types give OTHER (RESOLVED); a broken chain or no predefined type gives OTHER (UNRESOLVED).
- **Predefined records** are recognised by reserved name only once G32 has passed; before that, by exact default name. The "possibly renamed" Data Quality checks cover the gap.
- A change to an already RESOLVED group or voucher type is audited with before/after (ACC-7.5); a new record's first resolution is not.

## Data Quality (`app/services/data_quality.py`)
- A registry of checks. Each check is one SQL query whose count and paged rows are the view: `GET /companies/{id}/data-quality[/{check_id}]`. Later phases add theirs with `register(Check(...))`.
- P6 checks:
  - unresolved groups
  - groups not in any classification list
  - predefined group possibly renamed (before G32)
  - stale allow-list entries
  - unresolved voucher types (used by ACTIVE vouchers)
  - predefined voucher type possibly renamed (before G32)
  - missing masters
  - missing vouchers
  - suspicious key lists
  - imbalanced vouchers
  - unknown master references
  - sync held back by failing records
  - balance-sheet ledgers without an opening
