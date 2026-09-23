"""Tally Sync Agent CLI. Commands are stubs until Phase 7."""

import typer

from tally_contract.log import configure_logging, get_logger

app = typer.Typer(help="Tally Sync Agent", no_args_is_help=True)
log = get_logger(__name__)


@app.callback()
def _main() -> None:
    configure_logging("dev")


def _stub(name: str) -> None:
    log.warning("command_not_implemented", command=name, phase="P7")
    typer.echo(f"'{name}' is not implemented yet (Phase 7).", err=True)
    raise typer.Exit(code=2)


@app.command()
def register(token: str = typer.Option(..., help="One-time registration token")) -> None:
    """Register this Agent with the backend."""
    _stub("register")


@app.command()
def run() -> None:
    """Run the poll/sync loop in the foreground."""
    _stub("run")


@app.command()
def status() -> None:
    """Show Agent, queue and Tally status."""
    _stub("status")


@app.command("set-credential")
def set_credential() -> None:
    """Store a rotated credential."""
    _stub("set-credential")


@app.command("test-tally")
def test_tally() -> None:
    """Check connectivity to TallyPrime, the TDL version and the company GUID."""
    _stub("test-tally")


if __name__ == "__main__":
    app()
