-- Per-database grants for tally_app (SEC-1.15): DML only, never DDL.
-- Applied by the init script on first start, and again by phase_report after it recreates
-- the _test database (a fresh database does not inherit them).
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO tally_app;
ALTER DEFAULT PRIVILEGES FOR ROLE tally_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tally_app;
ALTER DEFAULT PRIVILEGES FOR ROLE tally_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO tally_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO tally_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO tally_app;

-- tally_readonly (P15, D-055 #5): the anomaly MCP server. Schema usage only here; SELECT on
-- anomaly_flags, and the row-level security policy that scopes it to one company, are granted by
-- migration 0010, since the table does not exist when this file runs. No ALTER DEFAULT
-- PRIVILEGES on purpose: this role must never pick up access to a table added later.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tally_readonly') THEN
    GRANT USAGE ON SCHEMA public TO tally_readonly;
  END IF;
END $$;
