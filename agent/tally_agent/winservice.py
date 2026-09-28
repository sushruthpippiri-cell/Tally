"""The Windows service (P7.9, D-043 #3): the same loop as `tally-agent run`, started by the
Service Control Manager as NT SERVICE\\TallyAgent. Built into tally-agent-service.exe; installed
by packaging/Install-TallyAgent.ps1. Windows only."""

import sys

assert sys.platform == "win32", "the Windows service runs on Windows only"

import servicemanager  # noqa: E402
import win32service  # noqa: E402
import win32serviceutil  # noqa: E402

from tally_agent import config, logging_setup  # noqa: E402
from tally_agent.service import Agent  # noqa: E402

SERVICE_NAME = "TallyAgent"


class TallyAgentService(win32serviceutil.ServiceFramework):  # type: ignore[misc]
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = "Tally Analytics Sync Agent"
    _svc_description_ = (
        "Reads TallyPrime (read-only) and uploads to Tally Analytics over HTTPS. "
        "Run `tally-agent status` for its state."
    )

    agent: Agent | None = None

    def SvcStop(self) -> None:  # noqa: N802 - the Service Control Manager's name
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        if self.agent is not None:
            self.agent.stop.set()

    def SvcDoRun(self) -> None:  # noqa: N802
        settings = config.load(config.config_path(config.default_data_dir()))
        logging_setup.setup(settings.data_dir, settings.service_account)
        self.agent = Agent(settings)
        servicemanager.LogInfoMsg(f"{self._svc_display_name_} started")
        self.agent.run_forever()
        servicemanager.LogInfoMsg(f"{self._svc_display_name_} stopped")


def main() -> None:
    if len(sys.argv) == 1:  # started by the Service Control Manager
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(TallyAgentService)
        servicemanager.StartServiceCtrlDispatcher()
    else:  # install / remove / debug from a console
        win32serviceutil.HandleCommandLine(TallyAgentService)
