import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _s(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


@pytest.mark.req("SEC-1.14")
def test_prod_missing_secrets_fails_startup() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        _s(env="prod")


@pytest.mark.req("SEC-1.14")
def test_prod_with_all_secrets_ok_and_incremental_off_by_default() -> None:
    s = _s(
        env="prod",
        database_url="postgresql+asyncpg://a",
        database_migration_url="postgresql+psycopg://b",
        jwt_secret="x",
        cors_origins="https://a.example, https://b.example",
    )
    assert s.cors_origins == ["https://a.example", "https://b.example"]
    assert s.allow_unverified_incremental is False  # D-029


@pytest.mark.parametrize("env", ["dev", "test"])
def test_dev_and_test_get_defaults_and_incremental_on(env: str) -> None:
    s = _s(env=env)
    assert s.allow_unverified_incremental is True  # D-029
    assert s.jwt_secret is not None and s.database_url


def test_explicit_flag_wins() -> None:
    assert _s(env="dev", allow_unverified_incremental=False).allow_unverified_incremental is False
