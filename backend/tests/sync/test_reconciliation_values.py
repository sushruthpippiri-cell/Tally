"""P10.3: a RECONCILIATION run's plan, and Tally's figures staged for its comparison
(D-048 #1, #3, #7), on committing connections."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, update

from app.models.agents import Agent, AgentCommand
from app.models.config import CompanySetting
from app.models.enums import SettingDataType, SyncMode
from app.models.sync import ReconciliationTallyValue, SyncError, SyncKeyList, SyncRun
from app.services.sync_runs import start_run
from app.sync.ingest import BatchResult
from tally_contract import normalize
from tally_contract.records import (
    LedgerClosingBalanceRecord,
    ParseError,
    ReconciliationStockRecord,
    ReconciliationTotalRecord,
)
from tests.factories import make_running_command
from tests.sync.helpers import Factory, Setup, count, envelope, setup, upload

DAY = date(2026, 3, 16)  # the test clock's today


def total(ledger: str = "l-sales", credit: str = "1000.00") -> ReconciliationTotalRecord:
    return ReconciliationTotalRecord(
        ledger_guid=ledger,
        ledger_name="Sales - Retail",
        voucher_type_guid="vt-sales",
        period_start=date(2026, 3, 1),
        period_end=DAY,
        debit=Decimal(0),
        credit=Decimal(credit),
    )


def closing(ledger: str = "l-cash", raw: str = "-4250.00", when: date = DAY) -> Any:
    return LedgerClosingBalanceRecord(
        ledger_guid=ledger, as_of_date=when, balance=normalize.to_amount(raw, True)
    )


def stock(qty: str = "40") -> ReconciliationStockRecord:
    return ReconciliationStockRecord(
        stock_item_guid="s-soap", as_of_date=DAY, closing_quantity=Decimal(qty), unit="Nos"
    )


async def _values(committed: Factory, st: Setup) -> list[tuple[Any, ...]]:
    async with committed() as s:
        rows = await s.execute(
            select(
                ReconciliationTallyValue.kind,
                ReconciliationTallyValue.entity_guid,
                ReconciliationTallyValue.debit,
                ReconciliationTallyValue.credit,
                ReconciliationTallyValue.value,
            )
            .where(ReconciliationTallyValue.sync_run_id == st.run_id)
            .order_by(ReconciliationTallyValue.kind)
        )
        return [tuple(r) for r in rows]


async def test_tally_values_are_staged_without_a_lease_and_a_replay_changes_nothing(
    committed: Factory,
) -> None:
    """D-048 #7: they touch no synced table, so no lease; a replayed batch upserts the same
    rows. The ledger balance is kept signed (Dr +), never as Tally's raw text (ACC-DATA-1)."""
    st = await setup(committed, sync_mode=SyncMode.RECONCILIATION)
    env = envelope(st, None, [total(), closing(), stock()])
    first = await upload(committed, st, env)
    assert isinstance(first, BatchResult) and (first.status, first.written) == ("COMPLETE", 3)
    assert await upload(committed, st, env) == first
    assert await _values(committed, st) == [
        ("LEDGER_CLOSING", "l-cash", None, None, Decimal("4250.000000")),
        ("STOCK_CLOSING", "s-soap", None, None, Decimal("40.000000")),
        ("TOTAL", "l-sales", Decimal("0.0000"), Decimal("1000.0000"), None),
    ]
    assert await count(committed, ReconciliationTallyValue, st.company_id) == 3


@pytest.mark.parametrize("mode", [SyncMode.FULL, SyncMode.INCREMENTAL])
async def test_tally_values_are_refused_outside_a_reconciliation_run(
    committed: Factory, mode: SyncMode
) -> None:
    st = await setup(committed, sync_mode=mode)
    assert await upload(committed, st, envelope(st, None, [closing()])) == "VALIDATION_ERROR"
    assert await count(committed, ReconciliationTallyValue, st.company_id) == 0


async def test_a_tally_value_dated_after_the_companys_today_is_refused(
    committed: Factory,
) -> None:
    """D-042 #5: dates come from the run plan, never the PC's clock."""
    st = await setup(committed, sync_mode=SyncMode.RECONCILIATION)
    tomorrow = closing(when=date(2026, 3, 17))
    assert await upload(committed, st, envelope(st, None, [tomorrow])) == "VALIDATION_ERROR"
    assert await count(committed, ReconciliationTallyValue, st.company_id) == 0


async def test_a_value_that_failed_to_parse_is_recorded_so_the_run_ends_partial(
    committed: Factory,
) -> None:
    st = await setup(committed, sync_mode=SyncMode.RECONCILIATION)
    bad = ParseError(message="a debit or credit sum is negative: -5.00, 0")
    result = await upload(committed, st, envelope(st, None, [total()], parse_errors=[bad]))
    assert isinstance(result, BatchResult) and (result.status, result.failed) == ("PARTIAL", 1)
    async with committed() as s:
        error = (await s.execute(select(SyncError))).scalar_one()
        run = await s.get(SyncRun, st.run_id)
    assert (error.entity_type, error.error_code) == ("RECONCILIATION", "PARSE_ERROR")
    assert run is not None and (run.records_fetched, run.records_failed) == (1, 1)


async def test_a_reconciliation_run_lists_every_collection_and_names_its_periods(
    committed: Factory,
) -> None:
    """D-048 #1: a reconciliation sends a key list for every collection (through the same
    evaluation as sync), whatever `sync.key_list_interval` says; REC-1.1: the plan names the
    periods whose totals to pull, and the ledger closing's financial year."""
    st = await setup(committed, sync_mode=SyncMode.INCREMENTAL)
    async with committed() as s:
        s.add(
            CompanySetting(
                company_id=st.company_id,
                setting_key="sync.key_list_interval",
                setting_value=5,
                data_type=SettingDataType.INTEGER,
            )
        )
        s.add(
            SyncKeyList(
                list_id=uuid.uuid4(),
                company_id=st.company_id,
                sync_run_id=st.run_id,
                collection_type="LEDGER",
                status="APPLIED",
                evaluated_at=DAY,
            )
        )
        await s.commit()
    plans = {}
    for mode in (SyncMode.INCREMENTAL, SyncMode.RECONCILIATION):
        async with committed() as s:  # one active command per Agent: end the last one
            await s.execute(
                update(AgentCommand)
                .where(AgentCommand.agent_id == st.agent.agent_id)
                .values(status="COMPLETED")
            )
            agent = await s.get(Agent, st.agent.agent_id)
            assert agent is not None
            command = await make_running_command(s, agent, mode)
            await s.commit()
            plans[mode] = await start_run(s, st.agent, command.command_id)
    incremental, reconciliation = plans[SyncMode.INCREMENTAL], plans[SyncMode.RECONCILIATION]
    assert incremental.collections["LEDGER"].key_list_due is False  # not due for 5 runs
    assert incremental.reconciliation_periods == []
    assert {c for c, p in reconciliation.collections.items() if p.key_list_due} == {
        "GROUP",
        "LEDGER",
        "VOUCHER_TYPE",
        "STOCK_ITEM",
        "COST_CENTRE",
        "VOUCHER",
    }
    assert reconciliation.financial_year_from == date(2025, 4, 1)
    labels = [(p.label, p.date_from, p.date_to) for p in reconciliation.reconciliation_periods]
    assert labels[0] == ("2025-04", date(2025, 4, 1), date(2025, 4, 30))
    assert labels[11] == ("2026-03", date(2026, 3, 1), DAY)
    assert labels[12:] == [
        ("FY2025-26 to date", date(2025, 4, 1), DAY),
        ("FY2024-25", date(2024, 4, 1), date(2025, 3, 31)),
    ]
