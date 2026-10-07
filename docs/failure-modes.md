# Failure modes (SRS 16)

One row per condition in SRS Section 16, with the test that proves it. Written in P16.4.

A row's **Proved by** names a test that exercises the behaviour, not merely the error code or a
helper that enables it. Where the behaviour can only be confirmed outside this repository
(Windows, a real TallyPrime, hosting), the row says so and points at
`docs/manual-verification.md` with the blocker named, rather than leaving the cell empty.

Error codes come from `tally_contract.errors.ErrorCode`. One naming trap worth stating: SRS 16's
"Incompatible Agent or TDL version" row says `INCOMPATIBLE`, which is an **`AgentStatus`**, not
an error code — the code is `AGENT_INCOMPATIBLE`. A mechanical code-to-row mapping gets that one
wrong.

| # | Condition | Detection | Behaviour | What the user sees | Proved by |
|---|---|---|---|---|---|
| 1 | Tally closed | Agent cannot connect | Nothing pulled; no data changed | "Tally unreachable since …" | `agent/tests/test_tally_client.py` (`TALLY_UNREACHABLE`), `backend/tests/api/test_agent_management.py` |
| 2 | Windows user logged off | Agent cannot connect | As above | "Tally not running — the Windows user may have logged off" | `agent/tests/test_tally_client.py`; the process check is `AGT-6.3`. **The message on a real logged-off session is a manual check** — `docs/manual-verification.md`, needs the Windows VM |
| 3 | Tally XML server disabled | Connection refused | `TALLY_SERVER_DISABLED` | Message naming the Tally setting | `agent/tests/test_tally_client.py::test_a_refused_connection_is_told_apart_by_the_process_table` (parametrised over both) |
| 4 | Required TDL not loaded | Unknown report response | `TDL_NOT_LOADED`; no fallback | Configuration error | `shared/tests/parser/test_parser.py::test_report_not_found_means_tdl_not_loaded`, and the Agent never falls back (CLAUDE.md rule 12) |
| 5 | Named company not loaded | Targeted request fails | `COMPANY_NOT_LOADED`; nothing pulled | Warning on the Agent | `shared/tests/parser/test_parser.py::test_company_not_open_means_company_not_loaded` |
| 6 | Company mismatch | GUID check fails | `COMPANY_MISMATCH`; sync halted | Warning on the Agent | `backend/tests/api/test_agent_registration.py`, `agent/tests/test_agent_sync.py` |
| 7 | Tally export stalls | No response within timeout | Retry at half batch, then fail the segment | Run PARTIAL, `TALLY_EXPORT_TIMEOUT` | `agent/tests/test_tally_client.py`, `agent/tests/test_agent_sync.py` |
| 8 | Long Tally uptime | Uptime above threshold | Sync continues; advisory raised | "Restart recommended" | `backend/tests/api/test_reconciliation_api.py::test_the_uptime_advisory_is_prominent_after_a_failed_reconciliation`, `backend/tests/api/test_heartbeat.py` |
| 9 | Malformed XML | Parser error | Record logged in `sync_errors`; batch continues | Run PARTIAL with error count | `shared/tests/parser/test_parser.py::test_one_bad_record_fails_alone_and_the_rest_parse`, `::test_malformed_xml_is_logged_and_never_raises` |
| 10 | Debit/credit inconsistency | Normalized entries do not balance | Voucher not written; flagged | Listed in Data Quality | `backend/tests/sync/test_ingest_vouchers.py` (`DEBIT_CREDIT_IMBALANCE`), `backend/tests/api/test_data_quality.py` |
| 11 | Agent loses internet | Upload fails | Local queue, backoff retries | "Last contact …" | `agent/tests/test_queue.py::test_retries_back_off_from_30_seconds_doubling_to_15_minutes_with_jitter`, `::test_nothing_is_ever_dropped_silently` |
| 12 | Agent queue full | Queue limit reached | Pulling stops; uploads keep retrying | `QUEUE_FULL` | `agent/tests/test_queue.py::test_the_queue_is_full_at_its_record_limit_or_when_its_oldest_item_is_too_old` |
| 13 | Agent crashes | Heartbeats stop | Agent OFFLINE; running command becomes `FAILED_AGENT_LOST` | Agent offline; command failed | `backend/tests/jobs/test_agent_jobs.py`, `backend/tests/jobs/test_command_jobs.py::test_a_running_command_past_its_lease_is_lost_and_never_reassigned` |
| 14 | Selected Agent offline | No recent heartbeat | Command stays PENDING | "Waiting — Agent offline since …" | `backend/tests/jobs/test_command_jobs.py::test_offline_agent_command_waits_labelled_and_is_claimed_on_return`, `::test_pending_expires_after_the_company_claim_timeout` |
| 15 | Several Agents, none chosen | Request lacks `agent_id` | Request rejected | Agent selector shown | `backend/tests/api/test_commands.py` (`AGENT_SELECTION_REQUIRED`), `frontend/e2e/pages.spec.ts` (AC-18 UI) |
| 16 | Two Agents sync the same collection | Lease already held | Second gets `SYNC_LOCKED` | "Sync in progress by …" | `backend/tests/races/test_lease_races.py`, `backend/tests/sync/test_runs_and_leases.py` |
| 17 | Duplicate command claim | Compare-and-set fails | Second claim rejected | None | `backend/tests/api/test_command_lifecycle.py::test_a_command_can_be_claimed_once` |
| 18 | Stale record | Lower ALTERID | Rejected, `STALE_ALTERID` | Sync log entry | `backend/tests/sync/test_ingest_vouchers.py`, `backend/tests/sync/test_ingest_masters.py` |
| 19 | Partial batch failure | Transaction failure | Batch rolled back; watermark not advanced | Run PARTIAL | `backend/tests/sync/test_run_bookkeeping.py`, `backend/tests/sync/test_watermarks.py` |
| 20 | Invalid or revoked credential | Auth fails | 401 `CREDENTIAL_INVALID` / `AGENT_REVOKED` | Agent-side error | `backend/tests/core/test_agent_auth.py::test_invalid_and_revoked_credentials_get_distinguishable_errors` |
| 21 | Incompatible Agent or TDL version | Version below minimum | `INCOMPATIBLE` (status); `AGENT_INCOMPATIBLE` (code); no commands | "Agent update required" | `backend/tests/api/test_heartbeat.py`, `backend/tests/api/test_commands.py` |
| 22 | Unresolved group / voucher type | Resolution fails | Excluded from classified metrics | Data Quality list | `backend/tests/sync/test_hierarchy.py`, `backend/tests/api/test_data_quality.py` |
| 23 | Missing opening balance | No record for the year | Balance shown as unavailable | "Opening balance unavailable" | `backend/tests/analytics/test_balances.py::test_no_opening_row_is_unavailable_never_zero_and_a_zero_opening_is_a_figure`, `backend/tests/exports/test_csv.py::test_an_unavailable_balance_is_empty_never_zero` |
| 24 | Unsupported bill allocation | Unknown type | Excluded from aging | Review list | `shared/tests/parser/test_parser.py::test_unknown_bill_type_is_unsupported_not_guessed`, `backend/tests/analytics/test_aging.py::test_unsupported_allocations_are_never_aged` |
| 25 | Unlinked credit/debit note | No bill link | Not subtracted | Unclassified Adjustments | `backend/tests/analytics/test_returns.py`, `backend/tests/api/test_data_quality.py` |
| 26 | Master missing in Tally | Absent from key list or reconciliation | `MISSING_IN_TALLY`; history kept | Missing masters list | `backend/tests/sync/test_key_lists.py` |
| 27 | Reconciliation with zero Tally value | Tally value is 0 | Exact-match rule (SRS 9.2) | PASS/FAIL | `backend/tests/reconciliation/test_tolerance.py::test_zero_in_tally_passes_only_on_an_exact_zero` |
| 28 | Mapped custom field missing | Absent from export | Stored as null, `UDF_NOT_FOUND` | Sync log | `shared/tests/test_udf.py`, `backend/tests/sync/test_run_bookkeeping.py` |
| 29 | Invalid time zone or FY start | Settings validation | Save rejected; quarter views show "financial year not configured" | Validation message | `backend/tests/api/test_companies.py::test_invalid_timezone_or_fy_start_is_422`, `backend/tests/core/test_periods.py` |
| 30 | ALTERID gate row failed | Validation table | Collection uses full-pull-only sync | "Full sync only" indicator | `backend/tests/test_gates.py` (`GATE_NOT_PASSED`), `backend/tests/api/test_commands.py` |
| 31 | Backend unavailable | Agent calls fail | Agent queues | Service-unavailable page | `agent/tests/test_queue.py::test_items_upload_first_in_first_out_and_a_backing_off_head_holds_the_rest`, `backend/tests/e2e/test_agent_end_to_end.py::test_the_backend_killed_mid_upload_loses_and_duplicates_nothing` |
| 32 | Database unavailable | Backend DB calls fail | HTTP 503; no partial writes | Service-unavailable page | `backend/tests/test_errors_and_health.py::test_a_lost_database_is_503_with_a_catalogue_code_not_500`, `::test_a_lost_database_in_the_rate_limiter_is_also_503`, `::test_health_db_unavailable_returns_503_and_logs` |
| 33 | MCP server or Claude unavailable | Tool call fails | Evidence still created and shown | "Explanation unavailable" | `backend/tests/anomaly/test_explainer.py::test_claude_unreachable_leaves_the_anomaly_with_its_evidence` (AC-58) |

## What P16.4 changed

Writing this matrix found one row that did not behave as the SRS says.

**Row 32, "Database unavailable → HTTP 503".** Nothing handled a database driver error, so an
outage on an ordinary route was an unhandled exception: HTTP **500**, with no machine-readable
code, and nothing an operator could act on. Only `/health/db` mapped its own failure, which is
the one path a reader would check and find correct.

Fixed in P16.4:

- `ErrorCode.DATABASE_UNAVAILABLE`, and handlers for `OperationalError` / `InterfaceError`
  returning 503. An `IntegrityError` deliberately keeps its 500: a constraint violation is a bug
  in our SQL, and dressing it as an outage would send a real defect to the wrong people.
- The rate limiter needs its own answer. Since P16.11 it counts in PostgreSQL, and it runs in
  middleware — outside the exception handlers — so without this a database outage would have
  been a bare 500 from *every* endpoint, including ones that touch no data themselves.
- "No partial writes" holds by construction rather than by rescue: a request's session commits
  only where the code says so, so a failure part way through leaves the transaction to roll
  back. The export path additionally runs in one `REPEATABLE READ, READ ONLY` snapshot (D-054).

## Rows that need the owner

Nothing in this table is blocked outright, but two rows are only partly provable here:

- **Row 2** — the exact wording shown when a Windows user logs off while TallyPrime is running
  needs the Windows VM. The detection (the process is gone) is tested; the message is not.
- **Rows 31 and 32's "service-unavailable page"** — the page itself is proved in the frontend
  suite, but that the deployed site serves it when the backend is down needs hosting (P16.12).

Both are entered in `docs/manual-verification.md` with their blocker.
