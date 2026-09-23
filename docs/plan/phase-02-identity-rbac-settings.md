# Phase 2 — Identity, RBAC, tenancy, audit, settings

**Size:** M · **Depends on:** P1 · **SRS:** 14 (all), 15, 17.5, 18, 19.2 (auth, users, settings rows)
**Requirements:** SEC-1.1–1.5, 1.7, 1.9, 1.10, 1.13, 1.14; RBAC-1.1, 1.2; LOG-1.1, 1.2; TZ-1.1, 1.2; Q-1.1, 1.2
**Acceptance:** AC-59, AC-60, AC-62, AC-63 · **Decisions:** D-006, D-016, D-020

## Goal
Users can log in, act only within companies they hold roles in, and only do what the SRS permission matrix allows. Settings, feature flags, audit logging and time-zone/financial-quarter utilities exist for every later phase to reuse.

## Tasks

### P2.1 Bootstrap
CLI `python -m app.cli create-owner --email --name` (prompts for the password) creates the first user (D-006).

### P2.2 Authentication (SEC-1.1)
- `POST /auth/login`: email + password (bcrypt via passlib) → access JWT (30 min) and refresh JWT (24 h). Both ≤ 24 h. Generic error message for wrong credentials. Rate-limited.
- `POST /auth/refresh`: rotates the refresh token; rejects inactive users.
- `POST /auth/change-password`.
- Audit login success and failure (LOG-1.1).

### P2.3 Permission model — `app/core/permissions.py`
`Permission` enum and `ROLE_PERMISSIONS`, mirroring SRS 14.1 exactly:

| Permission | OWNER | ACCOUNTANT | ADMIN |
|---|---|---|---|
| VIEW_FINANCIALS | ✅ | ✅ | ✅ |
| RUN_SYNC | ✅ | ✅ | ✅ |
| MANAGE_SCHEDULES | ✅ | ❌ | ✅ |
| EXPORT | ✅ | ✅ | ✅ |
| VIEW_RECON_AND_DQ | ✅ | ✅ | ✅ |
| VIEW_LOGS | ✅ | ❌ | ✅ |
| REVIEW_ANOMALIES | ✅ | ✅ | ❌ |
| MANAGE_SETTINGS (flags + settings) | ✅ | ❌ | ✅ |
| MANAGE_AGENTS (register/rotate/revoke, Tally settings) | ✅ | ❌ | ✅ |
| MANAGE_CUSTOM_FIELDS | ✅ | ❌ | ✅ |
| MANAGE_USERS | ✅ | ❌ | ❌ |

Dependency `require(Permission)` resolves the user's roles for the path's `company_id` from `user_roles` and returns a `CompanyContext(company_id, user_id, roles)`. A table-driven test asserts the dictionary equals the matrix above.

### P2.4 Tenant scoping (SEC-1.7, RBAC-1.1)
- `CompanyContext` is the only source of `company_id` for queries. A user with no role in the path company gets 403 — the same response whether the company exists or not (AC-60).
- Repository helper `scoped(select(Model), ctx)` adds `Model.company_id == ctx.company_id`; repository methods require `company_id`.

### P2.5 Companies (D-006)
`POST /companies` (caller becomes OWNER; company inactive until an Agent registers), `GET /companies` (mine), `GET/PUT /companies/{id}`. `company_timezone` validated with `zoneinfo`; `financial_year_start` validated as a real date. Invalid values → 422, and quarter views later show "financial year not configured" (SRS 16 failure mode).

### P2.6 Users and roles (MANAGE_USERS)
`GET/POST/PUT /companies/{id}/users`: create a user with an initial password, assign or remove roles per company, deactivate. The last OWNER of a company cannot be removed. All changes audited.

### P2.7 Audit service — `app/core/audit.py`
`record(ctx_or_system, action, entity_type, entity_id, before=None, after=None, data_range=None, result="SUCCESS")` writing every LOG-1.2 field; `user_id = None` means "system". A `diff(before, after)` helper stores only changed fields. Later phases call this for every action listed in LOG-1.1.

### P2.8 Settings and feature flags (Section 18, D-016)
- `app/core/settings_registry.py`: every key from SRS 18.2 with type, default and validator, plus `stock.fast_ranking_basis` (quantity|value), `sync.keylist_max_missing_ratio` (0.2), `agent.command_lease_seconds` (300). Validators: tolerances ≥ 0; bucket boundaries strictly ascending positive integers; percentile 1–99; windows and thresholds > 0; `top_n_default` 1–100; classification lists non-empty and each entry one of Tally's 28 predefined group names (D-001).
- `GET /companies/{id}/settings` returns effective values with an `is_default` flag; `PUT` validates, stores overrides, audits (before/after).
- Feature flags: boolean only, `FEATURE_ANOMALY_DETECTION` default off; changes audited.
- `get_setting(company_id, key)` service with a per-request cache.

### P2.9 Dates and periods — `app/core/periods.py` (17.5)
`today(company)`, `now_local(company)`, `local_day_bounds(date, tz)`, `financial_year_of(date, fy_start)`, `financial_quarter_of(date, fy_start, mode)` returning labels like `FY2024-25 Q2`, `period_key(date, granularity)` for day/month/quarter. Calendar-quarter mode per Q-1.1.

### P2.10 Cross-cutting middleware
CORS limited to `CORS_ORIGINS` (SEC-1.4); slowapi rate limits 100/min per IP unauthenticated and 1,000/min per user (SEC-1.9); in prod reject requests whose `X-Forwarded-Proto` is not https and send HSTS (SEC-1.3); request-ID header; security headers. No CSRF middleware because bearer headers are used (SEC-1.5) — note this in `docs/security-review.md` (created here, completed in P16).

## Tests
- AC-59: Accountant calling settings PUT and users endpoints → 403 regardless of UI.
- AC-60: user of company A requesting company B resources (company, settings, users) → 403 and no data.
- AC-62: `Asia/Kolkata`, event at 23:58 IST on day 1 (a UTC timestamp on day 1 18:28) groups to day 1 regardless of the server TZ (run the test with `TZ=UTC` and `TZ=America/New_York`).
- AC-63: FY start 1 April, an August date → Q2; FY start 1 January → calendar quarters; boundary dates (31 Mar, 1 Apr, 29 Feb).
- Token expiry and refresh rotation; inactive user cannot refresh; last-owner protection; every settings validator (valid and invalid); audit rows written for login, settings and user changes.

## Definition of done
All tests pass; `app/core/permissions.py` matches SRS 14.1; every later phase can depend on `require()`, `CompanyContext`, `audit.record()`, `get_setting()` and `periods`.

## Kickoff prompt
~~~text
Read CLAUDE.md, docs/plan/phase-02-identity-rbac-settings.md, docs/decisions.md and SRS Sections 14, 15, 17.5, 18. In plan mode, propose the auth flow, the permission/CompanyContext dependency design, the settings registry, and the tests for AC-59, 60, 62, 63. Wait for approval, then implement P2.1–P2.10 with tests first, commit per task, update docs/progress.md.
~~~
