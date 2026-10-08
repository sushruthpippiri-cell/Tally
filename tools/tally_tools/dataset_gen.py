"""One benchmark dataset, in both the forms the system consumes (P16.5, SRS 17.2).

`benchmark.py` seeds the **database** for the analytics benchmark. This module emits the same
dataset as the **Tally XML** the Agent pulls, so a full-sync figure and a dashboard figure
describe the same books rather than two different ones, and writes the manifest that says which
dataset a figure was measured on - the identifier PERF-VAL-1 requires.

    uv run python -m tally_tools.dataset_gen --out dataset           # 100,000 vouchers
    uv run python -m tally_tools.dataset_gen --out /tmp/d --vouchers 40

Both forms come from `benchmark.generate()`, which is already pure over a `Sink`, so neither can
drift from the other. The generator is not rewritten: `make bench-data` must keep producing the
same rows or the figures it has already produced stop being comparable.

Three places where the database's shape and Tally's differ, and what this does about each:

- **Sign.** `amount_signed` is positive on a debit; Tally's `AMOUNT` is negative on one
  (`DEBIT_IS_NEGATIVE`). `benchmark.py` already stores Tally's sign in `amount_raw`, so the XML
  uses that column and nothing has to be re-derived.
- **ALTERID.** Tally keeps masters and vouchers on separate sequences (G33) and reports the high
  water mark of each; `benchmark.py` has one counter. The XML therefore renumbers into two
  sequences. Nothing reads `alter_id` to compute a figure, so the two forms differ there by
  design, and the manifest says so.
- **Line sequence.** The database rows are 0-based; the parser numbers `LEDGERENTRY` elements
  1-based as it reads them. The XML carries no sequence at all - element order is the sequence -
  so this resolves itself, and the round-trip test compares order rather than the number.

**Known gap: no closing reports.** `TA_StockClosing` and `TA_LedgerClosing` are not emitted, so
the mock answers them from its own 12-voucher sample and the reconciliation run that follows a
sync has nothing real to compare against (it logs a `record_parse_failed` for the sample's
STOCK_CLOSING, which carries no ASOFDATE). That does not affect the sync timings this dataset
exists for - reconciliation runs after the sync completes - but it does mean a benchmark cannot
yet exercise REC-1.x at size. Emitting them needs the closing balances derived from the same
rows, which is a follow-up rather than a line of XML.
"""

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from tally_contract import tally_constants as tc
from tally_tools import benchmark

# Bumped whenever the emitted shape changes. With `benchmark.SEED` this is the dataset
# identifier: a figure quoting (seed, version) names the data it was measured on exactly.
DATASET_VERSION = 1

MANIFEST = "manifest.json"


def rows(vouchers: int = benchmark.VOUCHERS, seed: int = benchmark.SEED) -> dict[str, list[Any]]:
    """Every row of the dataset, by table, from the one generator."""
    tables, sink = benchmark._buffered()
    benchmark.generate(sink, vouchers=vouchers, seed=seed)
    return tables


def _records(tables: dict[str, list[Any]], table: str) -> Iterator[dict[str, Any]]:
    """A table's rows as dicts, named by `benchmark.COLUMNS`."""
    names = [c.strip() for c in benchmark.COLUMNS[table].split(",")]
    for row in tables[table]:
        yield dict(zip(names, row, strict=True))


def _by(tables: dict[str, list[Any]], table: str, key: str) -> dict[Any, list[dict[str, Any]]]:
    grouped: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for record in _records(tables, table):
        grouped[record[key]].append(record)
    return grouped


def _day(value: date) -> str:
    return value.strftime(tc.RESPONSE_DATE_FORMAT)


def _parent(name: str | None) -> str:
    """Tally's top-level parent, which the parser maps back to "no parent" (GATE-G12)."""
    return name or "Primary"


# --- the XML, one record per line so a human can grep the file ---------------------------
#
# Each record is a single unbroken string with no whitespace between elements. That is not
# tidiness: mock_tally's reconciliation reads LEDGERNAME/LEDGERGUID/AMOUNT off the raw text with
# a regex that allows nothing between them, and finds a cancelled voucher by the substring
# "<ISCANCELLED>Yes". Pretty-printing this file would silently empty the reconciliation report.


def _company_xml(tables: dict[str, list[Any]], master_high: int, voucher_high: int) -> str:
    company = next(_records(tables, "companies"))
    return (
        f"<COMPANY><GUID>{company['tally_guid']}</GUID><ALTERID>1</ALTERID>"
        f"<NAME>{escape(company['name'])}</NAME>"
        f"<BOOKSFROM>{_day(company['books_from'])}</BOOKSFROM>"
        f"<FYSTART>{_day(company['financial_year_start'])}</FYSTART>"
        f"<LASTMASTERALTERID>{master_high}</LASTMASTERALTERID>"
        f"<LASTVOUCHERALTERID>{voucher_high}</LASTVOUCHERALTERID></COMPANY>"
    )


def _group_xml(record: dict[str, Any], parents: dict[Any, dict[str, Any]], alter: int) -> str:
    parent = parents.get(record["parent_group_id"])
    return (
        f"<GROUP><GUID>{record['tally_guid']}</GUID><ALTERID>{alter}</ALTERID>"
        f"<NAME>{escape(record['name'])}</NAME>"
        f"<PARENT>{escape(_parent(parent['name'] if parent else None))}</PARENT>"
        f"<PARENTGUID>{parent['tally_guid'] if parent else ''}</PARENTGUID>"
        f"<RESERVEDNAME>{escape(record['reserved_name'] or '')}</RESERVEDNAME>"
        f"<ISREVENUE>{tc.YES if record['nature'] in ('INCOME', 'EXPENSE') else tc.NO}</ISREVENUE>"
        f"<ISDEEMEDPOSITIVE>{tc.YES if record['nature'] == 'ASSET' else tc.NO}"
        "</ISDEEMEDPOSITIVE></GROUP>"
    )


def _ledger_xml(
    record: dict[str, Any],
    groups: dict[Any, dict[str, Any]],
    opening: dict[str, Any] | None,
    alter: int,
) -> str:
    group = groups[record["group_id"]]
    # An absent OPENINGBALANCE means "unavailable" and a blank one means zero, so a ledger with
    # no opening row must omit the element rather than send an empty one.
    if opening is None:
        balance = ""
    else:
        amount = opening["amount_absolute"]
        signed = -amount if opening["accounting_direction"] == "DEBIT" else amount
        balance = f"<OPENINGBALANCE>{signed}</OPENINGBALANCE>"
    return (
        f"<LEDGER><GUID>{record['tally_guid']}</GUID><ALTERID>{alter}</ALTERID>"
        f"<NAME>{escape(record['name'])}</NAME>"
        f"<PARENT>{escape(group['name'])}</PARENT>"
        f"<PARENTGUID>{group['tally_guid']}</PARENTGUID>"
        f"{balance}</LEDGER>"
    )


def _voucher_type_xml(record: dict[str, Any], types: dict[Any, dict[str, Any]], alter: int) -> str:
    parent = types.get(record["parent_voucher_type_id"])
    name = parent["name"] if parent else record["reserved_name"]
    return (
        f"<VOUCHER_TYPE><GUID>{record['tally_guid']}</GUID><ALTERID>{alter}</ALTERID>"
        f"<NAME>{escape(record['name'])}</NAME>"
        f"<PARENT>{escape(name or '')}</PARENT>"
        f"<PARENTGUID>{parent['tally_guid'] if parent else ''}</PARENTGUID>"
        f"<RESERVEDNAME>{escape(record['reserved_name'] or '')}</RESERVEDNAME></VOUCHER_TYPE>"
    )


def _stock_item_xml(record: dict[str, Any], alter: int) -> str:
    return (
        f"<STOCK_ITEM><GUID>{record['tally_guid']}</GUID><ALTERID>{alter}</ALTERID>"
        f"<NAME>{escape(record['name'])}</NAME>"
        f"<BASEUNIT>{escape(record['base_unit'])}</BASEUNIT></STOCK_ITEM>"
    )


def _cost_centre_xml(record: dict[str, Any], alter: int) -> str:
    return (
        f"<COST_CENTRE><GUID>{record['tally_guid']}</GUID><ALTERID>{alter}</ALTERID>"
        f"<NAME>{escape(record['name'])}</NAME><PARENT>Primary</PARENT></COST_CENTRE>"
    )


def _voucher_xml(
    voucher: dict[str, Any],
    entries: list[dict[str, Any]],
    bills: dict[Any, list[dict[str, Any]]],
    splits: dict[Any, list[dict[str, Any]]],
    items: list[dict[str, Any]],
    ledgers: dict[Any, dict[str, Any]],
    centres: dict[Any, dict[str, Any]],
    stock: dict[Any, dict[str, Any]],
    types: dict[Any, dict[str, Any]],
    alter: int,
) -> str:
    kind = types[voucher["voucher_type_id"]]
    parts = [
        f"<VOUCHER><GUID>{voucher['tally_guid']}</GUID><ALTERID>{alter}</ALTERID>",
        f"<VOUCHERNUMBER>{escape(voucher['voucher_number'])}</VOUCHERNUMBER>",
        f"<VOUCHERTYPENAME>{escape(kind['name'])}</VOUCHERTYPENAME>",
        f"<VOUCHERTYPEGUID>{kind['tally_guid']}</VOUCHERTYPEGUID>",
        f"<DATE>{_day(voucher['voucher_date'])}</DATE>",
        f"<ISCANCELLED>{tc.YES if voucher['status'] == 'CANCELLED' else tc.NO}</ISCANCELLED>",
    ]
    # LEDGERENTRY and INVENTORYENTRY must be DIRECT children of VOUCHER: the builder uses
    # findall for those two and iter() for the allocations beneath them.
    for entry in sorted(entries, key=lambda e: e["line_sequence"]):
        ledger = ledgers[entry["ledger_id"]]
        debit = entry["accounting_direction"] == "DEBIT"
        # amount_raw already carries Tally's sign (negative on a debit), which is also what
        # ISDEEMEDPOSITIVE must agree with, or the parser rejects the voucher.
        parts.append(
            f"<LEDGERENTRY><LEDGERNAME>{escape(ledger['name'])}</LEDGERNAME>"
            f"<LEDGERGUID>{ledger['tally_guid']}</LEDGERGUID>"
            f"<AMOUNT>{entry['amount_raw']}</AMOUNT>"
            f"<ISDEEMEDPOSITIVE>{tc.YES if debit else tc.NO}</ISDEEMEDPOSITIVE>"
        )
        for bill in bills.get(entry["voucher_entry_id"], []):
            signed = -bill["amount_absolute"] if debit else bill["amount_absolute"]
            parts.append(
                f"<BILLALLOCATION><NAME>{escape(bill['reference_name'] or '')}</NAME>"
                f"<BILLTYPE>{escape(bill['allocation_type_raw'])}</BILLTYPE>"
                f"<DUEDATE></DUEDATE><AMOUNT>{signed}</AMOUNT></BILLALLOCATION>"
            )
        for split in splits.get(entry["voucher_entry_id"], []):
            centre = centres[split["cost_centre_id"]]
            signed = -split["amount_absolute"] if debit else split["amount_absolute"]
            parts.append(
                f"<COSTCENTREALLOCATION><NAME>{escape(centre['name'])}</NAME>"
                f"<COSTCENTREGUID>{centre['tally_guid']}</COSTCENTREGUID>"
                f"<AMOUNT>{signed}</AMOUNT></COSTCENTREALLOCATION>"
            )
        parts.append("</LEDGERENTRY>")
    for item in items:
        goods = stock[item["stock_item_id"]]
        parts.append(
            f"<INVENTORYENTRY><STOCKITEMNAME>{escape(goods['name'])}</STOCKITEMNAME>"
            f"<STOCKITEMGUID>{goods['tally_guid']}</STOCKITEMGUID>"
            f"<QUANTITY>{item['quantity']} {escape(item['unit'])}</QUANTITY>"
            f"<AMOUNT>{item['amount']}</AMOUNT>"
            f"<ISDEEMEDPOSITIVE>{tc.NO}</ISDEEMEDPOSITIVE></INVENTORYENTRY>"
        )
    parts.append("</VOUCHER>")
    return "".join(parts)


def _envelope(report: str, body: Iterator[str] | list[str]) -> str:
    root = report.upper()
    return f"<ENVELOPE><{root}>{''.join(body)}</{root}></ENVELOPE>"


def write_xml(directory: Path, tables: dict[str, list[Any]]) -> dict[str, int]:
    """One file per TDL report; the record count of each.

    ALTERIDs are assigned here into two sequences, masters and vouchers, the way Tally keeps
    them (G33), so the Agent's incremental windowing has something real to walk.
    """
    directory.mkdir(parents=True, exist_ok=True)
    groups = {r["group_id"]: r for r in _records(tables, "groups")}
    ledgers = {r["ledger_id"]: r for r in _records(tables, "ledgers")}
    types = {r["voucher_type_id"]: r for r in _records(tables, "voucher_types")}
    stock = {r["stock_item_id"]: r for r in _records(tables, "stock_items")}
    centres = {r["cost_centre_id"]: r for r in _records(tables, "cost_centres")}
    openings = {r["ledger_id"]: r for r in _records(tables, "ledger_opening_balances")}

    master = iter(range(2, 2 + 10_000_000))  # the company itself is ALTERID 1
    written: dict[str, int] = {}

    def emit(report: str, records: list[str]) -> None:
        (directory / f"{report}.xml").write_text(
            _envelope(report, records), encoding="utf-8", newline="\n"
        )
        written[report] = len(records)

    # Masters first, in the order the Agent syncs them, so a reader of the directory sees the
    # dependency order too.
    emit("TA_Groups", [_group_xml(r, groups, next(master)) for r in groups.values()])
    emit(
        "TA_Ledgers",
        [_ledger_xml(r, groups, openings.get(k), next(master)) for k, r in ledgers.items()],
    )
    emit("TA_VoucherTypes", [_voucher_type_xml(r, types, next(master)) for r in types.values()])
    emit("TA_StockItems", [_stock_item_xml(r, next(master)) for r in stock.values()])
    emit("TA_CostCentres", [_cost_centre_xml(r, next(master)) for r in centres.values()])
    master_high = next(master) - 1

    entries = _by(tables, "voucher_entries", "voucher_id")
    bills = _by(tables, "bill_allocations", "voucher_entry_id")
    splits = _by(tables, "cost_centre_allocations", "voucher_entry_id")
    items = _by(tables, "voucher_items", "voucher_id")
    voucher_xml: list[str] = []
    voucher_high = 0
    for alter, voucher in enumerate(_records(tables, "vouchers"), 1):
        voucher_high = alter
        voucher_xml.append(
            _voucher_xml(
                voucher,
                entries[voucher["voucher_id"]],
                bills,
                splits,
                items.get(voucher["voucher_id"], []),
                ledgers,
                centres,
                stock,
                types,
                alter,
            )
        )
    emit("TA_Vouchers", voucher_xml)
    emit("TA_Company", [_company_xml(tables, master_high, voucher_high)])
    return written


def manifest(
    tables: dict[str, list[Any]],
    written: dict[str, int],
    vouchers: int,
    seed: int,
) -> dict[str, Any]:
    """What a benchmark figure must cite to mean anything (PERF-VAL-1's dataset identifier).

    The digest covers every row of the generated data, so two runs claiming the same
    (seed, version) can be shown to have used the same books rather than assumed to have.
    """
    digest = hashlib.sha256()
    for table in benchmark.COLUMNS:
        digest.update(table.encode())
        for row in tables[table]:
            digest.update(repr(row).encode())
    company = next(_records(tables, "companies"))
    return {
        "seed": seed,
        "version": DATASET_VERSION,
        "vouchers_requested": vouchers,
        "sha256": digest.hexdigest(),
        "company": {"name": company["name"], "guid": company["tally_guid"]},
        "books": {"from": _day(company["books_from"]), "to": _day(benchmark.BOOKS_TO)},
        "database_rows": {t: len(r) for t, r in tables.items()},
        "xml_records": written,
        # The two forms deliberately disagree here; see this module's docstring.
        "alter_ids": "renumbered for XML into separate master and voucher sequences (G33)",
    }


def build(
    directory: Path, vouchers: int = benchmark.VOUCHERS, seed: int = benchmark.SEED
) -> dict[str, Any]:
    tables = rows(vouchers, seed)
    written = write_xml(directory, tables)
    meta = manifest(tables, written, vouchers, seed)
    (directory / MANIFEST).write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tally_tools.dataset_gen")
    parser.add_argument("--out", type=Path, default=Path("dataset"))
    parser.add_argument("--vouchers", type=int, default=benchmark.VOUCHERS)
    parser.add_argument("--seed", type=int, default=benchmark.SEED)
    args = parser.parse_args(argv)
    meta = build(args.out, args.vouchers, args.seed)
    for report, n in meta["xml_records"].items():
        sys.stdout.write(f"{report:<20} {n:>9,}\n")
    sys.stdout.write(f"\nseed {meta['seed']} version {meta['version']}\n")
    sys.stdout.write(f"sha256 {meta['sha256'][:16]}…\n{args.out / MANIFEST}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
