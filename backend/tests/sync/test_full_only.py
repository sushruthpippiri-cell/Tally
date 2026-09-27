"""P5.9: a collection whose ALTERID gate FAILED is synced by full pull only (VAL-1.2, AC-12,
D-040 #7), including in scheduled INCREMENTAL runs, which must not fail every hour."""

import uuid

import pytest
from sqlalchemy import func, select

from app.core import gates
from app.core.permissions import CompanyContext
from app.models.enums import CollectionType as C
from app.models.enums import SyncMode
from app.models.sync import SyncWatermark
from app.models.vouchers import Voucher
from app.schemas.sync import FinishRequest, ReleaseRequest
from app.services import sync_status
from app.services.sync_runs import finish_run, release_lease, start_run
from app.sync.ingest import BatchResult
from tally_contract.records import AlterIdWindow
from tests.sync.helpers import Factory, envelope, lease, sale, setup, sync_masters, upload


@pytest.fixture(autouse=True)
def voucher_gate_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    failed = {g: "NOT_TESTED" for g in gates.load_gate_status()} | {"G3": "FAILED"}
    monkeypatch.setattr(gates, "_default_statuses", lambda: failed)


async def _vouchers(committed: Factory) -> int:
    async with committed() as s:
        return int(await s.scalar(select(func.count()).select_from(Voucher)) or 0)


@pytest.mark.req("AC-12", "VAL-1.2")
async def test_a_scheduled_incremental_run_syncs_a_full_only_collection_by_full_pull(
    committed: Factory,
) -> None:
    st = await setup(committed, sync_mode=SyncMode.INCREMENTAL)  # what a schedule creates
    await sync_masters(committed, st)
    async with committed() as s:
        plan = (await start_run(s, st.agent, st.command_id)).collections
    assert (plan[C.VOUCHER].mode, plan[C.VOUCHER].full) == ("FULL_ONLY", True)
    assert (plan[C.LEDGER].mode, plan[C.LEDGER].full) == ("INCREMENTAL", False)
    await lease(committed, st, C.VOUCHER)

    # An ALTERID-windowed upload is the one thing refused, and it writes nothing.
    windowed = envelope(st, C.VOUCHER, [sale("v-1", 100, "1180.00")])
    assert isinstance(windowed.window, AlterIdWindow)
    assert await upload(committed, st, windowed) == "GATE_NOT_PASSED"
    assert await _vouchers(committed) == 0

    # The full pull, unwindowed, is stored.
    full = windowed.model_copy(update={"window": None, "batch_id": uuid.uuid4()})
    result = await upload(committed, st, full)
    assert isinstance(result, BatchResult) and result.written == 1, result
    async with committed() as s:
        out = await release_lease(
            s,
            st.agent,
            ReleaseRequest(
                sync_run_id=st.run_id,
                collection_type=C.VOUCHER,
                complete=True,
                start_max_alter_id=100,
            ),
        )
        assert out.last_alter_id == 0  # unverified ALTERIDs never move its watermark
        run = await finish_run(
            s, st.agent, st.command_id, st.run_id, FinishRequest(status="COMPLETED")
        )
    assert run.status == "COMPLETED"  # not a failure every hour

    async with committed() as s:
        mark = (
            await s.execute(select(SyncWatermark).where(SyncWatermark.collection_type == "VOUCHER"))
        ).scalar_one()
        assert mark.status == "NEVER_SYNCED"  # the next run pulls it in full again
        view = await sync_status.status(s, CompanyContext(st.company_id, uuid.uuid4(), frozenset()))
    shown = {c.collection_type: c.label for c in view.collections}
    assert (shown[C.VOUCHER], shown[C.LEDGER]) == ("Full sync only", "Incremental")
