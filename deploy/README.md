# Deployment files

| File | For |
|---|---|
| `docker-compose.yml` | **Local development** (`make up` / `make down`). Publishes Postgres on 5432 and the backend on 8000 for convenience; the passwords in it are dev-only defaults. |
| `docker-compose.prod.yml` | **Production** (P16.12). Only the proxy publishes ports, so every request arrives through TLS with the security headers (D-056 #7). No database service: production uses managed PostgreSQL with point-in-time recovery (D-056 #2). Every value comes from the environment with no default. |
| `caddy/Caddyfile`, `caddy/Dockerfile` | The production front door: serves the built SPA, proxies `/api` to the backend with the browser's `Host` intact, and carries the app's security headers plus HSTS. |
| `postgres/init/`, `postgres/grants.sql` | Creates `tally_owner` (DDL), `tally_app` (DML only) and `tally_readonly` (the anomaly MCP server, SELECT on one table under row-level security). Apply `grants.sql` once to a managed instance before the first migration. |

`docs/runbooks/deploy.md` is the procedure and the three checks to run against a deployed
site; `docs/runbooks/restore.md` is the backup and recovery runbook.
