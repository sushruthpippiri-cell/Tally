"""Dates, time zones and quarters (SRS 17.5). Everything uses company_timezone, never the
server's (TZ-1.1). Voucher dates are plain DATEs and are never shifted (D-020)."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Literal, NamedTuple
from zoneinfo import ZoneInfo

QuarterMode = Literal["financial", "calendar"]
Granularity = Literal["day", "month", "quarter"]


class Period(NamedTuple):
    start: date
    end: date  # inclusive
    label: str


def now_local(tz: str) -> datetime:
    return datetime.now(ZoneInfo(tz))


def today(tz: str) -> date:
    return now_local(tz).date()


def to_local_date(ts: datetime, tz: str) -> date:
    """The company-local day a timestamp belongs to (TZ-1.2)."""
    if ts.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return ts.astimezone(ZoneInfo(tz)).date()


def local_day_bounds(day: date, tz: str) -> tuple[datetime, datetime]:
    """[start, end) of a company-local day, in UTC."""
    zone = ZoneInfo(tz)
    start = datetime.combine(day, time(), zone)
    end = datetime.combine(day + timedelta(days=1), time(), zone)
    return start.astimezone(UTC), end.astimezone(UTC)


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    return date(d.year + y, m + 1, d.day)  # fy start day is 1-28 (validated on companies)


def financial_year_of(day: date, fy_start: date) -> Period:
    start = date(day.year, fy_start.month, fy_start.day)
    if day < start:
        start = date(day.year - 1, fy_start.month, fy_start.day)
    end = _add_months(start, 12) - timedelta(days=1)
    label = f"FY{start.year}" if start.year == end.year else f"FY{start.year}-{end.year % 100:02d}"
    return Period(start, end, label)


def financial_quarter_of(day: date, fy_start: date, mode: QuarterMode = "financial") -> Period:
    """Q-1.1/Q-1.2: quarters counted from fy_start, or calendar quarters when chosen."""
    year = financial_year_of(day, date(2000, 1, 1) if mode == "calendar" else fy_start)
    n = next(q for q in (4, 3, 2, 1) if _add_months(year.start, 3 * (q - 1)) <= day)
    start = _add_months(year.start, 3 * (n - 1))
    prefix = f"CY{year.start.year}" if mode == "calendar" else year.label
    return Period(start, _add_months(start, 3) - timedelta(days=1), f"{prefix} Q{n}")


def period_key(
    day: date, granularity: Granularity, fy_start: date, mode: QuarterMode = "financial"
) -> str:
    if granularity == "day":
        return day.isoformat()
    if granularity == "month":
        return f"{day.year}-{day.month:02d}"
    return financial_quarter_of(day, fy_start, mode).label
