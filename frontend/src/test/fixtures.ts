import type { Company } from "../lib/company";

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
    ...overrides,
  };
}
