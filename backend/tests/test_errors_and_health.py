import logging

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

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
