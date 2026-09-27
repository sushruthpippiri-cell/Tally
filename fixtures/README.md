# Test XML

`xml/synthetic/` is hand-built and **NOT verified Tally output**. `xml/live/` holds captures from a
real TallyPrime, taken with the capture kit (`tools/capture_kit/`, D-038) from a **test company
only**.

## Format
Each case is `<case>.xml` (the response bytes, exactly as the parser receives them) and
`<case>.expected.json`:

```json
{"parse": "collection:VOUCHER",          // or keys | info | stock_closing | ledger_closing
 "udf": [{"collection_type": "LEDGER", "tally_field": "...", "field_key": "...", "data_type": "..."}],
 "expected": {"records": [...], "errors": [...], "document_error": null,
              "invalid_characters_removed": 0}}
```

`shared/tests/test_contract_fixtures.py` parses every case and compares it with `expected`
(TEST-1.1, TEST-1.3). Live captures join once gate-track step G-E adds
`<id>.response.expected.json` next to a captured `<id>.response.xml`.

**Changing an expectation is deliberate:** `make update-fixtures` only reports what would change;
`make update-fixtures FORCE=1` rewrites `expected`, and the diff must be read before committing.
Files here are byte-exact (`.gitattributes`: `-text`).

## Synthetic cases (TEST-1.2)
| Case | What it covers |
|---|---|
| `vouchers_v1`, `vouchers_v2_modified` | a new voucher, the same GUID modified (higher ALTERID, new amount), a cancelled voucher |
| `voucher_journal_multiple_entries` | four ledger entries |
| `voucher_sales_inventory` | inventory entries and a freight line; a compound alternate-unit quantity is rejected until G27 |
| `bill_allocations_all_types` | New Ref, Agst Ref, Advance, On Account (no name), an unknown type -> UNSUPPORTED |
| `cost_centre_allocations` | one entry split across two cost centres |
| `debit_credit_by_ledger_kind` | debits and credits on sales, purchase, receipt, payment and tax ledgers (AC-34) |
| `voucher_unbalanced` | a paisa off -> DEBIT_CREDIT_IMBALANCE; a balanced voucher beside it still parses |
| `voucher_foreign_currency` | amounts with currency symbols or a conversion -> rejected, never partly read |
| `missing_optional_fields` | no number, narration or GUIDs (D-002 name fallback) |
| `unexpected_structure` | unknown tags, a missing required tag, a record inside an unexpected wrapper |
| `malformed` | truncated XML -> a document error, no records (AC-66) |
| `groups_three_level_chain`, `group_missing_parent` | a three-level chain and a parent that does not exist (resolution is P6) |
| `voucher_types_custom_and_unresolvable` | POS Invoice derived from Sales; a type whose parent does not exist |
| `ledgers_opening_balances`, `stock_items_opening` | opening balances, opening bills (D-022), units |
| `stock_snapshots`, `ledger_closing`, `keys_vouchers`, `company`, `info` | the other report shapes |
| `udf_present_and_missing` | one mapped field present, one missing (UDF_NOT_FOUND) |
| `tally_error_tdl_not_loaded`, `tally_error_company_not_open` | Tally's error answers |
| `encoding_utf16_invalid_chars` | UTF-16 with a BOM, and invalid XML characters removed |
