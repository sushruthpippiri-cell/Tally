import type { Page, Route } from "@playwright/test";
import { ANALYTICS } from "./analyticsMock";

/** A mocked backend for page tests: signed in (refresh always succeeds), one company, and data
 * with long names and wide tables so the 360 px checks have something to overflow. */
type Handler = unknown | ((route: Route, body: unknown) => unknown);
export type Api = Record<string, Handler>;

export const LONG = "Shree Lakshmi Venkateswara Wholesale Traders and Distributors Private Limited";
const at = "2026-03-16T06:30:00Z";

export const company = {
  company_id: "c-1",
  name: LONG,
  financial_year_start: "2025-04-01",
  company_timezone: "Asia/Kolkata",
  is_active: true,
  tally_guid: "guid-1",
  my_roles: ["OWNER"],
  // P15: the Anomalies section is listed only when the flag is on.
  anomaly_detection_enabled: true,
  my_permissions: [
    "EXPORT",
    "MANAGE_AGENTS",
    "MANAGE_CUSTOM_FIELDS",
    "MANAGE_SCHEDULES",
    "MANAGE_SETTINGS",
    "MANAGE_USERS",
    "REVIEW_ANOMALIES",
    "RUN_SYNC",
    "VIEW_FINANCIALS",
    "VIEW_LOGS",
    "VIEW_RECON_AND_DQ",
  ],
};

export function agent(id: string, name: string, extra: Record<string, unknown> = {}) {
  return {
    agent_id: id,
    agent_name: name,
    status: "ACTIVE",
    agent_version: "1.2.0",
    tdl_version: "1.1.0",
    tally_version: "TallyPrime 5.1",
    tally_company_name: LONG,
    tally_host: "head-office-accounts-desktop.local",
    tally_port: 9000,
    extraction_batch_size: null,
    last_heartbeat_at: at,
    offline_since: null,
    tally_uptime_seconds: 900000,
    uptime_advisory: "advisory",
    queue_status: { records: 12, dead_letter_count: 0, full: false, oldest_age_seconds: 30 },
    last_tally_status: "OK",
    tally_status_since: null,
    registered_at: at,
    revoked_at: null,
    warnings: ["QUEUE_FULL: the Agent's local queue is full"],
    ...extra,
  };
}

export function command(status: string, extra: Record<string, unknown> = {}) {
  return {
    command_id: "cmd-1",
    agent_id: "a-1",
    agent_name: "Head Office PC",
    sync_mode: "INCREMENTAL",
    date_from: null,
    date_to: null,
    status,
    created_at: at,
    created_by: null,
    claimed_at: status === "PENDING" ? null : "2026-03-16T06:31:00Z",
    lease_expires_at: null,
    completed_at: ["COMPLETED", "FAILED"].includes(status) ? "2026-03-16T06:35:00Z" : null,
    error_code: null,
    error_message: null,
    waiting_label: null,
    ...extra,
  };
}

const run = {
  sync_run_id: "r-1",
  status: "PARTIAL",
  records_fetched: 1200,
  records_failed: 3,
  started_at: at,
  ended_at: "2026-03-16T06:40:00Z",
  agent_id: "a-1",
  command_id: null,
  sync_mode: "INCREMENTAL",
};

const setting = (value: unknown) => ({ value, is_default: true });

const DEFAULTS: Api = {
  ...ANALYTICS,
  "GET /companies": [company, { ...company, company_id: "c-2", name: "Gupta Stores" }],
  "GET /companies/c-1": company,
  "GET /companies/c-1/agents": {
    warnings: [
      "NO_ACTIVE_SCHEDULE: an Agent is ACTIVE but no schedule is active, so no automatic syncs run",
    ],
    agents: [agent("a-1", "Head Office PC")],
  },
  "GET /companies/c-1/sync/status": {
    warnings: [
      "INITIAL_SYNC_INCOMPLETE: no sync has completed without errors yet, so some data may be missing",
    ],
    last_run: run,
    reconciliation: { sync_run_id: "r-1", run_at: at, overall: "FAIL" },
    collections: ["LEDGER", "VOUCHER", "STOCK_ITEM"].map((c, i) => ({
      collection_type: c,
      mode: i === 0 ? "FULL_ONLY" : "INCREMENTAL",
      label: i === 0 ? "Full sync only" : "Incremental",
      watermark: 123456789,
      status: "OK",
      last_successful_sync_at: at,
      lease_holder: i === 1 ? "Head Office PC" : null,
      lease_expires_at: i === 1 ? at : null,
      held_back: i === 1 ? 3 : 0,
    })),
  },
  "GET /companies/c-1/sync/runs": [run, { ...run, sync_run_id: "r-2", status: "FAILED" }],
  "GET /companies/c-1/sync/errors": [
    {
      id: 1,
      sync_run_id: "r-1",
      entity_type: "VOUCHER",
      tally_guid: "a1b2c3d4-e5f6-7890-abcd-ef0123456789-0000000a",
      alter_id: 4567,
      error_code: "PARSE_ERROR",
      message:
        "Element <AMOUNT> could not be read as a decimal number in voucher Sales/2025-26/00123",
      watermark_hold: 4566,
      created_at: at,
    },
  ],
  "GET /companies/c-1/sync-schedules": [
    {
      schedule_id: "s-1",
      agent_id: "a-1",
      agent_name: "Head Office PC",
      cron_expression: "0 2 * * *",
      sync_mode: "INCREMENTAL",
      is_active: true,
      next_fire_at: "2026-03-16T20:30:00Z",
      created_by: null,
    },
  ],
  "GET /companies/c-1/reconciliation": {
    run: {
      sync_run_id: "r-1",
      run_at: at,
      as_of: "2026-03-16",
      overall: "INCOMPLETE",
      compared: 2,
      failed: 1,
    },
    history: [
      {
        sync_run_id: "r-1",
        run_at: at,
        as_of: "2026-03-16",
        overall: "INCOMPLETE",
        compared: 2,
        failed: 1,
      },
    ],
    unverified_gates: ["G36", "G37"],
    total_rows: 1,
    not_compared: [
      {
        metric: "LEDGER_BALANCE",
        entity_guid: "guid-x",
        name: LONG,
        reason: "opening balance unavailable (Data Quality)",
        fails: false,
      },
    ],
    rows: [
      {
        metric: "LEDGER_BALANCE",
        entity_id: null,
        entity_name: LONG,
        period_start: "2025-04-01",
        period_end: "2026-03-16",
        tally_value: "123456789012.34",
        local_value: "123456789000.00",
        absolute_difference: "12.34",
        percentage_difference: "0.00000001",
        result: "FAIL",
      },
    ],
  },
  "GET /companies/c-1/data-quality": [
    {
      check_id: "sync_held_back",
      title: "Sync held back by failing records",
      severity: "ERROR",
      count: 3,
      how_to_fix: "Fix these records in Tally; the next sync moves past them.",
    },
  ],
  "GET /companies/c-1/data-quality/sync_held_back": {
    check_id: "sync_held_back",
    title: "Sync held back by failing records",
    severity: "ERROR",
    count: 3,
    how_to_fix: "Fix these records in Tally.",
    limit: 50,
    offset: 0,
    items: [
      {
        collection_type: "VOUCHER",
        tally_guid: "a1b2c3d4-e5f6-7890-abcd-ef0123456789-0000000a",
        alter_id: 4567,
        error_code: "PARSE_ERROR",
        message: LONG,
        created_at: at,
      },
    ],
  },
  "GET /companies/c-1/settings": {
    feature_flags: { FEATURE_ANOMALY_DETECTION: { enabled: false, is_default: true } },
    settings: {
      "classification.sales_groups": setting([
        {
          type: "PREDEFINED",
          reserved_name: "Sales Accounts",
          display_name: "Sales Accounts",
          is_missing: false,
        },
      ]),
      "classification.purchase_groups": setting([]),
      "classification.expense_groups": setting([]),
      "classification.cash_bank_groups": setting([]),
      "classification.tax_groups": setting([]),
      "analytics.taxable_value_mode": setting(true),
      "cashflow.include_journal": setting(true),
      "aging.bucket_boundaries": setting([30, 60, 90]),
      "payment.window_days": setting(365),
      "stock.measurement_period_days": setting(90),
      "reconciliation.money_absolute_tolerance": setting("1.00"),
      "analytics.quarter_mode": setting("financial"),
    },
  },
  "GET /companies/c-1/masters/groups": [],
  "GET /companies/c-1/settings/custom-fields": [],
  "GET /companies/c-1/users": [
    {
      user_id: "u-1",
      email: "owner.with.a.very.long.address@sharma-traders-example.co.in",
      name: LONG,
      is_active: true,
      roles: ["OWNER"],
    },
  ],
};

/** Routes every `/api/...` call to `api` (over the defaults). A handler is a JSON body, or a
 * function of (route, request body) returning one; returning undefined means it fulfilled the
 * route itself. Returns the calls seen, as "METHOD path". */
export async function mockApi(page: Page, api: Api = {}): Promise<string[]> {
  const handlers = { ...DEFAULTS, ...api };
  const calls: string[] = [];
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api/, "");
    const key = `${request.method()} ${path}`;
    calls.push(key);
    if (path === "/auth/refresh") {
      return route.fulfill({
        json: { access_token: "t", expires_in: 1800, must_change_password: false },
      });
    }
    const handler = handlers[key];
    if (handler === undefined)
      return route.fulfill({ status: 404, json: { code: "NOT_FOUND", message: key } });
    const body: unknown =
      typeof handler === "function" ? await handler(route, request.postDataJSON()) : handler;
    if (body !== undefined) await route.fulfill({ json: body });
  });
  return calls;
}
