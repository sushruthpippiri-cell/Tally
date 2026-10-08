"""The end-to-end harness: the real Agent against the real backend (a uvicorn process on the
`_test` database) and the mock TallyPrime.

Extracted from test_agent_end_to_end.py in P16.7, when the use-case suite became a second
consumer. Nothing here is a test; the fixtures (`start_server`, `tally`) are picked up through
each test module's own import.
"""

import asyncio
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from typer.testing import CliRunner

from app.models.enums import RoleName
from tally_agent import config as agent_config
from tally_agent.cli import app as agent_cli
from tally_agent.queue import Limits
from tally_agent.service import Agent
from tally_agent.tally_client import TallyClient
from tally_agent.tally_process import TallyProcess
from tally_agent.uploader import Uploader
from tally_tools.mock_tally import (
    MockConfig,
    company_guid,
    running,
    sample_company,
)
from tests.factories import auth_header, make_company, make_registration_token, make_user
from tests.sync.helpers import Factory

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the backend runs on Linux")
BACKEND = Path(__file__).parents[2]
SHARMA = "Sharma Traders"


class Server:
    """The backend in its own process: killable, restartable on the same port."""

    def __init__(self, log: Path | None = None, **env: str) -> None:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.env = os.environ | {"PYTHONPATH": str(BACKEND)} | env
        self.proc: subprocess.Popen[bytes] | None = None
        # Where to capture the server's own output. Only the log-redaction test needs it; left
        # None, the subprocess inherits stdout as before so pytest shows its logs.
        self.log = log
        self._log_file: Any = None

    def start(self) -> None:
        now = datetime.now(UTC).isoformat()  # the test's clock, not the machine's
        if self.log is not None:
            # "wb": the capture file is fresh for each server, so truncating is right, and
            # binary because the subprocess writes bytes (no encoding to name).
            self._log_file = self.log.open("wb")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "tests.e2e.server", str(self.port), now],
            cwd=BACKEND,
            env=self.env,
            stdout=self._log_file,
            stderr=subprocess.STDOUT if self._log_file else None,
        )
        for _ in range(300):
            try:
                if httpx.get(f"{self.url}/health", timeout=1, trust_env=False).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        raise RuntimeError("the backend did not start")

    def kill(self) -> None:
        assert self.proc is not None
        self.proc.send_signal(signal.SIGKILL)
        self.proc.wait()
        self._close_log()

    def _close_log(self) -> None:
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(10)
        self._close_log()


@pytest.fixture
def start_server() -> Iterator[Any]:
    servers: list[Server] = []

    def start(log: Path | None = None, **env: str) -> Server:
        server = Server(log=log, **env)
        server.start()
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.stop()


@pytest.fixture
def tally() -> Iterator[tuple[MockConfig, int]]:
    mock = MockConfig(companies=[SHARMA], data=sample_company(SHARMA))
    with running(mock) as url:
        yield mock, int(url.rsplit(":", 1)[1])


class Running:
    """The process table says TallyPrime is running (AGT-6.3)."""

    def find(self, name: str) -> TallyProcess:
        return TallyProcess(4242, time.time() - 3600)


async def _seed(committed: Factory) -> tuple[Any, Any, str]:
    async with committed() as s:
        company = await make_company(s, tally_guid=company_guid(SHARMA))
        owner = await make_user(s, company, RoleName.OWNER)
        token = await make_registration_token(s, company, owner)
        await s.commit()
    return company, owner, token


async def _register(server: Server, tally_port: int, token: str, data: Path) -> None:
    args = [
        "register", "--token", token, "--name", "Head Office", "--backend-url", server.url,
        "--company", SHARMA, "--tally-host", "127.0.0.1", "--tally-port", str(tally_port),
        "--data-dir", str(data),
    ]  # fmt: skip
    result = await asyncio.to_thread(CliRunner().invoke, agent_cli, args)
    assert result.exit_code == 0, result.output


def _agent(data: Path, tally_port: int, **settings: Any) -> Agent:
    loaded = agent_config.load(agent_config.config_path(data)).model_copy(update=settings)
    client = TallyClient(
        "127.0.0.1", tally_port, timeout_seconds=30, process_name="tally.exe", processes=Running()
    )
    return Agent(loaded, tally=client, queue_limits=Limits(first_backoff=1))


class Uploading:
    """The Agent's uploader thread, as the service runs it."""

    def __init__(self, agent: Agent) -> None:
        self.stop = threading.Event()
        uploader = Uploader(agent.queue, agent.backend, self.stop, agent.on_lost, idle_seconds=0.05)
        self.thread = threading.Thread(target=uploader.run, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.stop.set()
        self.thread.join(10)


def _sync_now(server: Server, company: Any, owner: Any, mode: str) -> None:
    r = httpx.post(
        f"{server.url}/companies/{company.company_id}/sync",
        json={"sync_mode": mode},
        headers=auth_header(owner),
        trust_env=False,
    )
    assert r.status_code == 201, r.text


async def _full(server: Server, company: Any, owner: Any, agent: Agent) -> None:
    """A FULL sync, then the reconciliation it queues (REC-1.4, D-048 #6), both COMPLETED, so
    the next command the test creates is the next one the Agent runs."""
    _sync_now(server, company, owner, "FULL")
    assert (await _run(agent)).status == "COMPLETED"
    reconciliation = await _run(agent)
    assert reconciliation.status == "COMPLETED"


async def _run(agent: Agent) -> Any:
    """Heartbeat until the offered command has been run (the first beat makes it ACTIVE)."""
    before = agent.last_outcome
    for _ in range(5):
        await asyncio.to_thread(agent.tick)
        if agent.last_outcome is not before:
            return agent.last_outcome
    raise AssertionError("no command was run")


async def _counts(committed: Factory) -> dict[str, int]:
    tables = [
        "groups",
        "ledgers",
        "voucher_types",
        "stock_items",
        "cost_centres",
        "vouchers",
        "stock_snapshots",
    ]
    async with committed() as s:
        return {t: int(await s.scalar(text(f"SELECT count(*) FROM {t}")) or 0) for t in tables}
