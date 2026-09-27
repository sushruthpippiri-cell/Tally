"""Fixtures for the Agent tests: local HTTPS servers with a throwaway CA and an HTTP CONNECT
proxy (D-042 #4). As fixtures, because `tests` on the path is the backend's package."""

import json
import socket
import ssl
import threading
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
