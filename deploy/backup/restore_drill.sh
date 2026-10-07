#!/usr/bin/env bash
# BKP-1.2: restore into staging and compare row counts with a known snapshot.
#
# This is the whole point of a backup, and the only part that can be got wrong silently: a
# backup nobody has restored is a hope, not a recovery plan. Run it before go-live and after any
# change to the provider's backup settings.
#
#   ./restore_drill.sh --snapshot snapshots/2026-10-07.json [--staging-url URL]
#
# It never writes to production. The staging URL must name a database whose name ends in
# `_staging`, and the script refuses to run otherwise - the same guard the benchmark tools use
# for `_bench` (D-035 #14).
set -euo pipefail

SNAPSHOT=""
STAGING_URL="${STAGING_DATABASE_URL:-}"
RESTORE_LABEL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --snapshot) SNAPSHOT="$2"; shift 2 ;;
    --staging-url) STAGING_URL="$2"; shift 2 ;;
    --label) RESTORE_LABEL="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$SNAPSHOT" ]] || { echo "--snapshot is required (see take_snapshot.sh)" >&2; exit 2; }
[[ -f "$SNAPSHOT" ]] || { echo "no such snapshot: $SNAPSHOT" >&2; exit 2; }
[[ -n "$STAGING_URL" ]] || { echo "--staging-url or STAGING_DATABASE_URL is required" >&2; exit 2; }

# Refuse anything that is not plainly a staging database. A drill that restores over production
# is worse than no drill.
DB_NAME="${STAGING_URL##*/}"
DB_NAME="${DB_NAME%%\?*}"
if [[ "$DB_NAME" != *_staging ]]; then
  echo "refusing: '$DB_NAME' does not end in _staging" >&2
  exit 1
fi

echo "== restore drill =="
echo "snapshot: $SNAPSHOT"
echo "staging:  $DB_NAME"
START=$(date -u +%s)

# 1. Restore. This step is the provider's, and it is the one line you must fill in for the
#    provider you chose - see docs/runbooks/restore.md. It must end with the staging database
#    holding the restored data.
if [[ -z "${RESTORE_COMMAND:-}" ]]; then
  cat >&2 <<'MSG'
RESTORE_COMMAND is not set.

This script does not guess how your provider restores a backup: a managed instance is restored
through its own API or console into a new instance, and a self-hosted one with pg_restore or
pgBackRest. Set RESTORE_COMMAND to the command that restores into the staging database, for
example:

  RESTORE_COMMAND='pg_restore --clean --if-exists -d "$STAGING_URL" /backups/latest.dump'

docs/runbooks/restore.md records what was used, so the next person does not have to work it out
under pressure.
MSG
  exit 2
fi
echo "-- restoring"
eval "$RESTORE_COMMAND"

RESTORED=$(date -u +%s)
echo "-- restore took $((RESTORED - START))s"

# 2. Compare row counts with the snapshot, and the reconciliation figures with it.
echo "-- comparing with the snapshot"
python3 "$(dirname "$0")/compare_snapshot.py" --snapshot "$SNAPSHOT" --url "$STAGING_URL"

END=$(date -u +%s)
echo
echo "== drill passed in $((END - START))s =="
echo "Record in docs/progress.md: the date, the achieved RTO ($((END - START))s), the backup's"
echo "age at restore (the achieved RPO), the provider and region, and this snapshot's id."
[[ -n "$RESTORE_LABEL" ]] && echo "label: $RESTORE_LABEL"
exit 0
