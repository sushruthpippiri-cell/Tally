"""Opening balances and stock snapshots (SRS 5.6), and opening bill allocations (D-022)."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    Money,
    Quantity,
    bigint_pk,
    company_id_col,
    enum_check,
    tenant_fk,
)
from app.models.enums import AccountingDirection


class LedgerOpeningBalance(Base):
    __tablename__ = "ledger_opening_balances"
    __table_args__ = (
        tenant_fk("ledger_id", "ledgers.ledger_id"),
        enum_check("accounting_direction", AccountingDirection),
        CheckConstraint("amount_absolute >= 0", name="amount_absolute"),
    )

    company_id: Mapped[uuid.UUID] = company_id_col()
    ledger_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    financial_year_start: Mapped[date] = mapped_column(primary_key=True)
    amount_absolute: Mapped[Decimal] = mapped_column(Money)
    accounting_direction: Mapped[str]


class StockOpeningBalance(Base):
    __tablename__ = "stock_opening_balances"
    __table_args__ = (tenant_fk("stock_item_id", "stock_items.stock_item_id"),)

    company_id: Mapped[uuid.UUID] = company_id_col()
    stock_item_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    financial_year_start: Mapped[date] = mapped_column(primary_key=True)
    quantity: Mapped[Decimal] = mapped_column(Quantity)
    unit: Mapped[str | None]
    value: Mapped[Decimal | None] = mapped_column(Money)


class StockSnapshot(Base):
    __tablename__ = "stock_snapshots"
    __table_args__ = (
        tenant_fk("stock_item_id", "stock_items.stock_item_id"),
        tenant_fk("sync_run_id", "sync_runs.sync_run_id"),
    )

    company_id: Mapped[uuid.UUID] = company_id_col()
    stock_item_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    as_of_date: Mapped[date] = mapped_column(primary_key=True)
    closing_quantity: Mapped[Decimal] = mapped_column(Quantity)
    unit: Mapped[str | None]
    sync_run_id: Mapped[uuid.UUID | None]


class OpeningBillAllocation(Base):
    """Bills outstanding at books-beginning, stored by Tally on the ledger (D-022).
    Aging treats them as New References."""

    __tablename__ = "opening_bill_allocations"
    __table_args__ = (
        tenant_fk("ledger_id", "ledgers.ledger_id"),
        enum_check("accounting_direction", AccountingDirection),
        CheckConstraint("amount_absolute >= 0", name="amount_absolute"),
        # Bill identity is (company, ledger, reference) (D-004), per financial year.
        UniqueConstraint(
            "company_id",
            "ledger_id",
            "financial_year_start",
            "reference_name",
            name="uq_opening_bill_allocations_bill",
        ),
    )

    id: Mapped[int] = bigint_pk()
    company_id: Mapped[uuid.UUID] = company_id_col(index=False)
    ledger_id: Mapped[uuid.UUID]
    reference_name: Mapped[str]
    bill_date: Mapped[date | None]
    due_date: Mapped[date | None]
    amount_absolute: Mapped[Decimal] = mapped_column(Money)
    accounting_direction: Mapped[str]
    financial_year_start: Mapped[date]
