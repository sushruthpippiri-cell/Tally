# Test company checklist

> ## ⚠ TEST COMPANY ONLY
> Create a **new company used only for this**. **Never** use a real business's books: the
> captured responses are committed to the project repository.

Tick each box as you enter the data. Dates use only the **1st, 2nd and 31st** of a month so the
list also works in TallyPrime's Educational mode.

## Your setup (fill in)
| | |
|---|---|
| TallyPrime version and build (F1 → About) | |
| Licensed or Educational mode | |
| Windows version (the script also records it) | |
| Hypervisor (Parallels / UTM / other) | |
| Test company name (exact) | |
| Second company name (exact) | |
| Anything odd you noticed (emulation, errors) | |

## A. Companies
- [ ] **Test company**, financial year from **1 April 2024**, books beginning **1 April 2024**.
- [ ] A **second company** (any data), kept **open at the same time** as the test company
      (gate G20: targeting a company that is not the active one).

## B. Groups
- [ ] Under **Sales Accounts**: a group **Sales - Online**, and under it **Sales - Online -
      Marketplace** (a three-level chain; G12, G13).
- [ ] Under **Sundry Debtors**: a group **Retail Customers** (used by scenario ACC-7.5).
- [ ] Under **Bank Accounts**: a group **Current Accounts**.
- [ ] Directly under **Primary**: a group **Government Schemes** with nature **Assets** (G14:
      nature of a user top-level group).

## C. Ledgers (with opening balances where stated)
- [ ] Customers, bill-wise **on**: **Sharma Traders** (in *Retail Customers*), **Gupta Stores**,
      **Mehta & Sons** (the `&` matters). Customer, bill-wise **off**: **Walk-in Customer**.
- [ ] **Gupta Stores** has an opening balance given as **two opening bills** (bill-wise opening:
      e.g. `OB-1` ₹10,000 dated 31 Mar 2024 and `OB-2` ₹5,000) (G31, D-022).
- [ ] Suppliers: **Kumar Wholesale**, **Singh Distributors** (one with an opening **credit**
      balance).
- [ ] Sales ledgers: **Sales - Retail** (under Sales Accounts) and **Sales - Marketplace** (under
      *Sales - Online - Marketplace*).
- [ ] **Purchases** (Purchase Accounts); **Freight Inward** (Direct Expenses); **Office Rent**
      (Indirect Expenses).
- [ ] **Cash** (Cash-in-Hand, opening **debit** balance); **HDFC Current** and **SBI Current**
      (in *Current Accounts*); **Axis OD** (Bank OD A/c, opening **credit** balance) (G16).
- [ ] **Output GST** and **Input GST** under Duties & Taxes (they are only ordinary ledgers here:
      GST analytics are out of scope, D-037).
- [ ] **Capital** (Capital Account, opening credit).
- [ ] **Subsidy Receivable** under *Government Schemes*.

## D. Voucher types
- [ ] **POS Invoice**, type of voucher **Sales** (G15, a custom type derived from Sales).
- [ ] **Bank Receipt**, type of voucher **Receipt**.

## E. Stock items
- [ ] Units: **Nos**, **Kgs**, and a compound unit **Box of 12 Nos** (G27).
- [ ] Five items: **Soap** (Nos, alternate unit Box = 12 Nos), **Rice** (Kgs), **Pen** (Nos),
      **Notebook** (Nos), **Bag** (Nos). Opening stock (quantity and value) on **Soap** and
      **Rice** (G17).

## F. Cost centres
- [ ] Two cost centres: **Retail**, **Online** (enable cost centres for the company first).

## G. Vouchers (dates only on the 1st, 2nd or 31st)
- [ ] **Sales** to Sharma Traders with stock items (Soap, Pen), bill-wise **New Ref** `S-1`,
      Output GST line, 1 Apr 2024.
- [ ] **Cash sale** to Walk-in Customer (Cash), with stock, 2 Apr 2024.
- [ ] **Sales** with stock items **plus a Freight/Service ledger line** (non-product revenue,
      G28), 31 May 2024.
- [ ] **POS Invoice** voucher, 1 Jun 2024.
- [ ] **Purchase** from Kumar Wholesale with stock (Soap in Boxes, G27), Input GST, 2 Apr 2024.
- [ ] **Payment** of Office Rent from HDFC Current **with a cost-centre allocation** (Retail
      60% / Online 40%), 31 May 2024.
- [ ] **Journal** touching a bank ledger (e.g. HDFC Current to SBI Current transfer charge),
      1 Jul 2024.
- [ ] **Contra**: Cash → HDFC Current, 2 Jul 2024.
- [ ] **Receipt** from Sharma Traders settling `S-1` in **two parts**, each **Agst Ref** `S-1`
      (1 Jul 2024 and 31 Jul 2024) (G25).
- [ ] **Receipt** from Gupta Stores as **Advance** (1 Aug 2024), and a **Payment** to Singh
      Distributors **On Account** (2 Aug 2024) (G25).
- [ ] **Credit Note** to Sharma Traders **against bill `S-1`** (a sales return, G26), 31 Aug 2024.
- [ ] **Credit Note** to Mehta & Sons **with no bill reference**, 1 Sep 2024.
- [ ] **Debit Note** to Kumar Wholesale, 2 Sep 2024.
- [ ] **Optional voucher**: any voucher marked *Optional*, and a **Sales Order** and a
      **Delivery Note** (these must NOT appear in the voucher capture, G34).
- [ ] At least **25 accounting vouchers** in total (so the 0–20 and 20–40 ALTERID windows both
      have data, G7, G33).
- [ ] **Only if you have a TDL customisation that adds a user-defined field** to vouchers: one
      voucher with it filled in (G22). Otherwise leave G22 for later.

## H. Captures (after all the data above exists)
- [ ] `-Step check` passed with `TA_Minimal.tdl`, then with `TallyAnalytics.tdl`.
- [ ] `-Step all` with `-OtherCompany`.
- [ ] Scenarios, each on its own (the script tells you what to change and captures before and
      after):
  - [ ] `G8`  edit a sales voucher (amount and narration)
  - [ ] `G9`  cancel a voucher
  - [ ] `G11` delete a voucher
  - [ ] `G29` mark a ledger inactive, if TallyPrime has that option
  - [ ] `G32` rename *Sundry Debtors* and voucher type *Sales* (then rename back)
  - [ ] `ACC-7.5` move *Retail Customers* under a different parent (then move back)
  - [ ] `AGT-5.4` rename the company (then rename back)
- [ ] Optional: tally-database-loader CSV output (README, last section).

## Which data proves which gate
| Gate | Evidence from |
|---|---|
| G1–G4, G5, G10 | the `*_full` captures (GUID and ALTERID on every object) |
| G6, G8, G24 | scenario G8 (before/after) |
| G7, G33 | `*_window_*` captures compared with the full ones; company capture |
| G9 | scenario G9 |
| G11, G21 | scenario G11; the `*_keys` captures |
| G12–G15, G32 | groups and voucher types (B, D); scenarios G32 and ACC-7.5 |
| G16, G17, G31 | opening balances and opening bills (C, E) |
| G18, G19 | `stock_closing`, `ledger_closing`; Trial Balance and Stock Summary references |
| G20 | the second company (A); `info_other_company`; scenario AGT-5.4 |
| G22 | the optional user-defined field (G) |
| G23, G28, G30 | the vouchers (G); compared with the Trial Balance reference |
| G25, G26 | receipts, payments and credit notes with bill allocations (G) |
| G27 | units and the compound unit (E); purchase in boxes (G) |
| G29 | scenario G29 |
| G34 | the optional voucher, Sales Order and Delivery Note (G) |
| G35 | the `error_*` captures and every response's encoding |
