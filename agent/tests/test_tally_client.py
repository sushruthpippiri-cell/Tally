"""P7.3: TallyPrime's XML server and the SRS 16 error codes."""

import os
from typing import Any

import pytest

from tally_agent.tally_client import TallyError, TallyTimeout
from tally_agent.tally_process import SystemProcesses, uptime_seconds
from tally_contract import requests
from tally_contract import tally_constants as tc
from tally_contract.enums import CollectionType
from tally_contract.errors import ErrorCode
from tally_contract.testing import assert_logged
from tally_tools.mock_tally import company_guid


@pytest.mark.parametrize(
    ("running", "code"),
    [(True, ErrorCode.TALLY_SERVER_DISABLED), (False, ErrorCode.TALLY_UNREACHABLE)],
)
def test_a_refused_connection_is_told_apart_by_the_process_table(
    make_tally: Any, closed_port: int, running: bool, code: ErrorCode
) -> None:
    """SRS 16: TallyPrime running with its XML server off, versus not running at all."""
    with pytest.raises(TallyError) as caught:
        make_tally(closed_port, running=running).info("Sharma Traders")
    assert caught.value.code == code
    if not running:
        assert "logged off" in caught.value.message


def test_info_names_the_company_and_reads_our_tdl_version_and_its_guid(
    make_tally: Any, mock_tally: tuple[Any, str]
) -> None:
    config, port = mock_tally
    info = make_tally(port).info("Sharma Traders")
    assert (info.tdl_version, info.company_guid, info.company_name) == (
        tc.TDL_VERSION,
        company_guid("Sharma Traders"),
        "Sharma Traders",
    )
    assert config.requests == [(tc.INFO_REPORT, "Sharma Traders")]  # named, never "active"


@pytest.mark.req_partial("FR-1.4")  # reported in the command result and heartbeat: P7.5/P7.7
def test_without_our_tdl_the_agent_reports_it_and_never_falls_back(
    make_tally: Any, mock_tally: tuple[Any, str]
) -> None:
    config, port = mock_tally
    config.tdl_loaded = False
    with pytest.raises(TallyError) as caught:
        make_tally(port).info("Sharma Traders")
    assert caught.value.code == ErrorCode.TDL_NOT_LOADED
    assert all(report.startswith("TA_") for report, _ in config.requests)


def test_a_company_that_is_not_open_is_reported(
    make_tally: Any, mock_tally: tuple[Any, str]
) -> None:
    _, port = mock_tally
    with pytest.raises(TallyError) as caught:
        make_tally(port).info("Closed Company")
    assert caught.value.code == ErrorCode.COMPANY_NOT_LOADED


def test_a_slow_answer_times_out_and_is_logged(
    make_tally: Any, mock_tally: tuple[Any, str], caplog: pytest.LogCaptureFixture
) -> None:
    """AGT-4.3's first half: the request is abandoned (the retry at half size is P7.5)."""
    config, port = mock_tally
    config.delay_seconds = 1.0
    with pytest.raises(TallyTimeout) as caught:
        make_tally(port, timeout=0.3).export(
            requests.collection(CollectionType.LEDGER, "Sharma Traders")
        )
    assert caught.value.code == ErrorCode.TALLY_EXPORT_TIMEOUT
    assert_logged(caplog, "tally_export_timeout", level="warning", code="TALLY_EXPORT_TIMEOUT")


def test_tally_is_never_reached_through_a_proxy(
    make_tally: Any, mock_tally: tuple[Any, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, port = mock_tally
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "all_proxy"):
        monkeypatch.setenv(var, "http://127.0.0.1:9")  # nothing listens there
    assert make_tally(port).info("Sharma Traders").company_name == "Sharma Traders"


@pytest.mark.req_partial("AGT-6.3")  # reported in the heartbeat: P7.7
def test_tallys_uptime_comes_from_the_process_table() -> None:
    import psutil

    me = psutil.Process(os.getpid())
    found = SystemProcesses().find(me.name().upper())  # matched case-insensitively
    assert found is not None
    uptime = uptime_seconds(found)
    assert uptime is not None and uptime >= 0
    assert SystemProcesses().find("no-such-process.exe") is None
    assert uptime_seconds(None) is None
