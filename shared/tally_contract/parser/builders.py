"""One function per record tag: an XML element (as our TDL emits it) -> a record."""

import xml.etree.ElementTree as ET
from decimal import Decimal

from tally_contract import normalize
from tally_contract import tally_constants as tc
from tally_contract.records import (
    BillAllocation,
    CompanyRecord,
    CostCentreAllocation,
    CostCentreRecord,
    GroupRecord,
    InventoryEntry,
    KeyRecord,
    LedgerClosingBalanceRecord,
    LedgerEntry,
    LedgerRecord,
    OpeningBill,
    StockItemRecord,
    StockSnapshotRecord,
    VoucherRecord,
    VoucherTypeRecord,
)
from tally_contract.values import (
    parse_bool,
    parse_date,
    parse_int,
    parse_optional_date,
    parse_plain_decimal,
    parse_quantity,
    parse_rate,
    text,
)


def _get(e: ET.Element, tag: str) -> str | None:
    return text(e.findtext(tag))


def _required(e: ET.Element, tag: str) -> str:
    value = _get(e, tag)
    if value is None:
        raise ValueError(f"{tag} is missing")
    return value


def _optional_int(e: ET.Element, tag: str) -> int | None:
    value = _get(e, tag)
    return None if value is None else parse_int(value)


def _parent(e: ET.Element) -> str | None:
    """GATE-G12: "Primary" (or empty) means a top-level object."""
    name = _get(e, "PARENT")
    return None if name is None or name in tc.TOP_LEVEL_PARENT_NAMES else name


def _synced(e: ET.Element) -> dict[str, object]:
    return {
        "guid": _required(e, "GUID"),
        "alter_id": parse_int(_get(e, "ALTERID")),  # GATE-G1..G5
        "name": _required(e, "NAME"),
    }


def company(e: ET.Element) -> CompanyRecord:
    return CompanyRecord.model_validate(
        _synced(e)
        | {
            "books_from": parse_optional_date(_get(e, "BOOKSFROM")),
            "financial_year_start": parse_optional_date(_get(e, "FYSTART")),
            "last_master_alter_id": _optional_int(e, "LASTMASTERALTERID"),
            "last_voucher_alter_id": _optional_int(e, "LASTVOUCHERALTERID"),
        }
    )


def group(e: ET.Element) -> GroupRecord:
    return GroupRecord.model_validate(
        _synced(e)
        | {
            "parent_name": _parent(e),
            "parent_guid": _get(e, "PARENTGUID") if _parent(e) else None,
            "reserved_name": _get(e, "RESERVEDNAME"),
            "is_revenue": parse_bool(_get(e, "ISREVENUE")),
            "is_deemed_positive": parse_bool(_get(e, "ISDEEMEDPOSITIVE")),
            "affects_gross_profit": parse_bool(_get(e, "AFFECTSGROSSPROFIT")),
        }
    )


def _opening_bill(e: ET.Element) -> OpeningBill:
    return OpeningBill(
        reference_name=_required(e, "NAME"),
        bill_date=parse_optional_date(_get(e, "BILLDATE")),
        due_date=parse_optional_date(_get(e, "DUEDATE")),
        amount=normalize.to_amount(_required(e, "AMOUNT")),
    )


def ledger(e: ET.Element) -> LedgerRecord:
    opening = _get(e, "OPENINGBALANCE")
    return LedgerRecord.model_validate(
        _synced(e)
        | {
            "parent_group_name": _parent(e) or "",
            "parent_group_guid": _get(e, "PARENTGUID"),
            "is_bill_wise": parse_bool(_get(e, "ISBILLWISE")),
            "opening_balance": None if opening is None else normalize.to_amount(opening),
            "opening_bills": [_opening_bill(b) for b in e.iter("OPENINGBILL")],
            "is_inactive": parse_bool(_get(e, "ISINACTIVE")),  # GATE-G29
        }
    )


def voucher_type(e: ET.Element) -> VoucherTypeRecord:
    return VoucherTypeRecord.model_validate(
        _synced(e)
        | {
            "parent_name": _parent(e),
            "parent_guid": _get(e, "PARENTGUID") if _parent(e) else None,
            "reserved_name": _get(e, "RESERVEDNAME"),
        }
    )


def stock_item(e: ET.Element) -> StockItemRecord:
    quantity, _unit = parse_quantity(_get(e, "OPENINGQTY"))
    conversion = parse_plain_decimal(_get(e, "CONVERSION"))
    denominator = parse_plain_decimal(_get(e, "DENOMINATOR"))
    return StockItemRecord.model_validate(
        _synced(e)
        | {
            "base_unit": _get(e, "BASEUNIT"),
            "alternate_unit": _get(e, "ALTERNATEUNIT"),
            # GATE-G27: base units per alternate unit, when both parts are exported
            "conversion": (conversion / denominator if conversion and denominator else None),
            "opening_quantity": quantity,
            "opening_value": _absolute_or_none(_get(e, "OPENINGVALUE")),
            "opening_rate": parse_rate(_get(e, "OPENINGRATE"))[0],
        }
    )


def _absolute_or_none(raw: str | None) -> Decimal | None:
    return None if raw is None else normalize.absolute(raw)


def cost_centre(e: ET.Element) -> CostCentreRecord:
    return CostCentreRecord.model_validate(_synced(e) | {"parent_name": _parent(e)})


def key(e: ET.Element) -> KeyRecord:
    return KeyRecord(guid=_required(e, "GUID"), alter_id=parse_int(_get(e, "ALTERID")))


# --- vouchers --------------------------------------------------------------------------


def _bill(e: ET.Element) -> BillAllocation:
    raw_type = _get(e, "BILLTYPE") or ""
    return BillAllocation(
        reference_name=_required(e, "NAME"),
        allocation_type_raw=raw_type,
        allocation_type=normalize.allocation_type(raw_type),
        due_date=parse_optional_date(_get(e, "DUEDATE")),
        amount=normalize.to_amount(_required(e, "AMOUNT")),
    )


def _cost_centre_allocation(e: ET.Element) -> CostCentreAllocation:
    return CostCentreAllocation(
        cost_centre_guid=_get(e, "COSTCENTREGUID"),
        cost_centre_name=_required(e, "NAME"),
        amount_absolute=normalize.absolute(_required(e, "AMOUNT")),
    )


def _ledger_entry(e: ET.Element, sequence: int) -> LedgerEntry:
    return LedgerEntry(
        ledger_guid=_get(e, "LEDGERGUID"),
        ledger_name=_required(e, "LEDGERNAME"),
        line_sequence=sequence,
        amount=normalize.to_amount(_required(e, "AMOUNT"), parse_bool(_get(e, "ISDEEMEDPOSITIVE"))),
        bill_allocations=[_bill(b) for b in e.iter("BILLALLOCATION")],
        cost_centre_allocations=[
            _cost_centre_allocation(c) for c in e.iter("COSTCENTREALLOCATION")
        ],
    )


def _inventory_entry(e: ET.Element, sequence: int) -> InventoryEntry:
    quantity, unit = parse_quantity(_get(e, "QUANTITY"))
    rate, rate_unit = parse_rate(_get(e, "RATE"))
    return InventoryEntry(
        stock_item_guid=_get(e, "STOCKITEMGUID"),
        stock_item_name=_required(e, "STOCKITEMNAME"),
        line_sequence=sequence,
        quantity=None if quantity is None else abs(quantity),
        unit=unit or rate_unit,
        rate=rate,
        amount=normalize.to_amount(_required(e, "AMOUNT"), parse_bool(_get(e, "ISDEEMEDPOSITIVE"))),
    )


def voucher(e: ET.Element) -> VoucherRecord:
    return VoucherRecord(
        guid=_required(e, "GUID"),
        alter_id=parse_int(_get(e, "ALTERID")),
        voucher_number=_get(e, "VOUCHERNUMBER"),
        voucher_type_guid=_get(e, "VOUCHERTYPEGUID"),
        voucher_type_name=_required(e, "VOUCHERTYPENAME"),
        voucher_date=parse_date(_get(e, "DATE")),
        narration=_get(e, "NARRATION"),
        is_cancelled=parse_bool(_get(e, "ISCANCELLED")) is True,  # GATE-G9
        entries=[_ledger_entry(x, i) for i, x in enumerate(e.findall("LEDGERENTRY"), 1)],
        items=[_inventory_entry(x, i) for i, x in enumerate(e.findall("INVENTORYENTRY"), 1)],
    )


# --- closing balances as of a date --------------------------------------------------------


def stock_closing(e: ET.Element) -> StockSnapshotRecord:
    quantity, unit = parse_quantity(_get(e, "CLOSINGQTY"))
    return StockSnapshotRecord(
        stock_item_guid=_required(e, "GUID"),
        as_of_date=parse_date(_get(e, "ASOFDATE")),
        closing_quantity=quantity if quantity is not None else Decimal(0),
        unit=unit,
    )


def ledger_closing(e: ET.Element) -> LedgerClosingBalanceRecord:
    return LedgerClosingBalanceRecord(
        ledger_guid=_required(e, "GUID"),
        as_of_date=parse_date(_get(e, "ASOFDATE")),
        balance=normalize.to_amount(_get(e, "CLOSINGBALANCE") or "0"),
    )
