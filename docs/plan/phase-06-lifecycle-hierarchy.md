# Phase 6 — Lifecycle, deletion detection, hierarchy & classification resolution

**Size:** M · **Depends on:** P5
**SRS:** 6.7, 6.8, 6.10, 8.2, 8.3, 13.1 (FR-4.5), 19.2 (masters, data quality)
**Requirements:** SYNC-5.1–5.5, DR-ML-1–5, ACC-7.1–7.6, ACC-8.1–8.3, FR-4.5
**Acceptance:** AC-03, AC-04, AC-10, AC-11 (and the resolution parts of AC-28, AC-29) · **Gates:** G9, G11–G15, G21, G29, G32 · **Decisions:** D-001, D-007

## Goal
Cancelled, deleted, reappearing and renamed records are handled without losing history; every group resolves to its predefined group and every voucher type to its base type; problems surface in a Data Quality view instead of silently distorting figures.

## Tasks

### P6.1 Cancellation (SRS 6.7)
A voucher with a higher ALTERID and the cancellation indicator (G9) → status CANCELLED, row kept, audited. Standard analytics exclude it (enforced in P8).

### P6.2 Key-list deletion detection (SYNC-5.x)
- `POST /agent/commands/{id}/keylists {collection_type, scope, keys[], chunk_seq, is_final}`. Scope for vouchers is a date range (`date_from`, `date_to`); for masters it is `all`. Chunks are staged in `sync_keylist_staging(run_id, collection_type, tally_guid, alter_id)` and evaluated on `is_final`.
- Evaluation: ACTIVE local records in scope that are absent → MISSING_IN_TALLY (SYNC-5.2); MISSING_IN_TALLY records present again → ACTIVE (reappeared). Each transition audited (LOG-1.1). Keys whose ALTERID exceeds the stored value are logged as "missed change — will be re-pulled" (sync_errors, info level).
- Safety guard (D-007): empty list with local records in scope, or too many would go missing → change nothing, log `KEY_LIST_SUSPICIOUS`, add a Data Quality item.
- Frequency from `sync.key_list_interval` (SYNC-5.4); the Agent reads it from its plan.

### P6.3 Master lifecycle (DR-ML-1–5)
- Same key-list mechanism for groups, ledgers, voucher types, stock items, cost centres (scope `all`).
- MISSING_IN_TALLY masters keep all FKs; historical vouchers still reference them (DR-ML-2). Reappearance → ACTIVE, audited (DR-ML-4).
- INACTIVE status only if G29 passes (DR-ML-5) — mapping constant tagged `# GATE-G29`.

### P6.4 Group hierarchy resolution — `app/sync/hierarchy.py` (ACC-7.2, 7.4, 7.5, D-001)
- After any group batch commits, recompute the company's entire group forest in memory (groups are few):
  - `is_predefined` from `reserved_name` (G32; fallback: exact predefined name when G32 not passed).
  - `predefined_group_id` = nearest predefined ancestor including self; `primary_group_id` = top-level primary.
  - `nature` from the top-level primary group via the fixed table below (G14).
  - Missing parent or a cycle → `resolution_status = UNRESOLVED_GROUP` for that group and every descendant (ACC-7.4).
- Persist only changes; each changed group → audit (system) with old/new predefined and primary group (ACC-7.5).
- Refresh the cached `predefined_group_id`/`primary_group_id` on ledgers under changed groups, and on every ledger upsert.

Tally's 28 predefined groups (verify against a live export, G13/G32):

| Primary group (15) | Nature | Predefined sub-groups under it |
|---|---|---|
| Capital Account | Liability | Reserves & Surplus |
| Loans (Liability) | Liability | Bank OD A/c, Secured Loans, Unsecured Loans |
| Current Liabilities | Liability | Duties & Taxes, Provisions, Sundry Creditors |
| Branch / Divisions | Liability | — |
| Suspense A/c | Liability | — |
| Fixed Assets | Asset | — |
| Investments | Asset | — |
| Current Assets | Asset | Bank Accounts, Cash-in-Hand, Deposits (Asset), Loans & Advances (Asset), Stock-in-Hand, Sundry Debtors |
| Misc. Expenses (ASSET) | Asset | — |
| Sales Accounts | Income | — |
| Direct Incomes | Income | — |
| Indirect Incomes | Income | — |
| Purchase Accounts | Expense | — |
| Direct Expenses | Expense | — |
| Indirect Expenses | Expense | — |

### P6.5 Voucher type resolution (ACC-8.1–8.3)
Walk parents to a predefined voucher type (G15, G32). Sales, Purchase, Receipt, Payment, Contra, Journal, Credit Note, Debit Note → the matching `base_voucher_type`. Any other predefined type (orders, notes, stock journal, memorandum, etc.) → OTHER with `resolution_status = RESOLVED`. Missing parent or cycle → OTHER with `resolution_status = UNRESOLVED` (listed in Data Quality). Re-resolve on every voucher-type batch; audit changes.

### P6.6 Data Quality service — `app/services/data_quality.py` (FR-4.5)
A registry of checks, each returning `{check_id, title, severity, count, items[] (paginated), how_to_fix}`, so later phases can register more. Checks in this phase: unresolved groups; unresolved voucher types; ledgers without an opening balance for the current financial year; missing masters; MISSING_IN_TALLY vouchers; imbalanced vouchers (from `sync_errors`); suspicious key lists; unknown master references. Placeholders registered by later phases: unsupported bill allocations (P11), unlinked credit/debit notes (P8), multi-unit items (P12), over-settled bills (P11).
`GET /companies/{id}/data-quality` (VIEW_RECON_AND_DQ) and `GET /companies/{id}/data-quality/{check_id}`.

### P6.7 Masters endpoints
`GET /companies/{id}/masters/groups` (tree with predefined/primary group, nature, resolution status) and `/masters/voucher-types` (with base type, resolution status).

### P6.8 Tests
- AC-03: cancellation → CANCELLED, row exists.
- AC-04: voucher absent from key list → MISSING_IN_TALLY, row exists, appears in Data Quality.
- AC-10: ledger absent from full key list → MISSING_IN_TALLY, not deleted, vouchers still reference it.
- AC-11: reappears with same GUID → ACTIVE, audited.
- Safety guard: empty and heavily truncated key lists change nothing.
- Hierarchy: three-level chain under Sales Accounts; custom group under Sundry Debtors resolves `predefined_group` = Sundry Debtors and `primary_group` = Current Assets; missing parent; cycle; reparenting recomputes descendants and audits.
- Voucher types: "POS Invoice" derived from Sales → SALES; two-level custom chain; unresolvable → OTHER + Data Quality.

## Definition of done
Tests pass; Data Quality endpoint returns all checks listed; `docs/sync-engine.md` updated with lifecycle and key-list behaviour.

## Kickoff prompt
~~~text
Read CLAUDE.md, docs/plan/phase-06-lifecycle-hierarchy.md, docs/sync-engine.md, docs/decisions.md (D-001, D-007) and SRS Sections 6.7, 6.8, 6.10, 8.2, 8.3. In plan mode, propose the key-list staging design, the safety-guard logic, the hierarchy algorithm (with cycle detection) and the Data Quality check registry. Wait for approval, implement P6.1–P6.8 with tests first, commit per task, update docs/progress.md.
~~~
