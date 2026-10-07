#!/usr/bin/env bash
# BKP-1.2's "known reconciliation snapshot": the row counts and the latest reconciliation
# figures, taken from production, against which a restore is compared.
#
#   ./take_snapshot.sh > snapshots/$(date -u +%F).json
#
# Row counts alone would pass a restore that brought back the right number of wrong rows, so the
# snapshot also carries each company's latest reconciliation run and its figures. Those are the
# numbers the business would notice.
set -euo pipefail
URL="${1:-${DATABASE_URL:?set DATABASE_URL or pass it as the first argument}}"
exec python3 "$(dirname "$0")/compare_snapshot.py" --url "$URL" --emit
