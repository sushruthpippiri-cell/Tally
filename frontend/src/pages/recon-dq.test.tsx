import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import type { Schemas } from "../api/types";
import { setAccessToken } from "../lib/session";
import { agent, company, serve, serveCompanies } from "../test/fixtures";
import { renderApp } from "../test/render";
import { withMockApi } from "../test/server";

withMockApi();
afterEach(() => setAccessToken(null));

const run: Schemas["RunOverview"] = {
  sync_run_id: "r-1",
  run_at: "2026-03-16T06:30:00Z",
  as_of: "2026-03-16",
  overall: "INCOMPLETE",
  compared: 2,
  failed: 1,
};

function row(overrides: Partial<Schemas["ReconciliationRow"]>): Schemas["ReconciliationRow"] {
  return {
    metric: "SALES_CREDITS",
    entity_id: null,
    entity_name: null,
    period_start: "2025-04-01",
    period_end: "2026-03-16",
    tally_value: "100000.00",
    local_value: "100000.00",
    absolute_difference: "0.00",
    percentage_difference: "0.00",
    result: "PASS",
    ...overrides,
  };
}

const REASONS: [string, boolean][] = [
  ["in Tally, not in the synced ledgers", true],
  ["unresolved group chain (Data Quality)", false],
  ["opening balance unavailable (Data Quality)", false],
  ["not in Tally's closing balances", true],
  ["in Tally, not in the synced stock items", true],
  ["no snapshot stored by this run", true],
  ["units differ: Tally kg, stored nos", true],
  ["ledger or voucher type (vt-guid) not synced", true],
];

describe("Reconciliation page", () => {
  it("shows the backend's differences, not ones computed from the values on screen", async () => {
    serveCompanies(company());
    serve("/agents", { warnings: [], agents: [agent()] });
    serve("/reconciliation", {
      run: { ...run, overall: "FAIL" },
      history: [run],
      not_compared: [],
      unverified_gates: [],
      total_rows: 2,
      rows: [
        // |100010 - 100000| is 10, and the rows' values differ by 10 in total: the backend's
        // figures (deliberately different here) are the ones shown.
        row({
          tally_value: "100010.00",
          local_value: "100000.00",
          absolute_difference: "7.77",
          percentage_difference: "0.0123",
        }),
        row({
          metric: "LEDGER_BALANCE",
          entity_name: "Cash",
          result: "FAIL",
          tally_value: "500.00",
          local_value: "400.00",
          absolute_difference: "123.45",
          percentage_difference: null,
        }),
      ],
    });
    renderApp("/c/c-1/reconciliation");
    const table = within(await screen.findByRole("table", { name: "Comparisons with Tally" }));
    expect(table.getByText("₹7.77")).toBeInTheDocument();
    expect(table.getByText("0.0123%")).toBeInTheDocument();
    expect(table.getByText("₹123.45")).toBeInTheDocument();
    expect(table.queryByText("₹10.00")).not.toBeInTheDocument();
    expect(table.queryByText("₹100.00")).not.toBeInTheDocument();
    expect(table.getByText("₹1,00,010.00")).toBeInTheDocument();
  });

  it("shows every warning: unverified gates, incomplete, every not-compared reason", async () => {
    serveCompanies(company());
    serve("/agents", { warnings: [], agents: [agent()] });
    serve("/reconciliation", {
      run,
      history: [run],
      unverified_gates: ["G36", "G37"],
      total_rows: 0,
      rows: [],
      not_compared: REASONS.map(([reason, fails], i) => ({
        metric: "LEDGER_BALANCE",
        entity_guid: `guid-${i}`,
        name: `Ledger ${i}`,
        reason,
        fails,
      })),
    });
    renderApp("/c/c-1/reconciliation");
    expect(await screen.findByText("INCOMPLETE")).toBeInTheDocument();
    expect(screen.getByText(/^Incomplete: some figures could not be compared/)).toBeInTheDocument();
    expect(screen.getByText(/^Awaiting Tally validation \(G36, G37\)/)).toBeInTheDocument();
    const table = within(screen.getByRole("table", { name: "Figures that could not be compared" }));
    for (const [reason] of REASONS) expect(table.getByText(reason)).toBeInTheDocument();
    expect(table.getAllByText("Counts as a failure")).toHaveLength(6);
    expect(table.getAllByText("Not compared")).toHaveLength(2);
  });
});

describe("Data Quality page (FR-4.5)", () => {
  const checks: Schemas["CheckSummary"][] = [
    {
      check_id: "sync_held_back",
      title: "Sync held back by failing records",
      severity: "ERROR",
      count: 137,
      how_to_fix: "Fix these records in Tally; the next sync moves past them.",
    },
    {
      check_id: "groups_not_in_classification_list",
      title: "Groups not in any classification list",
      severity: "WARNING",
      count: 2,
      how_to_fix: "Add them to a classification list in Settings.",
    },
    {
      check_id: "unlinked_notes",
      title: "Unlinked credit and debit notes",
      severity: "INFO",
      count: 0,
      how_to_fix: "Link them to a bill.",
    },
  ];

  it("shows every check with its how-to-fix and the backend's count, with only one page of items loaded", async () => {
    serveCompanies(company());
    serve("/data-quality", checks);
    serve("/data-quality/sync_held_back", {
      ...checks[0],
      limit: 50,
      offset: 0,
      items: Array.from({ length: 50 }, (_, i) => ({
        collection_type: "VOUCHER",
        tally_guid: `guid-${i}`,
        alter_id: 1000 + i,
        error_code: "PARSE_ERROR",
        created_at: "2026-03-16T06:30:00Z",
      })),
    });
    const user = userEvent.setup();
    renderApp("/c/c-1/data-quality");
    for (const c of checks) {
      expect(await screen.findByText(c.title)).toBeInTheDocument();
      expect(screen.getByText(c.how_to_fix)).toBeInTheDocument();
    }
    expect(screen.getByText("137 · ERROR")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show the 137 items" }));
    const table = await screen.findByRole("table", { name: /Sync held back/ });
    expect(within(table).getAllByRole("row")).toHaveLength(51); // header + one page
    expect(screen.getByText("1–50 of 137")).toBeInTheDocument();
    expect(within(table).getAllByText("16 Mar 2026, 12:00")).toHaveLength(50);
  });
});
