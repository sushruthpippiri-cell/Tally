"""P7.10: the real Agent against the real backend (a uvicorn process on the `_test` database)
and the mock TallyPrime: registration, FULL and INCREMENTAL syncs, edits and deletions in Tally,
the backend killed mid-upload, and a queue drained through the Agent's own rate limit."""

import asyncio
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, text
from typer.testing import CliRunner

from app.models.config import AuditLog
from app.models.enums import RoleName
from app.models.vouchers import Voucher, VoucherEntry
from tally_agent import config as agent_config
from tally_agent.cli import app as agent_cli
from tally_agent.queue import BATCH, Limits
from tally_agent.service import Agent
from tally_agent.tally_client import TallyClient
from tally_agent.tally_process import TallyProcess
from tally_agent.uploader import Uploader
from tally_contract.enums import CollectionType
from tally_contract.records import AlterIdWindow, BatchEnvelope, CostCentreRecord
from tally_contract.testing import assert_logged
from tally_tools.mock_tally import (
    MockConfig,
    add_voucher,
    company_guid,
    delete,
    edit_voucher,
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

    def __init__(self, **env: str) -> None:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.env = os.environ | {"PYTHONPATH": str(BACKEND)} | env
        self.proc: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        now = datetime.now(UTC).isoformat()  # the test's clock, not the machine's
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "tests.e2e.server", str(self.port), now],
            cwd=BACKEND,
            env=self.env,
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

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(10)


@pytest.fixture
def start_server() -> Iterator[Any]:
    servers: list[Server] = []

    def start(**env: str) -> Server:
        server = Server(**env)
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


FIXTURE = {
    "groups": 3, "ledgers": 3, "voucher_types": 1, "stock_items": 1, "cost_centres": 1,
    "vouchers": 12, "stock_snapshots": 1,
}  # fmt: skip


@pytest.mark.req("AC-01", "AC-02", "AC-04")
async def test_register_sync_edit_and_delete_end_to_end(
    committed: Factory, start_server: Any, tally: tuple[MockConfig, int], tmp_path: Path
) -> None:
    mock, tally_port = tally
    server = start_server()
    company, owner, token = await _seed(committed)
    await _register(server, tally_port, token, tmp_path / "agent")
    agent = _agent(tmp_path / "agent", tally_port)
    uploading = Uploading(agent)
    try:
        # AC-01: Tally holds the fixture; a FULL sync stores exactly that, and again adds nothing.
        _sync_now(server, company, owner, "FULL")
        assert (await _run(agent)).status == "COMPLETED"
        assert await _counts(committed) == FIXTURE
        _sync_now(server, company, owner, "FULL")
        assert (await _run(agent)).status == "COMPLETED"
        assert await _counts(committed) == FIXTURE

        # AC-02: edited in Tally (₹1,180 -> ₹2,360, a new ALTERID); an INCREMENTAL applies it.
        edited = edit_voucher(mock.data, "v-3", "2360.00")
        _sync_now(server, company, owner, "INCREMENTAL")
        assert (await _run(agent)).status == "COMPLETED"
        async with committed() as s:
            voucher = (
                await s.execute(select(Voucher).where(Voucher.tally_guid == "v-3"))
            ).scalar_one()
            debit = await s.scalar(
                select(func.max(VoucherEntry.amount_absolute)).where(
                    VoucherEntry.voucher_id == voucher.voucher_id
                )
            )
            [audit] = (
                (await s.execute(select(AuditLog).where(AuditLog.action == "VOUCHER_MODIFIED")))
                .scalars()
                .all()
            )
        assert (voucher.alter_id, debit) == (edited.alter_id, Decimal("2360.00"))
        assert Decimal(audit.before_value["total"]) == Decimal("1180")  # old and new, audited
        assert Decimal(audit.after_value["total"]) == Decimal("2360")

        # AC-04: deleted in Tally; the key list after the next INCREMENTAL marks it missing.
        delete(mock.data, "TA_Vouchers", "v-5")
        _sync_now(server, company, owner, "INCREMENTAL")
        assert (await _run(agent)).status == "COMPLETED"
        async with committed() as s:
            status = await s.scalar(select(Voucher.status).where(Voucher.tally_guid == "v-5"))
        assert status == "MISSING_IN_TALLY"
        assert (await _counts(committed))["vouchers"] == 12  # the row is kept
        listed = httpx.get(
            f"{server.url}/companies/{company.company_id}/data-quality/missing_vouchers",
            headers=auth_header(owner),
            trust_env=False,
        ).json()["items"]
        assert [item["tally_guid"] for item in listed] == ["v-5"]  # in the Data Quality view
    finally:
        uploading.close()


async def test_a_post_dated_voucher_syncs_in_the_run_after_it_is_created(
    committed: Factory, start_server: Any, tally: tuple[MockConfig, int], tmp_path: Path
) -> None:
    """Owner (D-048 #2, GATE-G37): a voucher entered today but dated next month gets the next
    ALTERID. The next INCREMENTAL stores it, even with Tally's selected period ending today,
    so the watermark that moves past its ALTERID has not skipped it."""
    mock, tally_port = tally
    mock.selected_period = (date(2024, 4, 1), date(2026, 3, 16))  # today (FIXED_NOW)
    server = start_server()
    company, owner, token = await _seed(committed)
    await _register(server, tally_port, token, tmp_path / "agent")
    agent = _agent(tmp_path / "agent", tally_port)
    uploading = Uploading(agent)
    try:
        _sync_now(server, company, owner, "FULL")
        assert (await _run(agent)).status == "COMPLETED"
        post_dated = add_voucher(mock.data, date(2026, 4, 1))
        _sync_now(server, company, owner, "INCREMENTAL")
        assert (await _run(agent)).status == "COMPLETED"
        async with committed() as s:
            stored = (
                await s.execute(select(Voucher).where(Voucher.tally_guid == post_dated.guid))
            ).scalar_one()
            watermark = await s.scalar(
                text(
                    "SELECT last_alter_id FROM sync_watermarks "
                    "WHERE company_id = :c AND collection_type = 'VOUCHER'"
                ),
                {"c": company.company_id},
            )
        assert (stored.voucher_date, stored.alter_id) == (date(2026, 4, 1), post_dated.alter_id)
        assert watermark == post_dated.alter_id
    finally:
        uploading.close()


async def test_the_backend_killed_mid_upload_loses_and_duplicates_nothing(
    committed: Factory, start_server: Any, tally: tuple[MockConfig, int], tmp_path: Path
) -> None:
    """The queue holds while the backend is down; after a restart it drains, replays are safe
    (SYNC-6.3), and the run completes with exactly the fixture stored."""
    mock, tally_port = tally
    mock.data = sample_company(SHARMA, vouchers=200)  # 200 one-voucher uploads: a wide window
    server = start_server()
    company, owner, token = await _seed(committed)
    await _register(server, tally_port, token, tmp_path / "agent")
    agent = _agent(tmp_path / "agent", tally_port, upload_batch_records=1)
    uploading = Uploading(agent)
    try:
        _sync_now(server, company, owner, "FULL")
        running_sync = asyncio.create_task(_run(agent))
        for _ in range(1200):  # until some of the vouchers are in
            async with committed() as s:
                stored = await s.scalar(text("SELECT count(*) FROM vouchers")) or 0
            if stored >= 20:
                break
            await asyncio.sleep(0.05)
        server.kill()
        await asyncio.sleep(2)
        assert agent.queue.status().records > 0  # holding what could not be uploaded
        server.start()
        outcome = await asyncio.wait_for(running_sync, 180)
        assert outcome.status == "COMPLETED"
        assert await _counts(committed) == FIXTURE | {"vouchers": 200}
    finally:
        uploading.close()


async def test_a_large_queue_drains_after_an_outage_through_the_agents_own_rate_limit(
    committed: Factory,
    start_server: Any,
    tally: tuple[MockConfig, int],
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Owner (D-043): 200 batches queued while the backend was unreachable drain as fast as
    the Agent can send them. The Agent's own bucket (here 100 per 5 s) answers 429 with
    Retry-After; the uploader waits and carries on: nothing is dead-lettered, everything is
    stored, and anonymous traffic behind the same IP keeps its whole bucket meanwhile."""
    _, tally_port = tally
    server = start_server(AGENT_RATE_LIMIT="100", RATE_LIMIT_WINDOW_SECONDS="5")
    company, owner, token = await _seed(committed)
    await _register(server, tally_port, token, tmp_path / "agent")
    agent = _agent(tmp_path / "agent", tally_port)
    _sync_now(server, company, owner, "INCREMENTAL")
    backend = agent.backend()
    beat = backend.call("POST", "/agent/heartbeat", agent.heartbeat_payload(), patience=5)
    command_id = beat["command"]["command_id"] if beat["command"] else None
    if command_id is None:  # the first beat made it ACTIVE; the next one offers the command
        beat = backend.call("POST", "/agent/heartbeat", agent.heartbeat_payload(), patience=5)
        command_id = beat["command"]["command_id"]
    backend.call("POST", f"/agent/commands/{command_id}/claim", patience=5)
    backend.call("POST", f"/agent/commands/{command_id}/progress", patience=5)
    run_id = backend.call("POST", f"/agent/commands/{command_id}/runs", patience=5)["sync_run_id"]
    lease = {"sync_run_id": run_id, "collection_type": "COST_CENTRE"}
    backend.call("POST", "/agent/leases/acquire", lease, patience=5)
    for i in range(1, 201):  # queued during the outage
        envelope = BatchEnvelope(
            collection_type=CollectionType.COST_CENTRE,
            command_id=uuid.UUID(command_id),
            sync_run_id=uuid.UUID(run_id),
            batch_seq=i,
            batch_id=uuid.uuid4(),
            window=AlterIdWindow(from_alter_id=i - 1, to_alter_id=i),
            records=[CostCentreRecord(guid=f"cc-{i}", alter_id=i, name=f"Centre {i}")],
        )
        agent.queue.add(
            kind=BATCH,
            item_id=str(envelope.batch_id),
            command_id=command_id,
            sync_run_id=run_id,
            collection="COST_CENTRE",
            body_json=envelope.model_dump_json(),
            record_count=1,
        )
    uploading = Uploading(agent)  # the backend is back: drain
    try:
        await asyncio.sleep(1)
        # Other traffic behind the same office IP (anonymous: the IP's own bucket, 100 per
        # window) is untouched by the Agent's drain, which counts only in its own bucket.
        with httpx.Client(base_url=server.url, trust_env=False) as office:
            codes = [office.get("/health").status_code for _ in range(95)]
        assert set(codes) == {200}, codes.count(429)
        for _ in range(1200):
            if agent.queue.status().records == 0:
                break
            await asyncio.sleep(0.1)
    finally:
        uploading.close()
    status = agent.queue.status()
    assert (status.records, status.dead_letter_count, status.obsolete_dropped) == (0, 0, 0)
    assert (await _counts(committed))["cost_centres"] == 200
    assert_logged(caplog, "upload_rate_limited", level="info")  # the limit was really hit


def test_the_dev_certificate_is_trusted_only_through_its_ca(tmp_path: Path) -> None:
    """tally_tools.dev_backend: the throwaway CA the Windows checklist hands to the Agent."""
    import ssl
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from tally_tools import dev_backend

    dev_backend.OUT = tmp_path / "dev-https"
    ca = dev_backend.make_tls(["192.0.2.10"], dev_backend.OUT)

    class Ok(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            pass

    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(dev_backend.OUT / "server.pem", dev_backend.OUT / "server-key.pem")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Ok)
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        url = f"https://127.0.0.1:{httpd.server_address[1]}/"
        trusting = ssl.create_default_context(cafile=str(ca))
        assert httpx.get(url, verify=trusting, trust_env=False).status_code == 200
        with pytest.raises(httpx.ConnectError):
            httpx.get(url, trust_env=False)  # the public roots do not trust it
    finally:
        httpd.shutdown()


async def test_the_dev_setup_creates_a_company_a_token_and_a_sync(
    committed: Factory, start_server: Any, tally: tuple[MockConfig, int], tmp_path: Path
) -> None:
    """tally_tools.dev_backend setup/sync, as the Windows checklist uses them."""
    from app.cli import create_owner
    from tally_tools import dev_backend

    dev_backend.OUT = tmp_path / "dev-https"
    _, tally_port = tally
    server = start_server()
    async with committed() as s:
        await create_owner(s, "owner@example.com", "Owner", "a-long-dev-password-1")
        await s.commit()
    made = await asyncio.to_thread(
        dev_backend.setup, server.url, None, "owner@example.com", "a-long-dev-password-1", SHARMA
    )
    await _register(server, tally_port, made["registration_token"], tmp_path / "agent")
    answer = await asyncio.to_thread(
        dev_backend.sync,
        server.url,
        None,
        "owner@example.com",
        "a-long-dev-password-1",
        made["company_id"],
        "FULL",
    )
    assert answer["status"] == "PENDING"
    view = await asyncio.to_thread(
        dev_backend.call,
        server.url,
        None,
        "owner@example.com",
        "a-long-dev-password-1",
        "GET",
        "/companies/{company}/agents",
    )
    assert [a["agent_name"] for a in view["agents"]] == ["Head Office"]
