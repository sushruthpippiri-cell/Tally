# PyInstaller: one folder, two executables (D-043 #3). Built by the manual `agent-build`
# workflow on an x64 Windows runner:  pyinstaller agent/packaging/tally-agent.spec --noconfirm
# ruff: noqa
from pathlib import Path

root = Path(SPECPATH).parents[1]  # the repository
hidden = ["win32timezone", "tally_agent.winservice"]
# The TDL files, install scripts and guide are copied next to the executables by the
# agent-build workflow (not bundled: PyInstaller would put them under _internal\).

cli = Analysis([str(root / "agent" / "packaging" / "cli_entry.py")], hiddenimports=hidden)
svc = Analysis([str(root / "agent" / "packaging" / "service_entry.py")], hiddenimports=hidden)
MERGE((cli, "tally-agent", "tally-agent"), (svc, "tally-agent-service", "tally-agent-service"))

cli_exe = EXE(PYZ(cli.pure), cli.scripts, [], exclude_binaries=True, name="tally-agent", console=True)
svc_exe = EXE(PYZ(svc.pure), svc.scripts, [], exclude_binaries=True, name="tally-agent-service", console=True)
COLLECT(cli_exe, cli.binaries, cli.datas, svc_exe, svc.binaries, svc.datas, name="TallyAgent")
