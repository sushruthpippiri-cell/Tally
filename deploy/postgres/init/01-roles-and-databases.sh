#!/bin/bash
# Runs once, on first start of an empty data volume.
#  tally_owner: owns the databases and schema; used only by Alembic (DDL).
#  tally_app:   SELECT/INSERT/UPDATE/DELETE only, no DDL (SEC-1.15).
# Databases: `tally` (dev) and `tally_test` (tests; the only database the phase report may reset).
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" ${PGHOST:+--host "$PGHOST"} --dbname postgres <<SQL
CREATE ROLE tally_owner LOGIN PASSWORD '${TALLY_OWNER_PASSWORD}';
CREATE ROLE tally_app   LOGIN PASSWORD '${TALLY_APP_PASSWORD}';
CREATE DATABASE tally      OWNER tally_owner;
CREATE DATABASE tally_test OWNER tally_owner;
SQL

for db in tally tally_test; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" ${PGHOST:+--host "$PGHOST"} --dbname "$db" <<SQL
REVOKE ALL ON DATABASE ${db} FROM PUBLIC;
GRANT CONNECT ON DATABASE ${db} TO tally_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO tally_app;
ALTER DEFAULT PRIVILEGES FOR ROLE tally_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tally_app;
ALTER DEFAULT PRIVILEGES FOR ROLE tally_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO tally_app;
SQL
done
