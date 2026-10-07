# Backup and recovery scripts (P16.6)

| File | Does |
|---|---|
| `take_snapshot.sh` | Prints the "known snapshot" BKP-1.2 compares a restore against: row counts plus each company's latest reconciliation figures. |
| `restore_drill.sh` | Restores into staging and compares. Refuses any database not named `*_staging`. Needs `RESTORE_COMMAND` — it does not guess how your provider restores. |
| `compare_snapshot.py` | Takes or checks a snapshot. stdlib + psycopg only, and imports nothing from `app`: a recovery tool has to run from a bare checkout while the application is down. |

The procedure, the targets and what the provider must be configured to do are in
[`docs/runbooks/restore.md`](../../docs/runbooks/restore.md). The drill itself has **not been
run** — it needs hosting and a staging database, and is recorded as blocked in
`docs/progress.md`.
