"""Alembic environment: migrations always use the owner role (DATABASE_MIGRATION_URL)."""

from alembic import context
from sqlalchemy import create_engine

from app.core.config import get_settings
from app.models import Base

config = context.config
# An explicit sqlalchemy.url (set by tests on a throwaway database) wins over settings.
url = config.get_main_option("sqlalchemy.url") or get_settings().database_migration_url
assert url is not None
target_metadata = Base.metadata


def run_migrations_online() -> None:
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
