"""Files on the customer's PC readable only by the Agent (AGT-2.6, D-042 #3).

Windows: a protected DACL for the service account, SYSTEM and Administrators (administrators can
take ownership of any file anyway, and the elevated CLI must write). When the service account
does not exist (development, CI) the current account stands in for it. Elsewhere (development
and CI only): 0700 directories, 0600 files.
"""

import os
import stat
import sys
from pathlib import Path


class InsecurePermissions(Exception):
    pass


if sys.platform == "win32":  # pragma: no cover - exercised on the agent-windows CI job
    import ntsecuritycon
    import pywintypes
    import win32api
    import win32security

    def _allowed_sids(service_account: str) -> list[object]:
        try:
            service = win32security.LookupAccountName(None, service_account)[0]
        except pywintypes.error:
            token = win32security.OpenProcessToken(
                win32api.GetCurrentProcess(), win32security.TOKEN_QUERY
            )
            service = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        return [
            service,
            win32security.CreateWellKnownSid(win32security.WinLocalSystemSid, None),
            win32security.CreateWellKnownSid(win32security.WinBuiltinAdministratorsSid, None),
        ]

    def restrict(path: Path, service_account: str) -> None:
        dacl = win32security.ACL()
        inherit = (
            win32security.OBJECT_INHERIT_ACE | win32security.CONTAINER_INHERIT_ACE
            if path.is_dir()
            else 0
        )
        for sid in _allowed_sids(service_account):
            dacl.AddAccessAllowedAceEx(
                win32security.ACL_REVISION, inherit, ntsecuritycon.FILE_ALL_ACCESS, sid
            )
        win32security.SetNamedSecurityInfo(
            str(path),
            win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION
            | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
            None,
            None,
            dacl,
            None,
        )

    def check(path: Path, service_account: str) -> None:
        allowed = {str(s) for s in _allowed_sids(service_account)}
        descriptor = win32security.GetNamedSecurityInfo(
            str(path), win32security.SE_FILE_OBJECT, win32security.DACL_SECURITY_INFORMATION
        )
        dacl = descriptor.GetSecurityDescriptorDacl()
        if dacl is None:
            raise InsecurePermissions(f"{path} has no access list: everyone can read it")
        for i in range(dacl.GetAceCount()):
            sid = dacl.GetAce(i)[2]
            if str(sid) not in allowed:
                name = win32security.LookupAccountSid(None, sid)
                raise InsecurePermissions(f"{path} is readable by {name[1]}\\{name[0]}")

else:

    def restrict(path: Path, service_account: str) -> None:
        os.chmod(path, 0o700 if path.is_dir() else 0o600)

    def check(path: Path, service_account: str) -> None:
        if os.stat(path).st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise InsecurePermissions(f"{path} is accessible to other users")


def private_dir(path: Path, service_account: str) -> Path:
    """Create (if needed) and restrict the Agent's data directory."""
    path.mkdir(parents=True, exist_ok=True)
    restrict(path, service_account)
    return path
