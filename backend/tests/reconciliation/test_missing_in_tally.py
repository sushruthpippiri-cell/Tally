"""P10.5, REC-1.5: what a reconciliation finds only locally becomes MISSING_IN_TALLY through the
same key-list evaluation as sync, D-007 guard and date-window rule included (D-048 #1). There
is no second path, and the architecture test below keeps it that way."""

import ast
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select

import app
from app.models.enums import CollectionType as C
from app.models.enums import SyncMode
from app.models.masters import CostCentre, Ledger
from app.models.vouchers import Voucher, VoucherEntry
from app.schemas.sync import KeyListOut
from tally_contract import tally_constants as tc
from tally_contract.records import DateWindow
from tally_contract.testing import assert_logged
from tests.sync.helpers import Factory, masters, sale, setup, sync_masters
from tests.sync.test_key_lists import _actions, _cost_centres, _key_list, _statuses, _vouchers

APP = Path(app.__file__).parent
EVERYTHING = DateWindow(date_from=date(2024, 4, 1), date_to=tc.FULL_PULL_DATE_TO)  # D-048 #2


@pytest.mark.req("AC-10", "REC-1.5")
async def test_a_ledger_missing_from_a_full_reconciliation_is_kept_as_missing_in_tally(
    committed: Factory,
) -> None:
    """AC-10: missing from a full reconciliation -> MISSING_IN_TALLY, not deleted, and the
    historical vouchers still reference it. Audited like any key list (D-041 #3)."""
    st = await setup(committed, sync_mode=SyncMode.RECONCILIATION)
    await sync_masters(committed, st)
    await _vouchers(committed, st, [sale("v-1", 100, "1180.00")])
    keys = [(r.guid, r.alter_id) for r in masters()[C.LEDGER] if r.guid != "l-sharma"]
    out = await _key_list(committed, st, C.LEDGER, keys)
    assert isinstance(out, KeyListOut) and (out.status, out.marked_missing) == ("APPLIED", 1)
    async with committed() as s:
        sharma = (
            await s.execute(select(Ledger).where(Ledger.tally_guid == "l-sharma"))
        ).scalar_one()
        referenced = await s.scalar(
            select(func.count()).where(VoucherEntry.ledger_id == sharma.ledger_id)
        )
    assert sharma.status == "MISSING_IN_TALLY" and referenced
    assert await _actions(committed, "MISSING_IN_TALLY") == 1


@pytest.mark.req_partial("REC-1.5")  # the guard half; marking: the AC-10 test above
async def test_the_d007_guard_holds_for_a_reconciliation_key_list(
    committed: Factory, caplog: pytest.LogCaptureFixture
) -> None:
    """Owner (D-048 #1): reconciliation is not a way around the guard. An empty or implausibly
    short list marks nothing, is SUSPICIOUS and logged."""
    st = await setup(committed, sync_mode=SyncMode.RECONCILIATION)
    keys = await _cost_centres(committed, st, 30)
    for listed in ([], keys[:1]):
        out = await _key_list(committed, st, C.COST_CENTRE, listed)
        assert isinstance(out, KeyListOut) and (out.status, out.marked_missing) == (
            "SUSPICIOUS",
            0,
        )
    assert set((await _statuses(committed, CostCentre)).values()) == {"ACTIVE"}
    assert_logged(caplog, "key_list_suspicious", level="warning", collection="COST_CENTRE")


async def test_a_reconciliation_voucher_list_touches_only_vouchers_inside_its_dates(
    committed: Factory,
) -> None:
    """D-048 #2 with D-041 #3: the list names books-beginning to FULL_PULL_DATE_TO, so a
    post-dated voucher is inside it (and kept, being listed) while one dated before the books
    begin is outside and never touched."""
    st = await setup(committed, sync_mode=SyncMode.RECONCILIATION)
    await sync_masters(committed, st)
    await _vouchers(
        committed,
        st,
        [
            sale("v-1", 100, "1180.00", number="S-1", when=date(2025, 5, 1)),
            sale("v-2", 110, "1180.00", number="S-2", when=date(2025, 6, 1)),
            sale("v-future", 120, "590.00", number="S-3", when=date(2026, 4, 1)),
            sale("v-before", 130, "590.00", number="S-4", when=date(2024, 3, 31)),
        ],
    )
    keys = [("v-1", 100), ("v-future", 120)]  # v-2 deleted in Tally; v-before not listed
    out = await _key_list(committed, st, C.VOUCHER, keys, window=EVERYTHING)
    assert isinstance(out, KeyListOut) and (out.candidates, out.marked_missing) == (3, 1)
    assert await _statuses(committed, Voucher) == {
        "v-1": "ACTIVE",
        "v-2": "MISSING_IN_TALLY",
        "v-future": "ACTIVE",
        "v-before": "ACTIVE",  # outside the list's dates: never a candidate
    }


def test_only_the_key_list_evaluation_marks_anything_missing_in_tally() -> None:
    """D-048 #1: `lifecycle.MISSING` is written in app/sync/keylists.py alone, and the
    reconciliation package never reaches the lifecycle or key-list code."""
    writers, reachers = set(), set()
    for path in APP.rglob("*.py"):
        rel = path.relative_to(APP).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "MISSING":
                writers.add(rel)
            if rel.startswith("reconciliation/") and isinstance(node, ast.ImportFrom | ast.Import):
                names = [getattr(node, "module", None) or ""] + [a.name for a in node.names]
                if any("keylists" in n or "lifecycle" in n for n in names):
                    reachers.add(rel)
    assert writers == {"sync/keylists.py"}
    assert reachers == set()
