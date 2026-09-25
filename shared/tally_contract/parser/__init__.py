"""Parse Tally's responses to our reports into records (P4.4). Every function returns a
ParseResult and never raises (TEST-1.4)."""

import xml.etree.ElementTree as ET
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict

from tally_contract import tally_constants as tc
from tally_contract.enums import CollectionType
from tally_contract.parser import builders
from tally_contract.parser.document import DocumentError, ParseResult, parse
from tally_contract.records import (
    KeyRecord,
    LedgerClosingBalanceRecord,
    StockSnapshotRecord,
)
from tally_contract.values import text

__all__ = [
    "DocumentError",
    "ParseResult",
    "TallyInfo",
    "parse_collection",
    "parse_info",
    "parse_keys",
    "parse_ledger_closing",
    "parse_stock_closing",
]

_BUILDERS: dict[CollectionType, Callable[[ET.Element], Any]] = {
    CollectionType.COMPANY: builders.company,
    CollectionType.GROUP: builders.group,
    CollectionType.LEDGER: builders.ledger,
    CollectionType.VOUCHER_TYPE: builders.voucher_type,
    CollectionType.STOCK_ITEM: builders.stock_item,
    CollectionType.COST_CENTRE: builders.cost_centre,
    CollectionType.VOUCHER: builders.voucher,
}


class TallyInfo(BaseModel):
    """What TA_Info reports: our TDL version and the named company (VER-1.1, AGT-3.2)."""

    model_config = ConfigDict(frozen=True)
    tdl_version: str
    company_guid: str
    company_name: str


def parse_collection(raw: bytes, collection_type: CollectionType) -> ParseResult[Any]:
    report = tc.REPORTS[collection_type]
    return parse(raw, tc.RECORD_TAGS[report], _BUILDERS[collection_type])


def parse_keys(raw: bytes) -> ParseResult[KeyRecord]:
    return parse(raw, "KEY", builders.key)


def parse_stock_closing(raw: bytes) -> ParseResult[StockSnapshotRecord]:
    return parse(raw, tc.RECORD_TAGS[tc.STOCK_CLOSING_REPORT], builders.stock_closing)


def parse_ledger_closing(raw: bytes) -> ParseResult[LedgerClosingBalanceRecord]:
    return parse(raw, tc.RECORD_TAGS[tc.LEDGER_CLOSING_REPORT], builders.ledger_closing)


def _info(e: ET.Element) -> TallyInfo:
    guid = text(e.findtext("COMPANYGUID"))
    if not guid:  # the company is not open, or the TDL cannot see it
        raise ValueError("TA_Info returned no company GUID")
    return TallyInfo(
        tdl_version=text(e.findtext("TDLVERSION")) or "",
        company_guid=guid,
        company_name=text(e.findtext("COMPANYNAME")) or "",
    )


def parse_info(raw: bytes) -> ParseResult[TallyInfo]:
    return parse(raw, tc.RECORD_TAGS[tc.INFO_REPORT], _info)
