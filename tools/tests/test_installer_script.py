"""P16.8: the Inno Setup script says what the Agent needs (D-042 #3, D-043 #3/#4).

Compiling it needs Windows, and `agent-build` is manual-only because Windows minutes cost twice
as much (D-038 #7). These checks run free on Linux and catch the errors most likely to reach the
owner's real PC otherwise: a `{code:...}` naming a function that does not exist, a [Run] entry
pointing at a file the build never stages, and a regression in the three behaviours the task
specifies (the virtual service account, the locked-down data folder, and an uninstall that
leaves the queue).
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
ISS = ROOT / "agent/packaging/TallyAgent.iss"
WORKFLOW = ROOT / ".github/workflows/agent-build.yml"
_RAW = ISS.read_text(encoding="utf-8")


def _expanded() -> str:
    """The script with its `#define`s substituted, as ISCC sees it. Asserting on the macro
    names instead would pass even if a define were changed to the wrong value."""
    text = _RAW
    for name, value in re.findall(r'^#define\s+(\w+)\s+"([^"]*)"', _RAW, re.M):
        text = text.replace("{#" + name + "}", value)
    return text


SOURCE = _expanded()


def _section(name: str) -> str:
    match = re.search(rf"^\[{name}\]\n(.*?)(?=^\[|\Z)", SOURCE, re.S | re.M)
    return match.group(1) if match else ""


def test_the_sections_the_installer_needs_are_all_present() -> None:
    for name in ("Setup", "Files", "Dirs", "Run", "UninstallRun", "Code"):
        assert _section(name).strip(), f"[{name}] is missing or empty"


def test_every_code_reference_names_a_function_that_exists() -> None:
    """`{code:GetToken}` compiles only if GetToken does; a typo here would otherwise be found
    by the owner, mid-install, with the wizard's answers already typed in."""
    referenced = set(re.findall(r"\{code:(\w+)\}", SOURCE))
    defined = set(re.findall(r"^function\s+(\w+)\s*\(", _section("Code"), re.M))
    assert referenced, "no {code:...} parameters found - has the wizard gone?"
    assert referenced <= defined, f"no such function: {sorted(referenced - defined)}"


def test_every_check_names_a_function_that_exists() -> None:
    checks = set(re.findall(r"Check:\s*(\w+)", SOURCE))
    defined = set(re.findall(r"^function\s+(\w+)\s*\(", _section("Code"), re.M))
    assert checks <= defined, f"no such Check function: {sorted(checks - defined)}"


def test_the_installer_runs_only_executables_the_build_stages() -> None:
    """A [Run] line naming a file PyInstaller does not produce fails at install time, not build
    time."""
    staged = {"tally-agent.exe", "tally-agent-service.exe"}
    for section in ("Run", "UninstallRun"):
        for filename in re.findall(r"Filename:\s*\"\{app\}\\([\w.-]+)\"", _section(section)):
            assert filename in staged, f"{filename} is not staged by agent-build.yml"


@pytest.mark.req("AGT-2.6")
def test_the_data_folder_is_restricted_to_the_service_account() -> None:
    """The queue, the logs and the DPAPI-encrypted credential live there. Inheritance must be
    broken, or the machine's default "Users: read" applies to all of it."""
    run = _section("Run")
    assert "icacls.exe" in run
    assert "/inheritance:r" in run, "without this the folder keeps the machine's default ACL"
    assert "NT SERVICE\\TallyAgent" in run  # the service account
    assert "*S-1-5-18" in run  # SYSTEM
    assert "*S-1-5-32-544" in run  # Administrators


def test_the_service_runs_as_a_virtual_account_and_not_localsystem() -> None:
    """A read-only Tally reader has no business being LocalSystem."""
    run = _section("Run")
    # Inno escapes a quote by doubling it, so the parameter reads obj= ""NT SERVICE\TallyAgent"".
    assert re.search(r'obj=\s*"+NT SERVICE\\TallyAgent"+', run), "the service account is not set"
    # The comment explaining the choice names it; no directive may select it.
    assert not re.search(r'obj=\s*"*LocalSystem', SOURCE)
    assert "start= delayed-auto" in run, "TallyPrime and the network should be up first"


def test_the_service_restarts_itself_after_a_failure() -> None:
    """An Agent that dies overnight should be running by morning without a site visit."""
    assert "failure TallyAgent reset= 86400 actions= restart/" in _section("Run")


@pytest.mark.req("AGT-2.6")
def test_an_upgrade_keeps_the_configuration_credential_and_queue() -> None:
    """Re-registering would issue a second Agent for the same machine, and wiping the queue
    would lose records already read from Tally."""
    code = _section("Code")
    assert "function IsUpgrade" in code
    assert "agent.toml" in code, "the upgrade check looks for an existing configuration"
    assert "function ShouldRegister" in code
    assert "not AlreadyConfigured" in code
    # The data folder is never in [Files] or an uninstall delete.
    assert "{commonappdata}" not in _section("Files")


def test_uninstall_removes_the_service_and_leaves_the_data_folder() -> None:
    """D-043 #4: the queue and the logs are how anyone finds out why the Agent was removed, and
    the credential is useless once revoked in the dashboard."""
    uninstall = _section("UninstallRun")
    assert "stop TallyAgent" in uninstall and "delete TallyAgent" in uninstall
    assert "{commonappdata}" not in uninstall, "the data folder must survive an uninstall"
    assert "rmdir" not in uninstall.lower()


def test_the_installer_is_x64_only() -> None:
    """D-043 #3: the Agent is a 64-bit build, and the launch requirement is real x64 hardware."""
    setup = _section("Setup")
    assert "ArchitecturesAllowed=x64compatible" in setup
    assert "ArchitecturesInstallIn64BitMode=x64compatible" in setup


def test_the_wizard_asks_for_everything_registration_needs() -> None:
    """The CLI's `register` needs all six; a wizard that collects five fails after the files are
    already copied."""
    code = _section("Code")
    for prompt in ("Backend URL", "name for this Agent", "Registration token"):
        assert prompt in code, f"the wizard does not ask for: {prompt}"
    for prompt in ("Tally company name", "Tally host", "Tally port"):
        assert prompt in code, f"the wizard does not ask for: {prompt}"
    # And it checks them before the install starts, not after.
    assert "function NextButtonClick" in code
    assert "https://" in code, "the backend URL must be https (SEC-2.0)"


def test_signing_is_absent_and_said_to_be_absent() -> None:
    """P16.8a needs an EV certificate in a hardware token or HSM, which does not exist yet.
    A half-configured SignTool line would either fail every build or, worse, silently produce
    unsigned installers that look configured."""
    # The comment explaining why may mention it; a directive must not exist.
    assert not re.search(r"^\s*SignTool\s*=", SOURCE, re.M)
    assert not re.search(r"^\s*SignedUninstaller\s*=", SOURCE, re.M)
    assert "P16.8a" in SOURCE, "the script should say why it is unsigned"


def test_ci_compiles_the_installer() -> None:
    """The one real check available without a Windows machine. If this step is ever removed, an
    .iss that does not compile could ship."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "innosetup" in workflow and "ISCC.exe" in workflow
    assert "TallyAgent.iss" in workflow
