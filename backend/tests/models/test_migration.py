"""P1.9: the initial migration upgrades and downgrades cleanly, and matches the models."""

from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.models import Base

BACKEND = Path(__file__).parents[2]
SCRATCH_DB = "tally_migr_test"


def _dsn(database: str) -> str:
    url = make_url(get_settings().database_migration_url or "").set(database=database)
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


@pytest.fixture
def scratch_db() -> Iterator[str]:
    """An empty throwaway database, so the shared test database is never downgraded."""
    with psycopg.connect(_dsn("postgres"), autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')
        admin.execute(f'CREATE DATABASE "{SCRATCH_DB}"')
    try:
        yield _dsn(SCRATCH_DB).replace("postgresql://", "postgresql+psycopg://", 1)
    finally:
        with psycopg.connect(_dsn("postgres"), autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')


def _alembic(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def _objects(url: str) -> tuple[set[str], set[str]]:
    engine = create_engine(url)
    with engine.connect() as conn:
        tables = set(
            conn.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
        )
        functions = set(
            conn.scalars(
                text(
                    "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                    "WHERE n.nspname = 'public'"
                )
            )
        )
    engine.dispose()
    return tables, functions


def test_upgrade_matches_models_and_downgrade_removes_everything(scratch_db: str) -> None:
    cfg = _alembic(scratch_db)
    command.upgrade(cfg, "head")

    tables, functions = _objects(scratch_db)
    assert tables == set(Base.metadata.tables) | {"alembic_version"}
    assert functions == {
        "agent_commands_immutable_owner",
        "forbid_delete",
        "audit_logs_append_only",
    }

    engine = create_engine(scratch_db)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == [], "models and migration disagree; regenerate 0001 before it is applied"

    command.downgrade(cfg, "base")
    assert _objects(scratch_db) == ({"alembic_version"}, set())
