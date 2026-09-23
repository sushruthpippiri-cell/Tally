"""SEC-1.15: the app role has no DDL; the owner role does. Uses the real tally_test database."""

import psycopg
import pytest
from sqlalchemy.engine import make_url

from app.core.config import get_settings


def _sync_url(async_url: str) -> str:
    return make_url(async_url).set(drivername="postgresql").render_as_string(hide_password=False)


# Partial: proves the dev/test grants; the production deployment is checked in P16.
@pytest.mark.req_partial("SEC-1.15")
def test_app_role_cannot_create_tables_but_owner_can() -> None:
    s = get_settings()
    assert s.database_url and s.database_migration_url
    assert make_url(s.database_url).database.endswith("_test")  # never the dev database
    with psycopg.connect(_sync_url(s.database_url), autocommit=True) as app_conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app_conn.execute("CREATE TABLE p0_probe (a int)")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app_conn.execute("ALTER TABLE alembic_version ADD COLUMN p0_probe int")
    with psycopg.connect(_sync_url(s.database_migration_url), autocommit=True) as owner:
        owner.execute("CREATE TABLE p0_probe (a int)")
        owner.execute("DROP TABLE p0_probe")
