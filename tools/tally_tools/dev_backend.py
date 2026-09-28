"""Development helpers for testing a real Windows Agent against the backend on this Mac
(docs/agent-windows-checklist.md). Never for production.

    uv run python -m tally_tools.dev_backend tls --host 192.168.1.20
        a throwaway CA and a server certificate for that address, in dev-https/
        (the Agent refuses plain HTTP to anything but itself, D-042 #4; this also exercises
        its ca_bundle setting)
    uv run python -m tally_tools.dev_backend setup --email you@example.com --company "Test Co"
        signs in, creates the company, prints a one-time Agent registration token
    uv run python -m tally_tools.dev_backend sync --email you@example.com --mode FULL
        "Sync Now" for the company created by `setup`
    uv run python -m tally_tools.dev_backend call GET /companies/{company}/agents --email ...
        any API call as the Owner ({company} = the company created by `setup`)
"""

import argparse
import getpass
import json
import ssl
import sys
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import trustme

OUT = Path("dev-https")
DEFAULT_URL = "https://localhost:8443"


def make_tls(hosts: list[str], out: Path = OUT) -> Path:
    """Writes ca.pem (give it to the Agent as ca_bundle), server.pem and server-key.pem."""
    out.mkdir(parents=True, exist_ok=True)
    ca = trustme.CA(organization_name="Tally Analytics DEV ONLY")
    server = ca.issue_cert(*hosts, "localhost", "127.0.0.1")
    ca.cert_pem.write_to_path(str(out / "ca.pem"))
    server.private_key_pem.write_to_path(str(out / "server-key.pem"))
    with (out / "server.pem").open("wb") as f:
        for blob in server.cert_chain_pems:
            f.write(blob.bytes())
    return out / "ca.pem"


def _client(url: str, ca: Path | None, token: str | None = None) -> httpx.Client:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    verify: Any = ssl.create_default_context(cafile=str(ca)) if ca else True
    return httpx.Client(base_url=url, verify=verify, headers=headers, trust_env=False, timeout=30)


def login(url: str, ca: Path | None, email: str, password: str) -> str:
    with _client(url, ca) as c:
        r = c.post("/auth/login", json={"email": email, "password": password})
        r.raise_for_status()
        token: str = r.json()["access_token"]
        return token


def setup(
    url: str,
    ca: Path | None,
    email: str,
    password: str,
    company: str,
    *,
    timezone: str = "Asia/Kolkata",
    financial_year_start: date = date(2024, 4, 1),
) -> dict[str, str]:
    """Creates the company and a registration token; remembers the company in dev-https/."""
    token = login(url, ca, email, password)
    with _client(url, ca, token) as c:
        r = c.post(
            "/companies",
            json={
                "name": company,
                "financial_year_start": financial_year_start.isoformat(),
                "company_timezone": timezone,
            },
        )
        r.raise_for_status()
        company_id = r.json()["company_id"]
        r = c.post(f"/companies/{company_id}/agents/register-token")
        r.raise_for_status()
        result = {"company_id": company_id, "registration_token": r.json()["token"]}
    (OUT / "company.json").parent.mkdir(parents=True, exist_ok=True)
    (OUT / "company.json").write_text(
        json.dumps({"company_id": company_id}) + "\n", encoding="utf-8", newline="\n"
    )
    return result


def sync(url: str, ca: Path | None, email: str, password: str, company_id: str, mode: str) -> Any:
    token = login(url, ca, email, password)
    with _client(url, ca, token) as c:
        r = c.post(f"/companies/{company_id}/sync", json={"sync_mode": mode})
        r.raise_for_status()
        return r.json()


def call(url: str, ca: Path | None, email: str, password: str, method: str, path: str) -> Any:
    """Any API call as the signed-in Owner; `{company}` in the path is the company from setup."""
    company = json.loads((OUT / "company.json").read_text(encoding="utf-8"))["company_id"]
    token = login(url, ca, email, password)
    with _client(url, ca, token) as c:
        r = c.request(method, path.replace("{company}", company))
        r.raise_for_status()
        return r.json() if r.content else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tally_tools.dev_backend")
    commands = parser.add_subparsers(dest="command", required=True)
    tls = commands.add_parser("tls", help="a throwaway CA and certificate for this Mac")
    tls.add_argument("--host", action="append", required=True, help="this Mac's LAN address")
    for name in ("setup", "sync", "call"):
        sub = commands.add_parser(name)
        sub.add_argument("--url", default=DEFAULT_URL)
        sub.add_argument("--ca", type=Path, default=OUT / "ca.pem")
        sub.add_argument("--email", required=True)
    commands.choices["setup"].add_argument("--company", required=True)
    commands.choices["sync"].add_argument("--mode", default="FULL")
    commands.choices["call"].add_argument("method", choices=["GET", "POST"])
    commands.choices["call"].add_argument("path", help="e.g. /companies/{company}/agents")
    args = parser.parse_args(argv)
    if args.command == "tls":
        ca = make_tls(args.host)
        sys.stdout.write(f"CA for the Agent's ca_bundle: {ca.resolve()}\n")
        return 0
    password = getpass.getpass("Password: ")
    if args.command == "setup":
        result = setup(args.url, args.ca, args.email, password, args.company)
        sys.stdout.write(
            f"company {result['company_id']}\n"
            f"registration token (one use, 24 h): {result['registration_token']}\n"
        )
        return 0
    if args.command == "call":
        answer = call(args.url, args.ca, args.email, password, args.method, args.path)
        sys.stdout.write(json.dumps(answer, indent=2) + "\n")
        return 0
    company_id = json.loads((OUT / "company.json").read_text(encoding="utf-8"))["company_id"]
    answer = sync(args.url, args.ca, args.email, password, company_id, args.mode)
    sys.stdout.write(f"command {answer['command_id']} {answer['status']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
