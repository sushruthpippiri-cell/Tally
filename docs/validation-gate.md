# Tally Validation Gate (SRS Section 7)

Maintained project artifact (VAL-1.3). A row may be set to PASSED or FAILED only with evidence: the path of the captured request/response under `fixtures/xml/live/`, the TallyPrime version and build, the date, and who ran it. Keep `backend/app/config/gate_status.yaml` in sync with the Status column.

How the probe tool and test company are set up: `docs/plan/gate-track.md`.

| ID | Test | Expected result | Status | Evidence | TallyPrime ver. | Date / by | What it unblocks |
|---|---|---|---|---|---|---|---|
| G1 | ALTERID on Ledger export | Present, integer | NOT TESTED | | | | Incremental LEDGER sync |
| G2 | ALTERID on Stock Item export | Present, integer | NOT TESTED | | | | Incremental STOCK_ITEM sync |
| G3 | ALTERID on Voucher export | Present, integer | NOT TESTED | | | | Incremental VOUCHER sync |
| G4 | ALTERID on Cost Centre export | Present, integer | NOT TESTED | | | | Incremental COST_CENTRE sync |
| G5 | ALTERID type and range | Integer, increasing per company | NOT TESTED | | | | All incremental sync |
| G6 | ALTERID ordering | Increases on every change to an object | NOT TESTED | | | | All incremental sync |
| G7 | ALTERID > filter in TDL | Collection accepts a numeric filter | NOT TESTED | | | | All incremental sync |
| G8 | Modified voucher | Editing raises its ALTERID | NOT TESTED | | | | AC-02 |
| G9 | Cancelled voucher | Cancelling raises ALTERID and sets a detectable indicator | NOT TESTED | | | | AC-03 |
| G10 | Consistency across collections | Same ALTERID behaviour for all collection types | NOT TESTED | | | | Incremental GROUP / VOUCHER_TYPE / COMPANY |
| G11 | Deletion | Deleting a record produces no ALTERID signal on other records | NOT TESTED | | | | Confirms key-list design (SYNC-5) |
| G12 | Group parent reference | Each group's parent is identifiable | NOT TESTED | | | | Hierarchy resolution (P6) |
| G13 | Primary group resolution | Every group's chain reaches a predefined group | NOT TESTED | | | | Classification (ACC-7, D-001) |
| G14 | Group nature | Nature identifiable from export or fixed mapping | NOT TESTED | | | | Balances ACC-9.2 |
| G15 | Voucher type parent | Each voucher type's parent is identifiable | NOT TESTED | | | | ACC-8 |
| G16 | Ledger opening balance | Exportable with debit/credit direction (also: are zero openings exported explicitly? per-FY or books-beginning only?) | NOT TESTED | | | | Balances ACC-9 |
| G17 | Stock opening balance | Opening quantity and value exportable | NOT TESTED | | | | stock_opening_balances |
| G18 | Stock closing quantity as of a date | Returned for a given date | NOT TESTED | | | | Stock analytics, reconciliation |
| G19 | Ledger closing balance as of a date | Returned for a given date | NOT TESTED | | | | Reconciliation, ACC-9.5 |
| G20 | Named-company targeting | A request can target a loaded, non-active company | NOT TESTED | | | | AGT-5.5, AC-23 |
| G21 | Key-only export | Collection exportable with only GUID and ALTERID | NOT TESTED | | | | Deletion detection |
| G22 | User-defined field extraction | A TDL-customised field can be requested | NOT TESTED | | | | DR-UDF, AC-61 |
| G23 | Debit/credit indicator | Raw indicator identified; parser maps it correctly (ACC-DATA-3) | NOT TESTED | | | | Parser — every metric |
| G24 | Stable line identifier | Whether ledger/inventory lines have a stable ID (DR-VE-1) | NOT TESTED | | | | Per-line update vs replacement |
| G25 | Bill allocation types | Exact exported values for New Ref, Against Ref, Advance, On Account | NOT TESTED | | | | Aging; payment behaviour (hidden until PASSED) |
| G26 | Return linkage | How Credit/Debit Notes reference original bills | NOT TESTED | | | | Return linking (all notes unlinked until PASSED) |
| G27 | Unit data | Base units and conversion factors exported | NOT TESTED | | | | Unit conversion (FR-STK-9) |
| G28 | Product revenue basis | Product-line revenue on same basis as Total Sales (ACC-VAL-1) | NOT TESTED | | | | "Unattributed / Non-product" label |
| G29 | Master inactive state | Whether Tally exposes an inactive state | NOT TESTED | | | | DR-ML-5 |
| G30* | Master GUID on voucher lines | TDL can emit ledger / stock item / cost centre GUID per line | NOT TESTED | | | | D-002 |
| G31* | Bill allocation details | Reference-name uniqueness scope; amount sign; opening bills on ledger master | NOT TESTED | | | | D-004, D-022, aging |
| G32* | Predefined group / voucher type identity | Reserved name exported and stable even if renamed | NOT TESTED | | | | D-001 |
| G33* | ALTERID window paging | from/to ALTERID filter returns exactly the objects in the window; company max ALTERID obtainable | NOT TESTED | | | | D-013 |
| G34* | Voucher scope | The voucher Collection returns accounting vouchers only: no orders, Delivery/Receipt Notes, Stock Journals or optional vouchers (SRS 1.3) | NOT TESTED | | | | Voucher sync scope |
| G35* | Error responses and encoding | Exact response for an unknown report and for a company that is not loaded; response encoding; invalid XML characters Tally emits | NOT TESTED | | | | TDL_NOT_LOADED, COMPANY_NOT_LOADED detection; parser sanitising |

\* Additions not in SRS v7.3: G30–G33 from planning, G34–G35 from Phase 4 (D-038).
