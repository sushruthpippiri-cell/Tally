# Deploying (P16.12)

What to run, and what to check afterwards. **Nothing here has been run against real hosting** —
there is none yet, so this is written to be followed and corrected, not relied on. The blocked
entry in `docs/progress.md` says so.

## What you need first

| Thing | Why | Decision |
|---|---|---|
| A domain name | Caddy obtains its certificate for this hostname | — |
| Managed PostgreSQL with point-in-time recovery, Indian region | The books stay in-country; PITR gives the RPO | D-056 #2 |
| A host for the two containers (proxy + backend) | 4 vCPU / 8 GB is the SRS 17.2 sizing for the backend | SRS 17.2 |
| An address for certificate-expiry notices | `ACME_EMAIL` | — |

## Environment

Every value is required; there are no defaults, so a missing one fails the start rather than
quietly running with a development value (SEC-1.14).

```sh
SITE_ADDRESS=app.example.in          # the public hostname, no scheme
ACME_EMAIL=ops@example.in
DATABASE_URL=postgresql+asyncpg://tally_app:…@…:5432/tally
DATABASE_MIGRATION_URL=postgresql+psycopg://tally_owner:…@…:5432/tally
JWT_SECRET=…                         # at least 32 bytes; prod refuses to start without it
CORS_ORIGINS=https://app.example.in
TRUSTED_PROXIES=172.16.0.0/12        # the Docker network Caddy is on
LOG_RETENTION_DAYS=180               # D-056 #4; the minimum is 90 (SRS 15)
```

`ANTHROPIC_API_KEY` is deliberately **not** set: the anomaly explainer stays off in production
until the owner decides otherwise (D-056 #5). With no key, anomalies are still found and shown
with their evidence and the explanation reads "unavailable" (AC-58).

`TRUSTED_PROXIES` is the one easy thing to get wrong. Too narrow and every client looks like one
IP to the rate limiter, and `HTTPS_REQUIRED` fires on traffic that really is https. Too wide and
a client can forge `X-Forwarded-For` to escape its own rate limit (D-033 #5-6).

## Deploy

```sh
cd deploy
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml run --rm backend alembic upgrade head
docker compose -f docker-compose.prod.yml up -d
```

Migrations run as the owner role (`DATABASE_MIGRATION_URL`); the application runs as
`tally_app`, which has DML only and no DDL (SEC-1.15). Apply `deploy/postgres/grants.sql` to the
managed instance once, as its superuser, before the first migration.

## The three checks P16.12 exists for

Run these against the deployed site. `tools/tests/test_deploy_config.py` already checks the
configuration *says* the right thing; these check the running system *does*.

**1. The browser's `Host` reaches the backend.** A rewritten Host makes every page reload look
cross-site and signs everyone out, because the refresh and logout endpoints compare `Origin`
against `Host` (D-051 #2). This is Caddy's default and the reason it was chosen over nginx — but
verify it, because it is invisible until someone reloads.

```sh
# Sign in, then reload. The session must survive.
npm --prefix frontend run e2e:live   # with LIVE_EMAIL / LIVE_PASSWORD set, against SITE_ADDRESS
```

**2. The security headers and HSTS are served.**

```sh
curl -sI "https://$SITE_ADDRESS/" | grep -iE 'content-security-policy|strict-transport|x-content-type|referrer'
# Expect: the SPA's CSP, HSTS with max-age=31536000; includeSubDomains, nosniff, no-referrer.

curl -sI "https://$SITE_ADDRESS/api/health" | grep -i 'content-security-policy'
# Expect the API's own stricter policy: default-src 'none'; frame-ancestors 'none'.
# If this shows the SPA's policy instead, the site-level header block is overwriting it.
```

**3. `/api` is stripped, and the backend is not reachable around the proxy.**

```sh
curl -s "https://$SITE_ADDRESS/api/health"     # {"status":"ok"} - the backend has no /api prefix
curl -s --max-time 5 "http://<host-public-ip>:8000/health"   # must FAIL to connect
curl -s --max-time 5 "http://<host-public-ip>:5432"          # must FAIL to connect
```

The last two are the point of `docker-compose.prod.yml` (D-056 #7): only the proxy publishes a
port, so every request arrives with TLS, HSTS and the headers above. If either connects, the
headers are optional for anyone who knows the address.

Also confirm the managed database's firewall admits **only** this backend. That is a hosting
setting, not something the compose file can enforce.

## Browsers

Check in **Chrome and Safari**. Safari is the one that matters: it will not return a `Secure`
cookie over plain `http://localhost`, which is why the live Playwright configuration serves
https (D-051 #8). A session that survives a reload in Chrome but not Safari is a cookie-attribute
problem, not a proxy problem.

## Rolling back

```sh
docker compose -f docker-compose.prod.yml up -d --no-deps backend   # with the previous image tag
```

Migrations are **not** rolled back as a matter of course: every migration in this project is
written to be additive, so the previous backend runs against the newer schema. If a migration
must be undone, do it deliberately and read its `downgrade()` first — and take a snapshot before
you do (`docs/runbooks/restore.md`).

## Afterwards

Record in `docs/progress.md`: the provider and region, the database instance size, and the date
the three checks above were run and passed.
