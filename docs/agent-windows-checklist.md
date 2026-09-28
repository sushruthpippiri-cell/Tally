# Agent on a real Windows machine — checklist (P7.9, D-043 #3)

**Status: PENDING.** Everything here needs Windows itself and is not proven by CI:
- the service running as `NT SERVICE\TallyAgent`
- DPAPI across accounts (encrypt as the installing user, decrypt as the service)
- the ACLs
- real TallyPrime

Run it in the Windows 11 ARM VM (the Agent's x64 build runs under Windows' x64 emulation, as
TallyPrime does). **Repeat it on a real x64 Windows PC before launch** (Phase 16, with the
PERF-VAL-1 benchmark).

Use the **test company** from the capture kit, never a real business's books.

Tick each box, note anything unexpected in the *Notes* column, and send this file back.

## What you need
- **The Agent build:** `TallyAgent-windows-x64.zip`, made by the `agent-build` workflow; where it
  is on your Mac is in `docs/progress.md`. Copy it into the VM the same way as the capture kit.
- **On the Mac, the backend over HTTPS.** The Agent refuses plain HTTP to another machine:
  ```bash
  make up                              # Postgres (+ the http backend on :8000, not used here)
  make migrate
  cd backend && uv run python -m app.cli create-owner --email you@example.com --name You && cd ..
  make dev-tls HOST=<the Mac's LAN IP, e.g. 192.168.1.20>
  make dev-https                       # leave running: https://<IP>:8443
  uv run python -m tally_tools.dev_backend setup --url https://<IP>:8443 \
      --email you@example.com --company "<test company exactly as in TallyPrime>"
  ```
  Keep the printed **registration token**, and copy `dev-https/ca.pem` into the VM (for example to
  `C:\TallyAgentTest\ca.pem`).
- **In the VM:** TallyPrime running with the test company open, its XML server on port 9000, and
  **`tdl\TallyAnalytics.tdl` from the Agent zip** loaded (it must be this Agent's version).

## Steps

| # | Do | Expect | Done | Notes |
|---|---|---|---|---|
| 1 | Unzip `TallyAgent-windows-x64.zip`. In **Windows PowerShell as administrator**, in the unzipped `TallyAgent` folder: `powershell -ExecutionPolicy Bypass -File .\Install-TallyAgent.ps1` | "Installed." and the next steps printed; **Services** lists *Tally Analytics Sync Agent*, Log On As = `NT SERVICE\TallyAgent`, startup = Automatic (Delayed Start) | [ ] | |
| 2 | `icacls C:\ProgramData\TallyAgent` | Exactly three entries, each `(OI)(CI)(F)`: `NT SERVICE\TallyAgent`, `NT AUTHORITY\SYSTEM`, `BUILTIN\Administrators`. No `Users`, no `Everyone` | [ ] | |
| 3 | Same administrator window: `& "C:\Program Files\TallyAgent\tally-agent.exe" register --token <token> --name "VM Agent" --backend-url https://<IP>:8443 --company "<test company>" --ca-bundle C:\TallyAgentTest\ca.pem` | "Registered as Agent … for '<company>'". **This encrypts the credential as you, the installing user** | [ ] | |
| 4 | `& "C:\Program Files\TallyAgent\tally-agent.exe" status`, then `test-tally` | Registered; Credential: stored; TallyPrime reachable, TDL `0.1.0`, the company's GUID | [ ] | |
| 5 | **The cross-account check.** `sc.exe start TallyAgent`, wait 1 minute, then open `C:\ProgramData\TallyAgent\logs\agent.log` | `agent_started`, and no `credential_invalid` or DPAPI error: **the service account decrypted what you encrypted.** On the Mac, `dev_backend call GET /companies/{company}/agents` (below) shows the Agent ACTIVE | [ ] | |
| 6 | On the Mac: `uv run python -m tally_tools.dev_backend sync --url https://<IP>:8443 --email you@example.com --mode FULL`, wait about a minute, then `dev_backend call GET /companies/{company}/sync/runs` | No errors in `agent.log`; the latest run is COMPLETED (or PARTIAL, with its reasons in `call GET /companies/{company}/sync/errors`) | [ ] | |
| 7 | As a **standard (non-administrator) Windows user** (e.g. `runas /user:<standard user> powershell`): `type C:\ProgramData\TallyAgent\credential.bin` and `type C:\ProgramData\TallyAgent\queue.db` | **Access is denied** for both (AGT-2.6) | [ ] | |
| 8 | Rotate: on the Mac, `dev_backend call POST /companies/{company}/agents/<agent id from step 5>/rotate-credential` prints the new credential. In the VM (administrator): `tally-agent set-credential` (paste it), then `sc.exe stop TallyAgent` and `sc.exe start TallyAgent` | The Agent is ACTIVE again (step 5's call); `agent.log` shows no `credential_invalid` after the restart | [ ] | |
| 9 | Restart Windows. Sign in, start TallyPrime, open the company | The service starts by itself; heartbeats resume | [ ] | |
| 10 | If you reach the VM over Remote Desktop: **disconnect** (close the window) and wait a few minutes; then connect again and **sign out** instead | Disconnected: syncs keep working. Signed out: TallyPrime closes and the Agent reports *TallyPrime is not running* | [ ] | |
| 11 | Close the company in TallyPrime; wait for a heartbeat | The Agent reports COMPANY_NOT_LOADED and pulls nothing; reopen it afterwards | [ ] | |
| 12 | Uninstall: `powershell -ExecutionPolicy Bypass -File "C:\Program Files\TallyAgent\Uninstall-TallyAgent.ps1"` | The service and `C:\Program Files\TallyAgent` are gone; the message tells you to revoke the Agent; `C:\ProgramData\TallyAgent` is still there | [ ] | |

`dev_backend call` runs any API call as the Owner, e.g.:
```bash
uv run python -m tally_tools.dev_backend call GET /companies/{company}/agents \
    --url https://<IP>:8443 --email you@example.com
```

## If something fails
- **Step 1, `sc.exe create` error:** note the exit code. The fallback is NSSM (D-043 #3); tell me
  and I will switch the scripts.
- **Step 5, `credential_invalid` or a DPAPI error:** the cross-account decryption failed. That is
  the most important finding here; send the log.
- Anything else: send `C:\ProgramData\TallyAgent\logs\agent.log` and this file.
