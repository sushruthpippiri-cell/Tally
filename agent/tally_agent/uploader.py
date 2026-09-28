"""Uploads the queue, first in first out, on its own thread (AGT-2.x, D-042 #1, #6).

- success: the item is removed
- 401 CREDENTIAL_INVALID: paused (nothing counted) until `set-credential` stores a new one
- 403 AGENT_REVOKED: stops
- 409 INVALID_COMMAND_STATE / SYNC_LOCKED: the run's command is over (D-039); its items are
  obsolete and the run's lost-flag is raised so the executor stops too
- other 4xx: the item can never be accepted; dead-lettered at once with the rest of its run
  and collection (retrying would hold the whole queue for hours)
- network trouble or 5xx: backoff, then dead-letter after `max_attempts`
"""

import threading
from collections.abc import Callable

from tally_agent.backend_client import (
    AgentRevoked,
    BackendClient,
    BackendError,
    BackendUnavailable,
    CredentialInvalid,
)
from tally_agent.queue import BATCH, Item, Queue
from tally_contract.log import get_logger

log = get_logger(__name__)
OVER = {"INVALID_COMMAND_STATE", "SYNC_LOCKED"}


class Uploader:
    def __init__(
        self,
        queue: Queue,
        backend: Callable[[], BackendClient],
        stop: threading.Event,
        on_lost: Callable[[str], None] = lambda command_id: None,
        idle_seconds: float = 0.5,
    ) -> None:
        self._queue, self._backend_factory, self._stop = queue, backend, stop
        self._on_lost, self._idle = on_lost, idle_seconds
        self.paused = False  # a rotated credential is waiting to be entered
        self.revoked = False

    def run(self) -> None:
        backend = self._backend_factory()
        while not self._stop.is_set():
            if self.paused:  # set-credential stores a new one; pick it up
                backend.close()
                backend = self._backend_factory()
                self.paused = False
            if not self.step(backend):
                self._stop.wait(self._idle)
        backend.close()

    def step(self, backend: BackendClient) -> bool:
        """Upload the head item if it is due. True when something was uploaded or settled."""
        item = self._queue.head()
        if item is None:
            return False
        kind = "batches" if item.kind == BATCH else "key-lists"
        try:
            backend.call("POST", f"/agent/commands/{item.command_id}/{kind}", item.body)
        except CredentialInvalid:
            log.error(
                "credential_invalid", hint="enter the new one with `tally-agent set-credential`"
            )
            self.paused = True
            self._stop.wait(30)
            return False
        except AgentRevoked:
            log.error("agent_revoked", hint="this installation must re-register as a new Agent")
            self.revoked = True
            self._stop.set()
            return False
        except BackendError as exc:
            self._refused(item, exc)
            return True
        except BackendUnavailable as exc:
            self._queue.failed(item, str(exc))
            return False
        self._queue.done(item)
        return True

    def _refused(self, item: Item, exc: BackendError) -> None:
        if exc.status == 409 and exc.code in OVER:
            self._queue.drop_run(item.sync_run_id, f"{exc.code}: {exc.message}")
            self._on_lost(item.command_id)
        else:
            self._queue.dead_letter(item, f"{exc.status} {exc.code}: {exc.message}")
