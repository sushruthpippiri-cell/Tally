"""P1.1: schema-wide conventions, checked on the model metadata so every new table obeys them."""

import pytest
from sqlalchemy import CheckConstraint, DateTime, Float, Numeric, Text, UniqueConstraint

from app.models import Base
from app.models.base import enum_check
from app.models.enums import AccountingDirection

TABLES = Base.metadata.sorted_tables
ALLOWED_NUMERIC = {(20, 4), (20, 6)}  # Money; Quantity and Rate (D-010)


def test_enum_check_lists_every_member() -> None:
    ck = enum_check("accounting_direction", AccountingDirection)
    assert str(ck.sqltext) == "accounting_direction IN ('DEBIT', 'CREDIT')"
    assert ck.name == "accounting_direction"


def test_no_float_columns_and_numeric_precision_is_fixed() -> None:
    for table in TABLES:
        for col in table.columns:
            assert not isinstance(col.type, Float), f"{table.name}.{col.name} is float"
            if isinstance(col.type, Numeric):
                precision = (col.type.precision, col.type.scale)
                assert precision in ALLOWED_NUMERIC, f"{table.name}.{col.name} {precision}"


def test_every_timestamp_is_timestamptz() -> None:
    for table in TABLES:
        for col in table.columns:
            if isinstance(col.type, DateTime):
                assert col.type.timezone, f"{table.name}.{col.name} is timestamp without tz"


@pytest.mark.req("DR-4.6")
def test_synced_tables_are_unique_on_company_and_guid() -> None:
    """Every table with tally_guid + alter_id has UNIQUE(company_id, tally_guid)."""
    synced = [t for t in TABLES if "tally_guid" in t.c and "alter_id" in t.c]
    for table in synced:
        uniques = {
            tuple(c.name for c in con.columns)
            for con in table.constraints
            if isinstance(con, UniqueConstraint)
        }
        assert ("company_id", "tally_guid") in uniques, table.name


def test_status_columns_have_a_check() -> None:
    for table in TABLES:
        checked = {c.name for c in table.constraints if isinstance(c, CheckConstraint)}
        for col in table.columns:
            is_status = col.name == "status" or col.name.endswith("_status")
            if is_status and isinstance(col.type, Text):  # skips e.g. agents.queue_status (jsonb)
                assert f"ck_{table.name}_{col.name}" in checked, f"{table.name}.{col.name}"
