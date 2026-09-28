"""The Agent's HTTPS client to the backend (SEC-2.0, D-042 #4).

TLS is always verified: certifi's roots plus an optional customer CA bundle (office antivirus
and firewalls often re-sign HTTPS), TLS 1.2 or later. An optional HTTP CONNECT proxy is used
only when configured; the environment is ignored, so a service behaves the same everywhere.
"""

import ssl
import time
from typing import Any

import certifi
import httpx

from tally_agent.config import AgentSettings
from tally_contract.log import get_logger

log = get_logger(__name__)


class BackendError(Exception):
    def __init__(self, status: int, code: str | None, message: str) -> None:
        super().__init__(f"{status} {code}: {message}")
        self.status, self.code, self.message = status, code, message


class CredentialInvalid(BackendError):
    """401: enter the new credential with `tally-agent set-credential` (SRS 4.4)."""


class AgentRevoked(BackendError):
    """This installation must re-register as a new Agent (SEC-2.3)."""


class BackendUnavailable(Exception):
    """Network trouble or a 5xx: retry later."""


class RateLimited(BackendUnavailable):
    """429: slow down, never a failure (D-043). `retry_after` is the backend's Retry-After."""

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"rate limited; retry after {retry_after:g} s")
        self.retry_after = retry_after


class TlsVerificationFailed(BackendUnavailable):
    """The backend's certificate is not trusted: set ca_bundle if an office proxy re-signs HTTPS."""


def tls_context(settings: AgentSettings) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=certifi.where())
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if settings.ca_bundle is not None:
        context.load_verify_locations(cafile=str(settings.ca_bundle))  # added, never instead
    return context


class BackendClient:
    def __init__(
        self,
        settings: AgentSettings,
        credential: str | None = None,
        proxy_credentials: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30,
    ) -> None:
        proxy = None
        if settings.proxy_url:
            auth = tuple(proxy_credentials.split(":", 1)) if proxy_credentials else None
            proxy = httpx.Proxy(settings.proxy_url, auth=auth)  # type: ignore[arg-type]
        headers = {"Authorization": f"Bearer {credential}"} if credential else {}
        self._http = httpx.Client(
            base_url=settings.backend_url,
            verify=tls_context(settings),
            proxy=proxy,
            trust_env=False,
            timeout=timeout,
            headers=headers,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        patience: int = 0,
    ) -> Any:
        """One request. With `patience`, a 429 (after its Retry-After, D-043) or a brief outage
        (after 1, 2, 4 ... 16 s) is retried up to that many times before it is raised; a TLS
        failure never is."""
        for attempt in range(patience):
            try:
                return self._call(method, path, body)
            except RateLimited as exc:
                log.warning("backend_rate_limited", path=path, retry_after=exc.retry_after)
                time.sleep(exc.retry_after)
            except TlsVerificationFailed:
                raise
            except BackendUnavailable as exc:
                log.warning("backend_unavailable_retrying", path=path, error=str(exc))
                time.sleep(min(16.0, 2.0**attempt))
        return self._call(method, path, body)

    def _call(self, method: str, path: str, body: dict[str, Any] | None) -> Any:
        try:
            response = self._http.request(method, path, json=body)
        except httpx.ConnectError as exc:
            if isinstance(
                exc.__context__, ssl.SSLCertVerificationError
            ) or "CERTIFICATE_VERIFY" in str(exc):
                log.error("backend_tls_verification_failed", error=str(exc))
                raise TlsVerificationFailed(
                    "The backend's certificate is not trusted. If an office proxy or antivirus "
                    "inspects HTTPS, set ca_bundle to its CA certificate (PEM)."
                ) from exc
            raise BackendUnavailable(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise BackendUnavailable(str(exc)) from exc
        if response.status_code == 429:
            try:
                retry_after = max(1.0, float(response.headers.get("Retry-After", "5")))
            except ValueError:
                retry_after = 5.0
            raise RateLimited(retry_after)
        if response.status_code >= 500:
            raise BackendUnavailable(f"{response.status_code} from the backend")
        if response.status_code >= 400:
            try:
                body_out = response.json()
            except ValueError:
                body_out = {}
            code, message = body_out.get("code"), body_out.get("message", response.text[:300])
            error = {"CREDENTIAL_INVALID": CredentialInvalid, "AGENT_REVOKED": AgentRevoked}.get(
                code or "", BackendError
            )
            raise error(response.status_code, code, message)
        return response.json() if response.content else None
