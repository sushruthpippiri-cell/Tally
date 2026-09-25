"""Admin CLI. `python -m app.cli create-owner --email E --name N` creates the first user
(D-006); they then create a company with POST /companies and become its Owner."""

import argparse
import asyncio
import getpass
import sys
import uuid

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.db import transaction
from app.core.security import hash_password
from app.models.company import User
from app.models.enums import RoleName
from app.schemas.users import UserCreate
from tally_contract.log import configure_logging, get_logger

log = get_logger(__name__)


class CliError(Exception):
    pass


async def create_owner(session: AsyncSession, email: str, name: str, password: str) -> uuid.UUID:
    try:
        data = UserCreate(email=email, name=name, password=password, roles=[RoleName.OWNER])
    except ValidationError as exc:
        raise CliError("; ".join(e["msg"] for e in exc.errors())) from exc
    taken = await session.execute(select(User.user_id).where(func.lower(User.email) == data.email))
    if taken.scalar_one_or_none() is not None:
        raise CliError(f"a user with email {data.email} already exists")
    user = User(email=data.email, name=data.name, password_hash=hash_password(data.password))
    session.add(user)
    await session.flush()
    await audit.record(
        session,
        company_id=None,
        user_id=None,  # system: no one is signed in yet
        action="USER_CREATED",
        entity_type="user",
        entity_id=str(user.user_id),
        after={"email": data.email, "via": "cli create-owner"},
    )
    log.info("owner_created", user_id=str(user.user_id), email=data.email)
    return user.user_id


def _read_password() -> str:
    password = getpass.getpass("Password: ")
    if getpass.getpass("Repeat password: ") != password:
        raise CliError("passwords do not match")
    return password


async def _create_owner_cmd(email: str, name: str, password: str) -> uuid.UUID:
    async with transaction() as session:
        return await create_owner(session, email, name, password)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    owner = commands.add_parser("create-owner", help="create the first user")
    owner.add_argument("--email", required=True)
    owner.add_argument("--name", required=True)
    args = parser.parse_args(argv)
    configure_logging("dev")
    try:
        user_id = asyncio.run(_create_owner_cmd(args.email, args.name, _read_password()))
    except CliError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    sys.stdout.write(f"created user {user_id}; sign in and POST /companies to create a company\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
