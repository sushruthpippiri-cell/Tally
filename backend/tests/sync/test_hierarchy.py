"""P6.4/P6.5: group and voucher-type resolution (D-001, ACC-7.x, ACC-8.x, D-041 #7, #8), through
the ingest pipeline on committing connections. One test per D-001 worked example."""

from typing import Any

import pytest
from sqlalchemy import func, select

from app.core import gates
from app.models.config import AuditLog, CompanySetting
from app.models.defaults import DEFAULT_CLASSIFICATION_ALLOW_LISTS, PREDEFINED_GROUPS
from app.models.enums import CollectionType as C
from app.models.enums import SettingDataType
from app.models.masters import Group, Ledger, VoucherType
from app.sync.hierarchy import BASE_TYPES
from app.sync.ingest import BatchResult
from tally_contract.records import AlterIdWindow, GroupRecord, LedgerRecord, VoucherTypeRecord
from tests.sync.helpers import (
    Factory,
    Setup,
    data_quality_items,
    envelope,
    lease,
    masters,
    sale,
    setup,
    sync_masters,
    upload,
)

ASSET = {"is_revenue": False, "is_deemed_positive": True}


def pg(name: str) -> str:
    return f"pg-{name}"


def predefined(*, without: str | None = None, alter: int = 1) -> list[GroupRecord]:
    """Tally's 28 predefined groups, primaries under Primary and sub-groups under them."""
    records = []
    for primary, (_, subs) in PREDEFINED_GROUPS.items():
        records.append(GroupRecord(guid=pg(primary), alter_id=alter, name=primary))
        records += [
            GroupRecord(guid=pg(sub), alter_id=alter, name=sub, parent_guid=pg(primary))
            for sub in subs
        ]
    return [r for r in records if r.name != without]


def group(guid: str, alter: int, name: str, parent: str | None = None, **kw: Any) -> GroupRecord:
    return GroupRecord(guid=guid, alter_id=alter, name=name, parent_guid=parent, **kw)


def ledger(guid: str, alter: int, name: str, parent: str) -> LedgerRecord:
    return LedgerRecord(
        guid=guid, alter_id=alter, name=name, parent_group_guid=parent, parent_group_name=""
    )


async def _send(committed: Factory, st: Setup, collection: C, records: list[Any]) -> None:
    await lease(committed, st, collection)
    top = max(r.alter_id for r in records)
    window = AlterIdWindow(from_alter_id=0, to_alter_id=top)
    result = await upload(committed, st, envelope(st, collection, records, window=window))
    assert isinstance(result, BatchResult) and result.failed == 0, result


async def _groups(committed: Factory) -> dict[str, Group]:
    async with committed() as s:
        return {g.tally_guid: g for g in (await s.execute(select(Group))).scalars()}


async def _ledger(committed: Factory, guid: str) -> Ledger:
    async with committed() as s:
        return (await s.execute(select(Ledger).where(Ledger.tally_guid == guid))).scalar_one()


def _gate(monkeypatch: pytest.MonkeyPatch, status: str) -> None:
    statuses = {g: "NOT_TESTED" for g in gates.load_gate_status()} | {"G32": status}
    monkeypatch.setattr(gates, "_default_statuses", lambda: statuses)


@pytest.mark.req("ACC-7.2")
async def test_example_1_nested_user_groups_roll_up_to_sales_accounts(committed: Factory) -> None:
    st = await setup(committed)
    await _send(
        committed,
        st,
        C.GROUP,
        [
            *predefined(),
            group("g-online", 2, "Sales - Online", pg("Sales Accounts")),
            group("g-market", 3, "Sales - Online - Marketplace", "g-online"),
        ],
    )
    await _send(committed, st, C.LEDGER, [ledger("l-amazon", 10, "Amazon Sales", "g-market")])
    groups = await _groups(committed)
    sales = groups[pg("Sales Accounts")]
    for guid in ("g-online", "g-market"):
        g = groups[guid]
        assert (g.classification_group_id, g.primary_group_id, g.nature, g.resolution_status) == (
            sales.group_id,
            sales.group_id,
            "INCOME",
            "RESOLVED",
        )
    amazon = await _ledger(committed, "l-amazon")
    assert amazon.group_id == groups["g-market"].group_id  # the immediate parent is only a link
    assert (
        amazon.classification_group_id,
        amazon.predefined_group_id,
        amazon.primary_group_id,
    ) == (
        sales.group_id,
        sales.group_id,
        sales.group_id,
    )


@pytest.mark.req_partial("ACC-7.6")  # "customers" as a metric: P8
async def test_example_2_a_group_under_sundry_debtors_anchors_to_sundry_debtors(
    committed: Factory,
) -> None:
    st = await setup(committed)
    await _send(
        committed,
        st,
        C.GROUP,
        [*predefined(), group("g-retail", 2, "Retail Customers", pg("Sundry Debtors"))],
    )
    await _send(committed, st, C.LEDGER, [ledger("l-sharma", 10, "Sharma Traders", "g-retail")])
    groups = await _groups(committed)
    debtors, current = groups[pg("Sundry Debtors")], groups[pg("Current Assets")]
    retail = groups["g-retail"]
    assert (retail.classification_group_id, retail.primary_group_id, retail.nature) == (
        debtors.group_id,  # not Current Assets
        current.group_id,
        "ASSET",
    )
    assert (await _ledger(committed, "l-sharma")).classification_group_id == debtors.group_id


async def test_example_3_a_user_group_under_primary_anchors_to_itself(committed: Factory) -> None:
    st = await setup(committed)
    await _send(
        committed, st, C.GROUP, [*predefined(), group("g-gov", 2, "Government Schemes", **ASSET)]
    )
    await _send(
        committed, st, C.LEDGER, [ledger("l-solar", 10, "Solar Subsidy Receivable", "g-gov")]
    )
    gov = (await _groups(committed))["g-gov"]
    assert (gov.classification_group_id, gov.predefined_group_id, gov.primary_group_id) == (
        gov.group_id,
        None,
        None,
    )
    assert (gov.nature, gov.resolution_status) == ("ASSET", "RESOLVED")  # nature from Tally (G14)
    assert (await _ledger(committed, "l-solar")).classification_group_id == gov.group_id
    unlisted = await data_quality_items(
        committed, st.company_id, "groups_not_in_classification_list"
    )
    assert [(i["name"], i["nature"], i["ledgers"]) for i in unlisted or []] == [
        ("Government Schemes", "ASSET", 1)
    ]
    # An Owner/Admin adds it to a list: it is classified, and leaves the check.
    key = "classification.cash_bank_groups"
    entry = {"type": "COMPANY_GROUP", "tally_guid": "g-gov"}
    async with committed() as s:
        s.add(
            CompanySetting(
                company_id=st.company_id,
                setting_key=key,
                setting_value=[*DEFAULT_CLASSIFICATION_ALLOW_LISTS[key], entry],
                data_type=SettingDataType.JSON,
            )
        )
        await s.commit()
    assert (
        await data_quality_items(committed, st.company_id, "groups_not_in_classification_list")
        == []
    )


async def test_a_user_group_under_primary_without_its_nature_stays_unresolved(
    committed: Factory,
) -> None:
    """D-041 #7: a guessed nature would put its balances on the wrong side."""
    st = await setup(committed)
    await _send(committed, st, C.GROUP, [*predefined(), group("g-gov", 2, "Government Schemes")])
    assert (await _groups(committed))["g-gov"].resolution_status == "UNRESOLVED_GROUP"


@pytest.mark.req_partial("ACC-7.4")  # excluded from classified metrics: P8
async def test_example_4_a_broken_chain_is_unresolved_down_to_its_descendants_and_recovers(
    committed: Factory,
) -> None:
    st = await setup(committed)
    await _send(
        committed,
        st,
        C.GROUP,
        [
            *predefined(),
            group("g-x", 2, "Project X", "g-ghost", **ASSET),  # a parent the company does not have
            group("g-x1", 3, "Project X - Phase 1", "g-x", **ASSET),
            group("g-a", 4, "Loop A", "g-b", **ASSET),  # a loop, with a child hanging off it
            group("g-b", 5, "Loop B", "g-a", **ASSET),
            group("g-c", 6, "Loop Child", "g-a", **ASSET),
        ],
    )
    await _send(committed, st, C.LEDGER, [ledger("l-x", 10, "Project X Costs", "g-x1")])
    groups = await _groups(committed)
    for guid in ("g-x", "g-x1", "g-a", "g-b", "g-c"):
        g = groups[guid]
        assert (g.resolution_status, g.classification_group_id, g.nature) == (
            "UNRESOLVED_GROUP",
            None,
            None,
        ), guid
    assert (await _ledger(committed, "l-x")).classification_group_id is None
    listed = await data_quality_items(committed, st.company_id, "unresolved_groups")
    assert {i["name"] for i in listed or []} == {
        "Project X",
        "Project X - Phase 1",
        "Loop A",
        "Loop B",
        "Loop Child",
    }

    # The missing parent arrives with the next sync: the chain resolves by itself.
    await _send(committed, st, C.GROUP, [group("g-ghost", 7, "Projects", pg("Indirect Expenses"))])
    groups = await _groups(committed)
    expenses = groups[pg("Indirect Expenses")]
    assert {groups[g].classification_group_id for g in ("g-ghost", "g-x", "g-x1")} == {
        expenses.group_id
    }
    assert (await _ledger(committed, "l-x")).classification_group_id == expenses.group_id
    assert groups["g-a"].resolution_status == "UNRESOLVED_GROUP"  # the loop stays broken
    listed = await data_quality_items(committed, st.company_id, "unresolved_groups")
    assert {i["name"] for i in listed or []} == {"Loop A", "Loop B", "Loop Child"}


@pytest.mark.parametrize("g32", ["PASSED", "NOT_TESTED"])
async def test_example_5_a_renamed_predefined_group_anchors_by_its_reserved_name(
    committed: Factory, monkeypatch: pytest.MonkeyPatch, g32: str
) -> None:
    _gate(monkeypatch, g32)
    st = await setup(committed)
    renamed = group(
        pg("Sundry Debtors"), 2, "Customers", pg("Current Assets"), reserved_name="Sundry Debtors"
    )
    records = [*predefined(without="Sundry Debtors"), renamed]
    if g32 == "PASSED":  # the exported reserved names identify every predefined group
        records = [
            r.model_copy(update={"reserved_name": r.reserved_name or r.name}) for r in records
        ]
    await _send(committed, st, C.GROUP, records)
    await _send(
        committed, st, C.LEDGER, [ledger("l-sharma", 10, "Sharma Traders", pg("Sundry Debtors"))]
    )
    groups = await _groups(committed)
    customers, current = groups[pg("Sundry Debtors")], groups[pg("Current Assets")]
    anchor = (await _ledger(committed, "l-sharma")).classification_group_id
    renamed_check = await data_quality_items(
        committed, st.company_id, "predefined_group_possibly_renamed"
    )
    if g32 == "PASSED":
        assert (customers.is_predefined, customers.reserved_name) == (True, "Sundry Debtors")
        assert anchor == customers.group_id  # still a customer
        assert renamed_check is None  # the check retires once G32 passes
    else:  # before G32: not recognised, so it anchors one level up - and the check says so
        assert customers.is_predefined is False
        assert anchor == current.group_id
        assert [(i["expected"], i["candidate"]) for i in renamed_check or []] == [
            ("Sundry Debtors", "Customers")
        ]


@pytest.mark.req("ACC-7.5")
async def test_a_reparented_group_is_recalculated_with_everything_beneath_it_and_logged(
    committed: Factory,
) -> None:
    st = await setup(committed)
    await _send(
        committed,
        st,
        C.GROUP,
        [
            *predefined(),
            group("g-online", 2, "Sales - Online", pg("Sales Accounts")),
            group("g-market", 3, "Sales - Online - Marketplace", "g-online"),
        ],
    )
    await _send(committed, st, C.LEDGER, [ledger("l-amazon", 10, "Amazon Sales", "g-market")])
    moved = group("g-online", 20, "Sales - Online", pg("Indirect Incomes"))
    await _send(committed, st, C.GROUP, [moved])
    groups = await _groups(committed)
    incomes = groups[pg("Indirect Incomes")]
    assert groups["g-online"].parent_group_id == incomes.group_id
    assert {groups[g].classification_group_id for g in ("g-online", "g-market")} == {
        incomes.group_id
    }
    assert (await _ledger(committed, "l-amazon")).classification_group_id == incomes.group_id
    async with committed() as s:
        audits = (
            (await s.execute(select(AuditLog).where(AuditLog.action == "GROUP_RESOLUTION_CHANGED")))
            .scalars()
            .all()
        )
    assert sorted(a.after_value["name"] for a in audits) == [
        "Sales - Online",
        "Sales - Online - Marketplace",
    ]
    sales = groups[pg("Sales Accounts")]
    assert all(a.before_value["classification_group_id"] == str(sales.group_id) for a in audits)


async def test_first_resolution_of_new_groups_is_not_audited(committed: Factory) -> None:
    st = await setup(committed)
    await _send(committed, st, C.GROUP, predefined())
    async with committed() as s:
        assert await s.scalar(select(func.count()).select_from(AuditLog)) == 0


# --- voucher types (ACC-8.x) -----------------------------------------------------------------


def vtype(
    guid: str, alter: int, name: str, parent: str | None = None, **kw: Any
) -> VoucherTypeRecord:
    return VoucherTypeRecord(guid=guid, alter_id=alter, name=name, parent_guid=parent, **kw)


async def _types(committed: Factory) -> dict[str, VoucherType]:
    async with committed() as s:
        return {t.name: t for t in (await s.execute(select(VoucherType))).scalars()}


@pytest.mark.req_partial("ACC-8.2", "ACC-8.3")  # included/excluded in metrics: P8
async def test_voucher_types_resolve_through_their_chain_to_a_base_type(committed: Factory) -> None:
    st = await setup(committed)
    await _send(
        committed,
        st,
        C.VOUCHER_TYPE,
        [
            vtype("vt-sales", 1, "Sales"),
            vtype("vt-receipt", 2, "Receipt"),
            vtype("vt-pos", 3, "POS Invoice", "vt-sales"),
            vtype("vt-mall", 4, "POS Invoice - Mall", "vt-pos"),  # two levels
            vtype("vt-lost", 5, "Orphan", "vt-ghost"),  # a parent the company does not have
            vtype("vt-journal-copy", 6, "My Journal"),  # no parent, not predefined
        ],
    )
    types = await _types(committed)
    assert {n: (types[n].base_voucher_type, types[n].resolution_status) for n in types} == {
        "Sales": ("SALES", "RESOLVED"),
        "Receipt": ("RECEIPT", "RESOLVED"),
        "POS Invoice": ("SALES", "RESOLVED"),
        "POS Invoice - Mall": ("SALES", "RESOLVED"),
        "Orphan": ("OTHER", "UNRESOLVED"),
        "My Journal": ("OTHER", "UNRESOLVED"),
    }
    assert (
        types["POS Invoice - Mall"].parent_voucher_type_id == types["POS Invoice"].voucher_type_id
    )

    # POS Invoice is re-pointed at Receipt: it and its child follow, and the change is logged.
    await _send(committed, st, C.VOUCHER_TYPE, [vtype("vt-pos", 10, "POS Invoice", "vt-receipt")])
    types = await _types(committed)
    assert {types[n].base_voucher_type for n in ("POS Invoice", "POS Invoice - Mall")} == {
        "RECEIPT"
    }
    async with committed() as s:
        logged = await s.scalar(
            select(func.count()).where(AuditLog.action == "VOUCHER_TYPE_RESOLUTION_CHANGED")
        )
    assert logged == 2


async def test_other_predefined_types_are_other_but_resolved_once_g32_names_them(
    committed: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    _gate(monkeypatch, "PASSED")
    st = await setup(committed)
    await _send(
        committed,
        st,
        C.VOUCHER_TYPE,
        [
            vtype("vt-sj", 1, "Stock Journal", reserved_name="Stock Journal"),
            vtype("vt-inv", 2, "Invoice", reserved_name="Sales"),  # a renamed Sales
        ],
    )
    types = await _types(committed)
    assert (types["Stock Journal"].base_voucher_type, types["Stock Journal"].resolution_status) == (
        "OTHER",
        "RESOLVED",
    )
    assert types["Invoice"].base_voucher_type == "SALES"


@pytest.mark.parametrize("g32", ["NOT_TESTED", "PASSED"])
async def test_a_renamed_sales_voucher_type_is_flagged_before_g32(
    committed: Factory, monkeypatch: pytest.MonkeyPatch, g32: str
) -> None:
    """Owner change (D-041 #9): vouchers of a renamed "Sales" would count as OTHER and sales
    would silently read zero; before G32 the Data Quality view says so."""
    _gate(monkeypatch, g32)
    st = await setup(committed)
    data = {**masters()}
    others = [n for n in BASE_TYPES if n != "Sales"]  # every company has all eight
    data[C.VOUCHER_TYPE] = [
        vtype("vt-sales", 20, "Invoice", reserved_name="Sales"),  # renamed in Tally
        *(vtype(f"vt-{n}", 21 + i, n, reserved_name=n) for i, n in enumerate(others)),
        vtype("vt-mine", 40, "My Journal"),  # unrecognised but unused: not flagged
    ]
    await sync_masters(committed, st, data)
    await lease(committed, st, C.VOUCHER)
    batch = [sale("v-1", 100, "1180.00"), sale("v-2", 110, "590.00", number="S-2")]
    assert isinstance(await upload(committed, st, envelope(st, C.VOUCHER, batch)), BatchResult)
    flagged = await data_quality_items(
        committed, st.company_id, "predefined_voucher_type_possibly_renamed"
    )
    invoice = (await _types(committed))["Invoice"]
    if g32 == "PASSED":
        assert invoice.base_voucher_type == "SALES"
        assert flagged is None
    else:
        assert (invoice.base_voucher_type, invoice.resolution_status) == ("OTHER", "UNRESOLVED")
        assert [(i["expected"], i["candidate"], i["vouchers"]) for i in flagged or []] == [
            ("Sales", "Invoice", 2)
        ]
        unresolved = await data_quality_items(committed, st.company_id, "unresolved_voucher_types")
        assert [i["name"] for i in unresolved or []] == ["Invoice"]  # "My Journal" is unused
