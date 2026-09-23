"""Masters (SRS 5.5) with the D-001 classification columns.

A trigger rejects DELETE on every master table (DR-ML-1): lifecycle is a status change.
"""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, Index, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Rate, TallySynced, enum_check, tenant_fk, uuid_pk
from app.models.enums import (
    BaseVoucherType,
    GroupResolution,
    MasterStatus,
    Nature,
    VoucherTypeResolution,
)


def _synced_args(pk: str) -> tuple[Any, ...]:
    return (
        UniqueConstraint("company_id", "tally_guid"),  # DR-4.6
        UniqueConstraint("company_id", pk),  # target of tenant FKs
        enum_check("status", MasterStatus),
    )


class Group(TallySynced, Base):
    """D-001: `classification_group_id` (the anchor) is what every allow-list and metric uses."""

    __tablename__ = "groups"
    __table_args__ = (
        *_synced_args("group_id"),
        tenant_fk("parent_group_id", "groups.group_id"),
        tenant_fk("predefined_group_id", "groups.group_id"),
        tenant_fk("classification_group_id", "groups.group_id"),
        tenant_fk("primary_group_id", "groups.group_id"),
        enum_check("nature", Nature),
        enum_check("resolution_status", GroupResolution),
        CheckConstraint(
            "resolution_status <> 'RESOLVED' OR "
            "(classification_group_id IS NOT NULL AND nature IS NOT NULL)",
            name="resolved_has_anchor",
        ),
        Index(None, "primary_group_id"),
        # A PREDEFINED allow-list entry resolves to its group in one join (D-001).
        Index(
            "uq_groups_company_id_reserved_name",
            "company_id",
            "reserved_name",
            unique=True,
            postgresql_where=text("reserved_name IS NOT NULL"),
        ),
    )

    group_id: Mapped[uuid.UUID] = uuid_pk()
    status: Mapped[str]
    name: Mapped[str]
    parent_group_id: Mapped[uuid.UUID | None]  # null for a primary group or a broken chain
    parent_tally_guid: Mapped[str | None]  # raw parent reference, kept until resolved
    predefined_group_id: Mapped[uuid.UUID | None]  # nearest predefined ancestor, incl. self
    classification_group_id: Mapped[uuid.UUID | None]  # the anchor; null only when broken
    primary_group_id: Mapped[uuid.UUID | None]  # top-level predefined primary group
    nature: Mapped[str | None]
    is_predefined: Mapped[bool]
    reserved_name: Mapped[str | None]  # Tally's reserved name (G32); null for user groups
    resolution_status: Mapped[str]


class Ledger(TallySynced, Base):
    """No closing balance column: balances depend on the date and are computed (SRS 5.5)."""

    __tablename__ = "ledgers"
    __table_args__ = (
        *_synced_args("ledger_id"),
        tenant_fk("group_id", "groups.group_id"),
        tenant_fk("primary_group_id", "groups.group_id"),
        tenant_fk("predefined_group_id", "groups.group_id"),
        tenant_fk("classification_group_id", "groups.group_id"),
        Index(None, "company_id", "primary_group_id"),
        Index(None, "company_id", "classification_group_id"),
    )

    ledger_id: Mapped[uuid.UUID] = uuid_pk()
    status: Mapped[str]
    name: Mapped[str]
    group_id: Mapped[uuid.UUID | None]  # null while the parent group is not yet synced
    parent_group_tally_guid: Mapped[str | None]
    primary_group_id: Mapped[uuid.UUID | None]  # cached from the group
    predefined_group_id: Mapped[uuid.UUID | None]  # cached from the group
    classification_group_id: Mapped[uuid.UUID | None]  # cached from the group
    is_bill_wise: Mapped[bool | None]
    custom_fields: Mapped[dict[str, Any] | None]


class VoucherType(TallySynced, Base):
    __tablename__ = "voucher_types"
    __table_args__ = (
        *_synced_args("voucher_type_id"),
        tenant_fk("parent_voucher_type_id", "voucher_types.voucher_type_id"),
        enum_check("base_voucher_type", BaseVoucherType),
        enum_check("resolution_status", VoucherTypeResolution),
    )

    voucher_type_id: Mapped[uuid.UUID] = uuid_pk()
    status: Mapped[str]
    name: Mapped[str]
    parent_voucher_type_id: Mapped[uuid.UUID | None]
    parent_tally_guid: Mapped[str | None]
    reserved_name: Mapped[str | None]
    base_voucher_type: Mapped[str]
    resolution_status: Mapped[str]


class StockItem(TallySynced, Base):
    __tablename__ = "stock_items"
    __table_args__ = _synced_args("stock_item_id")

    stock_item_id: Mapped[uuid.UUID] = uuid_pk()
    status: Mapped[str]
    name: Mapped[str]
    base_unit: Mapped[str | None]
    gst_rate: Mapped[Decimal | None] = mapped_column(Rate)  # descriptive only
    custom_fields: Mapped[dict[str, Any] | None]


class CostCentre(TallySynced, Base):
    __tablename__ = "cost_centres"
    __table_args__ = _synced_args("cost_centre_id")

    cost_centre_id: Mapped[uuid.UUID] = uuid_pk()
    status: Mapped[str]
    name: Mapped[str]
