import logging
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, install_error_handlers
from app.main import create_app
from tally_contract.errors import ErrorCode
from tally_contract.testing import assert_logged


class Body(BaseModel):
    n: int


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/401")
    def _401() -> None:
        raise HTTPException(401, "Not authenticated")

    @app.get("/403")
    def _403() -> None:
        raise HTTPException(403, "Forbidden")

    @app.get("/app-error")
    def _app_error() -> None:
        raise AppError(ErrorCode.SYNC_LOCKED, "locked by agent A", 409, {"agent": "A"})

    @app.post("/body")
    def _body(b: Body) -> None: ...

    @app.get("/405only")
    def _get() -> None: ...

    return TestClient(app)


def test_401_shape(client: TestClient) -> None:
    r = client.get("/401")
    assert r.status_code == 401
    assert r.json() == {
        "code": "NOT_AUTHENTICATED",
        "message": "Not authenticated",
        "details": None,
    }


def test_403_shape(client: TestClient) -> None:
    r = client.get("/403")
    assert r.status_code == 403
    assert r.json()["code"] == "FORBIDDEN"


def test_422_shape(client: TestClient) -> None:
    r = client.post("/body", json={"n": "x"})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "VALIDATION_ERROR" and body["details"]["errors"]


def test_app_error_shape_and_is_logged(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    r = client.get("/app-error")
    assert r.status_code == 409
    assert r.json() == {
        "code": "SYNC_LOCKED",
        "message": "locked by agent A",
        "details": {"agent": "A"},
    }
    assert_logged(caplog, "app_error", level="INFO", code="SYNC_LOCKED", status=409)


def test_unmapped_http_error_keeps_default(client: TestClient) -> None:
    assert client.post("/405only").status_code == 405


def test_health_returns_200() -> None:
    with TestClient(create_app()) as c:
        r = c.get("/health")
        assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_health_db_returns_200_against_real_postgres() -> None:
    with TestClient(create_app()) as c:
        r = c.get("/health/db")
        assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_health_db_unavailable_returns_503_and_logs(caplog: pytest.LogCaptureFixture) -> None:
    from app.core.db import get_session

    class Broken:
        async def execute(self, *_: object) -> None:
            raise ConnectionError("down")

    async def broken_session():  # type: ignore[no-untyped-def]
        yield Broken()

    app = create_app()
    app.dependency_overrides[get_session] = broken_session
    caplog.set_level(logging.DEBUG)
    r = TestClient(app).get("/health/db")
    assert r.status_code == 503
    assert_logged(caplog, "health_db_failed", level="ERROR", error="ConnectionError")


# --- SRS 16: "Database unavailable - HTTP 503; no partial writes" (P16.4) ---------------


@pytest.mark.req("TEST-1.4")
def test_a_lost_database_is_503_with_a_catalogue_code_not_500() -> None:
    """Before P16.4 nothing handled a driver error, so an outage on an ordinary route was a
    bare 500 with no code. SRS 16 asks for 503 and the service-unavailable page.

    /health/db already mapped its own failure, so this uses an ordinary route - the case that
    was not covered.
    """
    app = create_app()

    @app.get("/boom-db")
    async def _boom() -> None:
        raise OperationalError("SELECT 1", {}, OSError("connection refused"))

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom-db")
    assert response.status_code == 503
    assert response.json()["code"] == "DATABASE_UNAVAILABLE"


@pytest.mark.req("TEST-1.4")
def test_a_lost_database_in_the_rate_limiter_is_also_503() -> None:
    """The limiter counts in PostgreSQL (P16.11) and runs in middleware, outside the exception
    handlers, so it needs its own answer or an outage is a bare 500 from every endpoint."""

    class _Down:
        """A session factory whose sessions cannot be opened, as a lost database behaves."""

        def __call__(self) -> Any:
            return self

        async def __aenter__(self) -> Any:
            raise OperationalError("INSERT", {}, OSError("connection refused"))

        async def __aexit__(self, *_: object) -> None:
            return None

    app = create_app()
    # install_middleware closes over the limiter, so the object has to be changed, not replaced.
    app.state.rate_limiter._factory = _Down()
    with TestClient(app, raise_server_exceptions=False) as client:
        # Any path the limiter sees, and one that needs no database of its own, so the 503 can
        # only have come from the limiter. /health would not do: it is exempt.
        response = client.get("/openapi.json")
    assert response.status_code == 503
    assert response.json()["code"] == "DATABASE_UNAVAILABLE"


@pytest.mark.req("TEST-1.4")
def test_a_statement_with_too_many_parameters_is_a_500_not_an_outage() -> None:
    """asyncpg raises InterfaceError both for a lost connection and for a statement exceeding
    PostgreSQL's 32,767 bind parameters. P16.5's benchmark hit the second; calling it 503 told
    the Agent a permanent defect was transient, and it retried with backoff until its command's
    lease lapsed. A bug must stay loud."""
    app = create_app()

    @app.get("/boom-params")
    async def _boom() -> None:
        raise InterfaceError(
            "INSERT", {}, Exception("the number of query arguments cannot exceed 32767")
        )

    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/boom-params").status_code == 500


@pytest.mark.req("TEST-1.4")
def test_an_integrity_error_is_still_a_500() -> None:
    """Only "cannot reach the database" is 503. A constraint violation is a bug in our SQL and
    must stay loud, or a real defect would be reported to operations as an outage."""
    app = create_app()

    @app.get("/boom-integrity")
    async def _boom() -> None:
        raise IntegrityError("INSERT", {}, Exception("duplicate key"))

    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/boom-integrity").status_code == 500


# --- the driver's message never carries the failing row (SEC-1.12 in spirit) -------------

# A value that looks like a customer's books. If it reaches a log record, so would a real one.
PLANTED = "Sharma Traders invoice 4,50,000"


@pytest.mark.req("SEC-1.13")
async def test_a_constraint_violation_logs_the_message_and_sqlstate_but_no_row_values(
    session: AsyncSession,
) -> None:
    """PostgreSQL returns the offending row in a DETAIL line - "Failing row contains (…)" - with
    every column's value. `str()` on the error includes it, so logging the error would put a
    party name, an amount or a narration into the logs.

    A real violation from the real database, not a fabricated exception: the DETAIL has to be
    genuine for the test to mean anything.
    """
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    from app.core.errors import driver_fields

    with pytest.raises(IntegrityError) as caught:
        await session.execute(
            text(
                "INSERT INTO ai_tool_log (company_id, tool_name, status, result_summary,"
                " created_at) VALUES (gen_random_uuid(), 'get_anomaly_evidence',"
                " 'NOT_A_STATUS', :planted, now())"
            ),
            {"planted": PLANTED},
        )
    await session.rollback()

    # The exception itself does carry the row - that is the whole risk.
    assert PLANTED in str(caught.value)
    assert "Failing row contains" in str(caught.value)

    fields = driver_fields(caught.value)

    # What is logged: the constraint that was violated, and the SQLSTATE to act on.
    assert fields["sqlstate"] == "23514"  # check_violation
    assert "ck_ai_tool_log_status" in fields["driver_message"]
    # And nothing from the row.
    for forbidden in (PLANTED, "Failing row", "DETAIL", "get_anomaly_evidence"):
        assert forbidden not in fields["driver_message"], forbidden
    assert set(fields) == {"sqlstate", "driver_message"}, "no other field may be logged"


@pytest.mark.req("SEC-1.13")
def test_the_logged_record_for_an_outage_carries_no_detail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """End to end through the handler: the record that actually reaches the log."""
    app = create_app()

    @app.get("/boom-detail")
    async def _boom() -> None:
        raise OperationalError(
            "INSERT INTO vouchers ...",
            {"narration": PLANTED},
            Exception(f"connection failed\nDETAIL:  Failing row contains (1, {PLANTED})."),
        )

    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/boom-detail").status_code == 503

    record = assert_logged(caplog, "database_unavailable", level="error")
    rendered = repr(record)
    assert PLANTED not in rendered, "the failing row reached the log record"
    assert "DETAIL" not in rendered and "Failing row" not in rendered
    # The statement and its parameters must not come along either.
    assert "INSERT INTO vouchers" not in rendered
