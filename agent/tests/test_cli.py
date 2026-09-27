"""P7.2: the Agent's command line (SRS 4.2, 4.4; D-042 #3)."""

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from tally_agent import AGENT_VERSION, state
from tally_agent.__main__ import app
from tally_agent.secret_store import CREDENTIAL, PROXY, SecretStore
from tally_contract import tally_constants as tc
from tally_tools.mock_tally import company_guid

runner = CliRunner()
SHARMA = "Sharma Traders"
ACCOUNT = r"NT SERVICE\TallyAgent"


def _register(data: Path, backend: Any, port: str, *extra: str) -> Any:
    return runner.invoke(
        app,
        [
            "register",
            "--token", "one-time-token",
            "--name", "Head Office",
            "--backend-url", backend.url,
            "--company", SHARMA,
            "--tally-host", "127.0.0.1",
            "--tally-port", port,
            "--data-dir", str(data),
            *extra,
        ],
    )  # fmt: skip


def test_help_lists_all_commands() -> None:
    out = runner.invoke(app, ["--help"]).output
    for cmd in (
        "register",
        "run",
        "status",
        "set-credential",
        "set-proxy-credentials",
        "test-tally",
    ):
        assert cmd in out


@pytest.mark.req("AGT-3.1")
@pytest.mark.req_partial("SEC-2.0a")  # sent as a bearer token on every call: P7.5
def test_register_reads_the_named_companys_guid_and_stores_the_credential_only_in_the_secret_store(
    tmp_path: Path, fake_backend: Any, mock_tally: tuple[Any, str]
) -> None:
    _, port = mock_tally
    data = tmp_path / "agent"
    result = _register(data, fake_backend, port)
    assert result.exit_code == 0, result.output
    [(_, path, body, _)] = fake_backend.calls
    assert path == "/agent/register"
    assert body | {"token": "?"} == {
        "token": "?",
        "agent_name": "Head Office",
        "tally_guid": company_guid(SHARMA),
        "tally_company_name": SHARMA,
        "agent_version": AGENT_VERSION,
        "tdl_version": tc.TDL_VERSION,
        "tally_host": "127.0.0.1",
        "tally_port": int(port),
    }
    assert SecretStore(data, ACCOUNT).load(CREDENTIAL) == fake_backend.credential
    saved = state.load(data)
    assert saved is not None and saved.company_guid == company_guid(SHARMA)
    assert fake_backend.credential not in result.output
    for file in data.rglob("*"):  # nowhere but the secret store (plain only off Windows)
        if file.is_file() and file.name != "credential.bin":
            assert fake_backend.credential not in file.read_text(encoding="utf-8", errors="ignore")


def test_an_agent_is_never_registered_twice(
    tmp_path: Path, fake_backend: Any, mock_tally: tuple[Any, str]
) -> None:
    """AGT-3.4, SEC-2.3: re-registration is explicit, as a new Agent."""
    _, port = mock_tally
    assert _register(tmp_path / "agent", fake_backend, port).exit_code == 0
    again = _register(tmp_path / "agent", fake_backend, port)
    assert again.exit_code == 1 and "already registered" in again.output
    assert len(fake_backend.calls) == 1


def test_registration_needs_tally_and_our_tdl_first(
    tmp_path: Path, fake_backend: Any, mock_tally: tuple[Any, str]
) -> None:
    config, port = mock_tally
    config.tdl_loaded = False
    result = _register(tmp_path / "agent", fake_backend, port)
    assert result.exit_code == 1 and "TDL_NOT_LOADED" in result.output
    assert fake_backend.calls == []  # nothing sent to the backend
    assert state.load(tmp_path / "agent") is None


def test_set_credential_reads_a_hidden_prompt(
    tmp_path: Path, fake_backend: Any, mock_tally: tuple[Any, str]
) -> None:
    """SRS 4.4 step 4: the new credential typed in, never passed as an argument."""
    _, port = mock_tally
    data = tmp_path / "agent"
    _register(data, fake_backend, port)
    result = runner.invoke(
        app, ["set-credential", "--data-dir", str(data)], input="rotated\nrotated\n"
    )
    assert result.exit_code == 0, result.output
    assert "rotated" not in result.output
    assert SecretStore(data, ACCOUNT).load(CREDENTIAL) == "rotated"


def test_proxy_credentials_are_stored_and_can_be_cleared(
    tmp_path: Path, fake_backend: Any, mock_tally: tuple[Any, str]
) -> None:
    _, port = mock_tally
    data = tmp_path / "agent"
    _register(data, fake_backend, port)
    runner.invoke(app, ["set-proxy-credentials", "--data-dir", str(data)], input="office\ns3cret\n")
    assert SecretStore(data, ACCOUNT).load(PROXY) == "office:s3cret"
    runner.invoke(app, ["set-proxy-credentials", "--clear", "--data-dir", str(data)])
    assert SecretStore(data, ACCOUNT).load(PROXY) is None


def test_test_tally_and_status_report_the_registered_company(
    tmp_path: Path, fake_backend: Any, mock_tally: tuple[Any, str]
) -> None:
    config, port = mock_tally
    data = tmp_path / "agent"
    _register(data, fake_backend, port)
    ok = runner.invoke(app, ["test-tally", "--data-dir", str(data)])
    assert ok.exit_code == 0 and company_guid(SHARMA) in ok.output, ok.output
    status = runner.invoke(app, ["status", "--data-dir", str(data)])
    assert status.exit_code == 0 and "stored" in status.output, status.output
    config.guids[SHARMA] = "guid-another-company"
    mismatch = runner.invoke(app, ["test-tally", "--data-dir", str(data)])
    assert mismatch.exit_code == 1 and "COMPANY_MISMATCH" in mismatch.output
