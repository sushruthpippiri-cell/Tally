"""P2.9: dates, time zones and quarters (SRS 17.5, D-020)."""

import os
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
import time_machine

from app.core import periods

KOLKATA = "Asia/Kolkata"
APR_1 = date(2024, 4, 1)
JAN_1 = date(2024, 1, 1)


@pytest.fixture(params=["UTC", "America/New_York", "Asia/Tokyo"])
def server_tz(request: pytest.FixtureRequest) -> Iterator[str]:
    """Run the test under several server time zones; results must not change."""
    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset is POSIX-only; the backend runs on Linux")
    old = os.environ.get("TZ")
    os.environ["TZ"] = request.param
    time.tzset()
    yield request.param
    if old is None:
        del os.environ["TZ"]
    else:
        os.environ["TZ"] = old
    time.tzset()


# The grouping rule is proven here; the SQL daily grouping that must use it: P8.
@pytest.mark.req_partial("AC-62", "TZ-1.1", "TZ-1.2")
def test_2358_ist_belongs_to_the_local_day(server_tz: str) -> None:
    event = datetime(2024, 6, 1, 18, 28, tzinfo=UTC)  # 23:58 IST on 1 June
    assert periods.to_local_date(event, KOLKATA) == date(2024, 6, 1)
    assert periods.period_key(periods.to_local_date(event, KOLKATA), "day", APR_1) == "2024-06-01"
    start, end = periods.local_day_bounds(date(2024, 6, 1), KOLKATA)
    assert start <= event < end
    assert start == datetime(2024, 5, 31, 18, 30, tzinfo=UTC)
    assert end == datetime(2024, 6, 1, 18, 30, tzinfo=UTC)
    # Two minutes later it is already 2 June in Kolkata.
    assert periods.to_local_date(datetime(2024, 6, 1, 18, 30, tzinfo=UTC), KOLKATA) == date(
        2024, 6, 2
    )


@pytest.mark.req_partial("TZ-1.1")  # aging "today" and schedules use it: P11, P3
def test_today_is_the_company_day_not_the_server_day(server_tz: str) -> None:
    with time_machine.travel(datetime(2024, 6, 1, 19, 0, tzinfo=UTC), tick=False):
        assert periods.today(KOLKATA) == date(2024, 6, 2)
        assert periods.today("America/Los_Angeles") == date(2024, 6, 1)
        assert periods.now_local(KOLKATA).utcoffset() is not None


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        periods.to_local_date(datetime(2024, 6, 1, 12, 0), KOLKATA)


@pytest.mark.req("Q-1.2")
@pytest.mark.req_partial("AC-63")  # quarter grouping of transactions: P8
@pytest.mark.parametrize(
    ("day", "label"),
    [
        (date(2024, 4, 1), "FY2024-25 Q1"),
        (date(2024, 6, 30), "FY2024-25 Q1"),
        (date(2024, 7, 1), "FY2024-25 Q2"),
        (date(2024, 8, 15), "FY2024-25 Q2"),  # AC-63: August -> Q2
        (date(2024, 10, 1), "FY2024-25 Q3"),
        (date(2024, 12, 31), "FY2024-25 Q3"),
        (date(2025, 1, 1), "FY2024-25 Q4"),
        (date(2024, 2, 29), "FY2023-24 Q4"),
        (date(2025, 3, 31), "FY2024-25 Q4"),
    ],
)
def test_financial_quarters_from_1_april(day: date, label: str) -> None:
    assert periods.financial_quarter_of(day, APR_1).label == label


@pytest.mark.req("Q-1.2")
@pytest.mark.parametrize(
    ("day", "label"),
    [
        (date(2024, 1, 1), "FY2024 Q1"),
        (date(2024, 2, 29), "FY2024 Q1"),
        (date(2024, 3, 31), "FY2024 Q1"),
        (date(2024, 4, 1), "FY2024 Q2"),
        (date(2024, 8, 15), "FY2024 Q3"),
        (date(2024, 12, 31), "FY2024 Q4"),
    ],
)
def test_1_january_start_gives_calendar_quarters(day: date, label: str) -> None:
    assert periods.financial_quarter_of(day, JAN_1).label == label


# The rule is proven; analytics reading analytics.quarter_mode per company: P8.
@pytest.mark.req_partial("Q-1.1")
def test_financial_by_default_calendar_when_chosen() -> None:
    august = date(2024, 8, 15)
    assert periods.financial_quarter_of(august, APR_1).label == "FY2024-25 Q2"
    q = periods.financial_quarter_of(august, APR_1, mode="calendar")
    assert (q.label, q.start, q.end) == ("CY2024 Q3", date(2024, 7, 1), date(2024, 9, 30))


def test_quarter_and_year_bounds() -> None:
    q = periods.financial_quarter_of(date(2025, 2, 10), APR_1)
    assert (q.start, q.end) == (date(2025, 1, 1), date(2025, 3, 31))
    fy = periods.financial_year_of(date(2025, 2, 10), APR_1)
    assert (fy.start, fy.end, fy.label) == (date(2024, 4, 1), date(2025, 3, 31), "FY2024-25")


def test_period_keys() -> None:
    d = date(2024, 8, 15)
    assert periods.period_key(d, "day", APR_1) == "2024-08-15"
    assert periods.period_key(d, "month", APR_1) == "2024-08"
    assert periods.period_key(d, "quarter", APR_1) == "FY2024-25 Q2"
    assert periods.period_key(d, "quarter", APR_1, mode="calendar") == "CY2024 Q3"
