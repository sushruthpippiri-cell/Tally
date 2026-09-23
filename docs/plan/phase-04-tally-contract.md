# Phase 4 — Tally contract: TDL definitions, request builder, parser

**Size:** L (split: P4.1–P4.4, then P4.5–P4.9) · **Depends on:** P0 (can run in parallel with P1–P3)
**SRS:** 5.8, 5.11, 6.11, 23 (TEST-1.x), 1.3 (which vouchers are synced)
**Requirements:** FR-1.1–1.4, ACC-DATA-1–3, DR-UDF-1–4, DR-VE-1, TEST-1.1–1.4
**Acceptance:** AC-34 (parser half), AC-66 · **Gates involved:** G1–G7, G9, G12–G33 · **Decisions:** D-002, D-004, D-005, D-013

## Goal
A shared, fully tested package that (a) builds every XML export request the Agent sends to Tally, (b) parses Tally's XML responses into normalized, validated records, and (c) defines the JSON contract the Agent uploads. Plus the TDL source the requests rely on.

**Important:** until the gate track captures real TallyPrime output, all Tally tag names, indicator values and TDL are **drafts**. Keep every such assumption in one place, tagged `# GATE-Gxx`, so the gate track can correct it by editing constants and fixtures, not by rewriting the parser.

## Tasks

### P4.1 Record schemas — `tally_contract/records.py` (D-005)
Pydantic v2 models; money as `Decimal`, dates as `date`:
- `CompanyRecord` (guid, name, alter_id, books_from, financial_year_start, max_alter_id?)
- `GroupRecord` (guid, name, alter_id, parent_guid?, parent_name?, reserved_name?, nature_hint fields)
- `LedgerRecord` (guid, name, alter_id, parent_group_guid, is_bill_wise?, opening_balance?: amount_raw + normalized fields, opening_bills[] per D-022, custom_fields)
- `VoucherTypeRecord` (guid, name, alter_id, parent_guid?, reserved_name?)
- `StockItemRecord` (guid, name, alter_id, base_unit, gst_rate?, opening_qty?, opening_value?, alternate_units?, custom_fields)
- `CostCentreRecord`
- `VoucherRecord` (guid, alter_id, voucher_number, voucher_type_guid, voucher_date, narration, is_cancelled, custom_fields, `entries[]`, `items[]`)
  - entry: `ledger_guid` (D-002), `ledger_name`, `line_sequence`, `stable_line_id?`, `amount_raw: str`, `is_debit`, `amount_absolute`, `amount_signed`, `accounting_direction`, `bill_allocations[]` (reference_name, allocation_type_raw, allocation_type, due_date?, amount_absolute, accounting_direction), `cost_centre_allocations[]` (cost_centre_guid, amount_absolute)
  - item: `stock_item_guid`, quantity, unit, rate, amount, custom_fields
- `StockSnapshotRecord`, `LedgerClosingBalanceRecord`, `KeyRecord (guid, alter_id)`, `ReconciliationTotalRecord (metric, period_start, period_end, entity_guid?, value)`
- `BatchEnvelope`: contract_version, collection_type, command_id, sync_run_id, batch_seq, batch_id (uuid), window (`from_alter_id`/`to_alter_id` or `date_from`/`date_to`), `records[]` sorted by alter_id (D-026), `parse_errors[]`.

### P4.2 TDL sources — `tdl/`
- One Collection + Report per FR-1.1 item: company, groups, ledgers (with opening balances and opening bills), voucher types, stock items (with opening balances), cost centres, vouchers (header, ledger entries, inventory entries, bill allocations, cost-centre allocations), stock closing quantities as of a date, ledger closing balances as of a date, reconciliation totals (drafted here, completed in P10).
- Every Collection returns GUID and ALTERID, supports a from/to-ALTERID filter through static variables, and has a key-only variant (FR-1.2, G7, G21, G33).
- The voucher Collection excludes order vouchers and inventory-only vouchers (Delivery Note, Receipt Note, Stock Journal, orders — SRS 1.3) and emits master GUIDs on each line (G30).
- A `TallyAnalyticsInfo` report returns the TDL package version and the target company's GUID/name — the Agent uses it for version reporting (VER-1.1), the GUID check (AGT-3.2) and `TDL_NOT_LOADED` detection (FR-1.4).
- Every unverified assumption carries `;; GATE-Gxx`. `tdl/README.md`: how to load the files into TallyPrime (TDL management under Help → TDLs & Add-Ons, or `tally.ini`), `TDL_VERSION` bump rules, and a warning that files are drafts until the gate track verifies them.
- Reference for field names: tally-database-loader (MIT) — read its TDL/XML for guidance, attribute it in `tdl/README.md`, and treat nothing from it as verified.

### P4.3 Request builder — `tally_contract/requests.py`
Pure functions building XML envelopes: export request for a named report, `SVCURRENTCOMPANY` (explicit company targeting, AGT-5.1; mechanism is G20), from/to ALTERID, date range, as-of date, key-only switch. All tag and variable names in `tally_contract/tally_constants.py` with GATE tags. Golden-file tests of the generated XML.

### P4.4 XML parsing — `tally_contract/parser/`
- Pre-sanitize: strip characters and character references invalid in XML 1.0 (Tally is known to emit some; verify with live fixtures). Parse with lxml (`huge_tree=True`), streaming (`iterparse`) for voucher responses so 5,000-voucher responses do not load twice into memory.
- Per-record isolation: an exception in one record yields `ParseError(guid?, code=PARSE_ERROR, message, snippet)` and parsing continues (SYNC-6.5). A malformed document yields a `DocumentError`; **nothing raises out of the parser** (TEST-1.4, AC-66).
- Detect Tally error responses: unknown report → `TDL_NOT_LOADED`; company not found → `COMPANY_NOT_LOADED` (exact response text is gate-dependent; keep matchers in constants).
- Dates `YYYYMMDD` → `date`. Numbers: tolerant conversion to Decimal (whitespace, thousands separators, trailing Dr/Cr if present), failing the record rather than guessing on anything unexpected.

### P4.5 Normalization — `tally_contract/normalize.py` (ACC-DATA-2, ACC-DATA-3)
- The only module that turns Tally's raw amount and indicator into `is_debit`, `amount_absolute`, `amount_signed`, `accounting_direction`. The rule lives in `DEBIT_CREDIT_RULE` tagged `# GATE-G23`. Draft rule to verify: ledger entries carry `ISDEEMEDPOSITIVE` and a signed `AMOUNT` where debits appear negative.
- Voucher balance check: Σ `amount_signed` of entries must be 0 (tolerance 0.01) → otherwise the voucher record gets `DEBIT_CREDIT_IMBALANCE` and is excluded from the batch (SRS 16).
- Bill allocation type mapping `BILL_TYPE_MAP` (`# GATE-G25`): raw → NEW_REF / AGST_REF / ADVANCE / ON_ACCOUNT, anything else → UNSUPPORTED (AGE-BILL-1).
- Cancellation indicator constant (`# GATE-G9`).

### P4.6 User-defined fields (DR-UDF-1–4)
- `tally_contract/udf.py`: from a list of mappings `(collection_type, tally_field, field_key, data_type)` generate the TDL include that adds those fields to the relevant Collections (DR-UDF-4) and the parser configuration that reads them into `custom_fields`.
- Missing mapped field → `None` and one `UDF_NOT_FOUND` warning per field per run (DR-UDF-3).
- Backend endpoint `GET /companies/{id}/settings/custom-fields/tdl` returning the generated include (MANAGE_CUSTOM_FIELDS) is built in P5 but uses this generator.

### P4.7 Synthetic fixtures — `fixtures/xml/synthetic/`
One XML file + `*.expected.json` per case in TEST-1.2: new, modified and cancelled vouchers; multiple ledger entries; inventory entries; bill allocations of every type; cost-centre allocations; missing optional fields; malformed XML; unexpected structure; a three-level group chain; a group with a missing parent; a custom voucher type derived from Sales; an unresolvable voucher type; opening balances; stock snapshots; debit and credit entries on sales, purchase, receipt, payment and tax ledgers; an unbalanced voucher; a UDF present and missing. `fixtures/README.md` states that synthetic fixtures are **not** verified Tally output.

### P4.8 Contract test harness
Parametrized pytest over every fixture pair (TEST-1.1); runs in CI without Tally (TEST-1.3). The same harness runs over `fixtures/xml/live/` when present. `make update-fixtures` regenerates expected JSON only when run with an explicit flag, and the diff must be reviewed.

### P4.9 Tests
- AC-66: malformed fixture → logged error, no exception.
- AC-34 (parser half): debit and credit entries produce correct `accounting_direction`, `is_debit`, `amount_absolute`, `amount_signed`.
- Balance check, bill type mapping (incl. UNSUPPORTED), cancellation flag, UDF present/missing, request builder golden files, streaming parse of a 5,000-voucher synthetic file within a memory budget.

## Definition of done
`tally_contract` has no dependency on backend or agent code; all fixture tests pass; every Tally-specific assumption is findable with `grep -rn "GATE-G" shared tdl`.

## Kickoff prompt
~~~text
Read CLAUDE.md, docs/plan/phase-04-tally-contract.md, docs/decisions.md (D-002, D-004, D-005, D-013, D-022) and SRS Sections 1.3, 5.7, 5.8, 5.11, 6.11, 23. In plan mode, propose the record schemas, the module layout, and the list of GATE-tagged assumptions you will make (with the draft value for each). Implement P4.1–P4.4, stop and update docs/progress.md; then P4.5–P4.9 in a new session. Tests first, commit per task.
~~~
