"""Is TallyPrime running, and for how long (AGT-6.3)? Read from the process table. The table
is injectable, so tests decide what is running."""

import time
from dataclasses import dataclass
from typing import Protocol

import psutil


@dataclass(frozen=True)
class TallyProcess:
    pid: int
    started_at: float  # seconds since the epoch, from the process table


class ProcessTable(Protocol):
    def find(self, name: str) -> TallyProcess | None: ...


class SystemProcesses:
    def find(self, name: str) -> TallyProcess | None:
        wanted = name.lower()
        found = [
            TallyProcess(p.info["pid"], p.info["create_time"])
            for p in psutil.process_iter(["pid", "name", "create_time"])
            if (p.info["name"] or "").lower() == wanted
        ]
        return min(found, key=lambda p: p.started_at) if found else None  # the longest-running


def uptime_seconds(process: TallyProcess | None) -> int | None:
    """Sent to the backend as a duration, never as a time: the PC's clock is not trusted
    for anything the backend compares (D-042 #5)."""
    if process is None:
        return None
    return max(0, int(time.time() - process.started_at))
