"""The committing fixture really commits, and never cleans up a non-test database."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models.company import Company
from tally_tools.phase_report import UnsafeDatabase
from tests.conftest import committed_database_urls
from tests.factories import make_company


async def test_a_commit_is_visible_to_another_connection(
    committed: async_sessionmaker[AsyncSession],
) -> None:
    async with committed() as writer:
        company = await make_company(writer, name="Committed Co")
        await writer.commit()
    async with committed() as reader:
        found = await reader.scalar(
            select(Company.name).where(Company.company_id == company.company_id)
        )
    assert found == "Committed Co"


@pytest.mark.parametrize(
    ("app_db", "owner_db"), [("tally", "tally_test"), ("tally_test", "tally"), ("prod", "prod")]
)
def test_cleanup_refuses_a_database_not_named_test(app_db: str, owner_db: str) -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        env="test",
        database_url=f"postgresql+asyncpg://u:p@localhost/{app_db}",
        database_migration_url=f"postgresql+psycopg://u:p@localhost/{owner_db}",
    )
    with pytest.raises(UnsafeDatabase):
        committed_database_urls(settings)
