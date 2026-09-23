# Phase 13 — Frontend foundation & operations views

**Size:** L (split: P13.1–P13.5, then P13.6–P13.11) · **Depends on:** P3 (API), P6 (data quality); P10 for the reconciliation page
**SRS:** 13.1 (FR-4.2, FR-4.4, FR-4.5), 14.1, 17.4, 4.8–4.9 (user-visible states), 16 (user-facing messages)
**Requirements:** NFR-UI-1–3, AGT-1.6, RTE-1.2, RTE-1.6, RBAC-1.1 (UI side)
**Acceptance:** UI side of AC-17, AC-18, AC-19; groundwork for AC-65 · **Decisions:** D-018, D-028

## Goal
A responsive React app that non-technical owners can use on a phone, with login, company switching, role-aware navigation, and every operational screen: Agents, Sync, Settings, Users, Data Quality and Reconciliation.

## Tasks

### P13.1 Scaffold — `frontend/`
Vite + React + TypeScript (strict) + Tailwind + React Router + TanStack Query + Recharts (D-018). `npm run gen:api` generates types from the backend's `/openapi.json` with openapi-typescript; a thin typed fetch client adds the bearer token and maps error bodies to `ApiError(code, message)`. ESLint, Prettier, Vitest + Testing Library, Playwright with two projects: desktop and a 360×740 touch-enabled mobile viewport. Add frontend jobs to CI.

### P13.2 Layout and shared components
- Responsive shell: sidebar on desktop, drawer + bottom navigation under the `md` breakpoint.
- `<ScrollableTable>`: every table is wrapped so wide content scrolls inside its own container, never the page (NFR-UI-1).
- Formatting helpers: money with Indian digit grouping (`Intl.NumberFormat('en-IN', {style: 'currency', currency: 'INR'})`) from Decimal strings (no arithmetic in the browser); dates and timestamps in the company time zone (`Intl.DateTimeFormat` with `timeZone`); Dr/Cr display.
- Status badges, empty states, loading skeletons, confirm dialogs, "shown once" secret dialog with copy button.

### P13.3 Authentication
Login page, token handling per D-028 (access token in memory, refresh in sessionStorage, automatic refresh on 401 once), logout, change password.

### P13.4 Company context and navigation
Company picker (one company at a time); navigation reflecting FR-4.2 sections, with Settings, Users, logs and Agent management hidden for roles without permission (the server still enforces, RBAC-1.1); a 403 page.

### P13.5 Error message catalogue — `src/lib/errorMessages.ts`
One human message per `ErrorCode`, for example:
- `TALLY_SERVER_DISABLED`: "TallyPrime's XML/HTTP server is off. Enable it in TallyPrime's connectivity settings (default port 9000)."
- `TALLY_UNREACHABLE`: "Tally not running — the Windows user may have logged off. Log in and start TallyPrime; Remote Desktop users should disconnect instead of logging off."
- `COMPANY_NOT_LOADED`, `COMPANY_MISMATCH`, `TDL_NOT_LOADED`, `QUEUE_FULL`, `SYNC_LOCKED` ("Sync in progress by <agent>"), `AGENT_SELECTION_REQUIRED`, `CREDENTIAL_INVALID`, `AGENT_REVOKED`, `AGENT_INCOMPATIBLE` ("Agent update required") — wording from SRS Section 16's "What the user sees" column.
A unit test fails if any `ErrorCode` lacks a message.

### P13.6 Agents page (FR-4.4)
List: name, status badge, Agent/TDL/Tally versions, last heartbeat (relative + local time), Tally uptime with restart advisory (prominent when the latest reconciliation failed), queue status, Tally status warning. Actions (Owner/Admin): generate registration token (shown once, 24 h expiry), rotate credential (confirm, shown once), revoke (typed confirmation), edit Tally settings (batch size ≤ 10,000 validated client-side too).

### P13.7 Sync page
- "Sync Now": Agent selector shown when more than one ACTIVE Agent (RTE-1.2, AC-18), mode selector, date range for DATE_RANGE.
- Live command timeline polling every 3 s while not terminal: PENDING → CLAIMED → RUNNING → COMPLETED/FAILED/EXPIRED/FAILED_AGENT_LOST (AGT-1.6, AC-17); "Waiting — Agent offline since …" label (RTE-1.6, AC-19).
- Runs history, errors (Owner/Admin), per-collection watermark with "Full sync only" badge, lease holder.
- Schedules (Owner/Admin): list, create, edit, activate/deactivate; cron helper with human-readable preview in the company time zone.

### P13.8 Settings pages
Company profile (time zone, FY start, with validation messages); accounting settings (allow-lists as multi-selects showing each group's current display name, sending the identifier the API expects - reserved name for predefined groups, GUID for the company's own top-level groups, D-001; stale entries flagged; taxable-value mode; journal-in-cash-flow toggle); thresholds (aging, payment, stock, reconciliation, Top-N); feature flags; custom field mappings with "Download UDF TDL" (P5.8); users and roles (Owner only).

### P13.9 Data Quality and Reconciliation pages
- Data Quality (FR-4.5): list of checks with counts, severity, drill into items, "how to fix" text.
- Reconciliation: latest run table (Tally value, local value, absolute difference, percentage difference, PASS/FAIL), history, "failures only" filter, "Run reconciliation" button.

### P13.10 Home placeholder
Last sync time and status, reconciliation status, Agent health summary. The full home dashboard arrives in P14.

### P13.11 Tests
- Component tests for role-based rendering (Accountant does not see Settings/Users/Agent actions).
- Playwright (API mocked with MSW or a seeded backend): login; company switch; token generation dialog; Sync Now with two Agents requires a selection (AC-18 UI); status progression (AC-17 UI); offline label (AC-19 UI); every page at 360 px has `document.scrollingElement.scrollWidth <= window.innerWidth`.

## Definition of done
All pages work against the real backend in `make up`; Playwright suite green on desktop and mobile projects; every `ErrorCode` has a message.

## Kickoff prompt
~~~text
Read CLAUDE.md, docs/plan/phase-13-frontend-foundation.md, docs/decisions.md (D-018, D-028), docs/agent-protocol.md and SRS Sections 13.1, 14.1, 16, 17.4. In plan mode, propose the app structure, routing, component list and test plan. Implement P13.1–P13.5 this session and P13.6–P13.11 in the next. Tests first where practical, commit per task, update docs/progress.md.
~~~
