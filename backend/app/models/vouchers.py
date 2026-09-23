"""Vouchers and their child rows (SRS 5.7, 5.8; D-003 company_id on children, D-004 bills).

Vouchers are never deleted (trigger). Child rows are: SRS 6.9 replaces a modified voucher's
children in one transaction, and the child FKs cascade for that.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    Money,
    Quantity,
    Rate,
    TallySynced,
    bigint_pk,
    enum_check,
    tenant_fk,
    uuid_pk,
)
from app.models.enums import AccountingDirection, AllocationType, VoucherStatus


class Voucher(TallySynced, Base):
    __tablename__ = "vouchers"
    __table_args__ = (
        UniqueConstraint("company_id", "tally_guid"),  # DR-4.1, DR-4.6
        UniqueConstraint("company_id", "voucher_id"),  # target of tenant FKs
        tenant_fk("voucher_type_id", "voucher_types.voucher_type_id"),
        enum_check("status", VoucherStatus),
        Index(None, "company_id", "voucher_date"),
        Index(None, "company_id", "alter_id"),
        Index(None, "company_id", "voucher_type_id", "voucher_date"),
    )

    voucher_id: Mapped[uuid.UUID] = uuid_pk()
    status: Mapped[str]
    voucher_number: Mapped[str | None]  # display only (DR-4.1)
    voucher_type_id: Mapped[uuid.UUID]
    voucher_date: Mapped[date]  # D-020: a date, never shifted by a time zone
    narration: Mapped[str | None]
    custom_fields: Mapped[dict[str, Any] | None]


class VoucherEntry(Base):
    """Normalized fields (SRS 5.8): analytics read accounting_direction, amount_absolute and
    amount_signed; amount_raw is kept for audit only (ACC-DATA-1)."""

    __tablename__ = "voucher_entries"
    __table_args__ = (
        UniqueConstraint("company_id", "voucher_entry_id"),  # target of tenant FKs
        tenant_fk("voucher_id", "vouchers.voucher_id", ondelete="CASCADE"),
        tenant_fk("ledger_id", "ledgers.ledger_id"),
        enum_check("accounting_direction", AccountingDirection),
        CheckConstraint("amount_absolute >= 0", name="amount_absolute"),
        CheckConstraint(
            "amount_signed = CASE WHEN accounting_direction = 'DEBIT' "
            "THEN amount_absolute ELSE -amount_absolute END",
            name="amount_signed",
        ),
        CheckConstraint("is_debit = (accounting_direction = 'DEBIT')", name="is_debit"),
        Index(None, "voucher_id"),
        Index(None, "company_id", "ledger_id"),
    )

    voucher_entry_id: Mapped[int] = bigint_pk()
    company_id: Mapped[uuid.UUID]  # D-003; checked through the composite FKs
    voucher_id: Mapped[uuid.UUID]
    ledger_id: Mapped[uuid.UUID]
    line_sequence: Mapped[int]
    stable_line_id: Mapped[str | None]  # only if Tally exposes one (DR-VE-1)
    amount_raw: Mapped[str]  # exactly as received from Tally; never read by analytics
    is_debit: Mapped[bool]
    amount_absolute: Mapped[Decimal] = mapped_column(Money)
    amount_signed: Mapped[Decimal] = mapped_column(Money)
    accounting_direction: Mapped[str]


class BillAllocation(Base):
    """Bill identity is (company_id, ledger_id, reference_name) (D-004)."""

    __tablename__ = "bill_allocations"
    __table_args__ = (
        tenant_fk("voucher_entry_id", "voucher_entries.voucher_entry_id", ondelete="CASCADE"),
        tenant_fk("ledger_id", "ledgers.ledger_id"),
        enum_check("allocation_type", AllocationType),
        enum_check("accounting_direction", AccountingDirection),
        CheckConstraint("amount_absolute >= 0", name="amount_absolute"),
        Index(None, "voucher_entry_id"),
        Index(None, "company_id", "ledger_id", "reference_name"),
        Index(None, "due_date"),
    )

    id: Mapped[int] = bigint_pk()
    company_id: Mapped[uuid.UUID]  # D-003; checked through the composite FKs
    voucher_entry_id: Mapped[int]
    ledger_id: Mapped[uuid.UUID]  # denormalized from the entry (D-004)
    allocation_type_raw: Mapped[str | None]
    allocation_type: Mapped[str]
    reference_name: Mapped[str | None]
    due_date: Mapped[date | None]
    amount_absolute: Mapped[Decimal] = mapped_column(Money)
    accounting_direction: Mapped[str]


class CostCentreAllocation(Base):
    __tablename__ = "cost_centre_allocations"
    __table_args__ = (
        tenant_fk("voucher_entry_id", "voucher_entries.voucher_entry_id", ondelete="CASCADE"),
        tenant_fk("cost_centre_id", "cost_centres.cost_centre_id"),
        CheckConstraint("amount_absolute >= 0", name="amount_absolute"),
        Index(None, "voucher_entry_id"),
    )

    id: Mapped[int] = bigint_pk()
    company_id: Mapped[uuid.UUID]  # D-003; checked through the composite FKs
    voucher_entry_id: Mapped[int]
    cost_centre_id: Mapped[uuid.UUID]
    amount_absolute: Mapped[Decimal] = mapped_column(Money)


class VoucherItem(Base):
    __tablename__ = "voucher_items"
    __table_args__ = (
        tenant_fk("voucher_id", "vouchers.voucher_id", ondelete="CASCADE"),
        tenant_fk("stock_item_id", "stock_items.stock_item_id"),
        Index(None, "voucher_id"),
        Index(None, "stock_item_id"),
    )

    id: Mapped[int] = bigint_pk()
    company_id: Mapped[uuid.UUID]  # D-003; checked through the composite FKs
    voucher_id: Mapped[uuid.UUID]
    stock_item_id: Mapped[uuid.UUID]
    quantity: Mapped[Decimal] = mapped_column(Quantity)
    unit: Mapped[str | None]
    rate: Mapped[Decimal | None] = mapped_column(Rate)
    amount: Mapped[Decimal] = mapped_column(Money)
    custom_fields: Mapped[dict[str, Any] | None]
