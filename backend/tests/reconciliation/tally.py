"""A finished RECONCILIATION run on the test books, and Tally's figures staged for it as the
Agent would upload them. The figures are written by hand in each test: they stand for what
Tally computes, never for anything derived from the synced rows."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from app.core import periods
from app.models.balances import StockSnapshot
from app.models.enums import SyncMode, SyncRunStatus, TallyValueKind
from app.models.sync import ReconciliationRun, ReconciliationTallyValue, SyncRun
from app.reconciliation.compare import reconcile_run
from tests.analytics.books import FY_START, Books
from tests.factories import make_command, make_registered_agent, make_sync_run

AS_OF = date(2026, 3, 16)  # the test clock's today in Asia/Kolkata
PERIODS = periods.reconciliation_periods(AS_OF, FY_START)
# the ledgers with a balance on a date (ASSET / LIABILITY), given a zero opening by `Tally.new`
BALANCE_SHEET = [
    "Customer A",
    "Customer B",
    "Supplier S",
    "Output GST",
    "Input GST",
    "Cash",
    "HDFC Bank",
    "ICICI OD",
    "Loan",
]


@dataclass
class Tally:
    books: Books
    run: SyncRun

    @classmethod
    async def new(
        cls, books: Books, openings: dict[str, str] | None = None, *, bare: bool = False
    ) -> "Tally":
        """A RECONCILIATION run that ended COMPLETED. Unless `bare`, every balance-sheet ledger
        gets a books-beginning Dr opening (`openings`, else 0), so every ledger has a balance."""
        if not bare:
            for name in BALANCE_SHEET:
                await books.opening(name, "DEBIT", (openings or {}).get(name, "0"))
        agent, _ = await make_registered_agent(books.session, books.company, str(uuid.uuid4()))
        run = await make_sync_run(
            books.session, await make_command(books.session, agent, SyncMode.RECONCILIATION)
        )
        run.status, run.ended_at = SyncRunStatus.COMPLETED, datetime.now(UTC)
        await books.session.flush()
        return cls(books, run)

    def _add(self, **values: object) -> None:
        self.books.session.add(
            ReconciliationTallyValue(
                company_id=self.books.company.company_id,
                sync_run_id=self.run.sync_run_id,
                **values,
            )
        )

    def total(
        self,
        ledger: str,
        vtype: str,
        day: date,
        debit: str = "0",
        credit: str = "0",
        guid: str | None = None,
    ) -> None:
        """Tally's sums for one (ledger, voucher type) in every period containing `day`.
        `guid`: a ledger only Tally has."""
        for p in PERIODS:
            if p.start <= day <= p.end:
                self._add(
                    kind=TallyValueKind.TOTAL,
                    entity_guid=guid or self.books.ledgers[ledger].tally_guid,
                    voucher_type_guid=self.books.types[vtype].tally_guid,
                    name=ledger,
                    period_start=p.start,
                    period_end=p.end,
                    debit=Decimal(debit),
                    credit=Decimal(credit),
                )

    def closings(
        self, balances: dict[str, str] | None = None, omit: frozenset[str] = frozenset()
    ) -> None:
        """Tally's closing balance on AS_OF for every ledger but `omit` (Dr +); unnamed ones
        are 0."""
        for name, ledger in self.books.ledgers.items():
            if name in omit:
                continue
            self._add(
                kind=TallyValueKind.LEDGER_CLOSING,
                entity_guid=ledger.tally_guid,
                name=name,
                period_start=AS_OF,
                period_end=AS_OF,
                value=Decimal((balances or {}).get(name, "0")),
            )

    def stock(self, item_guid: str, qty: str, unit: str = "Nos") -> None:
        self._add(
            kind=TallyValueKind.STOCK_CLOSING,
            entity_guid=item_guid,
            period_start=AS_OF,
            period_end=AS_OF,
            value=Decimal(qty),
            unit=unit,
        )

    def snapshot(self, item_id: object, qty: str, unit: str = "Nos", run: bool = True) -> None:
        self.books.session.add(
            StockSnapshot(
                company_id=self.books.company.company_id,
                stock_item_id=item_id,
                as_of_date=AS_OF,
                closing_quantity=Decimal(qty),
                unit=unit,
                sync_run_id=self.run.sync_run_id if run else None,
            )
        )

    async def reconcile(self) -> ReconciliationRun:
        await self.books.session.flush()
        return await reconcile_run(self.books.session, self.run, datetime.now(UTC))
