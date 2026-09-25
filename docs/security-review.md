# Security review

Started in P2 (identity, RBAC, middleware); completed in P16. One row per SRS 14.2 requirement:
how it is met, where, and what is still open.

| ID | How it is met | Where | Open |
|---|---|---|---|
| SEC-1.1 | bcrypt password hashes; access JWT 30 min, refresh JWT 24 h, rotated on every refresh; reuse of a rotated token revokes every open session (D-033 #2, #4) | `app/core/security.py`, `app/services/auth.py` | — |
| SEC-1.2 / RBAC-1.1 | Every company route depends on `require(Permission)`; `tests/api/test_route_access.py` enumerates all routes and fails on any company route without it or any other route not explicitly allow-listed | `app/core/permissions.py` | — |
| SEC-1.3 | In prod, a request whose effective scheme is not https gets 400 `HTTPS_REQUIRED`; `X-Forwarded-Proto` counts only from `TRUSTED_PROXIES`; HSTS on every prod response | `app/core/middleware.py` | TLS 1.2+ termination at the reverse proxy (P16 deploy) |
| SEC-1.4 | Starlette `CORSMiddleware` with `CORS_ORIGINS` only (required in prod); no credentials mode | `app/core/middleware.py` | — |
| SEC-1.5 | **No CSRF middleware, by design:** the API authenticates with `Authorization: Bearer` headers only and sets no cookies, so a cross-site request cannot carry credentials. If a cookie-based session is ever added, CSRF protection must be added with it | D-028 | Review in P16 with D-028 (token storage in the browser) |
| SEC-1.6 | SQLAlchemy ORM / Core expressions only | all | P16: grep gate for raw SQL string building |
| SEC-1.7 | `company_id` comes only from `CompanyContext` (the path parameter checked against `user_roles`); `scoped()` adds the filter; composite FKs stop cross-company references in the database (D-031) | `app/core/permissions.py` | — |
| SEC-1.9 | 100/min per client IP unauthenticated, 1,000/min per user; client IP from `X-Forwarded-For` only via a trusted proxy (D-033 #5). Per-email login throttle: 10 failures / 15 min, never a permanent lockout (D-033 #7) | `app/core/middleware.py`, `app/services/auth.py` | **Ceiling:** counters are per process; move them to Postgres/Redis before running more than one backend replica |
| SEC-1.10 | Every request body is a Pydantic model | `app/schemas/` | — |
| SEC-1.13 | `audit_logs` append-only: trigger + REVOKE; written only by `app/core/audit.py` | migration 0001 | — |
| SEC-1.14 | Secrets from the environment; prod refuses to start without them, and with a JWT secret under 32 bytes | `app/core/config.py` | Secret scanning in CI (P16) |
| SEC-1.15 | App role `tally_app` has DML only | `deploy/postgres/grants.sql` | — |

Other headers on every response: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer`, `X-Request-ID` (echoed if well-formed, else generated, and bound
into every log line of the request).
