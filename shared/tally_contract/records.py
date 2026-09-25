"""Records the Agent uploads to the backend (D-005, P4.1). Money is Decimal (a string in JSON),
dates are dates, and nothing is float. Every reference to a master carries its GUID when the
TDL can emit it (G30, D-002) and always its name, the fallback.

Amounts come in one shape, `Amount`, built only by `tally_contract.normalize` (ACC-DATA-2).
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tally_contract.enums import AccountingDirection, AllocationType, CollectionType
from tally_contract.errors import ErrorCode
from tally_contract.version import CONTRACT_VERSION

CustomValue = str | int | Decimal | bool | date | None


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Amount(_Record):
    """SRS 5.8. amount_raw is kept exactly as received, for audit only (ACC-DATA-1)."""

    amount_raw: str
    is_debit: bool
    amount_absolute: Decimal = Field(ge=0)
    amount_signed: Decimal  # debit positive, credit negative
    accounting_direction: AccountingDirection

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        direction = AccountingDirection.DEBIT if self.is_debit else AccountingDirection.CREDIT
        signed = self.amount_absolute if self.is_debit else -self.amount_absolute
        if self.accounting_direction != direction or self.amount_signed != signed:
            raise ValueError("amount fields disagree (is_debit, direction, signed, absolute)")
        return self


# --- masters -------------------------------------------------------------------------------


class _Synced(_Record):
    guid: str = Field(min_length=1)
    alter_id: int = Field(ge=0)  # GATE-G1..G5: integer on every object
    name: str


class CompanyRecord(_Synced):
    record_type: Literal["COMPANY"] = "COMPANY"
    books_from: date | None = None
    financial_year_start: date | None = None
    last_master_alter_id: int | None = None  # GATE-G33
    last_voucher_alter_id: int | None = None  # GATE-G33


class GroupRecord(_Synced):
    record_type: Literal["GROUP"] = "GROUP"
    parent_guid: str | None = None  # GATE-G12
    parent_name: str | None = None  # None: directly under Primary
    reserved_name: str | None = None  # GATE-G32
    is_revenue: bool | None = None  # GATE-G14 nature hints
    is_deemed_positive: bool | None = None
    affects_gross_profit: bool | None = None


class OpeningBill(_Record):
    """A bill outstanding at books-beginning, held on the ledger master (D-022, GATE-G31)."""

    reference_name: str
    bill_date: date | None = None
    due_date: date | None = None
    amount: Amount


class LedgerRecord(_Synced):
    record_type: Literal["LEDGER"] = "LEDGER"
    parent_group_guid: str | None = None  # GATE-G30-style GUID of the parent group
    parent_group_name: str
    is_bill_wise: bool | None = None
    opening_balance: Amount | None = None  # GATE-G16
    opening_bills: list[OpeningBill] = []  # GATE-G31
    is_inactive: bool | None = None  # GATE-G29: None = Tally does not tell us
    custom_fields: dict[str, CustomValue] = {}


class VoucherTypeRecord(_Synced):
    record_type: Literal["VOUCHER_TYPE"] = "VOUCHER_TYPE"
    parent_guid: str | None = None  # GATE-G15
    parent_name: str | None = None
    reserved_name: str | None = None  # GATE-G32


class StockItemRecord(_Synced):
    record_type: Literal["STOCK_ITEM"] = "STOCK_ITEM"
    base_unit: str | None = None  # GATE-G27
    alternate_unit: str | None = None
    conversion: Decimal | None = None  # base units per alternate unit
    opening_quantity: Decimal | None = None  # GATE-G17
    opening_value: Decimal | None = None
    opening_rate: Decimal | None = None
    custom_fields: dict[str, CustomValue] = {}


class CostCentreRecord(_Synced):
    record_type: Literal["COST_CENTRE"] = "COST_CENTRE"
    parent_name: str | None = None


# --- vouchers ------------------------------------------------------------------------------


class BillAllocation(_Record):
    reference_name: str
    allocation_type_raw: str  # GATE-G25, exactly as exported
    allocation_type: AllocationType
    due_date: date | None = None
    amount: Amount


class CostCentreAllocation(_Record):
    cost_centre_guid: str | None = None  # GATE-G30
    cost_centre_name: str
    amount_absolute: Decimal = Field(ge=0)


class LedgerEntry(_Record):
    ledger_guid: str | None = None  # GATE-G30; None -> name fallback (D-002)
    ledger_name: str
    line_sequence: int = Field(ge=1)
    stable_line_id: str | None = None  # GATE-G24
    amount: Amount
    bill_allocations: list[BillAllocation] = []
    cost_centre_allocations: list[CostCentreAllocation] = []


class InventoryEntry(_Record):
    stock_item_guid: str | None = None  # GATE-G30
    stock_item_name: str
    line_sequence: int = Field(ge=1)
    quantity: Decimal | None = None  # GATE-G27
    unit: str | None = None
    rate: Decimal | None = None
    amount: Amount
    custom_fields: dict[str, CustomValue] = {}


class VoucherRecord(_Record):
    record_type: Literal["VOUCHER"] = "VOUCHER"
    guid: str = Field(min_length=1)
    alter_id: int = Field(ge=0)
    voucher_number: str | None = None  # display only (DR-4.x)
    voucher_type_guid: str | None = None  # GATE-G30
    voucher_type_name: str
    voucher_date: date
    narration: str | None = None
    is_cancelled: bool = False  # GATE-G9
    custom_fields: dict[str, CustomValue] = {}
    entries: list[LedgerEntry] = []
    items: list[InventoryEntry] = []


# --- key lists, snapshots, balances, reconciliation ---------------------------------------


class KeyRecord(_Record):
    """Key-only export for deletion detection (FR-1.2, GATE-G21)."""

    record_type: Literal["KEY"] = "KEY"
    guid: str = Field(min_length=1)
    alter_id: int = Field(ge=0)


class StockSnapshotRecord(_Record):
    """Tally-computed closing quantity as of a date (SRS 11.3, GATE-G18)."""

    record_type: Literal["STOCK_SNAPSHOT"] = "STOCK_SNAPSHOT"
    stock_item_guid: str
    as_of_date: date
    closing_quantity: Decimal
    unit: str | None = None


class LedgerClosingBalanceRecord(_Record):
    """Tally's closing balance as of a date (GATE-G19)."""

    record_type: Literal["LEDGER_CLOSING_BALANCE"] = "LEDGER_CLOSING_BALANCE"
    ledger_guid: str
    as_of_date: date
    balance: Amount


class ReconciliationTotalRecord(_Record):
    """A Tally-side total for reconciliation (drafted here, completed in P10, D-008)."""

    record_type: Literal["RECONCILIATION_TOTAL"] = "RECONCILIATION_TOTAL"
    metric: str
    period_start: date
    period_end: date
    entity_guid: str | None = None
    value: Decimal


AnyRecord = Annotated[
    CompanyRecord
    | GroupRecord
    | LedgerRecord
    | VoucherTypeRecord
    | StockItemRecord
    | CostCentreRecord
    | VoucherRecord
    | KeyRecord
    | StockSnapshotRecord
    | LedgerClosingBalanceRecord
    | ReconciliationTotalRecord,
    Field(discriminator="record_type"),
]

_HAS_ALTER_ID = (
    CompanyRecord,
    GroupRecord,
    LedgerRecord,
    VoucherTypeRecord,
    StockItemRecord,
    CostCentreRecord,
    VoucherRecord,
    KeyRecord,
)
RECORD_TYPE_FOR_COLLECTION: dict[CollectionType, str] = {c: c.value for c in CollectionType}


# --- errors and the upload envelope --------------------------------------------------------


class ParseError(_Record):
    """One record that could not be parsed; parsing continued (SYNC-6.5)."""

    guid: str | None = None
    code: ErrorCode = ErrorCode.PARSE_ERROR
    message: str
    snippet: str | None = Field(default=None, max_length=500)


class AlterIdWindow(_Record):
    kind: Literal["ALTER_ID"] = "ALTER_ID"
    from_alter_id: int = Field(ge=0)  # exclusive
    to_alter_id: int = Field(ge=0)  # inclusive

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.to_alter_id < self.from_alter_id:
            raise ValueError("to_alter_id must not be below from_alter_id")
        return self


class DateWindow(_Record):
    kind: Literal["DATE"] = "DATE"
    date_from: date
    date_to: date

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.date_to < self.date_from:
            raise ValueError("date_to must not be before date_from")
        return self


class BatchEnvelope(_Record):
    """One upload batch (D-005). Records are sorted by alter_id ascending (D-026) and belong
    to the envelope's collection (or are its key list)."""

    contract_version: str = CONTRACT_VERSION
    collection_type: CollectionType | None  # None: snapshots, balances, reconciliation
    command_id: uuid.UUID
    sync_run_id: uuid.UUID
    batch_seq: int = Field(ge=0)
    batch_id: uuid.UUID
    window: Annotated[AlterIdWindow | DateWindow, Field(discriminator="kind")] | None = None
    records: list[AnyRecord] = []
    parse_errors: list[ParseError] = []

    @model_validator(mode="after")
    def _records_fit(self) -> Self:
        if self.collection_type is not None:
            allowed = {RECORD_TYPE_FOR_COLLECTION[self.collection_type], "KEY"}
            wrong = {r.record_type for r in self.records} - allowed
            if wrong:
                raise ValueError(f"{sorted(wrong)} records in a {self.collection_type} batch")
            alter_ids = [r.alter_id for r in self.records if isinstance(r, _HAS_ALTER_ID)]
            if alter_ids != sorted(alter_ids):
                raise ValueError("records must be sorted by alter_id (D-026)")
        return self
