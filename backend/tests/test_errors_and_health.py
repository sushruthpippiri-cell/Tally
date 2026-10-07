import logging
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError, OperationalError

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
def test_an_integrity_error_is_still_a_500() -> None:
    """Only "cannot reach the database" is 503. A constraint violation is a bug in our SQL and
    must stay loud, or a real defect would be reported to operations as an outage."""
    app = create_app()

    @app.get("/boom-integrity")
    async def _boom() -> None:
        raise IntegrityError("INSERT", {}, Exception("duplicate key"))

    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/boom-integrity").status_code == 500
