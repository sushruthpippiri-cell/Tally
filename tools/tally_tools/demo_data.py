"""`make demo-data`: a small, realistic company in the dev database, for checking the dashboard
by hand (D-053 #8).

Everything goes through the real HTTP API, in process, the way an Agent sends it: register,
Sync Now, claim, the run plan, leases, batches of `tally_contract` records, finish. So group
anchors, classification, stale protection and the first-sync schedules are the real ones;
nothing is written to a table directly.

About four months of trading ending on the backend's today (the run plan's `as_of`): sales
with inventory lines and bills due in 30 days, purchases, receipts and payments that leave some
bills overdue in several aging buckets, an advance, monthly rent, salaries and electricity over
two cost centres, cash deposits, a cancelled sale, an unlinked credit note, opening balances
with opening bills, today's stock snapshot, and a mapped "salesman" custom field.

    make demo-data                      # migrates the dev database, then loads
    DEMO_PASSWORD=... make demo-data    # the demo owner's password (default printed)
"""

import argparse
import asyncio
import os
import random
import subprocess
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import httpx
from sqlalchemy.engine import make_url

from tally_contract import normalize
from tally_contract.enums import AllocationType
from tally_contract.records import (
    BillAllocation,
    CompanyRecord,
    CostCentreAllocation,
    CostCentreRecord,
    DateWindow,
    GroupRecord,
    InventoryEntry,
    LedgerEntry,
    LedgerRecord,
    OpeningBill,
    StockItemRecord,
    StockSnapshotRecord,
    VoucherRecord,
    VoucherTypeRecord,
)
from tally_contract.tally_constants import TDL_VERSION
from tally_tools.phase_report import ROOT, UnsafeDatabase

DEV_DB = "postgresql+psycopg://tally_owner:tally_owner_dev@localhost:5432/tally"
DEV_APP_DB = "postgresql+asyncpg://tally_app:tally_app_dev@localhost:5432/tally"
EMAIL = "demo@example.com"
DEFAULT_PASSWORD = "demo-password-14"
COMPANY = "Sharma Trading Co. (demo)"
COMPANY_GUID = "demo-sharma-trading-co"
SEED = 14
DAYS = 120  # about four months of trading
BATCH = 200  # records per upload
GST = Decimal("0.05")
P = Decimal("0.01")

CUSTOMERS = [
    "Mehta Electricals",
    "Gupta Kirana Stores",
    "Sri Lakshmi Traders",
    "Patel Provision Mart",
    "Annapurna Supermarket",
    "Reddy & Sons",
    "Bharat General Stores",
    "Joshi Wholesale",
    "Kaveri Foods",
    "New India Mart",
    "Shree Ganesh Traders",
    "Balaji Agencies",
    "Royal Bakers",
    "Ganga Departmental Store",
    "Nair Brothers",
]
SUPPLIERS = [
    "Adani Wilmar Distributors",
    "Punjab Grain Suppliers",
    "Hindustan Packaging Co.",
    "Deccan Pulses Ltd.",
    "Western Spices",
    "Kerala Coconut Oils",
]
# name -> (base unit, selling rate); Sunflower Oil also sells by the Box of 12 (two units)
ITEMS = {
    "Basmati Rice 25kg": ("Bag", "1850"),
    "Sona Masoori Rice 25kg": ("Bag", "1350"),
    "Toor Dal": ("Kg", "135"),
    "Chana Dal": ("Kg", "95"),
    "Sugar 50kg": ("Bag", "2150"),
    "Sunflower Oil 1L": ("Nos", "145"),
    "Turmeric Powder 500g": ("Nos", "85"),
    "Red Chilli Powder 500g": ("Nos", "120"),
    "Wheat Atta 10kg": ("Bag", "420"),
    "Tea 1kg": ("Nos", "480"),
    "Cardamom 100g": ("Nos", "260"),  # not sold, out of stock: "not classified"
    "Saffron 1g": ("Nos", "350"),  # not sold, in stock: "no sale since the books began"
}
UNSOLD = {"Cardamom 100g", "Saffron 1g"}
OIL, BOX = "Sunflower Oil 1L", 12
SALESMEN = ["Ravi", "Priya", "Arjun"]
# predefined group -> parent (None: under Primary)
GROUPS = {
    "Current Assets": None,
    "Current Liabilities": None,
    "Capital Account": None,
    "Sales Accounts": None,
    "Purchase Accounts": None,
    "Direct Expenses": None,
    "Indirect Expenses": None,
    "Sundry Debtors": "Current Assets",
    "Cash-in-Hand": "Current Assets",
    "Bank Accounts": "Current Assets",
    "Sundry Creditors": "Current Liabilities",
    "Duties & Taxes": "Current Liabilities",
}
LEDGERS = {
    **{c: "Sundry Debtors" for c in CUSTOMERS},
    **{s: "Sundry Creditors" for s in SUPPLIERS},
    "Sales - Retail": "Sales Accounts",
    "Sales - Wholesale": "Sales Accounts",
    "Purchase - Goods": "Purchase Accounts",
    "Output GST": "Duties & Taxes",
    "Input GST": "Duties & Taxes",
    "Cash": "Cash-in-Hand",
    "HDFC Bank": "Bank Accounts",
    "Capital - R. Sharma": "Capital Account",
    "Rent": "Indirect Expenses",
    "Salaries": "Indirect Expenses",
    "Electricity": "Indirect Expenses",
    "Freight Inward": "Direct Expenses",
}
TYPES = ["Sales", "Purchase", "Receipt", "Payment", "Contra", "Journal", "Credit Note"]
CENTRES = ["Head Office", "Godown"]


def money(value: Decimal) -> Decimal:
    return value.quantize(P, ROUND_HALF_UP)


def dr(amount: Decimal) -> Any:
    return normalize.to_amount(f"-{amount}", True)


def cr(amount: Decimal) -> Any:
    return normalize.to_amount(str(amount), False)


def guid(kind: str, name: str) -> str:
    return f"demo-{kind}-{uuid.uuid5(uuid.NAMESPACE_URL, name)}"


@dataclass
class Books:
    """What the generator wrote, for the summary and the test."""

    sales_credits: Decimal = Decimal(0)  # Σ sales-ledger credits on ACTIVE sales
    vouchers: list[VoucherRecord] = field(default_factory=list)
    sold: dict[str, Decimal] = field(default_factory=lambda: defaultdict(Decimal))  # base units
    bought: dict[str, Decimal] = field(default_factory=lambda: defaultdict(Decimal))


class Generator:
    def __init__(self, today: date, seed: int = SEED) -> None:
        self.today = today
        self.start = today - timedelta(days=DAYS)
        self.books_from = date(self.start.year - (self.start.month < 4), 4, 1)
        self.rng = random.Random(seed)
        self.alter = 0
        self.books = Books()

    def next_alter(self) -> int:
        self.alter += 1
        return self.alter

    def day(self, lo: date, hi: date) -> date:
        return lo + timedelta(days=self.rng.randint(0, max((hi - lo).days, 0)))

    # --- masters --------------------------------------------------------------------------

    def company(self) -> list[Any]:
        return [
            CompanyRecord(
                guid=COMPANY_GUID,
                alter_id=0,
                name="Sharma Trading Co.",
                books_from=self.books_from,
                financial_year_start=self.books_from,
            )
        ]

    def groups(self) -> list[Any]:
        return [
            GroupRecord(
                guid=guid("group", name),
                alter_id=self.next_alter(),
                name=name,
                reserved_name=name,
                parent_guid=guid("group", parent) if parent else None,
                parent_name=parent,
            )
            for name, parent in GROUPS.items()
        ]

    def voucher_types(self) -> list[Any]:
        return [
            VoucherTypeRecord(
                guid=guid("vtype", t), alter_id=self.next_alter(), name=t, reserved_name=t
            )
            for t in TYPES
        ]

    def ledgers(self) -> list[Any]:
        before = self.books_from
        bills = {  # bills outstanding when the books began: overdue by now
            "Mehta Electricals": ("OB/101", Decimal(35000), before - timedelta(days=20)),
            "Gupta Kirana Stores": ("OB/102", Decimal(18000), before - timedelta(days=5)),
        }
        openings = {
            "HDFC Bank": dr(Decimal(500000)),
            "Cash": dr(Decimal(50000)),
            "Capital - R. Sharma": cr(Decimal(603000)),
            **{name: dr(amount) for name, (_, amount, _) in bills.items()},
        }
        records = []
        for name, group in LEDGERS.items():
            bill = bills.get(name)
            records.append(
                LedgerRecord(
                    guid=guid("ledger", name),
                    alter_id=self.next_alter(),
                    name=name,
                    parent_group_guid=guid("group", group),
                    parent_group_name=group,
                    is_bill_wise=group in ("Sundry Debtors", "Sundry Creditors"),
                    opening_balance=openings.get(name, cr(Decimal(0))),
                    opening_bills=[
                        OpeningBill(
                            reference_name=bill[0],
                            bill_date=bill[2],
                            due_date=bill[2] + timedelta(days=30),
                            amount=dr(bill[1]),
                        )
                    ]
                    if bill
                    else [],
                )
            )
        return records

    def cost_centres(self) -> list[Any]:
        return [
            CostCentreRecord(guid=guid("centre", c), alter_id=self.next_alter(), name=c)
            for c in CENTRES
        ]

    def stock_items(self) -> list[Any]:
        return [
            StockItemRecord(
                guid=guid("item", name),
                alter_id=self.next_alter(),
                name=name,
                base_unit=unit,
                alternate_unit="Box" if name == OIL else None,
                conversion=Decimal(BOX) if name == OIL else None,
                opening_quantity=Decimal(0) if name == "Cardamom 100g" else Decimal(400),
            )
            for name, (unit, _) in ITEMS.items()
        ]

    def snapshots(self) -> list[Any]:
        found = []
        for name, (unit, _) in ITEMS.items():
            opening = Decimal(0) if name == "Cardamom 100g" else Decimal(400)
            closing = opening + self.books.bought[name] - self.books.sold[name]
            found.append(
                StockSnapshotRecord(
                    stock_item_guid=guid("item", name),
                    as_of_date=self.today,
                    closing_quantity=max(closing, Decimal(0)),
                    unit=unit,
                )
            )
        return found

    # --- vouchers -------------------------------------------------------------------------

    def _voucher(
        self,
        vtype: str,
        when: date,
        number: str | None,
        entries: list[tuple[str, Any, list[Any], list[Any]]],
        items: list[Any] | None = None,
        **kw: Any,
    ) -> VoucherRecord:
        record = VoucherRecord(
            guid=guid("voucher", f"{vtype}/{number}/{len(self.books.vouchers)}"),
            alter_id=self.next_alter(),
            voucher_number=number,
            voucher_type_guid=guid("vtype", vtype),
            voucher_type_name=vtype,
            voucher_date=when,
            entries=[
                LedgerEntry(
                    ledger_guid=guid("ledger", ledger),
                    ledger_name=ledger,
                    line_sequence=n,
                    amount=amount,
                    bill_allocations=bills,
                    cost_centre_allocations=centres,
                )
                for n, (ledger, amount, bills, centres) in enumerate(entries, 1)
            ],
            items=items or [],
            **kw,
        )
        self.books.vouchers.append(record)
        return record

    @staticmethod
    def _bill(
        kind: AllocationType, raw: str, ref: str, amount: Any, due: date | None = None
    ) -> Any:
        return BillAllocation(
            reference_name=ref,
            allocation_type_raw=raw,
            allocation_type=kind,
            due_date=due,
            amount=amount,
        )

    def _lines(
        self, sellable: list[str], buying: bool
    ) -> tuple[list[Any], Decimal, dict[str, Decimal]]:
        lines: list[Any] = []
        net = Decimal(0)
        units: dict[str, Decimal] = {}
        for n, name in enumerate(self.rng.sample(sellable, self.rng.randint(1, 3)), 1):
            unit, rate = ITEMS[name]
            price = money(Decimal(rate) * (Decimal("0.85") if buying else 1))
            qty = Decimal(self.rng.randint(2, 20))
            if name == OIL and not buying and self.rng.random() < 0.5:  # sold by the Box too
                unit, price, base = "Box", price * BOX, qty * BOX
            else:
                base = qty
            amount = money(qty * price)
            lines.append(
                InventoryEntry(
                    stock_item_guid=guid("item", name),
                    stock_item_name=name,
                    line_sequence=n,
                    quantity=qty,
                    unit=unit,
                    rate=price,
                    amount=dr(amount) if buying else cr(amount),
                )
            )
            net += amount
            units[name] = units.get(name, Decimal(0)) + base
        return lines, net, units

    def trade(self) -> None:
        rng, today = self.rng, self.today
        sellable = [i for i in ITEMS if i not in UNSOLD]
        unpaid: list[tuple[str, str, date, Decimal]] = []  # (party, ref, date, gross)

        for n, when in enumerate(sorted(self.day(self.start, today) for _ in range(150)), 1):
            ref = f"SI/{n:03d}"
            cash = rng.random() < 0.15
            service = n % 30 == 0  # delivery charges only: no inventory lines
            lines: list[Any]
            units: dict[str, Decimal]
            if service:
                lines, net, units = [], Decimal(rng.randint(5, 25) * 100), {}
            else:
                lines, net, units = self._lines(sellable, buying=False)
            tax = money(net * GST)
            gross = net + tax
            party = "Cash" if cash else rng.choice(CUSTOMERS)
            sales_ledger = "Sales - Wholesale" if net > 20000 else "Sales - Retail"
            bills = (
                []
                if cash
                else [
                    self._bill(
                        AllocationType.NEW_REF, "New Ref", ref, dr(gross), when + timedelta(30)
                    )
                ]
            )
            fields: dict[str, Any] = {}
            if rng.random() < 0.6:
                fields["salesman"] = rng.choice(SALESMEN)
            self._voucher(
                "Sales",
                when,
                ref,
                [
                    (party, dr(gross), bills, []),
                    (sales_ledger, cr(net), [], []),
                    ("Output GST", cr(tax), [], []),
                ],
                lines,
                custom_fields=fields,
                narration="Delivery charges" if service else None,
            )
            self.books.sales_credits += net
            for name, qty in units.items():
                self.books.sold[name] += qty
            if not cash:
                unpaid.append((party, ref, when, gross))

        # receipts: older bills are mostly paid, recent ones mostly not; some in part
        for party, ref, when, gross in unpaid:
            age = (today - when).days
            if rng.random() >= (0.85 if age > 60 else 0.6 if age > 30 else 0.3):
                continue
            paid = money(gross / 2) if rng.random() < 0.1 else gross
            on = min(when + timedelta(days=rng.randint(7, 50)), today)
            self._voucher(
                "Receipt",
                on,
                f"RC/{ref}",
                [
                    ("HDFC Bank", dr(paid), [], []),
                    (
                        party,
                        cr(paid),
                        [self._bill(AllocationType.AGST_REF, "Agst Ref", ref, cr(paid))],
                        [],
                    ),
                ],
            )
        advance = Decimal(10000)
        self._voucher(
            "Receipt",
            today - timedelta(days=12),
            "RC/ADV/1",
            [
                ("HDFC Bank", dr(advance), [], []),
                (
                    "Royal Bakers",
                    cr(advance),
                    [self._bill(AllocationType.ADVANCE, "Advance", "ADV/1", cr(advance))],
                    [],
                ),
            ],
        )

        # purchases and their payments
        for n, when in enumerate(sorted(self.day(self.start, today) for _ in range(40)), 1):
            ref = f"PI/{n:03d}"
            lines, net, units = self._lines(sellable, buying=True)
            tax = money(net * GST)
            gross = net + tax
            supplier = rng.choice(SUPPLIERS)
            self._voucher(
                "Purchase",
                when,
                ref,
                [
                    ("Purchase - Goods", dr(net), [], []),
                    ("Input GST", dr(tax), [], []),
                    (
                        supplier,
                        cr(gross),
                        [
                            self._bill(
                                AllocationType.NEW_REF,
                                "New Ref",
                                ref,
                                cr(gross),
                                when + timedelta(45),
                            )
                        ],
                        [],
                    ),
                ],
                lines,
            )
            for name, qty in units.items():
                self.books.bought[name] += qty
            if rng.random() < (0.9 if (today - when).days > 45 else 0.4):
                on = min(when + timedelta(days=rng.randint(15, 50)), today)
                self._voucher(
                    "Payment",
                    on,
                    f"PY/{ref}",
                    [
                        (
                            supplier,
                            dr(gross),
                            [self._bill(AllocationType.AGST_REF, "Agst Ref", ref, dr(gross))],
                            [],
                        ),
                        ("HDFC Bank", cr(gross), [], []),
                    ],
                )

        # monthly expenses over two cost centres, cash deposits; freight paid in cash
        month = date(self.start.year, self.start.month, 1)
        while month <= today:
            for day, ledger, total, split in (
                (1, "Salaries", Decimal(120000), (Decimal(80000), Decimal(40000))),
                (5, "Rent", Decimal(45000), (Decimal(30000), Decimal(15000))),
                (10, "Electricity", Decimal(rng.randint(70, 95) * 100), None),
            ):
                when = month.replace(day=day)
                if self.start <= when <= today:
                    centres = (
                        [
                            CostCentreAllocation(
                                cost_centre_guid=guid("centre", c),
                                cost_centre_name=c,
                                amount_absolute=a,
                            )
                            for c, a in zip(CENTRES, split, strict=True)
                        ]
                        if split
                        else []
                    )
                    self._voucher(
                        "Payment",
                        when,
                        f"EX/{ledger[:3].upper()}/{when:%m%y}",
                        [(ledger, dr(total), [], centres), ("HDFC Bank", cr(total), [], [])],
                    )
            deposit = month.replace(day=25)
            if self.start <= deposit <= today:
                amount = Decimal(25000)
                self._voucher(
                    "Contra",
                    deposit,
                    f"CT/{deposit:%m%y}",
                    [("HDFC Bank", dr(amount), [], []), ("Cash", cr(amount), [], [])],
                )
            month = (month + timedelta(days=32)).replace(day=1)
        for n in range(10):
            amount = Decimal(rng.randint(15, 40) * 100)
            godown = [
                CostCentreAllocation(
                    cost_centre_guid=guid("centre", "Godown"),
                    cost_centre_name="Godown",
                    amount_absolute=amount,
                )
            ]
            self._voucher(
                "Payment",
                self.day(self.start, today),
                f"FR/{n + 1:02d}",
                [("Freight Inward", dr(amount), [], godown), ("Cash", cr(amount), [], [])],
            )

        # a cancelled sale (never counted) and an unlinked credit note (Unclassified
        # Adjustments until the return-link gate G26 passes)
        self._voucher(
            "Sales",
            today - timedelta(days=20),
            "SI/CANCELLED",
            [
                ("Nair Brothers", dr(Decimal("10500")), [], []),
                ("Sales - Retail", cr(Decimal("10000")), [], []),
                ("Output GST", cr(Decimal("500")), [], []),
            ],
            is_cancelled=True,
        )
        self._voucher(
            "Credit Note",
            today - timedelta(days=8),
            "CN/001",
            [
                ("Sales - Retail", dr(Decimal("2000")), [], []),
                ("Output GST", dr(Decimal("100")), [], []),
                (
                    "Kaveri Foods",
                    cr(Decimal("2100")),
                    [
                        self._bill(
                            AllocationType.AGST_REF, "Agst Ref", "SI/010", cr(Decimal("2100"))
                        )
                    ],
                    [],
                ),
            ],
        )


# --- the Agent's side of the protocol ---------------------------------------------------------


async def _ok(r: httpx.Response) -> Any:
    if r.status_code >= 400:
        raise RuntimeError(f"{r.request.method} {r.request.url.path}: {r.status_code} {r.text}")
    return r.json() if r.content else None


async def load(api: httpx.AsyncClient, user: dict[str, str]) -> dict[str, Any]:
    """Create the demo company as `user` (who becomes its Owner) and sync it through the Agent
    protocol. Returns what was loaded; refuses to load it twice."""
    companies = await _ok(await api.get("/companies", headers=user))
    if any(c["name"] == COMPANY for c in companies):
        return {"already_loaded": True}
    company = await _ok(
        await api.post(
            "/companies",
            headers=user,
            json={
                "name": COMPANY,
                "financial_year_start": "2026-04-01",
                "company_timezone": "Asia/Kolkata",
            },
        )
    )
    base = f"/companies/{company['company_id']}"
    await _ok(
        await api.put(
            f"{base}/settings/custom-fields",
            headers=user,
            json={
                "mappings": [
                    {
                        "collection_type": "VOUCHER",
                        "tally_field": "TA_Salesman",
                        "field_key": "salesman",
                        "data_type": "TEXT",
                    }
                ]
            },
        )
    )
    token = (await _ok(await api.post(f"{base}/agents/register-token", headers=user)))["token"]
    registered = await _ok(
        await api.post(
            "/agent/register",
            json={
                "token": token,
                "agent_name": "Demo Agent",
                "tally_guid": COMPANY_GUID,
                "tally_company_name": "Sharma Trading Co.",
                "agent_version": "1.0.0",
                "tdl_version": TDL_VERSION,
            },
        )
    )
    agent = {"Authorization": f"Bearer {registered['credential']}"}
    await _ok(await api.post(f"{base}/sync", headers=user, json={"sync_mode": "FULL"}))
    beat = await _ok(
        await api.post(
            "/agent/heartbeat",
            headers=agent,
            json={
                "agent_version": "1.0.0",
                "tdl_version": TDL_VERSION,
                "queue_status": {"records": 0, "dead_letter_count": 0, "full": False},
                "tally_status": "OK",
                "confirmed_tally_guid": COMPANY_GUID,
            },
        )
    )
    command = beat["command"]["command_id"]
    await _ok(await api.post(f"/agent/commands/{command}/claim", headers=agent))
    await _ok(await api.post(f"/agent/commands/{command}/progress", headers=agent))  # RUNNING
    plan = await _ok(await api.post(f"/agent/commands/{command}/runs", headers=agent))
    run = plan["sync_run_id"]
    gen = Generator(date.fromisoformat(plan["as_of"]))
    gen.trade()  # vouchers first: stock snapshots follow from what was sold and bought
    collections: list[tuple[str, list[Any]]] = [
        ("COMPANY", gen.company()),
        ("GROUP", gen.groups()),
        ("VOUCHER_TYPE", gen.voucher_types()),
        ("LEDGER", gen.ledgers()),
        ("COST_CENTRE", gen.cost_centres()),
        ("STOCK_ITEM", gen.stock_items()),
        ("VOUCHER", gen.books.vouchers),
    ]
    seq = 0
    rejected = 0

    async def upload(collection: str | None, records: list[Any], window: Any = None) -> None:
        nonlocal seq, rejected
        for i in range(0, max(len(records), 1), BATCH):
            body = {
                "collection_type": collection,
                "command_id": command,
                "sync_run_id": run,
                "batch_seq": seq,
                "batch_id": str(uuid.uuid4()),
                "window": window,
                "records": [r.model_dump(mode="json") for r in records[i : i + BATCH]],
            }
            seq += 1
            result = await _ok(
                await api.post(f"/agent/commands/{command}/batches", headers=agent, json=body)
            )
            rejected += result["failed"]

    for collection, records in collections:
        await _ok(
            await api.post(
                "/agent/leases/acquire",
                headers=agent,
                json={"sync_run_id": run, "collection_type": collection},
            )
        )
        mode = plan["collections"][collection]["mode"]
        window = None
        if collection == "VOUCHER":
            window = (
                DateWindow(date_from=gen.books_from, date_to=gen.today).model_dump(mode="json")
                if mode == "FULL_ONLY"
                else {"kind": "ALTER_ID", "from_alter_id": 0, "to_alter_id": gen.alter}
            )
        elif mode != "FULL_ONLY" and collection != "COMPANY":
            window = {"kind": "ALTER_ID", "from_alter_id": 0, "to_alter_id": gen.alter}
        await upload(collection, records, window)
        if collection == "STOCK_ITEM":
            await upload(None, gen.snapshots())
        await _ok(
            await api.post(
                "/agent/leases/release",
                headers=agent,
                json={
                    "sync_run_id": run,
                    "collection_type": collection,
                    "complete": True,
                    "start_max_alter_id": gen.alter,
                },
            )
        )
    await _ok(
        await api.post(
            f"/agent/commands/{command}/runs/{run}/finish",
            headers=agent,
            json={"status": "COMPLETED"},
        )
    )
    await _ok(
        await api.post(
            f"/agent/commands/{command}/result", headers=agent, json={"status": "COMPLETED"}
        )
    )
    return {
        "already_loaded": False,
        "company_id": company["company_id"],
        "as_of": gen.today,
        "books_from": gen.books_from,
        "vouchers": len(gen.books.vouchers),
        "sales_credits": gen.books.sales_credits,
        "rejected": rejected,
    }


# --- make demo-data ---------------------------------------------------------------------------


def assert_dev_database(url: str) -> str:
    """Only a local database that is neither a test nor a benchmark database."""
    parsed = make_url(url)
    name = parsed.database or ""
    if parsed.host not in ("localhost", "127.0.0.1") or name.endswith(("_test", "_bench")):
        raise UnsafeDatabase(f"refusing to load demo data into {parsed.host}/{name}")
    return name


async def _main(app_url: str, password: str) -> dict[str, Any]:
    os.environ.update(
        ENV="dev", DATABASE_URL=app_url, JWT_SECRET="dev-only-jwt-secret-change-me-in-prod"
    )
    from app.cli import CliError, create_owner
    from app.core.db import session_factory
    from app.main import create_app

    async with session_factory()() as session:
        try:
            await create_owner(session, EMAIL, "Demo Owner", password)
            await session.commit()
        except CliError:  # already there: sign in with it
            await session.rollback()
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as api:
        r = await api.post("/auth/login", json={"email": EMAIL, "password": password})
        tokens = await _ok(r)
        return await load(api, {"Authorization": f"Bearer {tokens['access_token']}"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--migration-url", default=DEV_DB)
    parser.add_argument("--app-url", default=DEV_APP_DB)
    args = parser.parse_args(argv)
    for url in (args.migration_url, args.app_url):
        assert_dev_database(url)
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT / "backend",
        env={**os.environ, "DATABASE_MIGRATION_URL": args.migration_url},
        check=True,
    )
    password = os.environ.get("DEMO_PASSWORD", DEFAULT_PASSWORD)
    summary = asyncio.run(_main(args.app_url, password))
    if summary["already_loaded"]:
        sys.stdout.write(f"{COMPANY} is already loaded; nothing changed.\n")
    else:
        sys.stdout.write(
            f"Loaded {COMPANY}: {summary['vouchers']} vouchers from {summary['books_from']} "
            f"to {summary['as_of']} ({summary['rejected']} rejected).\n"
        )
    sys.stdout.write(f"Sign in as {EMAIL} with password {password!r}.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
