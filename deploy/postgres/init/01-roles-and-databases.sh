#!/bin/bash
# Runs once, on first start of an empty data volume.
#  tally_owner: owns the databases and schema; used by Alembic (DDL). CREATEDB so the
#               phase report can recreate `tally_test`; it can never touch `tally` (guarded).
#  tally_app:   SELECT/INSERT/UPDATE/DELETE only, no DDL (SEC-1.15).
set -euo pipefail

HOST_ARG=${PGHOST:+--host $PGHOST}
GRANTS="$(dirname "$0")/../grants.sql"
[ -f "$GRANTS" ] || GRANTS=/docker-entrypoint-initdb.d/../grants.sql

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" $HOST_ARG --dbname postgres <<SQL
CREATE ROLE tally_owner LOGIN CREATEDB PASSWORD '${TALLY_OWNER_PASSWORD}';
CREATE ROLE tally_app   LOGIN PASSWORD '${TALLY_APP_PASSWORD}';
CREATE DATABASE tally      OWNER tally_owner;
CREATE DATABASE tally_test OWNER tally_owner;
SQL

for db in tally tally_test; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" $HOST_ARG --dbname "$db" <<SQL
REVOKE ALL ON DATABASE ${db} FROM PUBLIC;
GRANT CONNECT ON DATABASE ${db} TO tally_app;
SQL
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" $HOST_ARG --dbname "$db" -f "$GRANTS"
done
