"""Builders for tests in every phase. Amounts are passed as strings and stored as Decimal."""

import itertools
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal

import bcrypt
import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agents import Agent, AgentCommand
from app.models.balances import LedgerOpeningBalance
from app.models.company import Company, Role, User, UserRole
from app.models.defaults import PREDEFINED_GROUPS
from app.models.enums import (
    AccountingDirection,
    AgentStatus,
    BaseVoucherType,
    CommandStatus,
    CommandType,
    MasterStatus,
    Nature,
    RoleName,
    SyncMode,
)
from app.models.masters import CostCentre, Group, Ledger, StockItem, VoucherType
from app.models.vouchers import BillAllocation, Voucher, VoucherEntry, VoucherItem


@asynccontextmanager
async def db_error(session: AsyncSession, match: str) -> AsyncIterator[None]:
    """Expect the database to reject what the block does (run in a savepoint, then rolled back)."""
    with pytest.raises(DBAPIError, match=match):
        async with session.begin_nested():
            yield


def guid() -> str:
    return str(uuid.uuid4())


_alter_ids = itertools.count(1)


def _synced(company: Company) -> dict[str, object]:
    return {
        "company_id": company.company_id,
        "tally_guid": guid(),
        "alter_id": next(_alter_ids),
        "status": MasterStatus.ACTIVE,
    }


async def make_company(
    session: AsyncSession,
    fy_start: date = date(2024, 4, 1),
    tz: str = "Asia/Kolkata",
    name: str = "Test Traders",
    tally_guid: str | None = None,
) -> Company:
    company = Company(
        name=name, financial_year_start=fy_start, company_timezone=tz, tally_guid=tally_guid
    )
    session.add(company)
    await session.flush()
    return company


PASSWORD = "correct horse battery staple"
# Cost 4 keeps tests fast; bcrypt.checkpw works with any cost.
_PASSWORD_HASH = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
_emails = itertools.count(1)


async def make_user(
    session: AsyncSession,
    company: Company | None = None,
    *roles: RoleName,
    email: str | None = None,
    is_active: bool = True,
) -> User:
    """A user with password `PASSWORD` and the given roles in `company`."""
    user = User(
        email=email or f"user{next(_emails)}@example.com",
        password_hash=_PASSWORD_HASH,
        name="Test User",
        is_active=is_active,
    )
    session.add(user)
    await session.flush()
    if company is not None:
        await grant(session, user, company, *roles)
    return user


async def grant(session: AsyncSession, user: User, company: Company, *roles: RoleName) -> None:
    for role in roles:
        role_id = (
            await session.execute(select(Role.role_id).where(Role.role_name == role))
        ).scalar_one()
        session.add(UserRole(user_id=user.user_id, company_id=company.company_id, role_id=role_id))
    await session.flush()


async def make_agent(session: AsyncSession, company: Company, name: str = "agent-1") -> Agent:
    agent = Agent(company_id=company.company_id, agent_name=name, status=AgentStatus.ACTIVE)
    session.add(agent)
    await session.flush()
    return agent


async def make_command(
    session: AsyncSession, agent: Agent, sync_mode: SyncMode = SyncMode.FULL
) -> AgentCommand:
    command = AgentCommand(
        company_id=agent.company_id,
        agent_id=agent.agent_id,
        command_type=CommandType.RUN_SYNC,
        sync_mode=sync_mode,
        status=CommandStatus.PENDING,
    )
    session.add(command)
    await session.flush()
    return command


async def make_predefined_groups(session: AsyncSession, company: Company) -> dict[str, Group]:
    """All 28 predefined groups, each its own anchor (D-001), keyed by name."""
    groups: dict[str, Group] = {}

    async def add(name: str, nature: Nature, primary: Group | None) -> Group:
        group_id = uuid.uuid4()
        group = Group(
            **_synced(company),
            group_id=group_id,
            name=name,
            reserved_name=name,
            is_predefined=True,
            parent_group_id=primary.group_id if primary else None,
            parent_tally_guid=primary.tally_guid if primary else None,
            predefined_group_id=group_id,
            classification_group_id=group_id,
            primary_group_id=primary.group_id if primary else group_id,
            nature=nature,
            resolution_status="RESOLVED",
        )
        session.add(group)
        await session.flush()
        groups[name] = group
        return group

    for primary_name, (nature, subs) in PREDEFINED_GROUPS.items():
        primary = await add(primary_name, nature, None)
        for sub in subs:
            await add(sub, nature, primary)
    return groups


async def make_group(
    session: AsyncSession,
    company: Company,
    name: str,
    parent: Group | None,
    nature: Nature | None = None,
) -> Group:
    """A user group. Under a parent it rolls up to the parent's anchor; at the top level
    (directly under Primary) it is its own anchor and needs a `nature` (D-001 case 3)."""
    group_id = uuid.uuid4()
    if parent is None and nature is None:
        raise ValueError("a top-level user group needs a nature (G14)")
    group = Group(
        **_synced(company),
        group_id=group_id,
        name=name,
        is_predefined=False,
        parent_group_id=parent.group_id if parent else None,
        parent_tally_guid=parent.tally_guid if parent else None,
        predefined_group_id=parent.predefined_group_id if parent else None,
        classification_group_id=parent.classification_group_id if parent else group_id,
        primary_group_id=parent.primary_group_id if parent else None,
        nature=parent.nature if parent else nature,
        resolution_status="RESOLVED",
    )
    session.add(group)
    await session.flush()
    return group


async def make_ledger(
    session: AsyncSession,
    company: Company,
    name: str,
    group: Group,
    opening: tuple[str, str] | None = None,
) -> Ledger:
    """`opening` is (direction, amount), e.g. ("DEBIT", "5000"), at the company's FY start."""
    ledger = Ledger(
        **_synced(company),
        name=name,
        group_id=group.group_id,
        parent_group_tally_guid=group.tally_guid,
        primary_group_id=group.primary_group_id,
        predefined_group_id=group.predefined_group_id,
        classification_group_id=group.classification_group_id,
    )
    session.add(ledger)
    await session.flush()
    if opening is not None:
        await make_opening_balance(session, company, ledger, *opening)
    return ledger


async def make_opening_balance(
    session: AsyncSession,
    company: Company,
    ledger: Ledger,
    direction: str,
    amount: str,
    fy_start: date | None = None,
) -> LedgerOpeningBalance:
    balance = LedgerOpeningBalance(
        company_id=company.company_id,
        ledger_id=ledger.ledger_id,
        financial_year_start=fy_start or company.financial_year_start,
        amount_absolute=Decimal(amount),
        accounting_direction=AccountingDirection(direction),
    )
    session.add(balance)
    await session.flush()
    return balance


async def make_voucher_type(
    session: AsyncSession,
    company: Company,
    name: str,
    base: BaseVoucherType | None = None,
    parent: VoucherType | None = None,
) -> VoucherType:
    """Top-level types are predefined (reserved_name = name); base defaults from the parent,
    else from the name ("Credit Note" -> CREDIT_NOTE), else OTHER."""
    if base is None:
        if parent is not None:
            base = BaseVoucherType(parent.base_voucher_type)
        else:
            key = name.upper().replace(" ", "_")
            base = (
                BaseVoucherType(key)
                if key in BaseVoucherType.__members__
                else BaseVoucherType.OTHER
            )
    vtype = VoucherType(
        **_synced(company),
        name=name,
        reserved_name=None if parent else name,
        parent_voucher_type_id=parent.voucher_type_id if parent else None,
        parent_tally_guid=parent.tally_guid if parent else None,
        base_voucher_type=base,
        resolution_status="RESOLVED",
    )
    session.add(vtype)
    await session.flush()
    return vtype


async def make_stock_item(
    session: AsyncSession, company: Company, name: str, base_unit: str = "Nos"
) -> StockItem:
    item = StockItem(**_synced(company), name=name, base_unit=base_unit)
    session.add(item)
    await session.flush()
    return item


async def make_cost_centre(session: AsyncSession, company: Company, name: str) -> CostCentre:
    centre = CostCentre(**_synced(company), name=name)
    session.add(centre)
    await session.flush()
    return centre


Entry = tuple[str, str, str]  # (ledger name, "DEBIT" | "CREDIT", amount)
Item = tuple[str, str, str, str]  # (stock item name, quantity, rate, amount)
Bill = tuple[int, str, str, str]  # (entry index, allocation type, reference, amount)

DEFAULT_ENTRIES: list[Entry] = [("Customer A", "DEBIT", "10000"), ("Sales", "CREDIT", "10000")]


async def _by_name[M: (Ledger, StockItem)](
    session: AsyncSession, model: type[M], company: Company, name: str
) -> M:
    found = await session.scalar(
        select(model).where(model.company_id == company.company_id, model.name == name)
    )
    if found is None:
        raise LookupError(f"no {model.__tablename__} row named {name!r} in this company")
    return found


async def make_voucher(
    session: AsyncSession,
    company: Company,
    vtype: VoucherType,
    voucher_date: date,
    entries: list[Entry] | None = None,
    items: list[Item] | None = None,
    bills: list[Bill] | None = None,
    status: str = "ACTIVE",
    number: str | None = None,
) -> Voucher:
    """A voucher with normalized entries. Ledgers and stock items are looked up by name in the
    company (create them first). Refuses unbalanced input: debits must equal credits."""
    entries = DEFAULT_ENTRIES if entries is None else entries
    signed = [
        Decimal(amount) if AccountingDirection(d) is AccountingDirection.DEBIT else -Decimal(amount)
        for _, d, amount in entries
    ]
    if sum(signed, Decimal(0)) != 0:
        raise ValueError(f"unbalanced voucher: debits - credits = {sum(signed, Decimal(0))}")
    voucher = Voucher(
        **{**_synced(company), "status": status},
        voucher_number=number,
        voucher_type_id=vtype.voucher_type_id,
        voucher_date=voucher_date,
    )
    session.add(voucher)
    await session.flush()
    rows: list[VoucherEntry] = []
    for seq, ((ledger_name, direction, amount), amount_signed) in enumerate(
        zip(entries, signed, strict=True)
    ):
        ledger = await _by_name(session, Ledger, company, ledger_name)
        rows.append(
            VoucherEntry(
                company_id=company.company_id,
                voucher_id=voucher.voucher_id,
                ledger_id=ledger.ledger_id,
                line_sequence=seq,
                amount_raw=amount,
                is_debit=direction == AccountingDirection.DEBIT,
                amount_absolute=Decimal(amount),
                amount_signed=amount_signed,
                accounting_direction=direction,
            )
        )
    session.add_all(rows)
    await session.flush()
    for entry_idx, allocation_type, reference, amount in bills or []:
        entry = rows[entry_idx]
        session.add(
            BillAllocation(
                company_id=company.company_id,
                voucher_entry_id=entry.voucher_entry_id,
                ledger_id=entry.ledger_id,
                allocation_type_raw=allocation_type,
                allocation_type=allocation_type,
                reference_name=reference,
                amount_absolute=Decimal(amount),
                accounting_direction=entry.accounting_direction,
            )
        )
    for item_name, quantity, rate, amount in items or []:
        item = await _by_name(session, StockItem, company, item_name)
        session.add(
            VoucherItem(
                company_id=company.company_id,
                voucher_id=voucher.voucher_id,
                stock_item_id=item.stock_item_id,
                quantity=Decimal(quantity),
                unit=item.base_unit,
                rate=Decimal(rate),
                amount=Decimal(amount),
            )
        )
    await session.flush()
    return voucher
