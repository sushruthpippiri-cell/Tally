# Security review

Started in P2 (identity, RBAC, middleware); completed in P16.2. One row per SRS 14.2
requirement: how it is met, where it is proved, and what is still open.

Every row cites a test or a configuration file. Where the evidence can only come from outside
this repository (TLS at the proxy, the hosting posture), the row says so and points at
`docs/manual-verification.md` rather than claiming the requirement is met.

| ID | How it is met | Where | Proved by | Open |
|---|---|---|---|---|
| SEC-1.1 | bcrypt password hashes; access JWT 30 min, refresh JWT 24 h, rotated on every refresh; reuse of a rotated token revokes every open session (D-033 #2, #4) | `app/core/security.py`, `app/services/auth.py` | `tests/api/test_auth.py` (hashing, both token lifetimes, rotation, reuse revoking every session) | — |
| SEC-1.2 / RBAC-1.1 | Every company route depends on `require(Permission)`. `tests/api/test_route_access.py` enumerates every route and fails on a company route without one, on any other route not explicitly allow-listed, and — since P16.1 — on any route whose declared permission is **looser** than SRS 19.2 | `app/core/permissions.py` | `tests/api/test_route_access.py` (all 50 company routes × every role), `tests/core/test_permissions.py` (the SRS 14.1 matrix pinned) | — |
| SEC-1.3 | In prod a request whose effective scheme is not https gets 400 `HTTPS_REQUIRED`; `X-Forwarded-Proto` counts only from `TRUSTED_PROXIES`; HSTS on every prod response | `app/core/middleware.py`; the proxy half is P16.12's `deploy/caddy/Caddyfile` | `tests/api/test_middleware.py` | **TLS 1.2+ at the proxy** cannot be proved here: needs hosting. `docs/manual-verification.md` |
| SEC-1.4 | Starlette `CORSMiddleware` with `CORS_ORIGINS` only (required in prod); no credentials mode | `app/core/middleware.py` | `tests/api/test_middleware.py` | — |
| SEC-1.5 | **No CSRF middleware for the API, by design:** it authenticates with `Authorization: Bearer` only. The one cookie is the refresh cookie, `HttpOnly; Secure; SameSite=Strict; Path=/api/auth`, and the refresh and logout endpoints check `Origin` against `Host` (D-051 #2) | `app/api/auth.py`, `app/core/middleware.py` | `tests/api/test_auth.py`, `frontend/e2e/auth.spec.ts` | **Closed, not deferred:** D-028 is SUPERSEDED by D-051 — tokens are held in memory with the refresh cookie, never in `localStorage`. The P2 note asking to "review in P16 with D-028" is answered by D-051 |
| SEC-1.6 | SQLAlchemy ORM / Core expressions only; the one raw statement (`set_config` for the anomaly RLS) binds its parameter. XML from Tally is parsed with `xml.etree`, which does not resolve external entities, and a document declaring a DTD is refused outright, so entity expansion cannot be used to exhaust the Agent | all of `app/`, `shared/tally_contract/parser/document.py` | `tests/core/test_sql_is_parameterized.py` walks every shipped module and fails on `text()`/`execute()` given an f-string, a `%`/`+` concatenation or `.format()`; the guard is itself shown to fail on bad input. `shared/tests/parser/test_parser.py` proves the DTD refusal and that `SYSTEM` entities never resolve | — |
| SEC-1.7 | `company_id` comes only from `CompanyContext` (the path parameter checked against `user_roles`); `scoped()` adds the filter; composite FKs stop cross-company references in the database (D-031); `anomaly_flags` adds row-level security for the read-only MCP role | `app/core/permissions.py`, migration 0010 | `tests/api/test_route_access.py` (another company's user gets 403 with a byte-identical body to a nonexistent company, on every company route), `tests/anomaly/test_schema_and_rls.py` | — |
| SEC-1.8 | Agent authentication follows SRS 4.3–4.4: a one-time registration token, then a bearer credential `agt_<id>.<secret>` compared in constant time, bound to one company, with ACTIVE/REVOKED/INCOMPATIBLE states and rotation that switches in one instant | `app/core/agent_credentials.py`, `app/services/agents.py` | `tests/core/test_agent_auth.py`, `tests/api/test_agent_registration.py`, `tests/races/test_rotation_races.py`, `tests/api/test_route_access.py` (user JWTs rejected on Agent routes and the reverse) | — |
| SEC-1.9 | 100/min per client IP unauthenticated, 1,000/min per user, 1,000/min per Agent (D-043); client IP from `X-Forwarded-For` only via a trusted proxy (D-033 #5). Counters live in `rate_limit_counters` in PostgreSQL, so replicas share one limit (P16.11). Per-email login throttle: 10 failures / 15 min, counted from `audit_logs`, never a permanent lockout (D-033 #7) | `app/core/rate_limit.py`, `app/services/auth.py` | `tests/api/test_middleware.py`, including two limiter instances over one store together allowing no more than the limit | — (the P2 ceiling is closed) |
| SEC-1.10 | Every request body is a Pydantic model; `AppError(code, message, status)` for every refusal | `app/schemas/`, `app/core/errors.py` | `tests/test_errors_and_health.py` (every refusal is an `AppError` with a catalogue code; a malformed body is 422) | — |
| SEC-1.11 | Exports re-check permission and company scope on the server: the export endpoint depends on `require(Permission.EXPORT)` and a `CompanyContext`, and builds its figures from the same `app/analytics/metrics/` function as the screen — a client cannot widen a report by editing its query string | `app/api/exports.py`, `app/exports/reports.py` | `tests/api/test_exports.py` (a 403 is returned in the error catalogue's own wording rather than a broken file), `tests/api/test_route_access.py` | — |
| SEC-1.12 | Only one anomaly's stored numeric evidence is ever sent: parties and vouchers become `Party A`, `Voucher A`, `Voucher B` — letters, never digits. Never sent: real names, voucher numbers, voucher-type names, narration, dates, GUIDs. One `redact()` decides it, and names are restored locally for display | `app/anomaly/redact.py`, `app/anomaly/explainer.py` | `tests/anomaly/test_explainer.py`, including a dataset whose party name is itself an injection attempt, and an assertion that no placeholder constant contains a digit | — |
| SEC-1.13 | `audit_logs` append-only: a trigger rejects UPDATE and DELETE for everyone and the app role has neither; written only through `app/core/audit.py`. No retention job touches it (SRS 15 keeps it as long as the company's data) | migration 0001, `app/core/audit.py` | `tests/models/test_config_audit.py`, `tests/jobs/test_retention.py` | — |
| SEC-1.14 | Secrets come from the environment; prod refuses to start without them, or with a JWT secret under 32 bytes. The model id and API key for the optional explainer are server configuration, never code | `app/core/config.py` | `tests/test_config.py`; **in CI**: gitleaks over the whole history, `pip-audit` on the resolved Python set, `npm audit` on runtime JavaScript, and ruff's flake8-bandit (`S`) rules in `make lint` | — |
| SEC-1.15 | App role `tally_app` has DML only, never DDL; `tally_readonly` (the anomaly MCP server) has SELECT on one table under a row-level security policy and no default privileges, so it cannot pick up a table added later | `deploy/postgres/grants.sql`, migration 0010 | `tests/test_db_roles.py`, `tests/anomaly/test_schema_and_rls.py` | — |

## Response headers

On every response: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer`, `Content-Security-Policy: default-src 'none'; frame-ancestors
'none'` (the API serves no pages, D-051 #4), and `X-Request-ID` — echoed when well-formed, else
generated, and bound into every log line of the request. In prod, `Strict-Transport-Security`
as well. The SPA's own policy lives in `frontend/security/csp.ts`, served by `vite preview` in
development and by Caddy in production; a test keeps the two in step.

## Deviations from SRS 19.2

None. P16.1 compares every company route's declared permission against the 19.2 Access column:
all 50 agree exactly, in both directions. A route that is deliberately *stricter* than the SRS
would be listed here with its reason; a route that is looser fails the build.

## Supply chain

- `pip-audit` found **pyjwt 2.14.0** carrying PYSEC-2026-4141 / CVE-2026-102275 — in the
  token-signing path. Upgraded to 2.15.1 in P16.2; the audit now reports nothing. Our own four
  workspace packages are skipped because they are not on PyPI.
- `npm audit --omit=dev --audit-level=high`: 0 vulnerabilities. Dev-only advisories are excluded
  deliberately — they ship to nobody, and failing on them would mean ignoring the job.
- gitleaks runs over all history, pinned by digest, with `--network none` and a read-only mount,
  so a third-party image cannot send the repository anywhere. `.gitleaks.toml` holds one
  allowlist: PostgreSQL `EXPLAIN ANALYZE` plan lines in `docs/benchmarks/*.md`, which print
  `Group Key: voucher_entries_4.voucher_id` and are read as a secret after the word `Key:`. It
  requires the file **and** the plan's own wording (`condition = "AND"`), and was checked by
  planting a real-looking `API Key:` in that same file: 25 plan lines stayed suppressed and the
  planted key was reported.
- Earlier in P16 the full history was also scanned by hand for credentials, tokens, private keys
  and real passwords. Nothing was found beyond the documented local-development defaults
  (`deploy/docker-compose.yml`, `.env.example`), which are meant to be in the repository.

## Known ceilings

- **`assert` in shipped code** states invariants mypy cannot see (`assert url is not None  #
  guaranteed by Settings validation`), never validates untrusted input — that is Pydantic's job
  on every request body. Nothing runs under `-O`. Ruff's `S101` is therefore off, with that
  reasoning recorded in `pyproject.toml`.
- **`random`** is used for retry jitter and generated test data only. Tokens, credentials and
  salts use `secrets`.
- **The XML parser** accepts only TallyPrime's own report XML over `localhost`. External
  entities do not resolve and a DTD is refused, which closes the entity-expansion class without
  taking on `defusedxml`.
