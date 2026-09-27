"""Tests never see the real date: the repo-wide fixture sets the clock (CLAUDE.md)."""

import time
from datetime import UTC, date, datetime, timedelta

import time_machine

from tally_contract.testing import FIXED_NOW


def test_every_test_starts_on_the_fixed_clock() -> None:
    now = datetime.now(UTC)
    assert FIXED_NOW <= now < FIXED_NOW + timedelta(minutes=10)  # it ticks from the fixed instant
    assert abs(time.time() - FIXED_NOW.timestamp()) < 600
    assert date.today() == FIXED_NOW.date()


def test_a_test_can_still_travel_to_the_moment_it_needs() -> None:
    moment = datetime(2024, 3, 31, 18, 29, tzinfo=UTC)
    with time_machine.travel(moment, tick=False):
        assert datetime.now(UTC) == moment
    assert datetime.now(UTC) >= FIXED_NOW
