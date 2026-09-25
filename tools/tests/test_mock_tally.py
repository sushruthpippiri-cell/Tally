"""The mock Tally answers our real requests in the shape our parser reads (K1)."""

import urllib.request

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
            result = parse_collection(_post(url, rq.collection(collection, "Test Co")), collection)
            assert result.ok and len(result.records) == 1, collection
            keys = parse_keys(_post(url, rq.collection(collection, "Test Co", keys_only=True)))
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
