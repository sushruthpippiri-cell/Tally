import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import gates
from tests.analytics.books import Books, make_books


@pytest.fixture
async def books(session: AsyncSession) -> Books:
    return await make_books(session)


@pytest.fixture
def g26_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Return links are trusted only once gate G26 passes (ACC-5.5)."""
    statuses = {g: "NOT_TESTED" for g in gates.load_gate_status()} | {"G26": "PASSED"}
    monkeypatch.setattr(gates, "_default_statuses", lambda: statuses)
