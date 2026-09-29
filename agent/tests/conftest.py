"""Fixtures for the Agent tests: local HTTPS servers with a throwaway CA and an HTTP CONNECT
proxy (D-042 #4). As fixtures, because `tests` on the path is the backend's package."""

import json
import socket
import ssl
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
import trustme


class _Json(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        payload = json.dumps({"ok": True, "path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:
        pass


@contextmanager
def https_server(ca: trustme.CA, *, maximum: ssl.TLSVersion | None = None) -> Iterator[str]:
    """An HTTPS JSON server on 127.0.0.1 with a certificate from `ca`; yields its base URL."""
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ca.issue_cert("127.0.0.1", "localhost").configure_cert(context)
    if maximum is not None:
        context.minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED
        context.maximum_version = maximum
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Json)
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"https://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def write_ca(ca: trustme.CA, path: Path) -> Path:
    ca.cert_pem.write_to_path(str(path))
    return path


class ConnectProxy:
    """A minimal HTTP CONNECT proxy that records what it tunnelled and the auth it was sent."""

    def __init__(self) -> None:
        self.tunnels: list[str] = []
        self.auth: list[str | None] = []
        self._server = socket.create_server(("127.0.0.1", 0))
        self.url = f"http://127.0.0.1:{self._server.getsockname()[1]}"
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self) -> None:
        while True:
            try:
                client, _ = self._server.accept()
            except OSError:
                return
            threading.Thread(target=self._tunnel, args=(client,), daemon=True).start()

    def _tunnel(self, client: socket.socket) -> None:
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = client.recv(4096)
            if not chunk:
                return
            head += chunk
        lines = head.decode("latin-1").split("\r\n")
        target = lines[0].split()[1]
        auth = next(
            (
                line.split(":", 1)[1].strip()
                for line in lines
                if line.lower().startswith("proxy-authorization:")
            ),
            None,
        )
        self.tunnels.append(target)
        self.auth.append(auth)
        host, port = target.rsplit(":", 1)
        upstream = socket.create_connection((host, int(port)))
        client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
        for a, b in ((client, upstream), (upstream, client)):
            threading.Thread(target=self._pipe, args=(a, b), daemon=True).start()

    @staticmethod
    def _pipe(source: socket.socket, sink: socket.socket) -> None:
        try:
            while data := source.recv(65536):
                sink.sendall(data)
        except OSError:
            pass
        finally:
            for s in (source, sink):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def close(self) -> None:
        self._server.close()


@pytest.fixture
def ca() -> trustme.CA:
    return trustme.CA()


@pytest.fixture
def ca_bundle(ca: trustme.CA, tmp_path: Path) -> Path:
    return write_ca(ca, tmp_path / "office-ca.pem")


@pytest.fixture
def serve_https(ca: trustme.CA) -> Any:
    return lambda **kw: https_server(ca, **kw)


@pytest.fixture
def connect_proxy() -> Iterator[ConnectProxy]:
    proxy = ConnectProxy()
    yield proxy
    proxy.close()


# --- Tally ---------------------------------------------------------------------------------


class FakeProcesses:
    """What the process table says about TallyPrime (AGT-6.3)."""

    def __init__(self, running: bool = True, started_at: float = 0.0) -> None:
        self.running, self.started_at = running, started_at

    def find(self, name: str) -> Any:
        from tally_agent.tally_process import TallyProcess

        return TallyProcess(4242, self.started_at) if self.running else None


@pytest.fixture
def mock_tally() -> Iterator[tuple[Any, str]]:
    """The mock TallyPrime (tools/tally_tools/mock_tally.py): (its config, its port)."""
    from tally_tools.mock_tally import MockConfig, running

    config = MockConfig(companies=["Sharma Traders", "Other Co"])
    with running(config) as url:
        yield config, url.rsplit(":", 1)[1]


@pytest.fixture
def closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def make_tally() -> Any:
    """make_tally(port, running=True, timeout=5): a TallyClient with a fake process table."""
    from tally_agent.tally_client import TallyClient

    def make(port: Any, *, running: bool = True, timeout: float = 5) -> TallyClient:
        return TallyClient(
            "127.0.0.1",
            int(port),
            timeout_seconds=timeout,
            process_name="tally.exe",
            processes=FakeProcesses(running=running),
        )

    return make


# --- a fake backend -------------------------------------------------------------------------

ALL_COLLECTIONS = [
    "COMPANY",
    "GROUP",
    "LEDGER",
    "VOUCHER_TYPE",
    "STOCK_ITEM",
    "COST_CENTRE",
    "VOUCHER",
]


class FakeBackend:
    """The Agent protocol (docs/agent-protocol.md) on loopback HTTP, strict where it matters:
    the command lease is enforced live, so a command that stops sending progress is lost and
    every later call for it gets 409 INVALID_COMMAND_STATE, as the real backend does (D-039).
    It records every call, with its headers and timing."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.calls: list[tuple[str, str, dict[str, Any], dict[str, str]]] = []
        self.times: list[tuple[float, str]] = []  # (monotonic, path)
        self.credential = "cred-" + "x" * 40
        self.lease_seconds = 5.0
        self.config: dict[str, Any] = {
            "poll_interval_seconds": 30,
            "progress_interval_seconds": 1,
            "command_lease_seconds": 5,
            "extraction_batch_size": 5000,
            "tally_host": "127.0.0.1",
            "tally_port": 9000,
            "tally_company_name": "Sharma Traders",
            "expected_tdl_version": "0.0.0",
            "collection_sync_modes": {},
        }
        self.offers: list[dict[str, Any]] = []  # waiting to be handed out by a heartbeat
        self.offered: list[dict[str, Any]] = []  # every command ever offered
        self.commands: dict[str, dict[str, Any]] = {}
        self.plan: dict[str, Any] = {
            "as_of": "2026-03-16",
            "full_pull_from": "2024-04-01",
            "financial_year_from": "2025-04-01",
            "reconciliation_periods": [],
            "collections": {
                c: {"mode": "INCREMENTAL", "watermark": 0, "full": True, "key_list_due": False}
                for c in ALL_COLLECTIONS
            },
        }
        self.locked: set[str] = set()
        self.batches: list[dict[str, Any]] = []
        self.key_lists: list[dict[str, Any]] = []
        self.finishes: list[dict[str, Any]] = []
        self.results: list[dict[str, Any]] = []
        self.releases: list[dict[str, Any]] = []
        self.upload_failures: list[tuple[int, dict[str, Any]]] = []  # answers for the next uploads
        self.upload_delay = 0.0
        self.lose_after_batches = 0
        self.heartbeat_error: tuple[int, dict[str, Any]] | None = None
        self.next_answers: list[tuple[int, dict[str, Any]]] = []
        backend = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                with backend.lock:
                    backend.calls.append(("POST", self.path, body, dict(self.headers)))
                    backend.times.append((time.monotonic(), self.path))
                status, payload = backend.answer(self.path, body)
                extra = payload.pop("_headers", {})
                data = json.dumps(payload).encode()
                self.send_response(status)
                for name, value in extra.items():
                    self.send_header(name, str(value))
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, format: str, *args: Any) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    # --- helpers for tests ------------------------------------------------------------------

    def offer(self, sync_mode: str = "FULL", **fields: Any) -> str:
        command_id = str(uuid.uuid4())
        command = {
            "command_id": command_id,
            "sync_mode": sync_mode,
            "date_from": None,
            "date_to": None,
            "created_at": "2026-03-16T12:00:00Z",
        } | fields
        self.offers.append(command)
        self.offered.append(command)
        self.commands[command_id] = {"status": "PENDING", "lease": 0.0}
        return command_id

    def running(self, command_id: str) -> None:
        """A RUNNING command with a long lease, for tests that only upload."""
        self.commands[command_id] = {"status": "RUNNING", "lease": time.monotonic() + 3600}

    def paths(self, prefix: str = "") -> list[str]:
        return [path for _, path, _, _ in self.calls if path.startswith(prefix)]

    def lose(self, command_id: str) -> None:
        with self.lock:
            self.commands[command_id]["status"] = "FAILED_AGENT_LOST"

    # --- the protocol ---------------------------------------------------------------------

    def _live(self, command_id: str) -> bool:
        command = self.commands.get(command_id)
        if command is None:
            return False
        if command["status"] in ("CLAIMED", "RUNNING") and time.monotonic() > command["lease"]:
            command["status"] = "FAILED_AGENT_LOST"  # the lost-Agent job, applied live
        return bool(command["status"] in ("CLAIMED", "RUNNING"))

    def answer(self, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        gone = (409, {"code": "INVALID_COMMAND_STATE", "message": "The command is over"})
        if self.next_answers:  # whatever the path: e.g. a 429 before the real answer
            status, payload = self.next_answers.pop(0)
            return status, dict(payload)
        parts = path.strip("/").split("/")
        with self.lock:
            if path == "/agent/register":
                return 201, {
                    "agent_id": "8a1f3c1e-4c3b-4c55-9d2b-0f6c2a1b9e70",
                    "credential": self.credential,
                    "config": self.config
                    | {
                        "tally_host": body.get("tally_host", "localhost"),
                        "tally_port": body.get("tally_port", 9000),
                        "tally_company_name": body.get("tally_company_name", ""),
                    },
                }
            if path == "/agent/heartbeat" and self.heartbeat_error:
                return self.heartbeat_error
            if path == "/agent/heartbeat":
                offer = self.offers.pop(0) if self.offers else None
                return 200, {
                    "status": "ACTIVE",
                    "config": self.config,
                    "command": offer,
                    "warnings": [],
                }
            if parts[:2] == ["agent", "commands"]:
                command_id, action = parts[2], parts[3]
                command = self.commands.get(command_id)
                if action in ("batches", "key-lists") and self.upload_failures:
                    status, payload = self.upload_failures.pop(0)
                    return status, dict(payload)
                if action == "claim":
                    if command is None or command["status"] != "PENDING":
                        return gone
                    command.update(status="CLAIMED", lease=time.monotonic() + self.lease_seconds)
                    return 200, {"command_id": command_id, "status": "CLAIMED"}
                if not self._live(command_id):
                    return gone
                if action == "progress":
                    command["status"] = "RUNNING"
                    command["lease"] = time.monotonic() + self.lease_seconds
                    return 200, {"command_id": command_id, "status": "RUNNING"}
                if command["status"] != "RUNNING":
                    return gone
                if action == "runs" and len(parts) == 4:
                    offer = next(c for c in self.offered if c["command_id"] == command_id)
                    run_id = str(uuid.uuid4())
                    command["run_id"] = run_id
                    return 201, {
                        "sync_run_id": run_id,
                        "sync_mode": offer["sync_mode"],
                        "date_from": offer["date_from"],
                        "date_to": offer["date_to"],
                    } | self.plan
                if action == "runs":  # .../runs/{run}/finish
                    self.finishes.append(body)
                    return 200, {"sync_run_id": parts[4], "status": body["status"]}
                if action in ("batches", "key-lists"):
                    if self.upload_delay:
                        time.sleep(self.upload_delay)
                    (self.batches if action == "batches" else self.key_lists).append(body)
                    if self.lose_after_batches and len(self.batches) >= self.lose_after_batches:
                        command["status"] = "FAILED_AGENT_LOST"  # e.g. the lost-Agent job
                    return 200, {"status": "COMPLETE"}
                if action == "result":
                    self.results.append(body)
                    command["status"] = body["status"]
                    return 200, {"command_id": command_id, "status": body["status"]}
            if path == "/agent/leases/acquire":
                if body["collection_type"] in self.locked:
                    return 409, {
                        "code": "SYNC_LOCKED",
                        "message": "Held by Standby",
                        "details": {"holder": "Standby"},
                    }
                return 200, {
                    "collection_type": body["collection_type"],
                    "last_alter_id": 0,
                    "lock_expires_at": "2026-03-16T12:05:00Z",
                }
            if path == "/agent/leases/release":
                self.releases.append(body)
                return 200, {"collection_type": body["collection_type"], "last_alter_id": 0}
            return 404, {"code": "NOT_FOUND", "message": path}

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def fake_backend() -> Iterator[FakeBackend]:
    backend = FakeBackend()
    yield backend
    backend.close()


# --- a registered Agent against the fake backend and the mock Tally ----------------------------

SHARMA = "Sharma Traders"


@pytest.fixture
def make_agent(tmp_path: Path, fake_backend: FakeBackend, mock_tally: tuple[Any, str]) -> Any:
    """make_agent(data=..., limits=..., tally_timeout=..., upload_batch_records=..., **config)."""
    from tally_agent import state
    from tally_agent.config import AgentSettings
    from tally_agent.secret_store import CREDENTIAL, SecretStore
    from tally_agent.service import Agent
    from tally_agent.tally_client import TallyClient
    from tally_tools.mock_tally import company_guid, sample_company

    def make(
        *,
        data: dict[str, Any] | None = None,
        limits: Any = None,
        tally_timeout: float = 10,
        upload_batch_records: int = 500,
        processes: Any = None,
        **config: Any,
    ) -> Agent:
        mock, port = mock_tally
        mock.data = sample_company(SHARMA) if data is None else data
        fake_backend.config |= {"tally_port": int(port), **config}
        fake_backend.lease_seconds = float(fake_backend.config["command_lease_seconds"])
        directory = tmp_path / "agent"
        settings = AgentSettings(
            backend_url=fake_backend.url,
            company_name=SHARMA,
            data_dir=directory,
            upload_batch_records=upload_batch_records,
        )
        SecretStore(directory, settings.service_account).save(CREDENTIAL, fake_backend.credential)
        state.save(
            directory,
            state.AgentState(
                agent_id=uuid.uuid4(),
                company_guid=company_guid(SHARMA),
                company_name=SHARMA,
                backend_config=fake_backend.config,
            ),
            settings.service_account,
        )
        tally = TallyClient(
            "127.0.0.1",
            int(port),
            timeout_seconds=tally_timeout,
            process_name="tally.exe",
            processes=processes or FakeProcesses(),
        )
        return Agent(settings, tally=tally, queue_limits=limits)

    return make


def run_once(agent: Any) -> Any:
    """One heartbeat (and the command it offers) with the uploader running alongside."""
    from tally_agent.uploader import Uploader

    uploader = Uploader(
        agent.queue, agent.backend, agent.stop, on_lost=agent.on_lost, idle_seconds=0.02
    )
    thread = threading.Thread(target=uploader.run, daemon=True)
    thread.start()
    try:
        agent.tick()
    finally:
        agent.stop.set()
        thread.join(10)
    return agent.last_outcome


@pytest.fixture
def run_agent_once() -> Any:
    return run_once


@pytest.fixture
def fake_processes() -> type[FakeProcesses]:
    return FakeProcesses
