# TDL sources

**DRAFTS.** These files have never been loaded into a real TallyPrime. Every assumption about
Tally's own fields and functions carries a `;; GATE-Gxx` tag (`grep -n "GATE-G" tdl/*.tdl`) and
stays a draft until that gate PASSES with evidence in `docs/validation-gate.md`. Captures from
the gate track (`tools/capture_kit/`, D-038) correct them.

| File | What it is |
|---|---|
| `TA_Minimal.tdl` | Only the `TA_Info` report (TDL version, target company GUID and name). **Load this first**: an error here is about loading TDL at all. |
| `TallyAnalytics.tdl` | The full package: the `TA_Info` section (identical, tested) plus one Report per Collection (FR-1.1, FR-1.3), each with GUID, ALTERID, an ALTERID window filter and a `…Keys` key-only variant (FR-1.2), stock and ledger closing as of a date, and a reconciliation stub (P10). |

The XML tags these reports emit are ours, not Tally's, and must match
`shared/tally_contract/tally_constants.py`; `shared/tests/test_tdl.py` checks that, the version,
and FR-1.2 for every collection.

## Loading into TallyPrime
1. Copy the file to the Tally machine (e.g. `C:\TallyAnalytics\`).
2. In TallyPrime: **F1 (Help) → TDLs & Add-Ons → Manage Local TDLs**. Set *Load TDL files on
   startup* to **Yes** and add the full path of the file.
3. Check the status shown against the file (loaded / error). The capture kit README has a
   troubleshooting section for load errors and says exactly what to copy back.
4. Load `TA_Minimal.tdl` first; once `Capture-Tally.ps1 -Step check` reports the TDL as loaded,
   replace it with `TallyAnalytics.tdl` (never both at once: they define the same `TA_Info`).

The Agent never falls back to Tally's default reports: if these reports are not loaded it
reports `TDL_NOT_LOADED` (FR-1.4).

## Versioning
`TA_TDLVersion` (in both files) must equal `TDL_VERSION` in
`shared/tally_contract/tally_constants.py`. Bump all three on every change: patch for a fix that
keeps the XML the same, minor for new fields or reports, major for anything a parser must handle
differently. The backend's `MIN_TDL_VERSION` rejects older packages (VER-1.2).

## Scope
No GST tax detail (D-037); no godowns or batches, orders or inventory-only vouchers (SRS 1.3).

## Credits
Field names were cross-checked against **tally-database-loader** by Dhananjay Gokhale
(https://github.com/dhananjay1405/tally-database-loader, MIT licence). Nothing from it is treated
as verified; only live captures verify.
