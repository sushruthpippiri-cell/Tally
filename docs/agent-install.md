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

Run **`TallyAgent-Setup-<version>.exe`** and answer the two pages it asks. That is the whole
installation: it copies the Agent, registers it, creates the service and starts it.

Get the **registration token** first, from the dashboard: **Agents → Generate registration
token**. It can be used once, so generate it when you are at the PC.

The wizard asks for:

| Page | What |
|---|---|
| Connect this Agent | the backend URL (`https://…`), a name for this Agent (e.g. "Head Office"), and the registration token |
| TallyPrime on this PC | the Tally company name **exactly as Tally shows it**, and Tally's host and port (leave `localhost` / `9000` alone unless Tally's XML server has been moved) |

What it does, so there are no surprises:

- installs to `C:\Program Files\TallyAgent`;
- creates `C:\ProgramData\TallyAgent` for the settings, the encrypted credential, the upload
  queue and the logs, and **restricts it** to the service account, SYSTEM and Administrators;
- registers with the backend — which checks that TallyPrime answers, that the right TDL is
  loaded, and which company it is (its GUID), then stores the credential **encrypted with
  Windows DPAPI**. It is never written to a settings file and never shown again;
- creates the Windows service **TallyAgent**, running as its own low-privilege account
  `NT SERVICE\TallyAgent` — not LocalSystem — started with Windows (delayed, so Tally and the
  network are up first) and restarted automatically if it stops;
- starts it.

Within a minute the dashboard shows the Agent as ACTIVE. Its first FULL sync switches its
scheduled syncs on.

### Windows will warn you that the publisher is unknown

It will say something like *"Windows protected your PC"*. Click **More info → Run anyway**.

This is honest to report rather than hide: **the installer is not yet signed.** Code signing
needs a certificate the project has not bought (it is a launch requirement, not an optional
extra). Until it is signed, SmartScreen and some antivirus products will warn, and in a managed
office they may block it outright — if that happens, your IT administrator will need to allow it.
Check the download's SHA-256 against the one published with the release before you run it.

### Upgrading

Run the new installer over the old one. It stops the service, replaces the program files and
starts it again. **Your settings, credential and upload queue are kept**, and it does not ask the
wizard questions again or re-register — re-registering would create a second Agent for the same
PC. Anything still queued uploads after the restart; nothing is lost.

### If you would rather not use the installer

The zip still contains the PowerShell scripts, which do the same thing in steps you can read:

```powershell
powershell -ExecutionPolicy Bypass -File .\Install-TallyAgent.ps1
& "C:\Program Files\TallyAgent\tally-agent.exe" register --token <token> --name "Head Office" `
    --backend-url https://<your Tally Analytics address> --company "<Tally company name>"
sc.exe start TallyAgent
```

Add `--ca-bundle <file>` or `--proxy-url <url>` to `register` if your network needs them (see
**Office networks** below). The installer has no page for those yet; use the scripts if you need
them.

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

Uninstall from **Settings → Apps → Tally Analytics Sync Agent**, or run
`Uninstall-TallyAgent.ps1` from `C:\Program Files\TallyAgent` in an administrator PowerShell.
Either way the service is stopped and removed and the program files are deleted.

Then, two things that matter:

1. **Revoke the Agent in the dashboard** (Agents → Revoke). The uninstaller deliberately leaves
   `C:\ProgramData\TallyAgent` behind — the upload queue, the logs **and the encrypted
   credential**. The queue and logs are how anyone finds out later why the Agent was removed or
   what it had not yet uploaded. Revoking is what makes the credential useless.
2. **Delete `C:\ProgramData\TallyAgent`** once you no longer need the queue or the logs. On a
   PC being disposed of or sold, do this.

Removing the Agent changes nothing in TallyPrime and deletes nothing already uploaded: the
dashboard keeps every record it has, and a new Agent on another PC reading the same company
picks up from where this one left off.
