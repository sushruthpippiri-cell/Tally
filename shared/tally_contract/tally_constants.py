"""Every fact about TallyPrime the contract relies on, in one place (CLAUDE.md rule 15).

Anything tagged `GATE-Gxx` is a DRAFT until that gate PASSES with live evidence
(docs/validation-gate.md). The gate track (step G-E) corrects these constants and the TDL;
the parser and request builder read them and should not need rewriting.

Names that are *ours* (report IDs, the XML tags our own TDL emits) are not Tally facts and
carry no gate tag; they must match tdl/TallyAnalytics.tdl, which a test checks.
"""

from typing import Final

from tally_contract.enums import CollectionType

# --- our TDL package ----------------------------------------------------------------------
# Bump on every TDL change; must equal TA_TDLVersion in tdl/TallyAnalytics.tdl and
# tdl/TA_Minimal.tdl (tested). The Agent reports it on every heartbeat (VER-1.1).
TDL_VERSION: Final = "0.1.0"

INFO_REPORT: Final = "TA_Info"
REPORTS: Final[dict[CollectionType, str]] = {
    CollectionType.COMPANY: "TA_Company",
    CollectionType.GROUP: "TA_Groups",
    CollectionType.LEDGER: "TA_Ledgers",
    CollectionType.VOUCHER_TYPE: "TA_VoucherTypes",
    CollectionType.STOCK_ITEM: "TA_StockItems",
    CollectionType.COST_CENTRE: "TA_CostCentres",
    CollectionType.VOUCHER: "TA_Vouchers",
}
# FR-1.2 key-only form: GUID and ALTERID only (GATE-G21).
KEY_REPORTS: Final[dict[CollectionType, str]] = {c: f"{r}Keys" for c, r in REPORTS.items()}
STOCK_CLOSING_REPORT: Final = "TA_StockClosing"  # GATE-G18
LEDGER_CLOSING_REPORT: Final = "TA_LedgerClosing"  # GATE-G19
RECONCILIATION_REPORT: Final = "TA_ReconTotals"  # drafted; completed in P10

# XML our reports emit: <ROOT><RECORD>...</RECORD>...</ROOT> (ours, set by XMLTag in the TDL).
RECORD_TAGS: Final[dict[str, str]] = {
    INFO_REPORT: "INFO",
    **{r: c.value for c, r in REPORTS.items()},
    **{r: "KEY" for r in KEY_REPORTS.values()},
    STOCK_CLOSING_REPORT: "STOCK_CLOSING",
    LEDGER_CLOSING_REPORT: "LEDGER_CLOSING",
    RECONCILIATION_REPORT: "RECON_TOTAL",
}

# --- request envelope (GATE-G20, GATE-G7, GATE-G33) ----------------------------------------
# Tally's HTTP XML interface: POST an ENVELOPE; TYPE=Data + ID=<report> exports a report.
ENVELOPE_VERSION: Final = "1"
REQUEST_EXPORT: Final = "Export"
REQUEST_TYPE_DATA: Final = "Data"
VAR_EXPORT_FORMAT: Final = "SVEXPORTFORMAT"
EXPORT_FORMAT_XML: Final = "$$SysName:XML"
VAR_COMPANY: Final = "SVCURRENTCOMPANY"  # GATE-G20: names the company (AGT-5.1, AGT-5.5)
VAR_FROM_DATE: Final = "SVFROMDATE"
VAR_TO_DATE: Final = "SVTODATE"  # GATE-G18 GATE-G19: "as of" = SVTODATE
VAR_FROM_ALTER_ID: Final = "TAFromAlterId"  # GATE-G7 GATE-G33: declared in our TDL
VAR_TO_ALTER_ID: Final = "TAToAlterId"
REQUEST_DATE_FORMAT: Final = "%Y%m%d"  # GATE-G35: SVFROMDATE/SVTODATE accept YYYYMMDD
# GATE-G35: requests go out as UTF-8 without an XML declaration.
REQUEST_CONTENT_TYPE: Final = "text/xml;charset=utf-8"
# GATE-G33: a full voucher pull still sends a date window, or Tally limits a Voucher
# collection to the current period. The Agent sends books-from .. this far-future date.
FULL_PULL_DATE_TO: Final = "20991231"

# --- TallyPrime's built-in collection and reports: CAPTURE KIT ONLY --------------------------
# The Agent never uses built-in reports (FR-1.4); the capture kit uses these to check the
# server and company without our TDL, and to save reference evidence (TEST-4.1, D-038 #4).
REQUEST_TYPE_COLLECTION: Final = "Collection"
BUILTIN_COMPANY_LIST: Final = "List of Companies"  # GATE-G35
BUILTIN_REFERENCE_REPORTS: Final = (  # GATE-G35
    "Trial Balance",
    "Day Book",
    "Stock Summary",
    "List of Accounts",
)

# --- values in responses (GATE-G35 formats) -----------------------------------------------
RESPONSE_DATE_FORMAT: Final = "%Y%m%d"  # GATE-G35: our date fields use UniversalDate
YES: Final = "Yes"  # GATE-G35: Tally logical values
NO: Final = "No"
# GATE-G12: a top-level group's parent is exported as "Primary" (often preceded by the invalid
# character reference &#4;, which sanitising removes) or left empty.
TOP_LEVEL_PARENT_NAMES: Final = ("", "Primary")
# GATE-G23 GATE-G35: amounts may carry a trailing Dr/Cr instead of a sign in some fields.
DEBIT_SUFFIX: Final = "Dr"
CREDIT_SUFFIX: Final = "Cr"

# --- recognising Tally's own answers (GATE-G35) ---------------------------------------------
SERVER_RUNNING_TEXT: Final = "TallyPrime Server is Running"  # GET / on the XML port
ERROR_TAG: Final = "LINEERROR"
# Substrings of a LINEERROR that mean our report is not loaded -> TDL_NOT_LOADED (FR-1.4).
REPORT_NOT_FOUND_MARKERS: Final = ("Could not find Report", "Could not find Form")
# Substrings that mean the named company is not open -> COMPANY_NOT_LOADED (AGT-5.3).
COMPANY_NOT_LOADED_MARKERS: Final = ("Could not set 'SVCurrentCompany'", "Company not loaded")

# --- ledger entries, bills, vouchers (GATE-G23, G25, G9) ----------------------------------
# GATE-G23: a ledger entry's AMOUNT is signed, negative = debit, and ISDEEMEDPOSITIVE=Yes on a
# debit. Both must agree or the record is rejected; nothing is ever guessed (ACC-DATA-3).
DEBIT_IS_NEGATIVE: Final = True
# GATE-G25: exact BILLTYPE values; anything else normalizes to UNSUPPORTED (AGE-BILL-1).
BILL_TYPE_VALUES: Final[dict[str, str]] = {
    "New Ref": "NEW_REF",
    "Agst Ref": "AGST_REF",
    "Advance": "ADVANCE",
    "On Account": "ON_ACCOUNT",
}
