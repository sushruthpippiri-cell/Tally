"""P16.5: the generated dataset is the same books in both forms, and Tally-shaped.

The generated XML is correct exactly when the project's own parser reads the database rows back
out of it. That is the whole test: hand-checking element names would prove only that I typed what
I meant to type, while parsing proves the Agent can use it.

Small N on purpose - 40 vouchers exercises every record kind and runs in `make check`. The
100,000-voucher dataset is `make dataset`, and `test_the_full_size_dataset_is_the_srs_17_2_shape`
checks its counts without building it.
"""

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from tally_contract.enums import CollectionType
from tally_contract.parser import parse_collection, parse_info, parse_keys
from tally_tools import benchmark, dataset_gen

VOUCHERS = 40


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    directory = tmp_path_factory.mktemp("dataset")
    meta = dataset_gen.build(directory, vouchers=VOUCHERS)
    return directory, meta, dataset_gen.rows(VOUCHERS)


def _parse(directory: Path, report: str, collection: CollectionType) -> Any:
    raw = (directory / f"{report}.xml").read_bytes()
    result = parse_collection(raw, collection)
    assert result.document_error is None, result.document_error
    assert result.errors == [], result.errors[:3]
    return result.records


# --- every record kind parses, with no errors at all ------------------------------------


@pytest.mark.req("TEST-1.1")
@pytest.mark.parametrize(
    ("report", "collection"),
    [
        ("TA_Company", CollectionType.COMPANY),
        ("TA_Groups", CollectionType.GROUP),
        ("TA_Ledgers", CollectionType.LEDGER),
        ("TA_VoucherTypes", CollectionType.VOUCHER_TYPE),
        ("TA_StockItems", CollectionType.STOCK_ITEM),
        ("TA_CostCentres", CollectionType.COST_CENTRE),
        ("TA_Vouchers", CollectionType.VOUCHER),
    ],
)
def test_every_report_parses_with_no_record_errors(
    built: tuple[Path, dict[str, Any], dict[str, Any]],
    report: str,
    collection: CollectionType,
) -> None:
    directory, meta, _ = built
    records = _parse(directory, report, collection)
    assert len(records) == meta["xml_records"][report]


def test_the_counts_in_the_xml_match_the_database_rows(
    built: tuple[Path, dict[str, Any], dict[str, Any]],
) -> None:
    """The two forms are the same books: one generator, two sinks."""
    _, meta, tables = built
    for report, table in (
        ("TA_Groups", "groups"),
        ("TA_Ledgers", "ledgers"),
        ("TA_VoucherTypes", "voucher_types"),
        ("TA_StockItems", "stock_items"),
        ("TA_CostCentres", "cost_centres"),
        ("TA_Vouchers", "vouchers"),
    ):
        assert meta["xml_records"][report] == len(tables[table]), report


# --- the voucher, where the shape constraints actually bite ------------------------------


@pytest.mark.req("TEST-1.1")
def test_every_voucher_balances_and_keeps_its_children(
    built: tuple[Path, dict[str, Any], dict[str, Any]],
) -> None:
    """`normalize.check_balance` has a tolerance of exactly zero, and the parser rejects a
    voucher whose AMOUNT sign disagrees with ISDEEMEDPOSITIVE. Both would show up as a record
    error above; this checks the children survived rather than being silently dropped, which is
    what a mis-nested LEDGERENTRY would look like."""
    directory, _, tables = built
    records = _parse(directory, "TA_Vouchers", CollectionType.VOUCHER)
    by_guid = {v.guid: v for v in records}

    entries = sum(len(v.entries) for v in records)
    assert entries == len(tables["voucher_entries"])
    assert sum(len(e.bill_allocations) for v in records for e in v.entries) == len(
        tables["bill_allocations"]
    )
    assert sum(len(e.cost_centre_allocations) for v in records for e in v.entries) == len(
        tables["cost_centre_allocations"]
    )
    assert sum(len(v.items) for v in records) == len(tables["voucher_items"])

    # Entry order is the line sequence: the database rows are 0-based and the parser numbers
    # from 1 as it reads, so the check is that the ledgers line up in order.
    stored = dataset_gen._by(tables, "voucher_entries", "voucher_id")
    ledgers = {r["ledger_id"]: r["name"] for r in dataset_gen._records(tables, "ledgers")}
    for voucher in dataset_gen._records(tables, "vouchers"):
        parsed = by_guid[voucher["tally_guid"]]
        expected = [
            ledgers[e["ledger_id"]]
            for e in sorted(stored[voucher["voucher_id"]], key=lambda e: e["line_sequence"])
        ]
        assert [e.ledger_name for e in parsed.entries] == expected
        assert [e.line_sequence for e in parsed.entries] == list(range(1, len(expected) + 1))


def test_a_debit_is_negative_in_the_xml_and_positive_once_normalized(
    built: tuple[Path, dict[str, Any], dict[str, Any]],
) -> None:
    """The sign trap this module exists to get right: `amount_signed` in the database is positive
    on a debit, Tally's AMOUNT is negative on one, and `amount_raw` already holds Tally's. So the
    parser's `amount_raw` must come back byte for byte equal to the database column, and every
    normalized field must agree with it."""
    directory, _, tables = built
    records = _parse(directory, "TA_Vouchers", CollectionType.VOUCHER)
    parsed = {
        (v.guid, e.ledger_guid, e.line_sequence): e.amount for v in records for e in v.entries
    }
    assert parsed, "no entries parsed"

    vouchers = {r["voucher_id"]: r["tally_guid"] for r in dataset_gen._records(tables, "vouchers")}
    ledgers = {r["ledger_id"]: r["tally_guid"] for r in dataset_gen._records(tables, "ledgers")}
    checked = 0
    for entry in dataset_gen._records(tables, "voucher_entries"):
        # The database's own raw column already carries Tally's sign.
        assert (Decimal(entry["amount_raw"]) < 0) == entry["is_debit"]
        key = (
            vouchers[entry["voucher_id"]],
            ledgers[entry["ledger_id"]],
            entry["line_sequence"] + 1,  # the parser numbers from 1 as it reads
        )
        amount = parsed[key]
        assert Decimal(amount.amount_raw) == Decimal(entry["amount_raw"])
        assert amount.amount_absolute == entry["amount_absolute"]
        assert amount.is_debit == entry["is_debit"]
        assert amount.accounting_direction.value == entry["accounting_direction"]
        # And the one the database stores the other way round, to pin the difference.
        assert amount.amount_signed == entry["amount_signed"]
        checked += 1
    assert checked == len(tables["voucher_entries"])


def test_a_cancelled_voucher_says_so_and_the_rest_do_not(
    built: tuple[Path, dict[str, Any], dict[str, Any]],
) -> None:
    directory, _, tables = built
    records = _parse(directory, "TA_Vouchers", CollectionType.VOUCHER)
    cancelled = {v.guid for v in records if v.is_cancelled}
    expected = {
        r["tally_guid"]
        for r in dataset_gen._records(tables, "vouchers")
        if r["status"] == "CANCELLED"
    }
    assert cancelled == expected


# --- the key-only form the Agent uses for deletion detection ----------------------------


@pytest.mark.req("TEST-1.1")
def test_the_key_list_form_parses_from_the_same_file(
    built: tuple[Path, dict[str, Any], dict[str, Any]],
) -> None:
    """The mock derives `TA_VouchersKeys` from the `TA_Vouchers` rows, so the keys come from the
    same records the full pull serves - there is no second file to fall out of step."""
    directory, _, _ = built
    records = _parse(directory, "TA_Vouchers", CollectionType.VOUCHER)
    keys = "".join(
        f"<KEY><GUID>{v.guid}</GUID><ALTERID>{v.alter_id}</ALTERID></KEY>" for v in records
    )
    result = parse_keys(f"<ENVELOPE><TA_VOUCHERSKEYS>{keys}</TA_VOUCHERSKEYS></ENVELOPE>".encode())
    assert result.document_error is None and result.errors == []
    assert {k.guid for k in result.records} == {v.guid for v in records}


# --- the manifest, which is what a figure cites ------------------------------------------


def test_the_manifest_identifies_the_dataset(
    built: tuple[Path, dict[str, Any], dict[str, Any]],
) -> None:
    _, meta, tables = built
    assert meta["seed"] == benchmark.SEED
    assert meta["version"] == dataset_gen.DATASET_VERSION
    assert len(meta["sha256"]) == 64
    assert meta["database_rows"]["vouchers"] == VOUCHERS
    assert meta["company"]["guid"]


def test_the_same_seed_gives_the_same_dataset(tmp_path: Path) -> None:
    """Deterministic, or a figure cannot be reproduced and the digest is theatre."""
    first = dataset_gen.build(tmp_path / "a", vouchers=12)
    second = dataset_gen.build(tmp_path / "b", vouchers=12)
    assert first["sha256"] == second["sha256"]
    assert (tmp_path / "a/TA_Vouchers.xml").read_bytes() == (
        tmp_path / "b/TA_Vouchers.xml"
    ).read_bytes()


def test_a_different_seed_gives_a_different_dataset(tmp_path: Path) -> None:
    other = dataset_gen.build(tmp_path / "c", vouchers=12, seed=benchmark.SEED + 1)
    same = dataset_gen.build(tmp_path / "d", vouchers=12)
    assert other["sha256"] != same["sha256"]


def test_the_full_size_dataset_is_the_srs_17_2_shape() -> None:
    """100,000 vouchers, 500,000 entries, 5,000 ledgers, 10,000 stock items - checked against the
    generator's own constants rather than by building it, which takes minutes."""
    assert benchmark.VOUCHERS == 100_000
    assert benchmark.VOUCHERS * benchmark.ENTRIES_PER_VOUCHER == 500_000
    assert sum(count for _, count in benchmark.LEDGER_COUNTS.values()) == 5_000


# --- the XML must stay on one line per record (mock_tally reads it with regexes) ---------


@pytest.mark.req("TEST-1.1")
def test_no_record_is_pretty_printed(
    built: tuple[Path, dict[str, Any], dict[str, Any]],
) -> None:
    """mock_tally's reconciliation reads LEDGERNAME/LEDGERGUID/AMOUNT off the raw text with a
    regex that allows nothing between them, and finds a cancelled voucher by a substring.
    Whitespace between elements would empty the reconciliation report silently."""
    directory, _, _ = built
    for path in directory.glob("TA_*.xml"):
        text = path.read_text(encoding="utf-8")
        assert "> <" not in text and ">\n<" not in text, path.name
        assert ">\t<" not in text, path.name


def test_no_generated_document_looks_like_a_tally_error(
    built: tuple[Path, dict[str, Any], dict[str, Any]],
) -> None:
    """`tally_error()` rejects a whole document containing LINEERROR or the not-loaded markers,
    and `doctype_error()` one declaring a DTD. A generated name could in principle contain one."""
    directory, _, _ = built
    for path in directory.glob("TA_*.xml"):
        text = path.read_text(encoding="utf-8")
        assert "LINEERROR" not in text and "<!DOCTYPE" not in text.upper(), path.name


def test_the_company_record_carries_both_alter_id_high_water_marks(
    built: tuple[Path, dict[str, Any], dict[str, Any]],
) -> None:
    """The Agent windows masters and vouchers separately (G33), and mock_tally rewrites
    LASTVOUCHERALTERID when a voucher is edited - the tag has to be there to be rewritten."""
    directory, _, _ = built
    directory_meta = built[1]
    [company] = _parse(directory, "TA_Company", CollectionType.COMPANY)
    masters = sum(
        directory_meta["xml_records"][r]
        for r in ("TA_Groups", "TA_Ledgers", "TA_VoucherTypes", "TA_StockItems", "TA_CostCentres")
    )
    # Two sequences, each ending where its own records do: the company is ALTERID 1 and the
    # masters run from 2, so the master mark is one more than the master count.
    assert company.last_master_alter_id == masters + 1
    assert company.last_voucher_alter_id == VOUCHERS
    raw = (directory / "TA_Company.xml").read_text(encoding="utf-8")
    assert "<LASTVOUCHERALTERID>" in raw and "<LASTMASTERALTERID>" in raw


def test_info_is_not_a_file_because_the_mock_answers_it(
    built: tuple[Path, dict[str, Any], dict[str, Any]],
) -> None:
    """TA_Info reports the TDL version and the open company, which is the mock's own state, not
    the dataset's. It is served from MockConfig, so the manifest carries the company GUID for the
    loader to set instead."""
    directory, meta, _ = built
    assert not (directory / "TA_Info.xml").exists()
    assert meta["company"]["guid"] and meta["company"]["name"]
    probe = (
        f"<ENVELOPE><TA_INFO><INFO><TDLVERSION>0.2.0</TDLVERSION>"
        f"<COMPANYGUID>{meta['company']['guid']}</COMPANYGUID>"
        f"<COMPANYNAME>{meta['company']['name']}</COMPANYNAME></INFO></TA_INFO></ENVELOPE>"
    )
    assert parse_info(probe.encode()).records[0].company_guid == meta["company"]["guid"]
