"""Ledger classes from the allow-lists (ACC-7.3, 7.6, D-001, D-044 #3).

A ledger is in a class when its classification anchor (`ledgers.classification_group_id`) is
one of the class's groups. An unresolved ledger has no anchor and is in no class (ACC-7.4).
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.masters import Group
from app.services.settings import get_setting

CUSTOMER_GROUP = "Sundry Debtors"  # ACC-7.6
SUPPLIER_GROUP = "Sundry Creditors"
_LISTS = ("sales", "purchase", "expense", "cash_bank", "tax")


@dataclass(frozen=True)
class Classes:
    sales: frozenset[uuid.UUID]
    purchase: frozenset[uuid.UUID]
    expense: frozenset[uuid.UUID]
    cash_bank: frozenset[uuid.UUID]
    tax: frozenset[uuid.UUID]
    customer: frozenset[uuid.UUID]
    supplier: frozenset[uuid.UUID]


def _key(entry: dict[str, str]) -> tuple[str, str]:
    if entry["type"] == "PREDEFINED":
        return ("reserved", entry["reserved_name"])
    return ("guid", entry["tally_guid"])


async def load_classes(session: AsyncSession, company_id: uuid.UUID) -> Classes:
    lists: dict[str, list[dict[str, Any]]] = {
        name: await get_setting(session, company_id, f"classification.{name}_groups")
        for name in _LISTS
    }
    lists["customer"] = [{"type": "PREDEFINED", "reserved_name": CUSTOMER_GROUP}]
    lists["supplier"] = [{"type": "PREDEFINED", "reserved_name": SUPPLIER_GROUP}]
    wanted = {_key(e) for entries in lists.values() for e in entries}
    rows = await session.execute(
        select(Group.group_id, Group.reserved_name, Group.tally_guid).where(
            Group.company_id == company_id,
            or_(
                Group.reserved_name.in_([v for k, v in wanted if k == "reserved"]),
                Group.tally_guid.in_([v for k, v in wanted if k == "guid"]),
            ),
        )
    )
    ids: dict[tuple[str, str], set[uuid.UUID]] = {}
    for group_id, reserved, guid in rows:
        for key in (("reserved", reserved), ("guid", guid)):
            ids.setdefault(key, set()).add(group_id)
    return Classes(
        **{
            name: frozenset(g for e in entries for g in ids.get(_key(e), ()))
            for name, entries in lists.items()
        }
    )
