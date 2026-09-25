"""P4.1: record schemas (D-005). Money stays Decimal end to end; references carry GUID and
name (D-002); batches are ordered by alter_id (D-026)."""

import json
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from tally_contract.enums import AccountingDirection, AllocationType, CollectionType
from tally_contract.records import (
    Amount,
    AnyRecord,
    BatchEnvelope,
    BillAllocation,
    KeyRecord,
    LedgerEntry,
    LedgerRecord,
    VoucherRecord,
)


def debit(value: str) -> Amount:
    v = Decimal(value)
    return Amount(
        amount_raw=f"-{value}",
        is_debit=True,
        amount_absolute=v,
        amount_signed=v,
        accounting_direction=AccountingDirection.DEBIT,
    )


def credit(value: str) -> Amount:
    v = Decimal(value)
    return Amount(
        amount_raw=value,
        is_debit=False,
        amount_absolute=v,
        amount_signed=-v,
        accounting_direction=AccountingDirection.CREDIT,
    )


def sale(alter_id: int = 10) -> VoucherRecord:
    return VoucherRecord(
        guid=f"v-{alter_id}",
        alter_id=alter_id,
        voucher_number="S/1",
        voucher_type_guid="vt-sales",
        voucher_type_name="Sales",
        voucher_date=date(2024, 4, 1),
        entries=[
            LedgerEntry(
                ledger_guid="l-cust",
                ledger_name="Sharma Traders",
                line_sequence=1,
                amount=debit("1180.00"),
                bill_allocations=[
                    BillAllocation(
                        reference_name="S/1",
                        allocation_type_raw="New Ref",
                        allocation_type=AllocationType.NEW_REF,
                        amount=debit("1180.00"),
                    )
                ],
            ),
            LedgerEntry(ledger_name="Sales", line_sequence=2, amount=credit("1000.00")),
            LedgerEntry(ledger_name="Output GST", line_sequence=3, amount=credit("180.00")),
        ],
    )


def test_money_round_trips_as_decimal_strings_never_floats() -> None:
    voucher = sale()
    payload = json.loads(voucher.model_dump_json())
    assert payload["entries"][0]["amount"]["amount_absolute"] == "1180.00"
    back = VoucherRecord.model_validate_json(voucher.model_dump_json())
    assert back == voucher
    assert isinstance(back.entries[0].amount.amount_signed, Decimal)


def test_references_carry_guid_and_always_a_name() -> None:
    """D-002: the GUID may be missing (G30 not passed); the name never is."""
    entry = sale().entries[1]
    assert (entry.ledger_guid, entry.ledger_name) == (None, "Sales")
    with pytest.raises(ValidationError):
        LedgerEntry.model_validate({"line_sequence": 1, "amount": debit("1").model_dump()})


@pytest.mark.parametrize(
    "fields",
    [
        {"is_debit": True, "accounting_direction": "CREDIT"},
        {"amount_signed": Decimal("-5")},  # a debit must be positive
        {"amount_absolute": Decimal("-5"), "amount_signed": Decimal("-5")},
    ],
)
def test_inconsistent_amounts_are_rejected(fields: dict[str, Any]) -> None:
    base = debit("5").model_dump() | fields
    with pytest.raises(ValidationError):
        Amount.model_validate(base)


def test_records_are_immutable_and_reject_unknown_fields() -> None:
    record = KeyRecord(guid="g", alter_id=1)
    with pytest.raises(ValidationError):
        record.alter_id = 2  # type: ignore[misc]
    with pytest.raises(ValidationError):
        KeyRecord.model_validate({"guid": "g", "alter_id": 1, "surprise": True})


def test_any_record_is_chosen_by_record_type() -> None:
    adapter: TypeAdapter[Any] = TypeAdapter(AnyRecord)
    ledger = adapter.validate_python(
        {
            "record_type": "LEDGER",
            "guid": "l",
            "alter_id": 3,
            "name": "Cash",
            "parent_group_name": "Cash-in-Hand",
        }
    )
    assert isinstance(ledger, LedgerRecord)
    key = adapter.validate_python({"record_type": "KEY", "guid": "l", "alter_id": 3})
    assert isinstance(key, KeyRecord)


def _envelope(**kw: Any) -> BatchEnvelope:
    return BatchEnvelope(
        collection_type=CollectionType.VOUCHER,
        command_id=uuid.uuid4(),
        sync_run_id=uuid.uuid4(),
        batch_seq=0,
        batch_id=uuid.uuid4(),
        **kw,
    )


def test_envelope_round_trips_with_its_window() -> None:
    env = _envelope(
        window={"kind": "ALTER_ID", "from_alter_id": 0, "to_alter_id": 5000},
        records=[sale(3), sale(7)],
    )
    back = BatchEnvelope.model_validate_json(env.model_dump_json())
    assert back == env and back.contract_version == "1.0"


def test_envelope_records_must_be_sorted_by_alter_id() -> None:
    with pytest.raises(ValidationError, match="sorted by alter_id"):
        _envelope(records=[sale(7), sale(3)])


def test_envelope_records_must_belong_to_its_collection() -> None:
    ledger = LedgerRecord(guid="l", alter_id=1, name="Cash", parent_group_name="Cash-in-Hand")
    with pytest.raises(ValidationError, match="LEDGER"):
        _envelope(records=[ledger])
    assert _envelope(records=[KeyRecord(guid="v", alter_id=1)]).records  # key lists are fine


def test_windows_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        _envelope(window={"kind": "ALTER_ID", "from_alter_id": 10, "to_alter_id": 5})
    with pytest.raises(ValidationError):
        _envelope(window={"kind": "DATE", "date_from": "2024-05-01", "date_to": "2024-04-01"})
