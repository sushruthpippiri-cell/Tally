"""P2.1: bootstrap the first user (D-006)."""

import bcrypt
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import cli
from app.models.company import User
from app.models.config import AuditLog
from tests.factories import make_user


async def test_create_owner_stores_a_bcrypt_hash_and_audits(session: AsyncSession) -> None:
    user_id = await cli.create_owner(session, " Owner@Example.com", "Owner", "first-password")
    user = await session.get(User, user_id)
    assert user is not None
    assert user.email == "owner@example.com"
    assert user.password_hash.startswith("$2b$")
    assert bcrypt.checkpw(b"first-password", user.password_hash.encode())
    row = (await session.execute(select(AuditLog))).scalar_one()
    assert (row.action, row.user_id, row.entity_id) == ("USER_CREATED", None, str(user_id))


async def test_create_owner_refuses_a_taken_email_and_a_weak_password(
    session: AsyncSession,
) -> None:
    await make_user(session, email="owner@example.com")
    with pytest.raises(cli.CliError, match="already exists"):
        await cli.create_owner(session, "OWNER@example.com", "Owner", "first-password")
    with pytest.raises(cli.CliError, match="at least 8"):
        await cli.create_owner(session, "new@example.com", "New", "short")


def test_mismatched_passwords_stop_the_command(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["first-password", "different-password"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: next(answers))
    assert cli.main(["create-owner", "--email", "a@example.com", "--name", "A"]) == 1
