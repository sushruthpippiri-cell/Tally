# Progress log

Claude Code updates this at the end of every session. Newest entries at the top of each section.

## Current phase
P0 — plan proposed 2026-09-23, awaiting owner approval; no application code yet

## Done
| Date | Phase.Task | Commit | Notes |
|---|---|---|---|
| 2026-09-23 | Setup: repo, plan, SRS v7.3 PDF, .gitignore | 9b83697 | No application code. SRS PDF verified as "v7.3 Complete Edition", 34 pages. |
| 2026-09-23 | Setup: origin added, answers and toolchain recorded | (this commit) | Pushed `main` to origin. |

## In progress
-

## Blocked
| Item | Blocked by (gate / decision / question) | Since |
|---|---|---|
| Docker-based work (P0.6 `make up`, Postgres tests, `make phase-report`) | Owner says Docker Desktop is running, but from the Claude Code session the daemon is unreachable (`~/.docker/run/docker.sock` missing, no Docker process; checked twice, also outside the sandbox). Needs Docker Desktop actually started, then `docker info` re-checked | 2026-09-23 |

## Questions for the product owner
| # | Question | Raised in | Answer |
|---|---|---|---|
| 1 | Install poppler and use `pdftotext -layout` for the P0.11 SRS transcription? | Setup | Yes. poppler 26.09.0 installed via brew (2026-09-23). |
| 2 | GitHub remote for CI (P0.8)? | Setup | `origin` = https://github.com/sushruthpippiri-cell/Tally (private). |
| 3 | Repo location? | Setup | Moved to `/Users/sushruthp/code/tally-platform` (2026-09-23). |
| 4 | Git author correct? | Setup | Yes: `sushruthpippiri-cell <sushruth.pippiri@gmail.com>`. |
| 5 | D-001 (before P1), D-002 (before P4), D-021 (before P8)? | Setup | Noted. Owner will confirm D-001 before P1 and D-002 before P4, and answer D-021 before P8. Do not start those phases until confirmed. |

## Owner rules added at P0 start (2026-09-23)
Testing and logs rules (logs captured at DEBUG and saved per run, log-record assertions, per-phase full-suite report in `docs/test-reports/phase-NN.md`, no next phase on a red suite) are in `CLAUDE.md` -> "Testing and logs" and in `docs/plan/phase-00-foundation.md` (P0.12).

## Test reports
| Phase | Report |
|---|---|

## Environment (recorded 2026-09-23, macOS arm64)
| Tool | Version |
|---|---|
| uv | 0.12.17 |
| Python | 3.12.14 (`python3.12`, /opt/homebrew/bin) |
| Node | v24.13.0 (npm 11.6.2) |
| Docker | 29.8.0 (Compose v5.5.1). **Daemon not running when checked.** |
| poppler / pdftotext | 26.09.0 |
| make | /usr/bin/make |

Notes for P0.11: the Read tool cannot render PDFs without poppler (now installed); transcribe with `pdftotext -layout docs/srs/Tally_SRS_v7_3_Complete.pdf`. Plain `pypdf` output flattens tables, so do not use it for the transcription.

## Gate status summary
All gates NOT TESTED (see docs/validation-gate.md).
