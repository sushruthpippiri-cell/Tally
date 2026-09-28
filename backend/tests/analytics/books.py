"""A small set of books for the metric tests: the predefined groups, one ledger of each kind,
the predefined voucher types plus a custom "POS Invoice" and an OTHER type."""

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.context import AnalyticsFilter, MetricContext, load
from app.core.permissions import CompanyContext
from app.models.company import Company
from app.models.config import CompanySetting
from app.models.enums import BaseVoucherType, SettingDataType
from app.models.masters import Group, Ledger, VoucherType
from app.models.vouchers import Voucher
from tests.factories import (
    Bill,
    Entry,
    make_company,
    make_cost_centre,
    make_group,
    make_ledger,
    make_opening_balance,
    make_predefined_groups,
    make_stock_item,
    make_voucher,
    make_voucher_type,
)

FY_START = date(2025, 4, 1)
FY_END = date(2026, 3, 31)

LEDGERS = {
    "Customer A": "Sundry Debtors",
    "Customer B": "Sundry Debtors",
    "Supplier S": "Sundry Creditors",
    "Sales": "Sales Accounts",
    "Purchases": "Purchase Accounts",
    "Output GST": "Duties & Taxes",
    "Input GST": "Duties & Taxes",
    "Cash": "Cash-in-Hand",
    "HDFC Bank": "Bank Accounts",
    "ICICI OD": "Bank OD A/c",  # not on the Cash/Bank list
    "Rent": "Indirect Expenses",
    "Freight": "Direct Expenses",
    "Loan": "Unsecured Loans",
}
TYPES = [
    "Sales",
    "Purchase",
    "Receipt",
    "Payment",
    "Contra",
    "Journal",
    "Credit Note",
    "Debit Note",
]


@dataclass
class Books:
    session: AsyncSession
    company: Company
    groups: dict[str, Group]
    ledgers: dict[str, Ledger]
    types: dict[str, VoucherType]

    async def ctx(
        self, date_from: date = FY_START, date_to: date = FY_END, **kw: Any
    ) -> MetricContext:
        user = CompanyContext(self.company.company_id, uuid.uuid4(), frozenset())
        return await load(self.session, user, AnalyticsFilter(date_from, date_to, **kw))

    async def voucher(
        self,
        vtype: str,
        day: date,
        entries: list[Entry],
        bills: list[Bill] | None = None,
        **kw: Any,
    ) -> Voucher:
        return await make_voucher(
            self.session, self.company, self.types[vtype], day, entries, bills=bills, **kw
        )

    async def ledger(self, name: str, group: Group) -> Ledger:
        self.ledgers[name] = await make_ledger(self.session, self.company, name, group)
        return self.ledgers[name]

    async def opening(self, ledger: str, direction: str, amount: str) -> None:
        """A books-beginning opening (D-039 #5)."""
        await make_opening_balance(
            self.session, self.company, self.ledgers[ledger], direction, amount, FY_START
        )

    async def group(self, name: str, parent: Group | None, **kw: Any) -> Group:
        self.groups[name] = await make_group(self.session, self.company, name, parent, **kw)
        return self.groups[name]

    async def setting(self, key: str, value: Any, data_type: SettingDataType) -> None:
        self.session.add(
            CompanySetting(
                company_id=self.company.company_id,
                setting_key=key,
                setting_value=value,
                data_type=data_type,
            )
        )
        await self.session.flush()
        self.session.info.pop("settings_overrides", None)  # the per-request cache


async def make_books(session: AsyncSession, name: str = "Test Traders") -> Books:
    company = await make_company(session, fy_start=FY_START, name=name)
    company.books_from = FY_START
    groups = await make_predefined_groups(session, company)
    ledgers = {n: await make_ledger(session, company, n, groups[g]) for n, g in LEDGERS.items()}
    types = {t: await make_voucher_type(session, company, t) for t in TYPES}
    types["POS Invoice"] = await make_voucher_type(
        session, company, "POS Invoice", parent=types["Sales"]
    )
    types["Memorandum"] = await make_voucher_type(
        session, company, "Memorandum", BaseVoucherType.OTHER
    )
    for centre in ("Retail", "Online"):
        await make_cost_centre(session, company, centre)
    for item, unit in (("Soap", "Nos"), ("Rice", "Kgs"), ("Pen", "Nos")):
        await make_stock_item(session, company, item, unit)
    return Books(session, company, groups, ledgers, types)
