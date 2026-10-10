import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { setAccessToken } from "../lib/session";
import { agent, company, serve, serveCompanies } from "../test/fixtures";
import { renderApp } from "../test/render";
import { server, withMockApi } from "../test/server";

withMockApi();
afterEach(() => setAccessToken(null));

const INITIAL = "INITIAL_SYNC_INCOMPLETE: no sync has completed without errors yet";
const NO_SCHEDULE = "NO_ACTIVE_SCHEDULE: an Agent is ACTIVE but no schedule is active";

describe("Home (P13.10)", () => {
  it("shows every warning from sync, reconciliation and Agents", async () => {
    serveCompanies(company());
    serve("/sync/status", {
      warnings: [INITIAL],
      collections: [],
      last_run: {
        sync_run_id: "r-1",
        status: "PARTIAL",
        records_fetched: 10,
        records_failed: 2,
        started_at: "2026-03-16T05:30:00Z",
        ended_at: "2026-03-16T05:40:00Z",
        agent_id: "a-1",
        command_id: null,
        sync_mode: "INCREMENTAL",
      },
      reconciliation: { sync_run_id: "r-1", run_at: "2026-03-16T06:00:00Z", overall: "FAIL" },
    });
    serve("/agents", {
      warnings: [NO_SCHEDULE],
      agents: [
        agent({
          uptime_advisory: "prominent",
          warnings: ["QUEUE_FULL: the Agent's local queue is full"],
        }),
        agent({
          agent_id: "a-2",
          agent_name: "Godown PC",
          status: "OFFLINE",
          uptime_advisory: "advisory",
        }),
      ],
    });
    renderApp("/c/c-1/home");
    expect(await screen.findByText(INITIAL)).toBeInTheDocument();
    expect(screen.getByText("PARTIAL")).toBeInTheDocument();
    expect(screen.getByText("16 Mar 2026, 11:10")).toBeInTheDocument();
    expect(screen.getByText("FAIL")).toBeInTheDocument();
    expect(screen.getByText(/differ from Tally's beyond the tolerance/)).toBeInTheDocument();
    expect(await screen.findByText(NO_SCHEDULE)).toBeInTheDocument();
    expect(
      screen.getByText("Head Office PC: QUEUE_FULL: the Agent's local queue is full"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Restart recommended on Head Office PC: the latest reconciliation failed/),
    ).toBeInTheDocument();
    expect(screen.getByText("Restart recommended on Godown PC.")).toBeInTheDocument();
    expect(screen.getByText("1 ACTIVE")).toBeInTheDocument();
    expect(screen.getByText("1 OFFLINE")).toBeInTheDocument();
  });
});

describe("Home requests exactly what FR-4.1 lists (P16.5)", () => {
  /** The paths the home view fetched, relative to the company, with the query stripped. */
  async function homeRequests(): Promise<string[]> {
    const seen: string[] = [];
    server.events.on("request:start", ({ request }) => {
      const url = new URL(request.url);
      const match = url.pathname.match(/\/api\/companies\/c-1(\/.*)$/);
      if (match?.[1]) seen.push(match[1]);
    });
    const metric = (m: string) =>
      server.use(
        http.get(`*/api/companies/c-1/analytics/${m}`, () =>
          HttpResponse.json({
            metric: m,
            summary: { available: true, amount: "0.00", direction: null },
            notes: [],
          }),
        ),
      );
    serveCompanies(company());
    ["sales", "cash-bank-position", "receivables", "payables"].forEach(metric);
    serve("/sync/status", { warnings: [], collections: [], last_run: null, reconciliation: null });
    serve("/agents", { warnings: [], agents: [] });

    renderApp("/c/c-1");
    await screen.findByRole("heading", { name: "Home" });
    await screen.findByText("Agents");
    server.events.removeAllListeners();
    return [...new Set(seen)].sort();
  }

  it("asks for the four figures, the sync status and the Agents, and nothing else", async () => {
    // Seven requests: FR-4.1's six, plus the layout's availability probe. CompanyLayout asks
    // /analytics/payment-behaviour on every company page to decide whether to list that nav item
    // (FR-PAY-6). While gate G25 has not passed it answers `available: false` at once; once it
    // passes it is real work on every page load, which is why tools/tally_tools/loadtest includes
    // it - and why this list names it rather than hiding it.
    expect(await homeRequests()).toEqual(
      [
        "/analytics/cash-bank-position",
        "/analytics/payables",
        "/analytics/payment-behaviour",
        "/analytics/receivables",
        "/analytics/sales",
        "/agents",
        "/sync/status",
      ].sort(),
    );
  });

  it("does not request product-difference: it is a data-quality figure, not a headline", async () => {
    // PERF-1.1 (P16.5). Measured on the SRS 17.2 dataset it is the most expensive single figure
    // there is, and the home view never needed it - FR-4.1 lists six things and it is not one.
    // It loads when its own section opens.
    const requested = await homeRequests();
    expect(requested.filter((p) => p.includes("product-difference"))).toEqual([]);
  });
});
