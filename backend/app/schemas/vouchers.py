"""One voucher as synced (FR-DD-1's last level, DR-UDF-2), and audit history (LOG-1.2)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel

Direction = Literal["Dr", "Cr"]


class BillOut(BaseModel):
    allocation_type: str
    reference_name: str | None
    due_date: date | None
    amount: Decimal
    direction: Direction


class CentreOut(BaseModel):
    cost_centre_id: uuid.UUID
    cost_centre_name: str
    amount: Decimal


class EntryOut(BaseModel):
    line: int
    ledger_id: uuid.UUID
    ledger_name: str
    direction: Direction
    amount: Decimal  # the normalized absolute amount (ACC-DATA-1), never Tally's raw text
    bills: list[BillOut]
    cost_centres: list[CentreOut]


class ItemOut(BaseModel):
    stock_item_id: uuid.UUID
    stock_item_name: str
    quantity: Decimal | None
    unit: str | None
    rate: Decimal | None
    amount: Decimal | None
    custom_fields: dict[str, Any] | None


class CustomFieldOut(BaseModel):
    field_key: str
    tally_field: str | None  # None: stored before its mapping was removed
    value: Any


class VoucherDetailOut(BaseModel):
    voucher_id: uuid.UUID
    tally_guid: str
    alter_id: int
    voucher_number: str | None
    voucher_date: date
    voucher_type_name: str
    base_voucher_type: str
    status: str
    narration: str | None
    last_synced_at: datetime | None
    entries: list[EntryOut]
    items: list[ItemOut]
    custom_fields: list[CustomFieldOut]  # shown, never used in any figure (DR-UDF-2)


class AuditEntryOut(BaseModel):
    id: int
    created_at: datetime
    user_id: uuid.UUID | None  # None: a system change
    action: str
    entity_type: str
    entity_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    data_range: dict[str, Any] | None
    result: str
