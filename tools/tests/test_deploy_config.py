"""P16.12: the production deployment configuration says what we think it says.

Two things no other test can catch, both of which make every security header optional if they
go wrong, and neither of which shows up until the service is live:

- only the proxy publishes a port (D-056 #7), so every request arrives through Caddy;
- the proxy's security headers are the ones the app actually declares in
  frontend/security/csp.ts, which nothing checked before - the SPA's own test covers
  `vite preview`, not the proxy.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[2]
PROD_COMPOSE = ROOT / "deploy/docker-compose.prod.yml"
DEV_COMPOSE = ROOT / "deploy/docker-compose.yml"
CADDYFILE = ROOT / "deploy/caddy/Caddyfile"
CSP_TS = ROOT / "frontend/security/csp.ts"

PROXY = "caddy"


def published(compose: Path) -> dict[str, list[str]]:
    services = yaml.safe_load(compose.read_text(encoding="utf-8"))["services"]
    return {name: s.get("ports") or [] for name, s in services.items()}


@pytest.mark.req("SEC-1.3")
def test_only_the_proxy_publishes_ports_in_production() -> None:
    """The backend's 8000 and any database's 5432 must not be reachable from outside: a request
    that bypasses the proxy arrives with no TLS, no HSTS and none of the headers below."""
    ports = published(PROD_COMPOSE)
    assert ports[PROXY], "the proxy must publish 80 and 443"
    exposed = {name: p for name, p in ports.items() if name != PROXY and p}
    assert exposed == {}, f"these services publish ports in production: {exposed}"


def test_the_development_compose_is_a_separate_file() -> None:
    """Local work needs 5432 and 8000 on the host; production must not inherit that. The two
    are separate files rather than one with an override, so neither can be used by accident."""
    assert DEV_COMPOSE.is_file() and PROD_COMPOSE.is_file()
    dev = published(DEV_COMPOSE)
    assert dev.get("postgres"), "the dev file is the one that exposes Postgres"
    assert PROXY not in dev, "the proxy belongs to production only"


def test_production_runs_no_database_container() -> None:
    """D-056 #2: managed PostgreSQL with point-in-time recovery. A container here would be a
    database nobody is backing up."""
    assert "postgres" not in published(PROD_COMPOSE)


# --- the proxy's headers match the app's own declaration --------------------------------


def _csp_from_typescript() -> str:
    """The CSP as frontend/security/csp.ts builds it: the array entries, joined with "; "."""
    source = CSP_TS.read_text(encoding="utf-8")
    body = re.search(r"export const CSP = \[(.*?)\]\.join", source, re.S)
    assert body, "csp.ts no longer defines CSP as an array joined with '; '"
    entries = re.findall(r'"([^"]+)"', body.group(1))
    assert entries, "no CSP directives found"
    return "; ".join(entries)


def _security_headers_from_typescript() -> dict[str, str]:
    source = CSP_TS.read_text(encoding="utf-8")
    body = re.search(r"export const SECURITY_HEADERS[^{]*\{(.*?)\n\};", source, re.S)
    assert body, "csp.ts no longer defines SECURITY_HEADERS"
    headers = dict(re.findall(r'"([\w-]+)":\s*(?:"([^"]*)"|CSP)', body.group(1)))
    return {name: value or _csp_from_typescript() for name, value in headers.items()}


def _caddy_headers() -> dict[str, str]:
    """The headers the Caddyfile sets, from both its site-level and SPA `header` directives."""
    text = CADDYFILE.read_text(encoding="utf-8")
    uncommented = "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))
    return dict(re.findall(r'^\s*header\s+([\w-]+)\s+"([^"]*)"', uncommented, re.M)) | dict(
        re.findall(r'^\s*([\w-]+)\s+"([^"]*)"$', uncommented, re.M)
    )


@pytest.mark.req("SEC-1.3")
def test_the_proxy_serves_exactly_the_headers_the_app_declares() -> None:
    """csp.ts names the proxy as its second consumer. Nothing kept them in step until now, so a
    directive added for the SPA would have been served in development and silently dropped in
    production."""
    declared = _security_headers_from_typescript()
    served = _caddy_headers()
    for name, value in declared.items():
        assert name in served, f"the Caddyfile does not serve {name}"
        assert served[name] == value, (
            f"{name} differs:\n  csp.ts: {value}\n  Caddyfile: {served[name]}"
        )


def test_the_proxy_adds_hsts_which_the_app_deliberately_does_not() -> None:
    """HSTS is the proxy's own: csp.ts leaves it out because `vite preview` serves plain http
    and HSTS there would pin a developer's browser to https://localhost for a year."""
    assert "Strict-Transport-Security" not in _security_headers_from_typescript()
    hsts = _caddy_headers().get("Strict-Transport-Security", "")
    assert "max-age=31536000" in hsts and "includeSubDomains" in hsts


def test_the_proxy_strips_api_and_never_rewrites_host() -> None:
    """The two mistakes that would break the deployment. A rewritten Host makes every reload
    look cross-site and signs everyone out (D-051 #2, found with the Vite proxy in P13.3); not
    stripping /api gives the backend paths it does not serve (D-051 #4)."""
    text = CADDYFILE.read_text(encoding="utf-8")
    uncommented = "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))
    assert "uri strip_prefix /api" in uncommented
    assert "reverse_proxy backend:8000" in uncommented
    assert "header_up Host" not in uncommented, "setting Host is the P13.3 bug"


def test_the_spa_falls_back_to_index_html() -> None:
    """A deep link belongs to the router: without this, /c/<id>/sales is a 404 from the file
    server on a fresh page load, and only works when navigated to from inside the app."""
    assert "try_files {path} /index.html" in CADDYFILE.read_text(encoding="utf-8")
