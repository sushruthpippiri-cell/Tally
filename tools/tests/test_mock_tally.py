"""The mock Tally answers our real requests in the shape our parser reads (K1)."""

import urllib.request
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from tally_contract import requests as rq
from tally_contract import tally_constants as tc
from tally_contract.enums import CollectionType
from tally_contract.errors import ErrorCode
from tally_contract.parser import parse_collection, parse_info, parse_keys
from tally_tools.mock_tally import MockConfig, answer, running


def _post(url: str, body: bytes) -> bytes:
    request = urllib.request.Request(url, data=body, method="POST")
    with urllib.request.urlopen(request, timeout=5) as response:
        return bytes(response.read())


def test_root_says_the_server_is_running() -> None:
    with running(MockConfig()) as url, urllib.request.urlopen(url, timeout=5) as response:
        assert tc.SERVER_RUNNING_TEXT.encode() in response.read()


def test_info_and_collections_parse_with_the_real_parser() -> None:
    with running(MockConfig(companies=["Test Co"])) as url:
        [info] = parse_info(_post(url, rq.info("Test Co"))).records
        assert (info.tdl_version, info.company_name) == (tc.TDL_VERSION, "Test Co")
        for collection in CollectionType:
            dates: dict[str, Any] = (
                {"date_from": date(2024, 4, 1), "date_to": tc.FULL_PULL_DATE_TO}
                if collection == CollectionType.VOUCHER
                else {}
            )
            raw = _post(url, rq.collection(collection, "Test Co", **dates))
            result = parse_collection(raw, collection)
            assert result.ok and len(result.records) == 1, collection
            keys = parse_keys(
                _post(url, rq.collection(collection, "Test Co", keys_only=True, **dates))
            )
            assert [k.alter_id for k in keys.records] == [1]


@pytest.mark.parametrize(
    ("config", "company", "code"),
    [
        (MockConfig(tdl_loaded=False), "Test Co", ErrorCode.TDL_NOT_LOADED),
        (MockConfig(), "Not Open Ltd", ErrorCode.COMPANY_NOT_LOADED),
    ],
)
def test_error_responses_are_recognised(config: MockConfig, company: str, code: ErrorCode) -> None:
    _, body = answer(config, rq.info(company))
    error = parse_info(body).document_error
    assert error is not None and error.code == code


def test_utf16_answers_decode_and_failing_reports_are_http_500() -> None:
    status, body = answer(MockConfig(utf16=True), rq.info("Test Co"))
    assert status == 200 and body.startswith(b"\xff\xfe")
    assert parse_info(body).records[0].company_name == "Test Co"
    status, _ = answer(
        MockConfig(fail_reports={"TA_Ledgers"}), rq.collection(CollectionType.LEDGER, "Test Co")
    )
    assert status == 500


def test_builtin_company_list_names_every_open_company() -> None:
    _, body = answer(MockConfig(companies=["A & B", "C"]), rq.builtin_company_list())
    assert b"A &amp; B" in body and b"<NAME>C</NAME>" in body


def test_edits_between_runs_raise_the_alter_id_as_tally_does() -> None:
    from tally_contract.parser import parse_collection
    from tally_tools.mock_tally import (
        MockConfig,
        cancel_voucher,
        delete,
        edit_voucher,
        sample_company,
    )

    config = MockConfig(data=sample_company(vouchers=3))
    data = config.data
    edited = edit_voucher(config, "v-2", "2360.00")
    cancelled = cancel_voucher(config, "v-3")
    delete(config, "TA_Vouchers", "v-1")
    assert (edited.alter_id, cancelled.alter_id) == (4, 5)

    def parsed(report: str, collection: CollectionType) -> list[Any]:
        xml = "".join(r.xml for r in data[report])
        return parse_collection(f"<ENVELOPE><X>{xml}</X></ENVELOPE>".encode(), collection).records

    vouchers = {v.guid: v for v in parsed("TA_Vouchers", CollectionType.VOUCHER)}
    assert set(vouchers) == {"v-2", "v-3"}
    assert max(e.amount.amount_absolute for e in vouchers["v-2"].entries) == Decimal("2360.00")
    assert vouchers["v-3"].is_cancelled is True
    [company] = parsed("TA_Company", CollectionType.COMPANY)
    assert company.last_voucher_alter_id == 5


# --- serving a generated dataset, at size (P16.5) ---------------------------------------


def test_a_generated_dataset_is_served_and_filtered_like_the_sample(tmp_path: Path) -> None:
    """The dataset drops into the same seam the sample uses, so the ALTERID window, the date
    window and the key-list form all keep working over 60 vouchers instead of 12."""
    from tally_tools import dataset_gen
    from tally_tools.mock_tally import load_dataset

    meta = dataset_gen.build(tmp_path / "ds", vouchers=60)
    config = load_dataset(tmp_path / "ds")
    assert config.companies == [meta["company"]["name"]]
    assert config.guids[meta["company"]["name"]] == meta["company"]["guid"]
    assert len(config.data["TA_Vouchers"]) == 60

    full = _ask(config, "TA_Vouchers", {})
    records = parse_collection(full, CollectionType.VOUCHER)
    assert records.document_error is None and records.errors == []
    assert len(records.records) == 60

    # The half-open ALTERID window (D-013), over the dataset's own voucher sequence.
    window = _ask(config, "TA_Vouchers", {tc.VAR_FROM_ALTER_ID: "10", tc.VAR_TO_ALTER_ID: "20"})
    windowed = parse_collection(window, CollectionType.VOUCHER)
    assert [v.alter_id for v in windowed.records] == list(range(11, 21))

    # And the key-only form comes off the same rows.
    keys = parse_keys(_ask(config, "TA_VouchersKeys", {}))
    assert keys.document_error is None
    assert {k.guid for k in keys.records} == {v.guid for v in records.records}


def _ask(config: Any, report: str, variables: dict[str, str]) -> bytes:
    from tally_tools.mock_tally import answer

    static = "".join(f"<{k}>{v}</{k}>" for k, v in variables.items())
    request = (
        f"<ENVELOPE><HEADER><ID>{report}</ID></HEADER><BODY><DESC><STATICVARIABLES>"
        f"<{tc.VAR_COMPANY}>{config.companies[0]}</{tc.VAR_COMPANY}>{static}"
        "</STATICVARIABLES></DESC></BODY></ENVELOPE>"
    )
    status, body = answer(config, request.encode())
    assert status == 200
    return body


def test_a_rendered_body_is_reused_and_dropped_when_the_data_changes(tmp_path: Path) -> None:
    """The cache is the point of P16.5's mock work - a full sync asks for the same
    100,000-voucher window once per batch - but a stale body would be a silent wrong answer, so
    what is tested is the invalidation, not the speed."""
    from tally_tools import dataset_gen
    from tally_tools.mock_tally import delete, load_dataset

    dataset_gen.build(tmp_path / "ds", vouchers=20)
    config = load_dataset(tmp_path / "ds")

    first = _ask(config, "TA_Vouchers", {})
    assert len(config.bodies) == 1
    assert _ask(config, "TA_Vouchers", {}) == first  # served from the cache

    # A different window is a different entry, not a wrong hit.
    _ask(config, "TA_Vouchers", {tc.VAR_FROM_ALTER_ID: "5", tc.VAR_TO_ALTER_ID: "9"})
    assert len(config.bodies) == 2

    # The dataset's GUIDs are UUIDs, not the sample's `v-N`, so `edit_voucher` (which derives
    # the voucher number from the GUID) does not apply; `delete` is the mutation that does.
    doomed = config.data["TA_Vouchers"][0].guid
    delete(config, "TA_Vouchers", doomed)
    assert config.bodies == {}, "a mutation must drop every rendered body"
    rebuilt = _ask(config, "TA_Vouchers", {})
    assert rebuilt != first, "the rebuilt body must reflect the deletion"
    assert doomed not in rebuilt.decode()


def test_reconciliation_totals_are_computed_once_per_period(tmp_path: Path) -> None:
    """`_recon_totals` reads every voucher with a regex; at benchmark size that cannot run per
    call. Same rule as the bodies: cached per period, dropped on any change."""
    from tally_tools import dataset_gen
    from tally_tools.mock_tally import load_dataset

    dataset_gen.build(tmp_path / "ds", vouchers=30)
    config = load_dataset(tmp_path / "ds")
    period = {tc.VAR_FROM_DATE: "20230401", tc.VAR_TO_DATE: "20260331"}

    first = _ask(config, tc.RECONCILIATION_REPORT, period)
    assert len(config.recon) == 1
    assert _ask(config, tc.RECONCILIATION_REPORT, period) == first
    config.invalidate()
    assert config.recon == {}
    assert _ask(config, tc.RECONCILIATION_REPORT, period) == first  # same answer, recomputed


def test_replacing_the_whole_data_attribute_also_drops_the_cache() -> None:
    """Two mutation shapes exist in this codebase and both have to be safe: assigning one
    report's list, and swapping `data` wholesale. The second bypasses __post_init__, and when it
    was not handled a 200-voucher e2e test silently synced the 12-voucher data it replaced."""
    from tally_tools.mock_tally import MockConfig, Reports, sample_company

    config = MockConfig(companies=["Sharma Traders"], data=sample_company(vouchers=3))
    first = _ask(config, "TA_Vouchers", {})
    assert first.count(b"<VOUCHER>") == 3
    assert config.bodies  # cached

    config.data = sample_company("Sharma Traders", vouchers=9)  # a plain dict, not Reports
    second = _ask(config, "TA_Vouchers", {})

    assert isinstance(config.data, Reports), "the swap must be wrapped, or nothing counts changes"
    assert second.count(b"<VOUCHER>") == 9, "the cache served the data that was replaced"


def test_assigning_one_report_drops_the_cache() -> None:
    from tally_tools.mock_tally import MockConfig, Row, sample_company

    config = MockConfig(companies=["Sharma Traders"], data=sample_company(vouchers=3))
    before = _ask(config, "TA_LedgerClosing", {tc.VAR_TO_DATE: "20260331"})
    config.data["TA_LedgerClosing"] = [
        Row(r.guid, r.alter_id, r.xml.replace("0.00", "7.00"), r.day)
        for r in config.data["TA_LedgerClosing"]
    ]
    after = _ask(config, "TA_LedgerClosing", {tc.VAR_TO_DATE: "20260331"})
    assert after != before, "a direct report assignment must invalidate too"
