"""The Agent credential and proxy credentials (D-042 #3).

Windows: DPAPI in machine scope with Agent-specific entropy, so the service account can decrypt
what the installing person encrypted; the file's ACL (security.py) is what keeps other local
users out. Never written to agent.toml. Off Windows (development and CI only): the value in a
0600 file, refused if anyone else can read it.
"""

import os
import sys
from pathlib import Path

from tally_agent import security

ENTROPY = b"tally-agent/credential/v1"

if sys.platform == "win32":  # pragma: no cover - exercised on the agent-windows CI job
    import win32crypt

    _FLAGS = 0x1 | 0x4  # CRYPTPROTECT_UI_FORBIDDEN | CRYPTPROTECT_LOCAL_MACHINE

    def protect(data: bytes) -> bytes:
        blob: bytes = win32crypt.CryptProtectData(data, "tally-agent", ENTROPY, None, None, _FLAGS)
        return blob

    def unprotect(blob: bytes) -> bytes:
        data: bytes = win32crypt.CryptUnprotectData(blob, ENTROPY, None, None, _FLAGS)[1]
        return data

else:

    def protect(data: bytes) -> bytes:
        return data

    def unprotect(blob: bytes) -> bytes:
        return blob


class SecretStore:
    def __init__(self, data_dir: Path, service_account: str) -> None:
        self._dir = data_dir
        self._account = service_account

    def _path(self, name: str) -> Path:
        return self._dir / f"{name}.bin"

    def save(self, name: str, value: str) -> None:
        security.private_dir(self._dir, self._account)
        path, tmp = self._path(name), self._path(name).with_suffix(".tmp")
        tmp.write_bytes(b"")
        security.restrict(tmp, self._account)  # restricted before the secret is written
        tmp.write_bytes(protect(value.encode("utf-8")))
        os.replace(tmp, path)

    def load(self, name: str) -> str | None:
        path = self._path(name)
        if not path.exists():
            return None
        security.check(path, self._account)
        return unprotect(path.read_bytes()).decode("utf-8")

    def delete(self, name: str) -> None:
        self._path(name).unlink(missing_ok=True)


CREDENTIAL = "credential"
PROXY = "proxy"  # "user:password" for a basic-auth proxy
