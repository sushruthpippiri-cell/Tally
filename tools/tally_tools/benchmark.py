"""The SRS 17.2 benchmark dataset for timing analytics queries (P8, owner). Never in CI.

    make bench-data        # recreate tally_bench, migrate, load the seeded dataset (~2 min)
    make bench-analytics   # time every metric on it (tally_tools.bench_analytics)

The dataset is seeded and reproducible: one company with three financial years of books
(2023-04-01 to 2026-03-31), 5,000 ledgers, 10,000 stock items, 20 cost centres and 100,000
vouchers of exactly 5 entries each (500,000 entries), inventory lines on sales and credit
notes (some items also sold by the Box), bill allocations (sales and
purchase bills, notes and receipts against them), cost-centre splits on expense entries,
books-beginning openings for most balance-sheet ledgers and about 1% cancelled vouchers.
It lives in its own database, `tally_bench`; the loader refuses any other name.
"""

import argparse
import itertools
import os
import random
import subprocess
import sys
import uuid
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from sqlalchemy.engine import make_url

from app.models.defaults import PREDEFINED_GROUPS
from tally_tools.phase_report import ROOT, UnsafeDatabase, reset_database

BENCH_DB = "postgresql+psycopg://tally_owner:tally_owner_dev@localhost:5432/tally_bench"
SEED = 8
BOOKS_FROM = date(2023, 4, 1)
BOOKS_TO = date(2026, 3, 31)
VOUCHERS = 100_000
ENTRIES_PER_VOUCHER = 5
LEDGER_COUNTS = {  # 5,000 in all: name prefix -> (predefined anchor, count)
    "Customer": ("Sundry Debtors", 3000),
    "Supplier": ("Sundry Creditors", 1200),
    "Sales": ("Sales Accounts", 40),
    "Purchase": ("Purchase Accounts", 30),
    "Direct Exp": ("Direct Expenses", 100),
    "Indirect Exp": ("Indirect Expenses", 400),
    "Tax": ("Duties & Taxes", 10),
    "Cash": ("Cash-in-Hand", 5),
    "Bank": ("Bank Accounts", 15),
    "Bank OD": ("Bank OD A/c", 5),
    "Loan": ("Unsecured Loans", 30),
    "Capital": ("Capital Account", 5),
    "Fixed Asset": ("Fixed Assets", 60),
    "Advance": ("Loans & Advances (Asset)", 100),
}
# base type -> (share of vouchers, debit pools, credit pools); 5 entries per voucher
VOUCHER_MIX: dict[str, tuple[float, list[str], list[str]]] = {
    "Sales": (0.44, ["Customer"], ["Sales", "Sales", "Tax", "Tax"]),
    "POS Invoice": (0.01, ["Cash"], ["Sales", "Sales", "Tax", "Tax"]),
    "Purchase": (0.15, ["Purchase", "Purchase", "Tax", "Tax"], ["Supplier"]),
    "Receipt": (0.15, ["Bank", "Indirect Exp"], ["Customer", "Customer", "Customer"]),
    "Payment": (0.12, ["Supplier", "Supplier", "Indirect Exp", "Direct Exp"], ["Bank"]),
    "Journal": (0.06, ["Indirect Exp", "Indirect Exp", "Direct Exp"], ["Loan", "Advance"]),
    "Contra": (0.03, ["Cash", "Bank", "Bank OD"], ["Bank", "Cash"]),
    "Credit Note": (0.02, ["Sales", "Sales", "Tax", "Tax"], ["Customer"]),
    "Debit Note": (0.01, ["Supplier"], ["Purchase", "Purchase", "Tax", "Tax"]),
    "Memorandum": (0.01, ["Advance"], ["Capital", "Loan", "Loan", "Loan"]),
}
Sink = Callable[[str, tuple[Any, ...]], None]


def assert_bench_database(url: str) -> str:
    name = make_url(url).database
    if not name or not name.endswith("_bench"):
        raise UnsafeDatabase(f"refusing to load {name!r}: the name must end in '_bench'")
    return name


class _Ids:
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.alter = itertools.count(1)

    def new(self) -> uuid.UUID:
        return uuid.UUID(int=self.rng.getrandbits(128), version=4)

    def synced(self, company: uuid.UUID) -> tuple[uuid.UUID, str, int]:
        """(company_id, tally_guid, alter_id)"""
        return company, str(self.new()), next(self.alter)


def generate(sink: Sink, vouchers: int = VOUCHERS, seed: int = SEED) -> None:
    """Every row of the dataset, table by table, in foreign-key order."""
    rng = random.Random(seed)
    ids = _Ids(rng)
    company = ids.new()
    sink(
        "companies",
        (
            company,
            "bench-company",
            "Benchmark Traders",
            date(2023, 4, 1),
            "Asia/Kolkata",
            BOOKS_FROM,
        ),
    )

    anchors: dict[str, uuid.UUID] = {}
    for primary, (nature, subs) in PREDEFINED_GROUPS.items():
        pid = ids.new()
        anchors[primary] = pid
        sink(
            "groups",
            (
                pid,
                *ids.synced(company),
                "ACTIVE",
                primary,
                None,
                pid,
                pid,
                pid,
                nature,
                True,
                primary,
                "RESOLVED",
            ),
        )
        for sub in subs:
            gid = ids.new()
            anchors[sub] = gid
            sink(
                "groups",
                (
                    gid,
                    *ids.synced(company),
                    "ACTIVE",
                    sub,
                    pid,
                    gid,
                    gid,
                    pid,
                    nature,
                    True,
                    sub,
                    "RESOLVED",
                ),
            )

    ledgers: dict[str, list[uuid.UUID]] = {}
    balance_sheet: list[uuid.UUID] = []
    natures = {s: n for p, (n, subs) in PREDEFINED_GROUPS.items() for s in (p, *subs)}
    for prefix, (anchor, count) in LEDGER_COUNTS.items():
        for i in range(count):
            lid = ids.new()
            ledgers.setdefault(prefix, []).append(lid)
            sink(
                "ledgers",
                (
                    lid,
                    *ids.synced(company),
                    "ACTIVE",
                    f"{prefix} {i + 1}",
                    anchors[anchor],
                    anchors[anchor],
                    anchors[anchor],
                ),
            )
            if natures[anchor] in ("ASSET", "LIABILITY"):
                balance_sheet.append(lid)
    for lid in balance_sheet:  # openings: 97% have one, most of them zero
        if rng.random() < 0.97:
            paise = rng.choice([0, 0, 0, rng.randrange(1, 10_000_000)])
            sink(
                "ledger_opening_balances",
                (company, lid, BOOKS_FROM, Decimal(paise) / 100, rng.choice(["DEBIT", "CREDIT"])),
            )

    stock: list[uuid.UUID] = []
    for i in range(10_000):
        stock.append(ids.new())
        sink("stock_items", (stock[-1], *ids.synced(company), "ACTIVE", f"Item {i + 1}", "Nos"))
    centres = [ids.new() for _ in range(20)]
    for i, cid in enumerate(centres):
        sink("cost_centres", (cid, *ids.synced(company), "ACTIVE", f"Centre {i + 1}"))

    types: dict[str, uuid.UUID] = {}
    for name in VOUCHER_MIX:
        tid = ids.new()
        types[name] = tid
        base = {"POS Invoice": "SALES", "Memorandum": "OTHER"}.get(
            name, name.upper().replace(" ", "_")
        )
        parent = types["Sales"] if name == "POS Invoice" else None
        sink(
            "voucher_types",
            (
                tid,
                *ids.synced(company),
                "ACTIVE",
                name,
                parent,
                None if parent else name,
                base,
                "RESOLVED",
            ),
        )

    names, weights = list(VOUCHER_MIX), [share for share, _, _ in VOUCHER_MIX.values()]
    days = (BOOKS_TO - BOOKS_FROM).days + 1
    entry_ids = itertools.count(1)
    bills: dict[str, list[tuple[uuid.UUID, str]]] = {"Sales": [], "Purchase": []}
    parties = frozenset(ledgers["Customer"] + ledgers["Supplier"])
    expense = frozenset(ledgers["Direct Exp"] + ledgers["Indirect Exp"])
    for n in range(vouchers):
        kind = rng.choices(names, weights)[0]
        vid = ids.new()
        status = "CANCELLED" if rng.random() < 0.01 else "ACTIVE"
        day = BOOKS_FROM + timedelta(days=rng.randrange(days))
        sink("vouchers", (vid, *ids.synced(company), status, f"V{n + 1}", types[kind], day))
        _, debit_pools, credit_pools = VOUCHER_MIX[kind]
        debits = [rng.randrange(100, 5_000_000) for _ in debit_pools]
        total = sum(debits)
        cuts = (
            sorted(rng.sample(range(1, total), len(credit_pools) - 1))
            if len(credit_pools) > 1
            else []
        )
        credits = [b - a for a, b in itertools.pairwise([0, *cuts, total])]
        lines = [
            (rng.choice(ledgers[p]), "DEBIT", a) for p, a in zip(debit_pools, debits, strict=True)
        ]
        lines += [
            (rng.choice(ledgers[p]), "CREDIT", a)
            for p, a in zip(credit_pools, credits, strict=True)
        ]
        for seq, (lid, direction, paise) in enumerate(lines):
            eid = next(entry_ids)
            amount = Decimal(paise) / 100
            signed = amount if direction == "DEBIT" else -amount
            raw = str(-amount if direction == "DEBIT" else amount)
            sink(
                "voucher_entries",
                (eid, company, vid, lid, seq, raw, direction == "DEBIT", amount, signed, direction),
            )
            if lid in parties:
                _bill(sink, rng, company, kind, n, eid, lid, direction, amount, bills)
            if lid in expense and rng.random() < 0.5:
                _split(sink, rng, company, eid, amount, centres)
        if kind in ("Sales", "POS Invoice", "Credit Note"):
            pools = zip([*debit_pools, *credit_pools], [*debits, *credits], strict=True)
            goods = sum(a for pool, a in pools if pool == "Sales")
            _items(sink, rng, company, vid, goods, stock)


def _items(
    sink: Sink,
    rng: random.Random,
    company: uuid.UUID,
    vid: uuid.UUID,
    goods: int,
    stock: list[uuid.UUID],
) -> None:
    """1-3 inventory lines worth 85-100% of the voucher's sales-ledger amount (the rest is
    the product difference); the first 500 items are sometimes sold by the Box."""
    worth = goods * rng.randrange(85, 101) // 100
    count = rng.randint(1, 3)
    cuts = sorted(rng.sample(range(1, worth), count - 1)) if worth > count else []
    for part in (b - a for a, b in itertools.pairwise([0, *cuts, worth])):
        item = rng.randrange(len(stock))
        unit = "Box" if item < 500 and rng.random() < 0.5 else "Nos"
        sink(
            "voucher_items",
            (company, vid, stock[item], Decimal(rng.randint(1, 50)), unit, Decimal(part) / 100),
        )


def _bill(
    sink: Sink,
    rng: random.Random,
    company: uuid.UUID,
    kind: str,
    n: int,
    eid: int,
    lid: uuid.UUID,
    direction: str,
    amount: Decimal,
    bills: dict[str, list[tuple[uuid.UUID, str]]],
) -> None:
    """A party line: a new bill on a sale or purchase; on a note, receipt or payment a
    reference to a recent bill of the same party (80%) or to an unknown one."""
    if kind in ("Sales", "Purchase"):
        ref = f"{kind[0]}-{n + 1}"
        bills[kind].append((lid, ref))
        sink("bill_allocations", (company, eid, lid, "New Ref", "NEW_REF", ref, amount, direction))
        return
    origin = bills["Sales" if kind in ("Credit Note", "Receipt") else "Purchase"]
    own = [ref for owner, ref in origin[-500:] if owner == lid]
    ref = own[-1] if own and rng.random() < 0.8 else f"UNKNOWN-{n + 1}"
    sink("bill_allocations", (company, eid, lid, "Agst Ref", "AGST_REF", ref, amount, direction))


def _split(
    sink: Sink,
    rng: random.Random,
    company: uuid.UUID,
    eid: int,
    amount: Decimal,
    centres: list[uuid.UUID],
) -> None:
    """An expense line allocated to one or two cost centres, sometimes leaving a remainder."""
    first = (amount * Decimal(rng.randrange(30, 101)) / 100).quantize(Decimal("0.01"))
    sink("cost_centre_allocations", (company, eid, rng.choice(centres), first))
    if first < amount and rng.random() < 0.5:
        sink("cost_centre_allocations", (company, eid, rng.choice(centres), amount - first))


COLUMNS = {
    "companies": "company_id, tally_guid, name, financial_year_start, company_timezone, books_from",
    "groups": "group_id, company_id, tally_guid, alter_id, status, name, parent_group_id, "
    "predefined_group_id, classification_group_id, primary_group_id, nature, is_predefined, "
    "reserved_name, resolution_status",
    "ledgers": "ledger_id, company_id, tally_guid, alter_id, status, name, group_id, "
    "predefined_group_id, classification_group_id",
    "ledger_opening_balances": "company_id, ledger_id, financial_year_start, amount_absolute, "
    "accounting_direction",
    "stock_items": "stock_item_id, company_id, tally_guid, alter_id, status, name, base_unit",
    "cost_centres": "cost_centre_id, company_id, tally_guid, alter_id, status, name",
    "voucher_types": "voucher_type_id, company_id, tally_guid, alter_id, status, name, "
    "parent_voucher_type_id, reserved_name, base_voucher_type, resolution_status",
    "vouchers": "voucher_id, company_id, tally_guid, alter_id, status, voucher_number, "
    "voucher_type_id, voucher_date",
    "voucher_entries": "voucher_entry_id, company_id, voucher_id, ledger_id, line_sequence, "
    "amount_raw, is_debit, amount_absolute, amount_signed, accounting_direction",
    "bill_allocations": "company_id, voucher_entry_id, ledger_id, allocation_type_raw, "
    "allocation_type, reference_name, amount_absolute, accounting_direction",
    "cost_centre_allocations": "company_id, voucher_entry_id, cost_centre_id, amount_absolute",
    "voucher_items": "company_id, voucher_id, stock_item_id, quantity, unit, amount",
}


def _buffered() -> tuple[dict[str, list[tuple[Any, ...]]], Sink]:
    tables: dict[str, list[tuple[Any, ...]]] = {t: [] for t in COLUMNS}
    return tables, lambda table, row: tables[table].append(row)


def load(url: str = BENCH_DB, vouchers: int = VOUCHERS) -> dict[str, int]:
    """Recreate, migrate and fill the benchmark database; the row count of each table."""
    reset_database(url, guard=assert_bench_database)
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=ROOT / "backend",
        check=True,
        env={**os.environ, "DATABASE_MIGRATION_URL": url},
    )
    tables, sink = _buffered()
    generate(sink, vouchers=vouchers)
    dsn = make_url(url).render_as_string(hide_password=False).replace("+psycopg", "")
    with psycopg.connect(dsn) as conn:
        for table, rows in tables.items():
            with conn.cursor().copy(f"COPY {table} ({COLUMNS[table]}) FROM STDIN") as copy:
                for row in rows:
                    copy.write_row(row)
        conn.execute(
            "SELECT setval('voucher_entries_voucher_entry_id_seq', "
            "(SELECT max(voucher_entry_id) FROM voucher_entries))"
        )
        conn.commit()
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("VACUUM ANALYZE")
    return {t: len(r) for t, r in tables.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tally_tools.benchmark")
    parser.add_argument("--url", default=BENCH_DB)
    # The SRS 17.2 size by default; a smaller count is for trying the loader out, never for a
    # figure - a benchmark on 1,000 vouchers measures nothing.
    parser.add_argument("--vouchers", type=int, default=VOUCHERS)
    args = parser.parse_args(argv)
    for table, n in load(args.url, args.vouchers).items():
        sys.stdout.write(f"{table:<26} {n:>9,}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
