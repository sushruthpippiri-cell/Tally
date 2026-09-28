"""The command lease, kept alive on its own thread (AGT-1.7, D-035 #11, D-042 #1).

It never waits on Tally or the parser: a 10-minute Tally export, or a long parse, cannot make
the command lapse. The first call moves the command CLAIMED -> RUNNING. A 409/404 means the
command is over (lost, or finished elsewhere): `lost` is set and the executor stops.
"""

import threading
from collections.abc import Callable

from tally_agent.backend_client import BackendClient, BackendError, BackendUnavailable
from tally_contract.log import get_logger

log = get_logger(__name__)


class ProgressTimer(threading.Thread):
    def __init__(
        self,
        backend: Callable[[], BackendClient],
        command_id: str,
        interval_seconds: float,
        lost: threading.Event,
    ) -> None:
        super().__init__(name=f"progress-{command_id}", daemon=True)
        self._backend_factory, self._command_id = backend, command_id
        self._interval, self.lost = interval_seconds, lost
        self.running = threading.Event()  # set once the command is RUNNING
        self._halt = threading.Event()
        self.calls = 0

    def stop(self) -> None:
        self._halt.set()
        self.join()

    def run(self) -> None:
        backend = self._backend_factory()
        try:
            while not self._halt.is_set():
                try:
                    backend.call("POST", f"/agent/commands/{self._command_id}/progress")
                    self.calls += 1
                    self.running.set()
                except BackendError as exc:
                    log.warning(
                        "command_lost",
                        command_id=self._command_id,
                        status=exc.status,
                        code=exc.code,
                    )
                    self.lost.set()
                    return
                except (
                    BackendUnavailable
                ) as exc:  # keep trying: the lease is several intervals long
                    log.warning("progress_failed", command_id=self._command_id, error=str(exc))
                if self._halt.wait(self._interval):
                    return
        finally:
            backend.close()
