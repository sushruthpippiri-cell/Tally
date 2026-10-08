"""P16.5: an unhandled database error must not put the failing row in the server's log.

`driver_fields` keeps PostgreSQL's DETAIL out of the records **we** write. This is the other
path: Starlette's `ServerErrorMiddleware` re-raises after the 500 response precisely so the
server can log the traceback, and a traceback's last line is `str(exc)` - which for a database
error includes `DETAIL:  Failing row contains (…)` with every column value.

A `TestClient(raise_server_exceptions=False)` probe cannot settle this: Starlette swallows the
exception there instead of handing it to a real server's error logger. So this runs the backend
as the end-to-end harness already does - a real uvicorn subprocess - captures its output, and
reads it.
"""

import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.e2e.harness import start_server
from tests.e2e.server import LEAK_ROUTE

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the backend runs on Linux")

__all__ = ["start_server"]

# A value shaped like a customer's books, planted in the row the failing INSERT builds.
PLANTED = "Sharma Traders invoice 4,50,000"


@pytest.mark.req("SEC-1.13")
def test_an_unhandled_database_error_logs_no_row_values(start_server: Any, tmp_path: Path) -> None:
    log = tmp_path / "uvicorn.log"
    server = start_server(log=log, **{LEAK_ROUTE: PLANTED})

    response = httpx.get(f"{server.url}/e2e/unhandled-db-error", timeout=30, trust_env=False)
    assert response.status_code == 500, response.text

    # The server writes its traceback after responding; give it a moment to flush.
    for _ in range(50):
        if "Traceback" in log.read_text(encoding="utf-8", errors="replace"):
            break
        time.sleep(0.1)
    server.stop()
    captured = log.read_text(encoding="utf-8", errors="replace")

    # It did log the failure - this test is about *what* it logged, not whether.
    assert "ck_ai_tool_log_status" in captured or "Traceback" in captured, captured[-2000:]

    for forbidden in (PLANTED, "Failing row contains", "DETAIL:"):
        assert forbidden not in captured, (
            f"{forbidden!r} reached the server log:\n{captured[-2000:]}"
        )
