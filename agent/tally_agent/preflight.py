"""Before every sync (P7.4): is this the right Tally company, with our TDL?

- the request names the registered company, never Tally's active one (AGT-5.1, 5.2)
- the loaded TDL must be the version bundled with this Agent build (D-042 #7)
- the company's GUID must be the registered one, else COMPANY_MISMATCH: halt, pull and upload
  nothing (AGT-3.2, 3.3); an existing Agent is never re-bound silently (AGT-3.4)
- a closed or renamed company is COMPANY_NOT_LOADED (AGT-5.3, 5.4)
"""

from tally_agent.tally_client import TallyClient, TallyError
from tally_contract import tally_constants as tc
from tally_contract.errors import ErrorCode
from tally_contract.log import get_logger
from tally_contract.parser import TallyInfo

log = get_logger(__name__)


def preflight(tally: TallyClient, company_name: str, registered_guid: str) -> TallyInfo:
    info = tally.info(company_name)
    if info.tdl_version != tc.TDL_VERSION:
        log.error("tdl_version_mismatch", loaded=info.tdl_version, bundled=tc.TDL_VERSION)
        raise TallyError(
            ErrorCode.TDL_NOT_LOADED,
            f"TallyPrime has TDL {info.tdl_version or '(unknown)'} loaded; this Agent needs "
            f"{tc.TDL_VERSION}. Load the TDL files installed with this Agent.",
        )
    if info.company_guid != registered_guid:
        log.error(
            "company_mismatch",
            code=ErrorCode.COMPANY_MISMATCH.value,
            company=company_name,
            found_guid=info.company_guid,
            registered_guid=registered_guid,
        )
        raise TallyError(
            ErrorCode.COMPANY_MISMATCH,
            f"The company {company_name!r} open in TallyPrime is not the one this Agent was "
            "registered for. Nothing is synced; re-register if this is intended.",
        )
    return info
