"""P7.4: the preflight before every sync (AGT-3.x, AGT-5.x, D-042 #7)."""

from typing import Any

import pytest

from tally_agent.preflight import preflight
from tally_agent.tally_client import TallyError
from tally_contract import tally_constants as tc
from tally_contract.errors import ErrorCode
from tally_contract.testing import assert_logged
from tally_tools.mock_tally import company_guid

SHARMA = "Sharma Traders"


def test_the_named_company_is_confirmed_even_when_another_is_active(
    make_tally: Any, mock_tally: tuple[Any, str]
) -> None:
    config, port = mock_tally  # "Other Co" is loaded too; the mock has no notion of "active"
    info = preflight(make_tally(port), SHARMA, company_guid(SHARMA))
    assert info.company_guid == company_guid(SHARMA)
    assert config.requests == [(tc.INFO_REPORT, SHARMA)]  # every request names it (AGT-5.1)


@pytest.mark.req_partial("AGT-3.2", "AGT-3.3")  # "before every sync", "uploads nothing": P7.5
def test_a_different_company_guid_halts_before_anything_is_pulled(
    make_tally: Any, mock_tally: tuple[Any, str], caplog: pytest.LogCaptureFixture
) -> None:
    config, port = mock_tally
    config.guids[SHARMA] = "guid-of-a-restored-copy"
    with pytest.raises(TallyError) as caught:
        preflight(make_tally(port), SHARMA, company_guid(SHARMA))
    assert caught.value.code == ErrorCode.COMPANY_MISMATCH
    assert [r for r, _ in config.requests] == [tc.INFO_REPORT]  # nothing else was asked
    assert_logged(caplog, "company_mismatch", level="error", code="COMPANY_MISMATCH")


@pytest.mark.req_partial("AGT-5.3", "AGT-5.4")  # reported to the backend, pulls nothing: P7.5
def test_a_closed_or_renamed_company_is_not_loaded(
    make_tally: Any, mock_tally: tuple[Any, str]
) -> None:
    """Renamed in Tally: the stored name no longer opens it; the GUID is unchanged, so an
    Owner/Admin updates the name and no re-registration is needed."""
    config, port = mock_tally
    config.companies = ["Sharma Traders Pvt Ltd", "Other Co"]  # renamed
    with pytest.raises(TallyError) as caught:
        preflight(make_tally(port), SHARMA, company_guid(SHARMA))
    assert caught.value.code == ErrorCode.COMPANY_NOT_LOADED


def test_the_loaded_tdl_must_be_the_one_bundled_with_this_agent(
    make_tally: Any, mock_tally: tuple[Any, str]
) -> None:
    """D-042 #7: a newer or older TDL in Tally than this Agent's build is refused, naming both."""
    config, port = mock_tally
    config.tdl_version = "9.9.9"
    with pytest.raises(TallyError) as caught:
        preflight(make_tally(port), SHARMA, company_guid(SHARMA))
    assert caught.value.code == ErrorCode.TDL_NOT_LOADED
    assert "9.9.9" in caught.value.message and tc.TDL_VERSION in caught.value.message
