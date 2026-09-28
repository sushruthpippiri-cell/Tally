# Installing the Tally Analytics Sync Agent (Windows)

The Agent runs on the Windows PC where TallyPrime runs. It reads TallyPrime (read-only) through
TallyPrime's local XML server and uploads to Tally Analytics over HTTPS. Nothing connects *to*
the PC: all traffic is outbound.

## Before you start
- **Windows 10 or 11 (64-bit)**, and administrator rights to install.
- **TallyPrime running in a signed-in Windows session**, with the company open. The Agent
  cannot start or keep TallyPrime running (AGT-6.1).
  - **Remote Desktop users: disconnect, never sign out.** Signing out closes TallyPrime and every
    sync fails with *TallyPrime is not running* (AGT-6.2).
- **TallyPrime's XML server on:** F1 (Help) → Settings → Connectivity: *TallyPrime acts as*
  **Both** (or **Server**), **Port 9000**. Restart TallyPrime.
- **The project's TDL loaded:** F1 (Help) → TDLs & Add-Ons → Manage Local TDLs → *Load TDL files
  on startup* = Yes, and add `C:\Program Files\TallyAgent\tdl\TallyAnalytics.tdl` (installed with
  the Agent; use the one that came with *this* Agent version).
- **A registration token:** in the dashboard, Agents → Add Agent. It is valid for 24 hours and
  works once.

## Install
1. Unzip `TallyAgent-windows-x64.zip`.
2. Open **Windows PowerShell as administrator** in the unzipped `TallyAgent` folder and run:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\Install-TallyAgent.ps1
   ```
   This:
   - copies the Agent to `C:\Program Files\TallyAgent`
   - creates the Windows service **TallyAgent**, running as its own low-privilege account `NT SERVICE\TallyAgent` (not LocalSystem), started with Windows and restarted if it stops
   - restricts `C:\ProgramData\TallyAgent` (settings, the encrypted credential, the upload queue, logs) to that account, SYSTEM and Administrators
3. **Register**, in the same administrator window. Use the company name exactly as TallyPrime shows it:
   ```powershell
   & "C:\Program Files\TallyAgent\tally-agent.exe" register --token <token> --name "Head Office" `
       --backend-url https://<your Tally Analytics address> --company "<Tally company name>"
   ```
   Registration checks that TallyPrime answers, that the right TDL is loaded and which company it
   is (its GUID), then stores the Agent's credential **encrypted with Windows DPAPI**. It is never
   written to a settings file and never shown.
4. **Start it:** `sc.exe start TallyAgent`. Within a minute the dashboard shows the Agent as
   ACTIVE; its first FULL sync switches its scheduled syncs on.

## Office networks
- **An HTTPS proxy:** add `--proxy-url http://proxy:3128` when registering. If it needs a
  username and password, store them with `tally-agent set-proxy-credentials` (kept encrypted, like
  the credential). NTLM/Kerberos proxies are not supported.
- **Antivirus or a firewall that inspects HTTPS:** if registration says the certificate is not
  trusted, get the inspecting CA's certificate (a PEM file) from your IT team and add
  `--ca-bundle C:\path\to\office-ca.pem`. It is trusted *in addition to* the usual public
  certificates. There is no setting to turn certificate checks off.

## Day to day
| Task | Command (administrator PowerShell) |
|---|---|
| Is it registered, is the credential there, are the permissions right? | `tally-agent status` |
| Can it reach TallyPrime, with the right TDL and company? | `tally-agent test-tally` |
| The credential was rotated in the dashboard | `tally-agent set-credential` (typed at a hidden prompt), then `sc.exe stop TallyAgent` and `sc.exe start TallyAgent` |
| Logs | `C:\ProgramData\TallyAgent\logs\agent.log` |
| Uploads that failed 20 times | `C:\ProgramData\TallyAgent\deadletter.jsonl` (also counted on the dashboard) |

## Troubleshooting
| The dashboard says | What to do |
|---|---|
| TallyPrime is not running | Start TallyPrime and open the company. Over Remote Desktop, disconnect instead of signing out. |
| TallyPrime is running but does not answer | Turn on its XML server (above) on the port the Agent uses. |
| TDL not loaded / wrong TDL version | Load `tdl\TallyAnalytics.tdl` from *this* Agent's folder and restart TallyPrime. |
| Company not loaded | Open the company in TallyPrime. If it was renamed, update the name in the dashboard (Agent settings); no re-registration is needed. |
| Company mismatch | TallyPrime has a *different* company open under that name (e.g. a restored backup). Nothing is synced. Open the right one, or re-register if the change is intended. |
| Queue full | The Agent cannot upload (internet down?). It keeps retrying and resumes pulling once there is room. |

## Uninstall, or retiring the PC
1. Administrator PowerShell in `C:\Program Files\TallyAgent`:
   `powershell -ExecutionPolicy Bypass -File .\Uninstall-TallyAgent.ps1`.
2. **Revoke the Agent in the dashboard** (Agents → Revoke). The uninstaller leaves
   `C:\ProgramData\TallyAgent` (the queue for inspection, the logs **and the encrypted
   credential**); revoking is what makes that credential useless.
3. Delete `C:\ProgramData\TallyAgent` when you no longer need it.
