"""The Agent's command line (P7.2). `run` (the service loop) arrives with P7.5.

Registration follows SRS 4.2: test Tally, read the named company's GUID with our TDL, register
with the backend, store the credential with DPAPI (D-042 #3). Secrets are typed at a hidden
prompt and never printed.
"""

from pathlib import Path
from typing import NoReturn

import typer

from tally_agent import AGENT_VERSION, config, security, state
from tally_agent.backend_client import BackendClient, BackendError, BackendUnavailable
from tally_agent.config import AgentSettings, default_data_dir
from tally_agent.preflight import check_tdl, preflight
from tally_agent.protocol import RegisterResponse
from tally_agent.secret_store import CREDENTIAL, PROXY, SecretStore
from tally_agent.tally_client import TallyClient, TallyError
from tally_contract import tally_constants as tc
from tally_contract.log import configure_logging, get_logger

app = typer.Typer(help="Tally Sync Agent", no_args_is_help=True)
log = get_logger(__name__)
DATA_DIR = typer.Option(None, "--data-dir", help="Defaults to %ProgramData%\\TallyAgent")
CA_BUNDLE = typer.Option(None, help="CA certificate(s) your office network uses (PEM)")


@app.callback()
def _main() -> None:
    configure_logging("dev", "WARNING")


def _fail(message: str) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(code=1)


def _settings(data_dir: Path | None) -> AgentSettings:
    path = config.config_path(data_dir or default_data_dir())
    if not path.exists():
        _fail(f"No configuration at {path}. Run `tally-agent register` first.")
    return config.load(path)


def _tally(settings: AgentSettings, saved: state.AgentState | None = None) -> TallyClient:
    backend = (saved.backend_config if saved else {}) or {}
    return TallyClient(
        backend.get("tally_host", settings.tally_host),
        backend.get("tally_port", settings.tally_port),
        timeout_seconds=settings.tally_timeout_seconds,
        process_name=settings.tally_process_name,
    )


@app.command()
def register(
    token: str = typer.Option(..., help="One-time registration token from the dashboard"),
    name: str = typer.Option(..., help="A name for this Agent, e.g. 'Head Office'"),
    backend_url: str = typer.Option(None, help="Needed on first registration"),
    company: str = typer.Option(None, help="The Tally company, exactly as named in Tally"),
    tally_host: str = typer.Option("localhost"),
    tally_port: int = typer.Option(9000),
    ca_bundle: Path = CA_BUNDLE,
    proxy_url: str = typer.Option(None, help="HTTP proxy, e.g. http://proxy:3128"),
    data_dir: Path = DATA_DIR,
) -> None:
    """Register this Agent with the backend (SRS 4.2)."""
    directory = data_dir or default_data_dir()
    path = config.config_path(directory)
    if path.exists():
        settings = config.load(path)
    else:
        if not backend_url or not company:
            _fail("First registration needs --backend-url and --company.")
        settings = AgentSettings(
            backend_url=backend_url,
            company_name=company,
            tally_host=tally_host,
            tally_port=tally_port,
            data_dir=directory,
            ca_bundle=ca_bundle,
            proxy_url=proxy_url,
        )
    if state.load(directory) is not None:  # AGT-3.4, SEC-2.3: never re-bound silently
        _fail(
            "This Agent is already registered. To register again, revoke it in the "
            "dashboard, remove this installation's data, and register as a new Agent."
        )
    security.private_dir(directory, settings.service_account)
    config.save(settings)
    try:
        info = _tally(settings).info(settings.company_name)
        check_tdl(info)
    except TallyError as exc:
        _fail(f"{exc.code.value}: {exc.message}")
    store = SecretStore(directory, settings.service_account)
    backend = BackendClient(settings, proxy_credentials=store.load(PROXY))
    try:
        answer = RegisterResponse.model_validate(
            backend.call(
                "POST",
                "/agent/register",
                {
                    "token": token,
                    "agent_name": name,
                    "tally_guid": info.company_guid,
                    "tally_company_name": info.company_name,
                    "agent_version": AGENT_VERSION,
                    "tdl_version": info.tdl_version,
                    "tally_host": settings.tally_host,
                    "tally_port": settings.tally_port,
                },
            )
        )
    except (BackendError, BackendUnavailable) as exc:
        _fail(f"Registration failed: {exc}")
    store.save(CREDENTIAL, answer.credential)
    state.save(
        directory,
        state.AgentState(
            agent_id=answer.agent_id,
            company_guid=info.company_guid,
            company_name=info.company_name,
            backend_config=answer.config.model_dump(),
        ),
        settings.service_account,
    )
    log.info("agent_registered", agent_id=str(answer.agent_id), company=info.company_name)
    typer.echo(f"Registered as Agent {answer.agent_id} for {info.company_name!r}.")


@app.command("set-credential")
def set_credential(data_dir: Path = DATA_DIR) -> None:
    """Store a rotated credential from the dashboard (SRS 4.4 step 4)."""
    settings = _settings(data_dir)
    value = typer.prompt("New credential", hide_input=True, confirmation_prompt=True).strip()
    if not value:
        _fail("No credential entered.")
    SecretStore(settings.data_dir, settings.service_account).save(CREDENTIAL, value)
    typer.echo("Credential saved. The Agent uses it on its next call to the backend.")


@app.command("set-proxy-credentials")
def set_proxy_credentials(
    clear: bool = typer.Option(False, "--clear", help="Remove the stored proxy credentials"),
    data_dir: Path = DATA_DIR,
) -> None:
    """Store the username and password for a proxy that needs them (D-042 #4)."""
    settings = _settings(data_dir)
    store = SecretStore(settings.data_dir, settings.service_account)
    if clear:
        store.delete(PROXY)
        typer.echo("Proxy credentials removed.")
        return
    user = typer.prompt("Proxy username").strip()
    password = typer.prompt("Proxy password", hide_input=True)
    if not user or ":" in user:
        _fail("The username must be non-empty and contain no ':'.")
    store.save(PROXY, f"{user}:{password}")
    typer.echo("Proxy credentials saved.")


@app.command()
def status(data_dir: Path = DATA_DIR) -> None:
    """Show this Agent's registration and local security."""
    settings = _settings(data_dir)
    saved = state.load(settings.data_dir)
    store = SecretStore(settings.data_dir, settings.service_account)
    typer.echo(f"Backend:     {settings.backend_url}")
    typer.echo(f"Data:        {settings.data_dir}")
    if saved is None:
        typer.echo("Registered:  no")
        raise typer.Exit(code=1)
    typer.echo(f"Agent:       {saved.agent_id}")
    typer.echo(f"Company:     {saved.company_name} ({saved.company_guid})")
    try:
        security.check(settings.data_dir, settings.service_account)
        present = store.load(CREDENTIAL) is not None
    except security.InsecurePermissions as exc:
        _fail(f"Insecure: {exc}")
    typer.echo(f"Credential:  {'stored' if present else 'MISSING - run set-credential'}")


@app.command("test-tally")
def test_tally(data_dir: Path = DATA_DIR) -> None:
    """Check TallyPrime: reachable, our TDL loaded, and the company's GUID."""
    settings = _settings(data_dir)
    saved = state.load(settings.data_dir)
    company = (
        saved.backend_config.get("tally_company_name") if saved else None
    ) or settings.company_name
    tally = _tally(settings, saved)
    try:
        if saved is not None:
            info = preflight(tally, company, saved.company_guid)
        else:
            info = tally.info(company)
            check_tdl(info)
    except TallyError as exc:
        _fail(f"{exc.code.value}: {exc.message}")
    typer.echo(f"TallyPrime:  reachable on {tally.port}")
    typer.echo(f"TDL:         {info.tdl_version} (this Agent needs {tc.TDL_VERSION})")
    typer.echo(f"Company:     {info.company_name} ({info.company_guid})")


@app.command()
def run(data_dir: Path = DATA_DIR) -> None:
    """Run the poll/sync loop in the foreground (the Windows service runs the same loop)."""
    from tally_agent import logging_setup
    from tally_agent.service import Agent

    settings = _settings(data_dir)
    logging_setup.setup(settings.data_dir, settings.service_account)
    try:
        agent = Agent(settings)
    except RuntimeError as exc:
        _fail(str(exc))
    agent.run_forever()
    if agent.revoked:
        raise typer.Exit(code=3)
