"""Declarative base, column types and helpers shared by every model (P1.1).

- Money/Quantity/Rate are NUMERIC (D-010); money is never float (CLAUDE.md rule 10).
- Every `datetime` column is timestamptz; business dates are `date` (D-020).
- Enum columns are `text` + a CHECK generated from one StrEnum in `enums.py`.
- Company-scoped references are composite FKs `(company_id, x_id)`, so a row can never
  point at another company's row (SEC-1.7, D-031).
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    MetaData,
    Numeric,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names, so autogenerate output never depends on the database.
NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}

Money = Numeric(20, 4)
Quantity = Numeric(20, 6)
Rate = Numeric(20, 6)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {
        str: Text(),
        datetime: DateTime(timezone=True),
        uuid.UUID: UUID(as_uuid=True),
        dict[str, Any]: JSONB(),
        list[Any]: JSONB(),
    }


def uuid_pk() -> Mapped[uuid.UUID]:
    """UUID primary key (D-010), generated in Python so it is known before flush."""
    return mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )


def bigint_pk() -> Mapped[int]:
    """BIGINT identity primary key (D-010) for high-volume rows."""
    return mapped_column(BigInteger, primary_key=True, autoincrement=True)


def created_at() -> Mapped[datetime]:
    return mapped_column(server_default=text("now()"))


def company_id_col() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("companies.company_id"), index=True)


def enum_check(column: str, enum: type[StrEnum]) -> CheckConstraint:
    """CHECK (column IN (...)) from a StrEnum; NULL passes, so nullability is the column's."""
    values = ", ".join(f"'{member.value}'" for member in enum)
    return CheckConstraint(f"{column} IN ({values})", name=column)


def tenant_fk(column: str, target: str, **kwargs: Any) -> ForeignKeyConstraint:
    """FK (company_id, column) -> table(company_id, pk). `target` is 'table.pk_column'."""
    table = target.split(".")[0]
    return ForeignKeyConstraint(["company_id", column], [f"{table}.company_id", target], **kwargs)


class TallySynced:
    """Columns every synced master and voucher carries (SRS 5.1-2/3, DR-4.6).

    Tables using it add `UniqueConstraint("company_id", "tally_guid")` and their own
    `status` column (masters and vouchers have different lifecycles).
    """

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.company_id"))
    tally_guid: Mapped[str]
    alter_id: Mapped[int] = mapped_column(BigInteger)
    last_synced_at: Mapped[datetime | None]
