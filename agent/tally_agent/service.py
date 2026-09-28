"""The Agent's main loop (P7.5, P7.7): heartbeat every poll interval (±10%), run the command
the backend offers, and report status.

Each heartbeat carries versions, Tally's status, uptime and the company GUID it confirmed, and
the queue's status (AGT-1.1, VER-1.1, AGT-6.3, AGT-2.4). The uploader runs on its own thread
throughout; a command gets its own progress thread (D-042 #1).
"""

import random
import threading
from typing import Any

from tally_agent import AGENT_VERSION, state
from tally_agent.backend_client import (
    AgentRevoked,
    BackendClient,
    BackendError,
    BackendUnavailable,
    CredentialInvalid,
)
from tally_agent.config import AgentSettings
from tally_agent.executor import Executor, Outcome
from tally_agent.progress import ProgressTimer
from tally_agent.protocol import AgentConfig
from tally_agent.queue import Limits, Queue
from tally_agent.secret_store import CREDENTIAL, PROXY, SecretStore
from tally_agent.tally_client import TallyClient, TallyError
from tally_agent.tally_process import ProcessTable, uptime_seconds
from tally_agent.uploader import Uploader
from tally_contract import tally_constants as tc
from tally_contract.errors import ErrorCode
from tally_contract.log import get_logger

log = get_logger(__name__)

# D-025: what the heartbeat may say about Tally
TALLY_STATUSES = {
    ErrorCode.TALLY_UNREACHABLE,
    ErrorCode.TALLY_SERVER_DISABLED,
    ErrorCode.TDL_NOT_LOADED,
    ErrorCode.COMPANY_NOT_LOADED,
    ErrorCode.COMPANY_MISMATCH,
}


class Agent:
    def __init__(
        self,
        settings: AgentSettings,
        *,
        tally: TallyClient | None = None,
        processes: ProcessTable | None = None,
        queue_limits: Limits | None = None,
    ) -> None:
        saved = state.load(settings.data_dir)
        if saved is None:
            raise RuntimeError("This Agent is not registered: run `tally-agent register` first")
        self.settings, self.state = settings, saved
        self.store = SecretStore(settings.data_dir, settings.service_account)
        self.queue = Queue(settings.data_dir, settings.service_account, queue_limits)
        config = self.config
        self.tally = tally or TallyClient(
            config.tally_host,
            config.tally_port,
            timeout_seconds=settings.tally_timeout_seconds,
            process_name=settings.tally_process_name,
            processes=processes,
        )
        self.stop = threading.Event()
        self.revoked = False
        self._current_lost: threading.Event | None = None
        self.last_outcome: Outcome | None = None

    @property
    def config(self) -> AgentConfig:
        return AgentConfig.model_validate(self.state.backend_config)

    def backend(self) -> BackendClient:
        """A fresh client with the stored credential, so `set-credential` takes effect."""
        return BackendClient(
            self.settings,
            credential=self.store.load(CREDENTIAL),
            proxy_credentials=self.store.load(PROXY),
        )

    # --- heartbeat (P7.7) -----------------------------------------------------------------

    def heartbeat_payload(self) -> dict[str, Any]:
        status, confirmed = "OK", None
        try:
            info = self.tally.info(self.config.tally_company_name)
            confirmed = info.company_guid
            if info.company_guid != self.state.company_guid:
                status = ErrorCode.COMPANY_MISMATCH.value
            elif info.tdl_version != tc.TDL_VERSION:
                status = ErrorCode.TDL_NOT_LOADED.value
        except TallyError as exc:
            code = exc.code if exc.code in TALLY_STATUSES else ErrorCode.TALLY_UNREACHABLE
            status = code.value
        process = self.tally.processes.find(self.settings.tally_process_name)
        return {
            "agent_version": AGENT_VERSION,
            "tdl_version": tc.TDL_VERSION,
            "tally_version": None,  # VER-1.3: not read until a live capture shows where it is
            "tally_uptime_seconds": uptime_seconds(process),
            "queue_status": self.queue.status().payload(),
            "tally_status": status,
            "confirmed_tally_guid": confirmed,
        }

    def tick(self) -> None:
        """One heartbeat, and the command it offers, if any."""
        backend = self.backend()
        try:
            answer = backend.call("POST", "/agent/heartbeat", self.heartbeat_payload())
        except CredentialInvalid:
            log.error(
                "credential_invalid", hint="enter the new one with `tally-agent set-credential`"
            )
            return
        except AgentRevoked:
            log.error("agent_revoked", hint="this installation must re-register as a new Agent")
            self.revoked = True
            self.stop.set()
            return
        except (BackendUnavailable, BackendError) as exc:
            log.warning("heartbeat_failed", error=str(exc))
            return
        finally:
            backend.close()
        if answer.get("config") and answer["config"] != self.state.backend_config:
            self.state.backend_config = answer["config"]  # the backend owns these values
            state.save(self.settings.data_dir, self.state, self.settings.service_account)
        if answer.get("status") == "ACTIVE" and answer.get("command"):
            self.last_outcome = self.run_command(answer["command"])

    # --- one command ------------------------------------------------------------------------

    def run_command(self, command: dict[str, Any]) -> Outcome | None:
        command_id = command["command_id"]
        backend = self.backend()
        try:
            try:
                backend.call("POST", f"/agent/commands/{command_id}/claim")
            except BackendError as exc:  # someone else, expired, or one in progress
                log.info("command_not_claimed", command_id=command_id, code=exc.code)
                return None
            lost = threading.Event()
            self._current_lost = lost
            timer = ProgressTimer(
                self.backend, command_id, self.config.progress_interval_seconds, lost
            )
            timer.start()
            try:
                while not timer.running.wait(0.1):  # the first progress makes it RUNNING
                    if lost.is_set() or not timer.is_alive():
                        return None
                outcome = Executor(
                    settings=self.settings,
                    config=self.config,
                    registered_guid=self.state.company_guid,
                    backend=backend,
                    tally=self.tally,
                    queue=self.queue,
                    lost=lost,
                ).execute(command)
            finally:
                timer.stop()
                self._current_lost = None
            if outcome.status is None or lost.is_set():
                log.warning("command_abandoned", command_id=command_id)
                return outcome
            body: dict[str, Any] = {"status": outcome.status}
            if outcome.status == "FAILED":
                body |= {"error_code": outcome.error_code, "error_message": outcome.message}
            try:
                backend.call("POST", f"/agent/commands/{command_id}/result", body)
            except BackendError as exc:
                log.warning("result_refused", command_id=command_id, code=exc.code)
            return outcome
        finally:
            backend.close()

    def on_lost(self, command_id: str) -> None:
        """The uploader learned the command is over (D-039): the executor stops too."""
        if self._current_lost is not None:
            self._current_lost.set()

    # --- the service ----------------------------------------------------------------------------

    def run_forever(self) -> None:
        uploader = Uploader(self.queue, self.backend, self.stop, on_lost=self.on_lost)
        thread = threading.Thread(target=uploader.run, name="uploader", daemon=True)
        thread.start()
        log.info("agent_started", agent_id=str(self.state.agent_id), version=AGENT_VERSION)
        while not self.stop.is_set():
            self.tick()
            interval = self.config.poll_interval_seconds * random.uniform(0.9, 1.1)  # AGT-1.1
            self.stop.wait(interval)
        thread.join(timeout=10)
        log.info("agent_stopped", revoked=self.revoked)
