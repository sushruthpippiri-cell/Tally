"""D-042 #4 (owner): TLS is always verified; a customer CA bundle and an HTTP proxy are
supported for office networks; nothing can turn verification off (SEC-2.0)."""

import base64
import re
import ssl
from pathlib import Path

import pytest
import trustme
from pydantic import ValidationError

from tally_agent.backend_client import BackendClient, TlsVerificationFailed, tls_context
from tally_agent.config import AgentSettings
from tests.netutil import ConnectProxy, https_server, write_ca

AGENT = Path(__file__).parents[1] / "tally_agent"


def settings(tmp_path: Path, url: str, **kw: object) -> AgentSettings:
    return AgentSettings(backend_url=url, company_name="Test Co", data_dir=tmp_path, **kw)  # type: ignore[arg-type]


@pytest.fixture
def ca() -> trustme.CA:
    return trustme.CA()


@pytest.mark.req("SEC-2.0")
def test_an_untrusted_certificate_is_refused_and_a_customer_ca_bundle_is_trusted(
    tmp_path: Path, ca: trustme.CA
) -> None:
    with https_server(ca) as url:
        plain = BackendClient(settings(tmp_path, url))
        with pytest.raises(TlsVerificationFailed, match="ca_bundle"):
            plain.call("GET", "/health")
        bundle = write_ca(ca, tmp_path / "office-ca.pem")
        trusted = BackendClient(settings(tmp_path, url, ca_bundle=bundle))
        assert trusted.call("GET", "/health") == {"ok": True, "path": "/health"}


def test_the_ca_bundle_adds_to_the_public_roots_and_tls_1_2_is_the_minimum(
    tmp_path: Path, ca: trustme.CA
) -> None:
    bundle = write_ca(ca, tmp_path / "office-ca.pem")
    context = tls_context(settings(tmp_path, "https://backend.example", ca_bundle=bundle))
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2
    assert len(context.get_ca_certs()) > 1  # certifi's roots are still there


def test_requests_go_through_the_configured_proxy_with_its_credentials(
    tmp_path: Path, ca: trustme.CA
) -> None:
    proxy = ConnectProxy()
    try:
        with https_server(ca) as url:
            bundle = write_ca(ca, tmp_path / "office-ca.pem")
            config = settings(tmp_path, url, ca_bundle=bundle, proxy_url=proxy.url)
            client = BackendClient(config, proxy_credentials="office:s3cret")
            assert client.call("GET", "/agent/heartbeat")["ok"] is True
        assert proxy.tunnels == [url.removeprefix("https://")]
        assert proxy.auth == ["Basic " + base64.b64encode(b"office:s3cret").decode()]
    finally:
        proxy.close()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("verify", False),
        ("verify_tls", False),
        ("insecure", True),
        ("credential", "abc"),  # secrets never live in agent.toml
    ],
)
def test_no_setting_can_turn_verification_off_or_hold_a_secret(
    tmp_path: Path, field: str, value: object
) -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        settings(tmp_path, "https://backend.example", **{field: value})


@pytest.mark.parametrize(
    "url",
    ["http://backend.example", "http://10.0.0.5:8000", "https://user:pw@backend.example"],
)
def test_the_backend_is_reached_over_https_only(tmp_path: Path, url: str) -> None:
    with pytest.raises(ValidationError):
        settings(tmp_path, url)
    assert settings(tmp_path, "http://127.0.0.1:8000").backend_url  # loopback: tests only


def test_proxy_credentials_never_sit_in_the_config(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="set-proxy-credentials"):
        settings(tmp_path, "https://backend.example", proxy_url="http://u:p@proxy:3128")


def test_the_agent_source_has_no_way_to_disable_certificate_checks() -> None:
    forbidden = re.compile(
        r"verify\s*=\s*False|CERT_NONE|check_hostname\s*=\s*False|_create_unverified_context"
    )
    offenders = [
        p.name for p in AGENT.rglob("*.py") if forbidden.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []
