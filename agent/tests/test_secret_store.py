"""D-042 #3 (owner): the credential is stored with DPAPI on Windows, never in a plain config
file; the data directory is readable only by the Agent's account (AGT-2.6)."""

import os
import stat
import sys
from pathlib import Path

import pytest

from tally_agent import security, state
from tally_agent.secret_store import CREDENTIAL, SecretStore

ACCOUNT = r"NT SERVICE\TallyAgent"  # absent on dev machines and CI: the current account stands in
windows = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI and ACLs exist only on Windows")
posix = pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")


def test_a_secret_round_trips_and_is_replaced(tmp_path: Path) -> None:
    store = SecretStore(tmp_path / "agent", ACCOUNT)
    assert store.load(CREDENTIAL) is None
    store.save(CREDENTIAL, "first-credential")
    store.save(CREDENTIAL, "rotated-credential")
    assert store.load(CREDENTIAL) == "rotated-credential"
    assert sorted(p.name for p in (tmp_path / "agent").iterdir()) == ["credential.bin"]


@posix
def test_off_windows_the_secret_file_is_owner_only_and_a_readable_one_is_refused(
    tmp_path: Path,
) -> None:
    store = SecretStore(tmp_path / "agent", ACCOUNT)
    store.save(CREDENTIAL, "secret")
    path = tmp_path / "agent" / "credential.bin"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(tmp_path / "agent").st_mode) == 0o700
    os.chmod(path, 0o644)
    with pytest.raises(security.InsecurePermissions):
        store.load(CREDENTIAL)


@windows
def test_on_windows_the_secret_is_dpapi_encrypted_in_machine_scope(tmp_path: Path) -> None:
    import pywintypes
    import win32crypt

    store = SecretStore(tmp_path / "agent", ACCOUNT)
    store.save(CREDENTIAL, "plain-credential-value")
    blob = (tmp_path / "agent" / "credential.bin").read_bytes()
    assert b"plain-credential-value" not in blob
    assert "plain-credential-value".encode("utf-16-le") not in blob
    with pytest.raises(pywintypes.error):  # without the Agent's entropy it does not decrypt
        win32crypt.CryptUnprotectData(blob, None, None, None, 0x1)
    assert store.load(CREDENTIAL) == "plain-credential-value"


@windows
def test_on_windows_the_data_directory_is_restricted_and_a_widened_one_is_refused(
    tmp_path: Path,
) -> None:
    import ntsecuritycon
    import win32security

    directory = security.private_dir(tmp_path / "agent", ACCOUNT)
    security.check(directory, ACCOUNT)
    widened = directory / "widened.txt"
    widened.write_text("x", encoding="utf-8")
    security.restrict(widened, ACCOUNT)
    descriptor = win32security.GetNamedSecurityInfo(
        str(widened), win32security.SE_FILE_OBJECT, win32security.DACL_SECURITY_INFORMATION
    )
    dacl = descriptor.GetSecurityDescriptorDacl()
    users = win32security.CreateWellKnownSid(win32security.WinBuiltinUsersSid, None)
    dacl.AddAccessAllowedAce(win32security.ACL_REVISION, ntsecuritycon.FILE_GENERIC_READ, users)
    win32security.SetNamedSecurityInfo(
        str(widened),
        win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION,
        None,
        None,
        dacl,
        None,
    )
    with pytest.raises(security.InsecurePermissions, match="Users"):
        security.check(widened, ACCOUNT)


def test_the_registration_state_holds_no_secret(tmp_path: Path) -> None:
    import uuid

    saved = state.AgentState(agent_id=uuid.uuid4(), company_guid="guid-1", company_name="Test Co")
    state.save(tmp_path / "agent", saved, ACCOUNT)
    assert state.load(tmp_path / "agent") == saved
    assert "credential" not in (tmp_path / "agent" / "state.json").read_text(encoding="utf-8")
