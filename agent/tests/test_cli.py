import pytest
from typer.testing import CliRunner

from tally_agent.__main__ import app

runner = CliRunner()


def test_help_lists_all_commands() -> None:
    out = runner.invoke(app, ["--help"]).output
    for cmd in ("register", "run", "status", "set-credential", "test-tally"):
        assert cmd in out


@pytest.mark.parametrize(
    "args", [["register", "--token", "t"], ["run"], ["status"], ["set-credential"], ["test-tally"]]
)
def test_stubs_exit_2(args: list[str]) -> None:
    assert runner.invoke(app, args).exit_code == 2
