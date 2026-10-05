"""Deterministic anomaly rules (FR-3.2, FR-3.3). Every number here is computed by SQL and
Python arithmetic on Decimals — nothing in this module asks anything of a model, and the
import-linter forbids it from reaching `anthropic` or `mcp`.

The transaction amount is what moved on the party ledger: `abs(sum(amount_signed))` over that
ledger's entries on the voucher, which equals `amount_absolute` for the ordinary single-entry
case and nets correctly when a voucher touches the same party twice. The as-received Tally
amount is never read here (ACC-DATA-1) - the architecture guard checks even this docstring for
its name.

A voucher touching **two different** party ledgers is skipped rather than flagged twice: the
table's key is `(voucher_id, rule_triggered)`, so the second flag would be silently dropped, and
"which party was this unusual for" has no single answer (the rule ACC-6.3 applies to attribution).
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Date,
    Integer,
    Select,
    and_,
    cast,
    func,
    literal,
    select,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.classification import load_classes
from app.models.config import AnomalyFlag
from app.models.enums import AnomalyRule, ExplanationStatus, VoucherStatus
from app.models.masters import Ledger, VoucherType
from app.models.vouchers import Voucher, VoucherEntry
from app.services.settings import get_setting
from tally_contract.log import get_logger

E, V, VT, L = VoucherEntry, Voucher, VoucherType, Ledger
log = get_logger(__name__)


@dataclass(frozen=True)
class Thresholds:
    """The rule settings, read once per scan."""

    history_window_days: int
    deviation_sd: Decimal
    min_prior_transactions: int
    min_average_multiple: Decimal
    max_multiplier: Decimal | None
    duplicate_window_days: int

    @staticmethod
    async def load(session: AsyncSession, company_id: uuid.UUID) -> "Thresholds":
        async def get(key: str) -> Any:
            return await get_setting(session, company_id, f"anomaly.{key}")

        return Thresholds(
            history_window_days=int(await get("history_window_days")),
            deviation_sd=Decimal(str(await get("deviation_sd"))),
            min_prior_transactions=int(await get("min_prior_transactions")),
            min_average_multiple=Decimal(str(await get("min_average_multiple"))),
            max_multiplier=(
                None if (m := await get("max_multiplier")) is None else Decimal(str(m))
            ),
            duplicate_window_days=int(await get("duplicate_window_days")),
        )


@dataclass(frozen=True)
class Flag:
    """One row to write, with the evidence FR-3.4 requires."""

    voucher_id: uuid.UUID
    rule: AnomalyRule
    amount: Decimal
    average: Decimal | None = None
    maximum: Decimal | None = None
    deviation_percent: Decimal | None = None
    duplicate_of_voucher_id: uuid.UUID | None = None


def _party_txn(company_id: uuid.UUID, parties: frozenset[uuid.UUID], since: date) -> Select[Any]:
    """One row per (ACTIVE voucher, party ledger) from `since`: the amount transacted with that
    party, the voucher's date and base type, and **our** write time."""
    per_ledger = (
        select(
            V.voucher_id.label("voucher_id"),
            V.voucher_date.label("voucher_date"),
            V.last_synced_at.label("last_synced_at"),
            VT.base_voucher_type.label("base_voucher_type"),
            E.ledger_id.label("ledger_id"),
            func.abs(func.sum(E.amount_signed)).label("amount"),
        )
        .select_from(E)
        .join(V, and_(V.company_id == E.company_id, V.voucher_id == E.voucher_id))
        .join(VT, and_(VT.company_id == V.company_id, VT.voucher_type_id == V.voucher_type_id))
        .join(L, and_(L.company_id == E.company_id, L.ledger_id == E.ledger_id))
        .where(
            E.company_id == company_id,
            V.status == VoucherStatus.ACTIVE,
            V.voucher_date >= since,
            L.classification_group_id.in_(parties),
        )
        .group_by(V.voucher_id, V.voucher_date, V.last_synced_at, VT.base_voucher_type, E.ledger_id)
        .subquery()
    )
    counted = select(
        per_ledger,
        func.count().over(partition_by=per_ledger.c.voucher_id).label("party_ledgers"),
    ).subquery()
    # A zero-amount movement is not a transaction, and it would make the deviation undefined.
    return select(counted).where(counted.c.party_ledgers == 1, counted.c.amount > 0)


async def large_transactions(
    session: AsyncSession,
    company_id: uuid.UUID,
    parties: frozenset[uuid.UUID],
    thresholds: Thresholds,
    candidates: set[uuid.UUID],
    history_from: date,
) -> list[Flag]:
    """FR-3.2 as amended by D-015 and D-055 #1.

    The history is the same party's earlier transactions inside the window; "earlier" is a
    strictly earlier `voucher_date`, so the result does not depend on the order two vouchers of
    the same day happen to be stored in.
    """
    txn = _party_txn(company_id, parties, history_from).subquery("txn")
    hist = _party_txn(company_id, parties, history_from).subquery("hist")
    window = literal(thresholds.history_window_days, Integer)
    rows = await session.execute(
        select(
            txn.c.voucher_id,
            txn.c.amount,
            func.count().label("priors"),
            func.avg(hist.c.amount).label("mean"),
            func.max(hist.c.amount).label("peak"),
            func.stddev_samp(hist.c.amount).label("sd"),
        )
        .select_from(
            txn.join(
                hist,
                and_(
                    hist.c.ledger_id == txn.c.ledger_id,
                    hist.c.voucher_date < txn.c.voucher_date,
                    hist.c.voucher_date >= cast(txn.c.voucher_date - window, Date),
                ),
            )
        )
        .where(txn.c.voucher_id.in_(candidates))
        .group_by(txn.c.voucher_id, txn.c.amount)
    )

    flags: list[Flag] = []
    for voucher_id, amount, priors, mean, peak, sd in rows.tuples():
        if priors < thresholds.min_prior_transactions or not mean or mean <= 0:
            continue  # no sample, or an average of zero, which makes the deviation undefined
        deviation = (amount - mean) / mean * 100
        evidence = {
            "amount": amount,
            "average": mean,
            "maximum": peak,
            "deviation_percent": deviation,
        }
        # The SD term needs dispersion; the average-multiple term needs scale. Both must hold,
        # or a flat history flags a one-rupee increase (D-055 #1).
        if (
            sd is not None
            and amount > mean + thresholds.deviation_sd * sd
            and amount >= thresholds.min_average_multiple * mean
        ):
            flags.append(Flag(voucher_id, AnomalyRule.UNUSUALLY_LARGE_SD, **evidence))
        elif thresholds.max_multiplier is not None and amount > peak * thresholds.max_multiplier:
            flags.append(Flag(voucher_id, AnomalyRule.UNUSUALLY_LARGE_MULTIPLE, **evidence))
    return flags


async def duplicates(
    session: AsyncSession,
    company_id: uuid.UUID,
    parties: frozenset[uuid.UUID],
    thresholds: Thresholds,
    candidates: set[uuid.UUID],
    history_from: date,
) -> list[Flag]:
    """FR-3.3 as amended by D-055 #2: same party, same amount, **same base voucher type**, within
    the window. Without the base-type condition this flags an invoice followed by its payment of
    the same amount — the most ordinary pattern in accounting.

    The later voucher is flagged and points at the earlier one; a same-day pair is ordered by
    voucher id so the pair is stable between runs.
    """
    later = _party_txn(company_id, parties, history_from).subquery("later")
    earlier = _party_txn(company_id, parties, history_from).subquery("earlier")
    window = literal(thresholds.duplicate_window_days, Integer)
    rows = await session.execute(
        select(later.c.voucher_id, later.c.amount, earlier.c.voucher_id)
        .select_from(
            later.join(
                earlier,
                and_(
                    earlier.c.ledger_id == later.c.ledger_id,
                    earlier.c.amount == later.c.amount,
                    earlier.c.base_voucher_type == later.c.base_voucher_type,
                    earlier.c.voucher_id != later.c.voucher_id,
                    func.abs(earlier.c.voucher_date - later.c.voucher_date) <= window,
                    # "the later one": by date, then by id for a same-day pair
                    func.row(earlier.c.voucher_date, earlier.c.voucher_id)
                    < func.row(later.c.voucher_date, later.c.voucher_id),
                ),
            )
        )
        .where(later.c.voucher_id.in_(candidates))
        .distinct()
    )
    seen: dict[uuid.UUID, Flag] = {}
    for voucher_id, amount, other in rows.tuples():
        # One flag per voucher (the table's key); against the first match in a stable order.
        seen.setdefault(
            voucher_id,
            Flag(voucher_id, AnomalyRule.POSSIBLE_DUPLICATE, amount, duplicate_of_voucher_id=other),
        )
    return list(seen.values())


async def evaluate(
    session: AsyncSession,
    company_id: uuid.UUID,
    candidates: set[uuid.UUID],
    earliest: date,
    now: datetime,
) -> tuple[int, int]:
    """Run both rules over `candidates` and write the result. Returns (written, cleared).

    `earliest` is the earliest candidate voucher date; history reaches back a window before it.

    Both writes are bulk SQL, so a caller holding `AnomalyFlag` objects from before the call
    should expire them first. The job holds none.
    """
    if not candidates:
        return 0, 0
    thresholds = await Thresholds.load(session, company_id)
    classes = await load_classes(session, company_id)
    parties = classes.customer | classes.supplier
    if not parties:
        return 0, 0
    history_from = earliest - timedelta(
        days=max(thresholds.history_window_days, thresholds.duplicate_window_days)
    )
    found = await large_transactions(
        session, company_id, parties, thresholds, candidates, history_from
    )
    found += await duplicates(session, company_id, parties, thresholds, candidates, history_from)
    written = await _write(session, company_id, found, now)
    cleared = await _clear(session, company_id, candidates, found, now)
    return written, cleared


async def _write(
    session: AsyncSession, company_id: uuid.UUID, flags: list[Flag], now: datetime
) -> int:
    """Idempotent on `(voucher_id, rule_triggered)`. A re-evaluated voucher gets fresh evidence,
    its explanation dropped back to PENDING, and `cleared_at` reset — D-055 #10."""
    if not flags:
        return 0
    rows = [
        {
            "company_id": company_id,
            "voucher_id": f.voucher_id,
            "rule_triggered": f.rule.value,
            "transaction_amount": f.amount,
            "historical_average": f.average,
            "historical_max": f.maximum,
            "deviation_percent": f.deviation_percent,
            "duplicate_of_voucher_id": f.duplicate_of_voucher_id,
            "flagged_at": now,
            "explanation_status": ExplanationStatus.PENDING.value,
        }
        for f in flags
    ]
    statement = insert(AnomalyFlag).values(rows)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["voucher_id", "rule_triggered"],
            set_={
                "transaction_amount": statement.excluded.transaction_amount,
                "historical_average": statement.excluded.historical_average,
                "historical_max": statement.excluded.historical_max,
                "deviation_percent": statement.excluded.deviation_percent,
                "duplicate_of_voucher_id": statement.excluded.duplicate_of_voucher_id,
                "explanation_status": ExplanationStatus.PENDING.value,
                "explanation_text": None,
                "explanation_unavailable_reason": None,
                "explanation_attempts": 0,
                "cleared_at": None,
            },
            # Only when something actually changed, so an unchanged voucher does not lose a
            # perfectly good explanation on every re-scan.
            where=(
                (AnomalyFlag.transaction_amount != statement.excluded.transaction_amount)
                | (AnomalyFlag.historical_average != statement.excluded.historical_average)
                | (
                    AnomalyFlag.duplicate_of_voucher_id.is_distinct_from(
                        statement.excluded.duplicate_of_voucher_id
                    )
                )
                | AnomalyFlag.cleared_at.is_not(None)
            ),
        )
    )
    return len(rows)


async def _clear(
    session: AsyncSession,
    company_id: uuid.UUID,
    candidates: set[uuid.UUID],
    flags: list[Flag],
    now: datetime,
) -> int:
    """D-055 #10: a flag whose rule no longer triggers is cleared, never deleted, so a reviewed
    one survives for the audit trail and a later re-trigger simply un-clears it.

    One UPDATE rather than a loop over ORM objects: `_write` goes straight to SQL, so any
    AnomalyFlag already in the session's identity map is stale by now and a loop would decide
    from the values it was loaded with.
    """
    still = [(f.voucher_id, f.rule.value) for f in flags]
    statement = (
        update(AnomalyFlag)
        .where(
            AnomalyFlag.company_id == company_id,
            AnomalyFlag.voucher_id.in_(candidates),
            AnomalyFlag.cleared_at.is_(None),
        )
        .values(cleared_at=now)
    )
    if still:
        statement = statement.where(
            tuple_(AnomalyFlag.voucher_id, AnomalyFlag.rule_triggered).not_in(still)
        )
    result = await session.execute(statement)
    cleared = int(result.rowcount)  # type: ignore[attr-defined]
    if cleared:
        log.info("anomaly_flags_cleared", company_id=str(company_id), cleared=cleared)
    return cleared
