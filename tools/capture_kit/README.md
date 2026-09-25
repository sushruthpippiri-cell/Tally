# TallyPrime capture kit

> ## ⚠ TEST COMPANY ONLY
> Use a **dedicated test company** created for this purpose. **Never** run this kit against a
> real business's books: every response it captures is copied into the project repository.

This kit sends the project's export requests to TallyPrime and saves exactly what TallyPrime
answers, so the draft TDL and parser can be checked against real output (the validation gate,
`docs/validation-gate.md`, decision D-038). It uses only what ships with Windows
(Windows PowerShell 5.1); nothing needs installing.

What is in this folder:

| Item | What it is |
|---|---|
| `Capture-Tally.ps1` | The script. Every step below runs it. |
| `manifest.json`, `requests\` | The requests it sends (generated from the project's code; do not edit). |
| `tdl\TA_Minimal.tdl` | A tiny TDL with one report, loaded first to prove TDL loading works. |
| `tdl\TallyAnalytics.tdl` | The full project TDL. |
| `CHECKLIST.md` | The sample data the test company needs, gate by gate, with tick boxes. |

## 1. The virtual machine and a shared folder
The kit runs inside the Windows 11 ARM virtual machine where TallyPrime is installed.

- **Parallels Desktop:** enable *Shared Folders* for the VM (Configuration → Options → Sharing)
  and share one Mac folder, e.g. `~/tally-captures`. In Windows it appears under
  `\\Mac\Home\...` or as a drive letter; use that path as `-OutDir`.
- **UTM or another hypervisor:** use its shared-folder feature if you have it set up. If not,
  leave `-OutDir` at its default: every run also writes **one `.zip` file**, which you can copy to
  the Mac any way you like (network share, cloud drive, drag and drop).

Copy this whole kit folder into the VM (e.g. `C:\TallyCaptureKit\`).

**Known risks on this setup:** TallyPrime is an x64 program and runs on Windows 11 ARM through
Windows' built-in x64 emulation; if it misbehaves, note the symptom in `CHECKLIST.md`. If you use
TallyPrime in **Educational mode** (no licence), it only accepts voucher dates on the **1st, 2nd
and 31st** of a month, so `CHECKLIST.md` uses only those dates.

## 2. Turn on TallyPrime's XML server
In TallyPrime: **F1 (Help) → Settings → Connectivity** (in some releases: **Client/Server
configuration**). Set **TallyPrime acts as** = **Both** (or **Server**) and **Port** = **9000**.
Accept, then restart TallyPrime. Open the test company.

## 3. Load the TDL — the minimal one first
1. **F1 (Help) → TDLs & Add-Ons → Manage Local TDLs.**
2. Set **Load TDL files on startup** = **Yes**, and in the list add the full path of
   `tdl\TA_Minimal.tdl` (e.g. `C:\TallyCaptureKit\tdl\TA_Minimal.tdl`). Accept.
3. Look at the status shown next to the file. If it is not loaded, go to
   **Troubleshooting TDL errors** below.
4. Run the check (section 4). When it passes, go back to Manage Local TDLs, **replace**
   `TA_Minimal.tdl` with `tdl\TallyAnalytics.tdl` (never both at once), accept, and run the
   check again.

## 4. Run the steps
Open **Windows PowerShell** (Start → type *PowerShell*), go to the kit folder, and run the steps
below. `-ExecutionPolicy Bypass` lets this one script run without changing any Windows setting.
Replace the company names with your test companies' exact names as TallyPrime shows them.

```powershell
cd C:\TallyCaptureKit

# 1. Only checks: server reachable, company open, TDL loaded. Changes nothing.
powershell -ExecutionPolicy Bypass -File .\Capture-Tally.ps1 -Step check -Company "Tally Test Co" -OutDir "\\Mac\Home\tally-captures"

# 2. Everything: check, then every export request, then TallyPrime's own reports as reference.
#    Keep a second company open in TallyPrime for -OtherCompany (gate G20).
powershell -ExecutionPolicy Bypass -File .\Capture-Tally.ps1 -Step all -Company "Tally Test Co" -OtherCompany "Second Test Co" -OutDir "\\Mac\Home\tally-captures"

# 3. Scenarios: the script captures, asks you to change something in TallyPrime, then captures
#    again. Run each one after the full capture. Names: G8 G9 G11 G29 G32 ACC-7.5 AGT-5.4
powershell -ExecutionPolicy Bypass -File .\Capture-Tally.ps1 -Step scenario -Name G8 -Company "Tally Test Co" -OutDir "\\Mac\Home\tally-captures"
```

Useful options: `-BooksFrom 20240401` (the company's books-beginning date, `YYYYMMDD`),
`-AsOf 20250331` (the date for closing balances), `-Port 9000`, `-TimeoutMinutes 15`.

What you will see: one line per request, `OK` with its size, or `FAILED` with the reason. **A
failed request does not stop the run**: it is saved with its error, and the list of failures is
printed at the end and written to `summary.json`. Failures are useful evidence too; send them.

## 5. What gets saved, and how to hand it over
Each run creates a folder named like `20260926-101500-all` inside `-OutDir`, plus a zip of it:

```
20260926-101500-all\
  run.json          when, which step, company, Windows version, kit and TDL versions
  check.json        the check results
  summary.json      every request: ok / failed, gates, error
  check\  capture\  reference\      (scenarios: before\  after\  scenario.json)
    <id>.request.xml    exactly what was sent
    <id>.response.xml   exactly what TallyPrime answered (raw bytes, never re-encoded)
    <id>.meta.json      HTTP status, headers, time taken, size, any Tally error text
20260926-101500-all.zip
```

On the Mac, copy the run folders (or unzip the zips) into the repository under
`fixtures/xml/live/` and tell Claude Code they are there, together with your filled-in
`CHECKLIST.md`. Claude Code then analyses them (gate-track step G-E) and proposes each gate's
result; nothing is marked PASSED until you confirm.

## Troubleshooting TDL errors
This TDL has never been loaded into a real TallyPrime before, so the first load may fail. That
is expected and quick to fix; what matters is sending back the exact error.

**Where TallyPrime shows TDL errors**
1. **When the TDL loads** (on startup or after accepting Manage Local TDLs): TallyPrime may show
   an error panel naming the file, the line and the problem.
2. **F1 (Help) → TDLs & Add-Ons → Manage Local TDLs** (or *View Local TDLs*): the status next to
   each file shows whether it loaded, or its error.
3. **Files in the TallyPrime folder** (usually `C:\Program Files\TallyPrime\`): if there is a
   `tdlerror.log`, or a recently changed `tally.imp`, it contains the error text.
4. **The check step**: if TallyPrime loaded the file but our report still does not answer,
   `-Step check` prints `REPORT FAILED` or `NOT LOADED` and saves TallyPrime's answer in
   `check\info.response.xml`.

**What to copy back to Claude Code**
- the **full error text**, exactly as shown (copy it, or type it word for word);
- the **file name** (`TA_Minimal.tdl` or `TallyAnalytics.tdl`) and the **line number** if shown;
- the **TallyPrime version and build** (F1 → About, or the top of the Gateway screen);
- a **screenshot** if the text cannot be selected (Windows: `Win+Shift+S`);
- the check run's folder or zip, if you ran it.

Claude Code fixes the TDL, and you load the new file and run the check again.

## Optional: reference capture with tally-database-loader (TEST-4.1)
The SRS asks for tally-database-loader output as independent comparison evidence. It is optional
here because it needs **Node.js** (the only extra install); `-Step reference` already saves
TallyPrime's own Trial Balance, Day Book, Stock Summary and List of Accounts without it.

1. Install Node.js (LTS) from https://nodejs.org (Windows ARM64 installer).
2. Download the latest release of tally-database-loader from
   https://github.com/dhananjay1405/tally-database-loader/releases and unzip it.
3. In its `config.json` set, under `database`, **`"technology": "csv"`** (no database needed; the
   connection settings are then ignored), and under `tally`: `"server": "localhost"`,
   `"port": 9000`, `"company": "Tally Test Co"`, `"fromdate"` / `"todate"` = your financial year
   (`YYYY-MM-DD`, or `"auto"`).
4. Run `run.bat` in its folder. Copy the CSV files it writes into
   `<OutDir>\reference\tdl-loader\<date>\`.
