# Use-case coverage (SRS 20, TEST-5.1, P16.7)

Which test answers each use case, and what it does not. `tools/tests/test_use_case_coverage.py`
fails if a use case in SRS Section 20 has no row here, or if a test named below no longer exists.
A name is `path::test name`; for a TypeScript test the name is its title, or the start of it.

"Browser" tests run on desktop and the 360 px touch project (AC-65). "End to end" means the real
Agent and backend against the mock Tally (`backend/tests/e2e/`). Nothing here has run against a
real TallyPrime; that is the capture kit and the acceptance run (P16.10).

| UC | Answered by | Not proved |
|---|---|---|
| UC-1 Onboarding | End to end: `backend/tests/e2e/test_agent_end_to_end.py::test_register_sync_edit_and_delete_end_to_end` (token, registration, the Tally company confirmed, the full sync). Browser: `frontend/e2e/pages.spec.ts::a registration token is shown once` | The Windows installer's first-run wizard (P16.8, Windows-only) |
| UC-2 Scheduled incremental sync | The schedule creating its command: `backend/tests/jobs/test_schedule_jobs.py::test_at_2am_incremental_is_created_before_reconciliation`. The Agent claiming, pulling above the watermark and completing: `backend/tests/e2e/test_agent_end_to_end.py::test_register_sync_edit_and_delete_end_to_end` | The two halves are proved separately: the end-to-end backend runs without its scheduler, so no test goes from a schedule firing to the Agent running that command |
| UC-3 Manual sync, several Agents | `backend/tests/api/test_commands.py::test_two_active_agents_need_an_agent_id_and_only_that_one_gets_it`; browser: `frontend/e2e/pages.spec.ts::Sync Now with two ACTIVE Agents needs a choice` | Two real Agent processes racing; only the targeted Agent can claim, which the API test shows |
| UC-4 Modified voucher | End to end: `backend/tests/e2e/test_agent_end_to_end.py::test_register_sync_edit_and_delete_end_to_end`; `backend/tests/sync/test_ingest_vouchers.py::test_a_modified_voucher_has_its_children_replaced_with_no_orphans` and `::test_a_modified_voucher_shows_the_new_amount_and_the_audit_has_both` | - |
| UC-5 Cancelled and deleted vouchers | End to end: `backend/tests/e2e/test_use_cases.py::test_uc5_a_voucher_cancelled_in_tally_becomes_cancelled_and_is_kept` (cancelled) and `backend/tests/e2e/test_agent_end_to_end.py::test_register_sync_edit_and_delete_end_to_end` (deleted, MISSING_IN_TALLY); `backend/tests/sync/test_ingest_vouchers.py::test_a_cancelled_voucher_keeps_its_row_and_is_audited` | - |
| UC-6 Stale record | `backend/tests/sync/test_ingest_vouchers.py::test_a_stale_voucher_is_ignored_and_logged` and `::test_stale_protection_applies_to_every_synced_collection` | Deliberately not end to end: a real Agent never sends an older batch after a newer one, so an end-to-end test would forge the upload and only re-test the API |
| UC-7 Concurrent Agents | `backend/tests/races/test_lease_races.py::test_two_agents_at_once_exactly_one_gets_the_lease`; `backend/tests/sync/test_runs_and_leases.py::test_a_held_lease_refuses_another_agent_by_name` | Deliberately not with two real Agents: a race, so it would be timing-dependent |
| UC-8 Agent crash | End to end: `backend/tests/e2e/test_use_cases.py::test_uc8_an_agent_lost_mid_command_fails_it_and_a_new_command_can_be_issued` | - |
| UC-9 Credential rotation | End to end: `backend/tests/e2e/test_use_cases.py::test_uc9_a_rotated_credential_is_shown_once_and_the_old_one_stops_working` | Typing the new value into the Agent's wizard (Windows-only) |
| UC-10 Reconciliation review | The comparison and its figures: `backend/tests/e2e/test_agent_end_to_end.py::test_a_full_sync_is_reconciled_end_to_end_and_a_tally_difference_fails_it` and `::test_the_generated_dataset_reconciles_with_its_own_closing_balances`; `backend/tests/api/test_reconciliation_api.py::test_a_run_shows_tally_local_both_differences_and_the_result`. The page: `frontend/src/pages/recon-dq.test.tsx::shows the backend's differences, not ones computed from the values on screen`; its 360 px layout is in `frontend/e2e/pages.spec.ts::fits the screen with long names` | No browser test reads a FAIL on the page; the page's content is asserted in jsdom, its layout in the browser |
| UC-11 Analytics review and export | Browser: `frontend/e2e/analytics.spec.ts::a chart bar opens its exact figure`, `::a breakdown row drills to its vouchers` and `::a section exports to CSV and to PDF`. API: `backend/tests/api/test_drilldown.py::test_revenue_to_customer_to_vouchers_to_voucher_detail` and `backend/tests/api/test_exports.py::test_screen_drilldown_csv_and_pdf_show_the_same_figure` | Cash position and aging are rendered in the route walk but not driven through the same journey |
| UC-12 Product Attribution Difference review | Browser-level click-through in jsdom: `frontend/src/pages/analytics.test.tsx::opens from the Difference section to the vouchers that hold revenue not tied to a stock item`. API: `backend/tests/api/test_drilldown.py::test_product_difference_to_contributing_vouchers` | Not in Playwright, so not on the 360 px project |
| UC-13 Anomaly review | Browser: `frontend/e2e/pages.spec.ts::anomalies: evidence and explanation stay apart, and a review can be made`. `frontend/src/pages/anomalies.test.tsx::posts the review action and shows the new status`. API: `backend/tests/anomaly/test_api_and_jobs.py::test_an_owner_can_review_a_flag_and_it_is_audited` | The optional module against a real model (live, owner-run) |
| UC-14 Data-quality review | `backend/tests/api/test_data_quality.py::test_every_check_runs_and_a_new_company_has_nothing_to_report`; the checks themselves: `backend/tests/sync/test_hierarchy.py::test_example_4_a_broken_chain_is_unresolved_down_to_its_descendants_and_recovers` (unresolved groups), `::test_a_renamed_sales_voucher_type_is_flagged_before_g32` (voucher types), `backend/tests/api/test_data_quality.py::test_balance_sheet_ledgers_without_a_books_beginning_opening_are_listed` (openings), `backend/tests/analytics/test_returns.py::test_the_data_quality_check_lists_the_unlinked_notes` (unlinked notes). The page: `frontend/src/pages/recon-dq.test.tsx::shows every check with its how-to-fix` | No browser test; the Admin role's access is asserted by the route matrix (AC-59), not here |

## What this means for TEST-5.1

TEST-5.1 names four things. RBAC 403s are in the route sweep (AC-59, AC-60) and
`frontend/src/pages/company.test.tsx`; drill-down totals in
`frontend/src/pages/analytics.test.tsx::a drill-down shows the backend's total` and
`backend/tests/api/test_drilldown.py`; export/screen consistency in
`backend/tests/api/test_exports.py::test_screen_drilldown_csv_and_pdf_show_the_same_figure`; 360 px
layouts in `frontend/e2e/pages.spec.ts` on every route. The gaps above are what keep it from being
claimed in full: UC-2 across the scheduler, UC-10 and UC-14 in a browser, UC-12 at 360 px.
