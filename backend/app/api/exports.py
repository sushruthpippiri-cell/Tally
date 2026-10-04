"""CSV and PDF exports (EXP-1.1-1.6, SEC-1.11, LOG-1.1).

Permission and company scope are re-checked here, on the server, before anything is produced
(EXP-1.6): `company_id` comes only from the authorised `CompanyContext`, never from the query
string. The download is audited with its data range before it starts.

Every figure comes from `app.exports.reports`, which calls the same services the screen calls,
and every read of one export shares one snapshot, so a file always adds up to its own summary
(AC-39, D-054).
"""

import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import date
from enum import StrEnum
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.db import get_session, snapshot
from app.core.periods import Granularity
from app.core.permissions import CompanyContext, Permission, require
from app.exports import csv as csv_export
from app.exports import pdf as pdf_export
from app.exports import reports
from app.exports.reports import ExportParams
from app.services.analytics import Narrowing, RankBy

router = APIRouter(prefix="/companies/{company_id}/exports", tags=["exports"])
EXPORT = Depends(require(Permission.EXPORT))
FROM = Query(None, alias="from")  # `from` is a Python keyword
TO = Query(None, alias="to")
CLASS = Query(None, alias="class")
BY = Query([], description="Repeatable '<group_by option>:<key>'; key 'none' is the NULL bucket")

ReportName = StrEnum(  # type: ignore[misc]
    "ReportName", {name.upper().replace("-", "_"): name for name in reports.REPORTS}
)
Format = Literal["csv", "pdf"]
MEDIA: dict[str, str] = {"csv": "text/csv; charset=utf-8", "pdf": "application/pdf"}


def narrowing(
    customer: uuid.UUID | None = None,
    product: uuid.UUID | None = None,
    cost_centre: uuid.UUID | None = None,
    by: list[str] = BY,
) -> Narrowing:
    """The same filters and narrowing the screen sends (FR-4.3, D-053 #1, #2)."""
    return Narrowing(customer, product, cost_centre, tuple(by))


NARROW = Depends(narrowing)


def _disposition(report: str, fmt: str, covers: tuple[date, date]) -> str:
    date_from, date_to = covers
    return f'attachment; filename="{report}-{date_from.isoformat()}-to-{date_to.isoformat()}.{fmt}"'


async def _csv(ctx: CompanyContext, report: str, params: ExportParams) -> AsyncGenerator[str, None]:
    """Opens and closes its own snapshot session, so the stream never depends on when the
    framework tears down the request's dependencies (D-054)."""
    async with snapshot() as session:
        built = await reports.build(session, ctx, report, params)
        async for chunk in csv_export.render(built):
            yield chunk


async def _started(stream: AsyncGenerator[str, None]) -> AsyncIterator[str]:
    """Pulls the first chunk while we can still answer with a status code.

    Building the report is where a bad date range or an impossible stock period is found, and
    `StreamingResponse` sends the headers before it asks for a chunk - so an error raised then
    would arrive after a 200 had already gone out. Asking for the first chunk here keeps those
    refusals ordinary 4xx responses, with no file begun.
    """
    first = await anext(stream)

    async def rest() -> AsyncGenerator[str, None]:
        try:
            yield first
            async for chunk in stream:
                yield chunk
        finally:
            # A client that disconnects mid-download must still release the snapshot session.
            await stream.aclose()

    return rest()


@router.get("/{report}", summary="A report as CSV or PDF, with the figures shown on screen")
async def export(
    report: ReportName,
    format: Format = "csv",
    date_from: date | None = FROM,
    date_to: date | None = TO,
    granularity: Granularity = "month",
    group_by: str | None = None,
    include_cancelled: bool = False,
    include_missing: bool = False,
    rank_by: RankBy = "revenue",
    top_n: int | None = Query(None, ge=1, le=100),
    view_all: bool = False,
    period_days: int | None = None,
    movement_class: str | None = CLASS,
    narrow: Narrowing = NARROW,
    ctx: CompanyContext = EXPORT,
    session: AsyncSession = Depends(get_session),
) -> Response:
    name = str(report.value)
    params = ExportParams(
        date_from=date_from,
        date_to=date_to,
        granularity=granularity,
        group_by=group_by,
        include_cancelled=include_cancelled,
        include_missing=include_missing,
        narrow=narrow,
        rank_by=rank_by,
        top_n=top_n,
        view_all=view_all,
        period_days=period_days,
        movement_class=movement_class,
    )
    covers = await reports.effective_range(session, ctx, params)
    # LOG-1.1: an export is audited with the range of data it took, in the request's own
    # session, and committed before a byte is produced.
    await audit.record(
        session,
        company_id=ctx.company_id,
        user_id=ctx.user_id,
        action="EXPORT",
        entity_type="report",
        entity_id=name,
        data_range={
            "report": name,
            "format": format,
            "from": covers[0].isoformat(),
            "to": covers[1].isoformat(),
            "filters": {
                key: str(value)
                for key, value in (
                    ("customer", narrow.customer),
                    ("product", narrow.product),
                    ("cost_centre", narrow.cost_centre),
                    ("by", list(narrow.by) or None),
                    ("group_by", group_by),
                )
                if value
            },
        },
    )
    await session.commit()
    headers = {"Content-Disposition": _disposition(name, format, covers)}
    if format == "csv":
        body = await _started(_csv(ctx, name, params))
        return StreamingResponse(body, media_type=MEDIA["csv"], headers=headers)
    async with snapshot() as read:
        built = await reports.build(read, ctx, name, params)
        return Response(await pdf_export.render(built), media_type=MEDIA["pdf"], headers=headers)
