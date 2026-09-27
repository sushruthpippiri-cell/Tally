"""Requests to TallyPrime's XML server (P7.3, SRS 16, AGT-4.3).

Every request is built by `tally_contract.requests` and names the registered company
(AGT-5.1). Failures carry the SRS 16 error code; the Agent never falls back to Tally's own
reports (FR-1.4). Tally is on this machine or the LAN: no proxy, whatever the environment says.
"""

import httpx

from tally_agent.tally_process import ProcessTable, SystemProcesses
from tally_contract import requests
from tally_contract.errors import ErrorCode
from tally_contract.log import get_logger
from tally_contract.parser import TallyInfo, parse_info

log = get_logger(__name__)


class TallyError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(f"{code.value}: {message}")
        self.code, self.message = code, message


class TallyTimeout(TallyError):
    """AGT-4.3: abandoned after the timeout; the caller retries once at half the size."""


class TallyClient:
    def __init__(
        self,
        host: str,
        port: int,
        *,
        timeout_seconds: float,
        process_name: str,
        processes: ProcessTable | None = None,
    ) -> None:
        self.port = port
        self.process_name = process_name
        self.processes = processes or SystemProcesses()
        self._timeout = timeout_seconds
        self._http = httpx.Client(
            base_url=f"http://{host}:{port}",
            timeout=httpx.Timeout(timeout_seconds, connect=10),
            trust_env=False,  # never a proxy for Tally
        )

    def close(self) -> None:
        self._http.close()

    def export(self, request: bytes) -> bytes:
        try:
            response = self._http.post(
                "/", content=request, headers={"Content-Type": "text/xml; charset=utf-8"}
            )
        except httpx.TimeoutException as exc:
            if isinstance(exc, httpx.ConnectTimeout):
                raise self._unreachable() from exc
            log.warning(
                "tally_export_timeout",
                code=ErrorCode.TALLY_EXPORT_TIMEOUT.value,
                timeout_seconds=self._timeout,
            )
            raise TallyTimeout(
                ErrorCode.TALLY_EXPORT_TIMEOUT,
                f"TallyPrime did not answer within {self._timeout:g} seconds",
            ) from exc
        except httpx.TransportError as exc:
            raise self._unreachable() from exc
        if response.status_code != 200:
            raise TallyError(
                ErrorCode.PARSE_ERROR, f"TallyPrime answered HTTP {response.status_code}"
            )
        return response.content

    def _unreachable(self) -> TallyError:
        """SRS 16: the XML server is off while Tally runs, or Tally is not running at all."""
        if self.processes.find(self.process_name) is not None:
            log.warning("tally_server_disabled", port=self.port)
            return TallyError(
                ErrorCode.TALLY_SERVER_DISABLED,
                f"TallyPrime is running but does not answer on port {self.port}: "
                "enable its HTTP server on that port",
            )
        log.warning("tally_unreachable", port=self.port)
        return TallyError(
            ErrorCode.TALLY_UNREACHABLE,
            "TallyPrime is not running; the Windows user may have logged off (disconnect "
            "Remote Desktop sessions instead of logging off)",
        )

    def info(self, company: str) -> TallyInfo:
        """TA_Info for the named company: our TDL version and the company's GUID."""
        result = parse_info(self.export(requests.info(company)))
        if result.document_error is not None:
            raise TallyError(result.document_error.code, result.document_error.message)
        if not result.records:  # TA_Info saw no such company open
            raise TallyError(
                ErrorCode.COMPANY_NOT_LOADED, f"The company {company!r} is not open in TallyPrime"
            )
        return result.records[0]
