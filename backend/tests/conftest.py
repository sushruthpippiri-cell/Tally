"""Backend test setup: tests use the real `tally_test` database (docker compose), never dev."""

import os

# Must be set before app.core.config is first imported.
os.environ.setdefault("ENV", "test")
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://tally_app:tally_app_dev@localhost:5432/tally_test"
)
os.environ["DATABASE_MIGRATION_URL"] = os.environ.get(
    "TEST_DATABASE_MIGRATION_URL",
    "postgresql+psycopg://tally_owner:tally_owner_dev@localhost:5432/tally_test",
)
