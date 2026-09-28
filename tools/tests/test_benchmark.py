"""The benchmark dataset (tally_tools.benchmark) at a small size: counts, balance, seed."""

from collections import defaultdict
from decimal import Decimal
from typing import Any

import pytest

from tally_tools.benchmark import (
    ENTRIES_PER_VOUCHER,
    LEDGER_COUNTS,
    assert_bench_database,
    generate,
)
from tally_tools.phase_report import UnsafeDatabase


def _rows(vouchers: int, seed: int = 8) -> dict[str, list[tuple[Any, ...]]]:
    tables: dict[str, list[tuple[Any, ...]]] = defaultdict(list)
    generate(lambda table, row: tables[table].append(row), vouchers=vouchers, seed=seed)
    return tables


def test_the_dataset_has_the_srs_shape_and_balanced_vouchers() -> None:
    tables = _rows(400)
    assert len(tables["ledgers"]) == sum(n for _, n in LEDGER_COUNTS.values()) == 5000
    assert len(tables["stock_items"]) == 10_000
    assert len(tables["vouchers"]) == 400
    assert len(tables["voucher_entries"]) == 400 * ENTRIES_PER_VOUCHER
    net: dict[Any, Decimal] = defaultdict(Decimal)
    for _eid, _company, voucher, *_rest, signed, _direction in tables["voucher_entries"]:
        net[voucher] += signed
    assert set(net.values()) == {Decimal(0)}
    assert tables["bill_allocations"] and tables["cost_centre_allocations"]


def test_the_same_seed_gives_the_same_rows() -> None:
    assert _rows(50) == _rows(50)
    assert _rows(50) != _rows(50, seed=9)


@pytest.mark.parametrize("name", ["tally", "tally_test", "bench"])
def test_only_a_bench_database_is_loaded(name: str) -> None:
    with pytest.raises(UnsafeDatabase):
        assert_bench_database(f"postgresql+psycopg://u:p@localhost/{name}")
    assert assert_bench_database("postgresql+psycopg://u:p@localhost/tally_bench") == "tally_bench"
