#!/usr/bin/env python3
"""Take or check a restore-drill snapshot (BKP-1.2).

`--emit` prints a snapshot of production; without it, compares the database at `--url` against
a snapshot and exits non-zero on any difference.

Row counts alone would pass a restore that brought back the right *number* of wrong rows, so the
snapshot also carries each company's latest reconciliation run and its figures - the numbers a
business would actually notice were wrong.

Deliberately stdlib + psycopg only, with no import from `app`: a recovery tool must run from a
checkout with nothing installed, while the application is down.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

# Counted tables, in dependency order so a reader can see at a glance what came back. Money
# tables first: those are the ones whose loss shows up in a figure.
TABLES = (
    "companies",
    "users",
    "user_roles",
    "groups",
    "ledgers",
    "voucher_types",
    "stock_items",
    "cost_centres",
    "vouchers",
    "voucher_entries",
    "voucher_items",
    "bill_allocations",
    "cost_centre_allocations",
    "ledger_opening_balances",
    "opening_bill_allocations",
    "stock_opening_balances",
    "stock_snapshots",
    "agents",
    "sync_runs",
    "reconciliation_runs",
    "reconciliation_results",
    "audit_logs",
)


def _connect(url: str) -> Any:
    try:
        import psycopg
    except ModuleNotFoundError:  # pragma: no cover - the tool's own environment
        sys.exit("psycopg is required: pip install 'psycopg[binary]'")
    # SQLAlchemy-style URLs are what the rest of the project uses; psycopg wants plain postgres.
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://"):
        if url.startswith(prefix):
            url = "postgresql://" + url[len(prefix) :]
    return psycopg.connect(url)


def snapshot(url: str) -> dict[str, Any]:
    with _connect(url) as connection, connection.cursor() as cursor:
        counts = {}
        for table in TABLES:
            cursor.execute(f"SELECT count(*) FROM {table}")  # noqa: S608 - a fixed list above
            row = cursor.fetchone()
            counts[table] = int(row[0]) if row else 0
        # The latest reconciliation per company, with its figures.
        cursor.execute(
            """
            SELECT r.company_id, r.sync_run_id, r.overall, res.metric,
                   coalesce(res.entity_id, ''), res.local_value, res.tally_value, res.result
            FROM reconciliation_runs r
            JOIN reconciliation_results res
              ON res.sync_run_id = r.sync_run_id AND res.company_id = r.company_id
            WHERE r.sync_run_id IN (
                SELECT DISTINCT ON (company_id) sync_run_id
                FROM reconciliation_runs ORDER BY company_id, run_at DESC
            )
            ORDER BY r.company_id, res.metric, coalesce(res.entity_id, '')
            """
        )
        reconciliation = [
            {
                "company_id": str(company),
                "sync_run_id": str(run),
                "overall": overall,
                "metric": metric,
                "entity_id": entity,
                "local": str(local),
                "tally": str(tally),
                "result": result,
            }
            for company, run, overall, metric, entity, local, tally, result in cursor.fetchall()
        ]
    return {"version": 1, "row_counts": counts, "reconciliation": reconciliation}


def _key(figure: dict[str, Any]) -> tuple[str, str, str]:
    return (figure["company_id"], figure["metric"], figure["entity_id"])


def differences(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    problems = []
    for table, count in expected["row_counts"].items():
        got = actual["row_counts"].get(table)
        if got != count:
            problems.append(f"{table}: snapshot {count}, restored {got}")
    if expected["reconciliation"] != actual["reconciliation"]:
        before = {_key(r): r for r in expected["reconciliation"]}
        after = {_key(r): r for r in actual["reconciliation"]}
        for key in sorted(before.keys() | after.keys()):
            if before.get(key) != after.get(key):
                problems.append(f"reconciliation {key}: {before.get(key)} -> {after.get(key)}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--snapshot")
    parser.add_argument("--emit", action="store_true", help="print a snapshot instead of checking")
    args = parser.parse_args(argv)

    if args.emit:
        json.dump(snapshot(args.url), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    if not args.snapshot:
        parser.error("--snapshot is required unless --emit")
    with open(args.snapshot, encoding="utf-8") as handle:
        expected = json.load(handle)
    problems = differences(expected, snapshot(args.url))
    if problems:
        sys.stderr.write("the restore does not match the snapshot:\n")
        for problem in problems:
            sys.stderr.write(f"  {problem}\n")
        return 1
    tables = len(expected["row_counts"])
    checks = len(expected["reconciliation"])
    sys.stdout.write(f"restore matches: {tables} tables, {checks} reconciliation figures\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
