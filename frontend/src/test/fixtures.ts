import { http, HttpResponse } from "msw";
import type { Schemas } from "../api/types";
import type { Company } from "../lib/company";
import { server } from "./server";

/** SRS 14.1's permission sets, as the API reports them in `my_permissions`. */
export const OWNER = [
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
];
export const ACCOUNTANT = [
  "EXPORT",
  "REVIEW_ANOMALIES",
  "RUN_SYNC",
  "VIEW_FINANCIALS",
  "VIEW_RECON_AND_DQ",
];

export const ADMIN = [
  "EXPORT",
  "MANAGE_AGENTS",
  "MANAGE_CUSTOM_FIELDS",
  "MANAGE_SCHEDULES",
  "MANAGE_SETTINGS",
  "RUN_SYNC",
  "VIEW_FINANCIALS",
  "VIEW_LOGS",
  "VIEW_RECON_AND_DQ",
];

export function company(overrides: Partial<Company> = {}): Company {
  return {
    company_id: "c-1",
    name: "Sharma Traders",
    financial_year_start: "2025-04-01",
    company_timezone: "Asia/Kolkata",
    is_active: true,
    tally_guid: "guid-1",
    my_roles: ["OWNER"],
    my_permissions: OWNER,
    anomaly_detection_enabled: false,
    ...overrides,
  };
}

export const accountant = () => company({ my_roles: ["ACCOUNTANT"], my_permissions: ACCOUNTANT });
export const admin = () => company({ my_roles: ["ADMIN"], my_permissions: ADMIN });

/** Serves `GET /companies` and `GET /companies/{id}` for these companies. */
export function serveCompanies(...list: Company[]): void {
  server.use(
    http.get("*/api/companies", () => HttpResponse.json(list)),
    ...list.map((c) => http.get(`*/api/companies/${c.company_id}`, () => HttpResponse.json(c))),
  );
}

/** Serves one GET under company c-1 (path after `/companies/c-1`). */
export function serve(path: string, body: Parameters<typeof HttpResponse.json>[0]): void {
  server.use(http.get(`*/api/companies/c-1${path}`, () => HttpResponse.json(body)));
}

export function agent(overrides: Partial<Schemas["AgentOut"]> = {}): Schemas["AgentOut"] {
  return {
    agent_id: "a-1",
    agent_name: "Head Office PC",
    status: "ACTIVE",
    agent_version: "1.2.0",
    tdl_version: "1.1.0",
    tally_version: "TallyPrime 5.1",
    tally_company_name: "Sharma Traders",
    tally_host: "localhost",
    tally_port: 9000,
    extraction_batch_size: null,
    last_heartbeat_at: "2026-03-16T06:30:00Z",
    offline_since: null,
    tally_uptime_seconds: 3600,
    uptime_advisory: "none",
    queue_status: { records: 0, dead_letter_count: 0, full: false, oldest_age_seconds: null },
    last_tally_status: "OK",
    tally_status_since: null,
    registered_at: "2026-03-01T04:00:00Z",
    revoked_at: null,
    warnings: [],
    ...overrides,
  };
}
