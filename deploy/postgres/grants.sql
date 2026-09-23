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
