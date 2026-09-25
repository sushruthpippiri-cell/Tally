"""P4.3: request builder golden files. Regenerate with UPDATE_GOLDEN=1 and review the diff."""

import os
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from tally_contract import requests as rq
from tally_contract import tally_constants as tc
from tally_contract.enums import CollectionType

GOLDEN = Path(__file__).parent / "golden" / "requests"
CO = "Sharma & Sons Traders"  # an ampersand must be escaped

CASES: dict[str, Callable[[], bytes]] = {
    "info": lambda: rq.info(CO),
    "ledgers_window": lambda: rq.collection(
        CollectionType.LEDGER, CO, from_alter_id=100, to_alter_id=5100
    ),
    "ledgers_full": lambda: rq.collection(CollectionType.LEDGER, CO),
    "ledgers_keys": lambda: rq.collection(CollectionType.LEDGER, CO, keys_only=True),
    "vouchers_window": lambda: rq.collection(
        CollectionType.VOUCHER,
        CO,
        from_alter_id=0,
        to_alter_id=5000,
        date_from=date(2024, 4, 1),
        date_to=tc.FULL_PULL_DATE_TO,
    ),
    "vouchers_template": lambda: rq.collection(
        CollectionType.VOUCHER,
        "{{COMPANY}}",
        from_alter_id="{{FROM_ALTERID}}",
        to_alter_id="{{TO_ALTERID}}",
        date_from="{{BOOKS_FROM}}",
        date_to=tc.FULL_PULL_DATE_TO,
    ),
    "stock_closing": lambda: rq.stock_closing(CO, date(2025, 3, 31)),
    "ledger_closing": lambda: rq.ledger_closing(CO, date(2025, 3, 31)),
    "builtin_company_list": rq.builtin_company_list,
    "builtin_trial_balance": lambda: rq.builtin_report(
        "Trial Balance", CO, date(2024, 4, 1), date(2025, 3, 31)
    ),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_request_matches_golden_file(name: str) -> None:
    built = CASES[name]()
    golden = GOLDEN / f"{name}.xml"
    if os.environ.get("UPDATE_GOLDEN") == "1":
        golden.write_bytes(built)
    assert built == golden.read_bytes(), f"{name}: rerun with UPDATE_GOLDEN=1 and review"


def test_requests_are_well_formed_utf8_without_declaration() -> None:
    for build in CASES.values():
        raw = build()
        assert not raw.startswith(b"<?xml")  # GATE-G35
        root = ET.fromstring(raw.decode("utf-8"))
        assert root.tag == "ENVELOPE"


def test_company_names_are_escaped() -> None:
    raw = rq.info(CO)
    assert b"Sharma &amp; Sons Traders" in raw
    assert ET.fromstring(raw).findtext("BODY/DESC/STATICVARIABLES/SVCURRENTCOMPANY") == CO


@pytest.mark.parametrize("collection", list(CollectionType), ids=str)
def test_every_collection_and_key_list_has_a_request(collection: CollectionType) -> None:
    for keys in (False, True):
        root = ET.fromstring(rq.collection(collection, CO, keys_only=keys))
        report = (tc.KEY_REPORTS if keys else tc.REPORTS)[collection]
        assert root.findtext("HEADER/ID") == report


def test_window_and_dates_go_in_static_variables() -> None:
    root = ET.fromstring(
        rq.collection(
            CollectionType.VOUCHER, CO, from_alter_id=5, to_alter_id=10, date_from=date(2024, 4, 1)
        )
    )
    variables = root.find("BODY/DESC/STATICVARIABLES")
    assert variables is not None
    assert variables.findtext(tc.VAR_FROM_ALTER_ID) == "5"
    assert variables.findtext(tc.VAR_TO_ALTER_ID) == "10"
    from_date = variables.find(tc.VAR_FROM_DATE)
    assert from_date is not None and from_date.text == "20240401"
    assert from_date.get("TYPE") == "Date"
