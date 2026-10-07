"""Request rate limits (SEC-1.9), counted in Postgres so every replica shares one count.

Used by the HTTP middleware to count a request and by `app.jobs.retention` to purge windows
that have finished - both need the same idea of where a window starts, so it lives here.
"""

import time
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import session_factory


def window_start(now: float, seconds: int) -> datetime:
    """The start of the fixed window `now` falls in. Wall-clock, so every replica agrees;
    `app.jobs.retention` purges by the same boundary."""
    return datetime.fromtimestamp(int(now // seconds) * seconds, UTC)


_COUNT = text(
    """
    INSERT INTO rate_limit_counters AS c (bucket_key, window_start, count)
    VALUES (:key, :window_start, 1)
    ON CONFLICT (bucket_key, window_start) DO UPDATE SET count = c.count + 1
    RETURNING c.count
    """
)


class RateLimiter:
    """Fixed wall-clock windows per key, counted in Postgres so every replica shares one count.

    P16.11 (D-033 #3, SEC-1.9): the counters used to live in each process's memory, which let N
    replicas allow N x the limit. The window comes from the wall clock, never `time.monotonic`,
    whose origin is per-process - two replicas would never agree on a window.

    `_over` short-circuits a key already over its limit for the current window, so a flood costs
    one database round-trip rather than one per request. It can only skip writes for a key that
    has already been refused, so it never undercounts.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.time,
        seconds: int = 60,
        factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._clock, self._seconds, self._factory = clock, seconds, factory
        self._over: dict[str, int] = {}  # key -> the window in which it went over

    def _window(self, now: float) -> int:
        return int(now // self._seconds)

    def _retry_after(self, now: float) -> int:
        return max(1, self._seconds - int(now % self._seconds))

    async def hit(self, key: str, limit: int) -> int | None:
        """Count one request; seconds until the window resets if over the limit, else None."""
        now = self._clock()
        window = self._window(now)
        if self._over.get(key) == window:
            return self._retry_after(now)
        if len(self._over) > 50_000:  # drop keys from finished windows
            self._over = {k: w for k, w in self._over.items() if w == window}
        start = window_start(now, self._seconds)
        factory = self._factory or session_factory()
        async with factory() as session, session.begin():
            count = await session.scalar(_COUNT, {"key": key, "window_start": start})
        if count is not None and count > limit:
            self._over[key] = window
            return self._retry_after(now)
        return None
