# Progress log

Claude Code updates this at the end of every session. Newest entries at the top of each section.

## Current phase
P0 — **complete** 2026-09-23. Local suite PASS ([phase-00](test-reports/phase-00.md), 78 tests) and CI green (run 35881605525, both `check` and `agent-windows`). Next: P1 — blocked until D-001 is confirmed.

## Done
| Date | Phase.Task | Commit | Notes |
|---|---|---|---|
| 2026-09-23 | Setup: repo, plan, SRS v7.3 PDF, .gitignore | 9b83697 | No application code. SRS PDF verified as "v7.3 Complete Edition", 34 pages. |
| 2026-09-23 | Setup: origin added, answers and toolchain recorded | e769a15 | Pushed `main` to origin. |
| 2026-09-23 | P0.1 workspace and directory tree | ba0987a | uv workspace: shared, backend, agent, tools. |
| 2026-09-23 | P0.5 quality tooling | (see log) | ruff (T20: no print), mypy strict on tally_contract + app.core, 3 import-linter contracts. |
| 2026-09-23 | P0.12 logging and test-run infrastructure | 30db670 | structlog via stdlib logging, `assert_logged`, req-ID JUnit properties, skips must give a reason. |
| 2026-09-23 | P0.3 error codes and contract version | (see log) | 15 SRS + 14 additions (D-030). |
| 2026-09-23 | P0.6 docker environment | (see log) | postgres 16 + backend; `tally_owner` (DDL) / `tally_app` (DML only). |
| 2026-09-23 | P0.2 backend skeleton | (see log) | config, db, AppError handlers, /health, /health/db, alembic skeleton. |
| 2026-09-23 | P0.10 gate plumbing | (see log) | gate_status.yaml G1-G33 NOT_TESTED; `collection_sync_mode` per VAL-1.1/1.2. |
| 2026-09-23 | P0.4 Agent CLI stubs | (see log) | register, run, status, set-credential, test-tally. |
| 2026-09-23 | P0.11 SRS transcription | b926e89 | `docs/srs/SRS_v7_3.md`, proven word-for-word against the PDF. |
| 2026-09-23 | P0.9 traceability | (see log) | 356 requirement IDs found; 6 covered so far. |
| 2026-09-23 | P0.7/P0.8 Makefile and CI | (see log) | GitHub Actions: `check` (ubuntu + postgres 16) and `agent-windows` (may fail until P7). |
| 2026-09-23 | P0 CI fixes | 2f0c340 | First CI run failed in both jobs. (1) Windows: `read_text()` defaults to cp1252 -> UnicodeDecodeError; every text I/O call now names `encoding="utf-8"`, guarded by `tools/tests/test_text_io_encoding.py`. (2) Linux: the SRS tests re-ran `pdftotext` and demanded byte-equality, so Ubuntu's older poppler failed them; `docs/srs/SRS_v7_3.raw.txt` is now the committed reference extraction. Markdown unchanged; no test skipped or weakened. CI run 35881605525 green. |

## In progress
-

## Blocked
| Item | Blocked by (gate / decision / question) | Since |
|---|---|---|
| P1 (data model) | D-001 must be confirmed with the accountant first (`groups.predefined_group_id` shapes every masters table). | 2026-09-23 |

## Questions for the product owner
| # | Question | Raised in | Answer |
|---|---|---|---|
| 1 | Install poppler and use `pdftotext -layout` for the P0.11 SRS transcription? | Setup | Yes. poppler 26.09.0 installed via brew (2026-09-23). |
| 2 | GitHub remote for CI (P0.8)? | Setup | `origin` = https://github.com/sushruthpippiri-cell/Tally (private). |
| 3 | Repo location? | Setup | Moved to `/Users/sushruthp/code/tally-platform` (2026-09-23). |
| 4 | Git author correct? | Setup | Yes: `sushruthpippiri-cell <sushruth.pippiri@gmail.com>`. |
| 5 | D-001 (before P1), D-002 (before P4), D-021 (before P8)? | Setup | Noted. Owner will confirm D-001 before P1 and D-002 before P4, and answer D-021 before P8. Do not start those phases until confirmed. |
| 6 | Confirm D-001 (classification anchor = nearest predefined group) with the accountant. | P0 end | **Open — blocks P1.** |

## Owner rules added at P0 start (2026-09-23)
Testing and logs rules (logs captured at DEBUG and saved per run, log-record assertions, per-phase full-suite report in `docs/test-reports/phase-NN.md`, no next phase on a red suite) are in `CLAUDE.md` -> "Testing and logs" and in `docs/plan/phase-00-foundation.md` (P0.12).

## Test reports
| Phase | Report | Result |
|---|---|---|
| 00 | [phase-00.md](test-reports/phase-00.md) | PASS - 78 tests, 0 failed, 0 skipped, 83% coverage; CI run 35881605525 green |

## Environment (recorded 2026-09-23, macOS arm64)
| Tool | Version |
|---|---|
| uv | 0.12.17 |
| Python | 3.12.14 (`python3.12`, /opt/homebrew/bin) |
| Node | v24.13.0 (npm 11.6.2) |
| Docker | 29.8.0 (Compose v5.5.1). Daemon running (verified 2026-09-23). |
| poppler / pdftotext | 26.09.0 |
| make | /usr/bin/make |

Notes for P0.11: the Read tool cannot render PDFs without poppler (now installed); transcribe with `pdftotext -layout docs/srs/Tally_SRS_v7_3_Complete.pdf`. Plain `pypdf` output flattens tables, so do not use it for the transcription.

## Gate status summary
All gates NOT TESTED (see docs/validation-gate.md).
